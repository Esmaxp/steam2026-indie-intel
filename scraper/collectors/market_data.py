"""Phase 4 collector: public market & business intelligence per game.

Consumes the market_data queue (filled by the Phase 3 store collector).
Per game:

1. Steam appreviews API → review counts/score (authoritative)
2. SteamCharts → all-time peak CCU + last-30-days average CCU (public)
3. Steam News API → Steam Next Fest participation mentions

Provenance rules (never fabricate):
- Review stats come from Steam itself → stored as facts in steam_stats.
- CCU comes from SteamCharts → stored with source; missing chart = NULL.
  SteamCharts is third-party, but it publishes an observed MEASUREMENT
  rather than a model output, so it is labelled rather than retired.
- Wishlist/revenue are NOT exposed by Steam. Third-party ESTIMATE vendors
  (Gamalytic, SteamSpy, VG Insights) were retired: this project reports
  measured signals and developer disclosures only. Revenue therefore has no
  source at all and stays UNKNOWN; wishlist figures arrive solely via
  disclosed_numbers_source.py as CONFIRMED rows.
- Demand for unreleased games is measured elsewhere and first-party:
  follower counts (workers/refresh_followers.py) and Valve's Top-Wishlists
  ordinal (scraper/collectors/wishlist_rank.py).
- Next Fest participation recorded only with a concrete news link as source.
"""

import datetime
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from tqdm import tqdm

from app.db.session import async_session_factory
from app.models import (
    Festival,
    Game,
    SteamStats,
    SyncStage,
    SyncStatus,
    game_festivals,
)
from scraper.collectors.market_sources import (
    fetch_ccu_stats,
    fetch_next_fest_mentions,
    fetch_review_summary,
)
from scraper.common.http import SteamClient, make_session
from scraper.common.sync import mark, pending_appids
from tenacity import RetryError

logger = logging.getLogger(__name__)

STEAM_MIN_INTERVAL = 1.5
CHARTS_MIN_INTERVAL = 2.0

NEXT_FEST_NAME = "Steam Next Fest"

# Some public sources sit behind WAFs that reject non-browser user agents.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


# SourceBreaker (a consecutive-failure circuit breaker) was removed with the
# vendor sources that were its only consumers. SteamCharts, the one remaining
# third party, relies on max_attempts=2 instead. Reinstate it from git history
# if a future source needs run-level disabling.


async def _ensure_next_fest(db: AsyncSession) -> int:
    stmt = pg_insert(Festival).values(name=NEXT_FEST_NAME, is_next_fest=True)
    stmt = stmt.on_conflict_do_nothing(index_elements=[Festival.name])
    await db.execute(stmt)
    result = await db.execute(sa.select(Festival.id).where(Festival.name == NEXT_FEST_NAME))
    return result.scalar_one()


@dataclass
class MarketSources:
    """HTTP clients for every market-data source.

    Third-party ESTIMATE vendors (Gamalytic, SteamSpy, VG Insights) were
    retired: this project reports measured first-party signals and
    developer-disclosed figures only. SteamCharts stays — it publishes an
    observed measurement (concurrent players) rather than a model output.
    """

    steam: SteamClient
    charts: SteamClient


async def collect_one(
    db: AsyncSession,
    sources: MarketSources,
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
        reviews = await fetch_review_summary(sources.steam, appid)
    except Exception as exc:
        logger.warning("Reviews failed for %s: %s", appid, exc)

    # 2. SteamCharts CCU — only meaningful for released games.
    ccu = None
    if is_released:
        try:
            ccu = await fetch_ccu_stats(sources.charts, appid)
        except (Exception, RetryError) as exc:
            logger.debug("SteamCharts unavailable for %s: %s", appid, exc)

    # 3. Next Fest mentions from official Steam news.
    mentions = []
    try:
        mentions = await fetch_next_fest_mentions(sources.steam, appid)
    except Exception as exc:
        logger.warning("News fetch failed for %s: %s", appid, exc)

    # --- persist -----------------------------------------------------------
    # NB: named source_labels, not `sources` — that name is the MarketSources
    # parameter above. Rebinding it here used to shadow the dataclass, so any
    # fetch added below this line raised AttributeError on a list.
    source_labels = []
    if reviews is not None:
        source_labels.append("store.steampowered.com/appreviews")
    if ccu is not None:
        source_labels.append("steamcharts.com")

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
                # followers is written by workers/refresh_followers.py into
                # follower_snapshots, measured from Steam's own hub pages.
                # This column is vestigial and drops in a later migration.
                source_name=" + ".join(source_labels),
                source_url=f"https://steamcharts.com/app/{appid}" if ccu else None,
            )
        )

    # No revenue/wishlist estimate rows are written here any more. Wishlist
    # figures come only from developer disclosures (see
    # disclosed_numbers_source.py), which write CONFIRMED rows and run their
    # own merge; revenue has no first-party source at all and stays unknown.

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
    async with make_session() as http, make_session(BROWSER_UA) as browser_http:
        sources = MarketSources(
            steam=SteamClient(http, min_interval=STEAM_MIN_INTERVAL),
            # SteamCharts answers 500 for games it has no chart for — retrying
            # six times per missing game burned ~2 min each, so cap at 2.
            charts=SteamClient(
                browser_http, min_interval=CHARTS_MIN_INTERVAL, max_attempts=2
            ),
        )

        async with async_session_factory() as db:
            if only_appid is not None:
                queue = [only_appid]
            else:
                queue = await pending_appids(db, SyncStage.MARKET_DATA, limit)

        done = skipped = failed = 0
        async with async_session_factory() as db:
            for appid in tqdm(queue, desc="market data", unit="game"):
                try:
                    status, reason = await collect_one(db, sources, appid)
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
