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
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from tqdm import tqdm

from app.db.session import async_session_factory
from app.models import (
    DataStatus,
    Festival,
    Game,
    RevenueEstimate,
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
from scraper.collectors.revenue_merge import merge_estimates
from scraper.collectors.steamspy_source import fetch_steamspy
from scraper.collectors.vginsights_source import fetch_vginsights, robots_allows_games
from scraper.common.http import SteamClient, make_session
from scraper.common.sync import mark, pending_appids
from tenacity import RetryError

logger = logging.getLogger(__name__)

STEAM_MIN_INTERVAL = 1.5
CHARTS_MIN_INTERVAL = 2.0
GAMALYTIC_MIN_INTERVAL = 2.0
STEAMSPY_MIN_INTERVAL = 1.1   # SteamSpy recommends ~1 req/sec
VGINSIGHTS_MIN_INTERVAL = 2.0

NEXT_FEST_NAME = "Steam Next Fest"

# Some public sources sit behind WAFs that reject non-browser user agents.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class SourceBreaker:
    """Stops hammering a source that keeps refusing us (e.g. WAF 403s).

    After `threshold` consecutive failures the source is skipped for the rest
    of the run — its values simply stay Unknown instead of costing time."""

    def __init__(self, name: str, threshold: int = 3):
        self.name = name
        self.threshold = threshold
        self.failures = 0
        self.open = False

    def record_success(self) -> None:
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold and not self.open:
            self.open = True
            logger.warning(
                "Source %s disabled for this run after %d consecutive failures "
                "(its values stay Unknown)",
                self.name, self.failures,
            )


async def _ensure_next_fest(db: AsyncSession) -> int:
    stmt = pg_insert(Festival).values(name=NEXT_FEST_NAME, is_next_fest=True)
    stmt = stmt.on_conflict_do_nothing(index_elements=[Festival.name])
    await db.execute(stmt)
    result = await db.execute(sa.select(Festival.id).where(Festival.name == NEXT_FEST_NAME))
    return result.scalar_one()


@dataclass
class MarketSources:
    """Clients + circuit breakers for every market-data source."""

    steam: SteamClient
    charts: SteamClient
    gamalytic: SteamClient
    steamspy: SteamClient
    vginsights: SteamClient
    gamalytic_breaker: SourceBreaker
    steamspy_breaker: SourceBreaker
    vginsights_breaker: SourceBreaker


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

    # 3. Gamalytic estimates (skipped entirely once the breaker opens).
    estimates = None
    if not sources.gamalytic_breaker.open:
        try:
            estimates = await fetch_gamalytic(sources.gamalytic, appid)
            sources.gamalytic_breaker.record_success()
        except Exception as exc:
            sources.gamalytic_breaker.record_failure()
            logger.debug("Gamalytic unavailable for %s: %s", appid, exc)

    # 4. Next Fest mentions from official Steam news.
    mentions = []
    try:
        mentions = await fetch_next_fest_mentions(sources.steam, appid)
    except Exception as exc:
        logger.warning("News fetch failed for %s: %s", appid, exc)

    # 5. SteamSpy owners estimate (skipped once its breaker opens).
    steamspy = None
    if not sources.steamspy_breaker.open:
        try:
            steamspy = await fetch_steamspy(sources.steamspy, appid)
            sources.steamspy_breaker.record_success()
        except Exception as exc:
            sources.steamspy_breaker.record_failure()
            logger.debug("SteamSpy unavailable for %s: %s", appid, exc)

    # 6. VG Insights revenue estimate (skipped once its breaker opens).
    vginsights = None
    if not sources.vginsights_breaker.open:
        try:
            vginsights = await fetch_vginsights(sources.vginsights, appid)
            sources.vginsights_breaker.record_success()
        except Exception as exc:
            sources.vginsights_breaker.record_failure()
            logger.debug("VG Insights unavailable for %s: %s", appid, exc)

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

    # --- raw multi-source estimate rows (revenue_estimates table) ----------
    run_estimates: list[RevenueEstimate] = []
    if estimates is not None and (
        estimates.revenue_usd is not None
        or estimates.copies_sold is not None
        or estimates.owners is not None
    ):
        run_estimates.append(
            RevenueEstimate(
                appid=appid,
                source_name="gamalytic",
                status=DataStatus.ESTIMATED,
                revenue_usd=estimates.revenue_usd,
                estimated_sales=estimates.copies_sold,
                owners_min=estimates.owners,
                owners_max=estimates.owners,
                wishlist_count=estimates.wishlists,
                source_url=estimates.source_url,
            )
        )
    if steamspy is not None:
        run_estimates.append(
            RevenueEstimate(
                appid=appid,
                source_name="steamspy",
                status=DataStatus.ESTIMATED,
                owners_min=steamspy.owners_min,
                owners_max=steamspy.owners_max,
                source_url=steamspy.source_url,
            )
        )
    if vginsights is not None:
        run_estimates.append(
            RevenueEstimate(
                appid=appid,
                source_name="vginsights",
                status=DataStatus.ESTIMATED,
                revenue_usd=vginsights.revenue_usd,
                estimated_sales=vginsights.copies_sold,
                owners_min=vginsights.owners_min,
                owners_max=vginsights.owners_max,
                source_url=vginsights.source_url,
            )
        )
    for row in run_estimates:
        db.add(row)

    # Summary view: Confirmed wins; otherwise median of the estimates, with
    # status=conflicting when sources disagree by more than 50%.
    merged = merge_estimates(run_estimates)
    if merged is not None:
        db.add(
            RevenueRecord(
                appid=appid,
                status=merged.status,
                gross_revenue_usd=merged.gross_revenue_usd,
                estimated_sales=merged.estimated_sales,
                estimated_owners_min=merged.owners_min,
                estimated_owners_max=merged.owners_max,
                estimate_spread=merged.estimate_spread,
                source_name=merged.source_name,
                source_url=merged.source_url,
                notes=merged.notes,
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
    async with make_session() as http, make_session(BROWSER_UA) as browser_http:
        sources = MarketSources(
            steam=SteamClient(http, min_interval=STEAM_MIN_INTERVAL),
            # SteamCharts answers 500 for games it has no chart for — retrying
            # six times per missing game burned ~2 min each, so cap at 2.
            charts=SteamClient(
                browser_http, min_interval=CHARTS_MIN_INTERVAL, max_attempts=2
            ),
            gamalytic=SteamClient(browser_http, min_interval=GAMALYTIC_MIN_INTERVAL),
            steamspy=SteamClient(browser_http, min_interval=STEAMSPY_MIN_INTERVAL),
            vginsights=SteamClient(
                browser_http, min_interval=VGINSIGHTS_MIN_INTERVAL, max_attempts=2
            ),
            gamalytic_breaker=SourceBreaker("gamalytic.com"),
            steamspy_breaker=SourceBreaker("steamspy.com"),
            vginsights_breaker=SourceBreaker("vginsights.com"),
        )

        # robots.txt gate — checked once per run, before any page scraping.
        try:
            if not await robots_allows_games(sources.vginsights):
                sources.vginsights_breaker.open = True
                logger.warning("VG Insights robots.txt disallows game pages — source off")
        except Exception as exc:
            sources.vginsights_breaker.open = True
            logger.warning("VG Insights robots check failed (%s) — source off", exc)

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
