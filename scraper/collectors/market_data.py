"""Phase 4 collector: public market & business intelligence per game.

Consumes the market_data queue (filled by the Phase 3 store collector).
Per game:

1. Steam appreviews API → review counts/score (authoritative)
2. SteamCharts → all-time peak CCU + last-30-days average CCU (public)
3. Steam News API → Steam Next Fest participation mentions
4. Gamalytic public API → wishlist / sales / revenue ESTIMATES

Provenance rules (never fabricate):
- Review stats come from Steam itself → stored as facts in steam_stats.
- CCU comes from SteamCharts → stored with source; missing chart = NULL.
- Wishlist/revenue are NOT exposed by Steam → only recorded when a public
  estimator provides a number, always with status=ESTIMATED and source URL.
  No estimator data → status stays UNKNOWN (represented by the absence of
  confirmed/estimated records).
- Next Fest participation recorded only with a concrete news link as source.
"""

import datetime
import logging

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from tqdm import tqdm

from app.db.session import async_session_factory
from app.models import (
    DataStatus,
    Festival,
    Game,
    RevenueRecord,
    SteamStats,
    SyncStage,
    SyncStatus,
    WishlistRecord,
    game_festivals,
)
from scraper.collectors.market_sources import (
    fetch_ccu_stats,
    fetch_gamalytic,
    fetch_next_fest_mentions,
    fetch_review_summary,
)
from scraper.common.http import SteamClient, make_session
from scraper.common.sync import mark, pending_appids
from tenacity import RetryError

logger = logging.getLogger(__name__)

STEAM_MIN_INTERVAL = 1.5
CHARTS_MIN_INTERVAL = 2.0
GAMALYTIC_MIN_INTERVAL = 2.0

NEXT_FEST_NAME = "Steam Next Fest"


async def _ensure_next_fest(db: AsyncSession) -> int:
    stmt = pg_insert(Festival).values(name=NEXT_FEST_NAME, is_next_fest=True)
    stmt = stmt.on_conflict_do_nothing(index_elements=[Festival.name])
    await db.execute(stmt)
    result = await db.execute(sa.select(Festival.id).where(Festival.name == NEXT_FEST_NAME))
    return result.scalar_one()


async def collect_one(
    db: AsyncSession,
    steam_client: SteamClient,
    charts_client: SteamClient,
    gamalytic_client: SteamClient,
    appid: int,
) -> tuple[SyncStatus, str]:
    game = (
        await db.execute(sa.select(Game.is_released).where(Game.appid == appid))
    ).one_or_none()
    if game is None:
        return SyncStatus.SKIPPED, "game_not_in_catalog"
    is_released = game[0]

    # 1. Steam reviews — authoritative.
    reviews = None
    try:
        reviews = await fetch_review_summary(steam_client, appid)
    except Exception as exc:
        logger.warning("Reviews failed for %s: %s", appid, exc)

    # 2. SteamCharts CCU — only meaningful for released games.
    ccu = None
    if is_released:
        try:
            ccu = await fetch_ccu_stats(charts_client, appid)
        except (Exception, RetryError) as exc:
            logger.debug("SteamCharts unavailable for %s: %s", appid, exc)

    # 3. Gamalytic estimates.
    estimates = None
    try:
        estimates = await fetch_gamalytic(gamalytic_client, appid)
    except Exception as exc:
        logger.debug("Gamalytic unavailable for %s: %s", appid, exc)

    # 4. Next Fest mentions from official Steam news.
    mentions = []
    try:
        mentions = await fetch_next_fest_mentions(steam_client, appid)
    except Exception as exc:
        logger.warning("News fetch failed for %s: %s", appid, exc)

    # --- persist -----------------------------------------------------------
    sources = []
    if reviews is not None:
        sources.append("store.steampowered.com/appreviews")
    if ccu is not None:
        sources.append("steamcharts.com")
    if estimates is not None and estimates.followers is not None:
        sources.append("gamalytic.com (followers)")

    if reviews is not None or ccu is not None:
        db.add(
            SteamStats(
                appid=appid,
                positive_reviews=reviews.positive if reviews else None,
                negative_reviews=reviews.negative if reviews else None,
                total_reviews=reviews.total if reviews else None,
                positive_pct=reviews.positive_pct if reviews else None,
                review_score=reviews.review_score if reviews else None,
                review_score_desc=reviews.review_score_desc if reviews else None,
                peak_ccu=ccu.peak_all_time if ccu else None,
                avg_ccu=ccu.avg_recent if ccu else None,
                followers=estimates.followers if estimates else None,
                source_name=" + ".join(sources),
                source_url=f"https://steamcharts.com/app/{appid}" if ccu else None,
            )
        )

    if estimates is not None and estimates.wishlists is not None:
        db.add(
            WishlistRecord(
                appid=appid,
                status=DataStatus.ESTIMATED,
                wishlist_count=estimates.wishlists,
                source_name="Gamalytic (public estimate)",
                source_url=estimates.source_url,
            )
        )

    if estimates is not None and (
        estimates.revenue_usd is not None or estimates.copies_sold is not None
    ):
        db.add(
            RevenueRecord(
                appid=appid,
                status=DataStatus.ESTIMATED,
                gross_revenue_usd=estimates.revenue_usd,
                estimated_sales=estimates.copies_sold,
                estimated_owners_min=estimates.owners,
                estimated_owners_max=estimates.owners,
                source_name="Gamalytic (public estimate)",
                source_url=estimates.source_url,
            )
        )

    if mentions:
        festival_id = await _ensure_next_fest(db)
        first = mentions[0]
        mention_date = datetime.datetime.fromtimestamp(
            first.date_epoch, tz=datetime.timezone.utc
        ).date()
        stmt = pg_insert(game_festivals).values(
            appid=appid,
            festival_id=festival_id,
            source_url=first.url,
            notes=f"Official news: {first.title!r} ({mention_date.isoformat()})",
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[game_festivals.c.appid, game_festivals.c.festival_id]
        )
        await db.execute(stmt)

    await mark(db, appid, SyncStage.BUSINESS_DATA, SyncStatus.DONE)
    return SyncStatus.DONE, "ok"


async def run_market_collector(limit: int = 0, only_appid: int | None = None) -> dict:
    async with make_session() as http:
        steam_client = SteamClient(http, min_interval=STEAM_MIN_INTERVAL)
        charts_client = SteamClient(http, min_interval=CHARTS_MIN_INTERVAL)
        gamalytic_client = SteamClient(http, min_interval=GAMALYTIC_MIN_INTERVAL)

        async with async_session_factory() as db:
            if only_appid is not None:
                queue = [only_appid]
            else:
                queue = await pending_appids(db, SyncStage.MARKET_DATA, limit)

        done = skipped = failed = 0
        async with async_session_factory() as db:
            for appid in tqdm(queue, desc="market data", unit="game"):
                try:
                    status, reason = await collect_one(
                        db, steam_client, charts_client, gamalytic_client, appid
                    )
                except Exception as exc:
                    status, reason = SyncStatus.FAILED, str(exc)[:500]
                    logger.warning("appid %s failed: %s", appid, exc)
                await mark(db, appid, SyncStage.MARKET_DATA, status,
                           None if reason == "ok" else reason)
                await db.commit()
                if status is SyncStatus.DONE:
                    done += 1
                elif status is SyncStatus.SKIPPED:
                    skipped += 1
                else:
                    failed += 1

    logger.info("Market collector batch: done=%d skipped=%d failed=%d", done, skipped, failed)
    return {"done": done, "skipped": skipped, "failed": failed, "queued": len(queue)}
