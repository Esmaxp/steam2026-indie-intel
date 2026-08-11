"""Bulk video prefetch: warm the video cache for every approved game.

The per-game video fetch is normally lazy (only on page view). This worker
walks every game with approved channel info (`game_channels`) whose cache is
missing or stale and calls the exact same service path the page uses —
`app.services.videos.get_game_videos` — so quota accounting, caching and
graceful degradation behave identically. Never-fetched games go first, then
the oldest caches.

The daily API budget is shared with live page views: after 3 consecutive
`quota_exhausted` results the run stops early (continuing would be pointless
until the quota resets).

Usage:
    python -m workers.prefetch_videos [--limit 200] [--min-age-hours 24]
    docker compose run --rm video_prefetch
"""

import argparse
import asyncio
import datetime
from collections import Counter

import sqlalchemy as sa

from app.core.config import get_settings
from app.db.session import async_session_factory
from app.models import GameChannels, VideoCache
from app.services.videos import get_game_videos
from scraper.common.logging import setup_logging

REQUEST_PAUSE_SECONDS = 0.5
QUOTA_STOP_STREAK = 3
PROGRESS_EVERY = 25


async def select_stale(min_age_hours: int, limit: int) -> list[int]:
    """Approved games with no cache row or one older than min_age_hours,
    never-fetched first, then oldest cache first."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        hours=min_age_hours
    )
    async with async_session_factory() as db:
        stmt = (
            sa.select(GameChannels.appid)
            .outerjoin(VideoCache, VideoCache.appid == GameChannels.appid)
            .where(
                sa.or_(VideoCache.appid.is_(None), VideoCache.fetched_at < cutoff)
            )
            .order_by(sa.nulls_first(VideoCache.fetched_at.asc()), GameChannels.appid)
            .limit(limit)
        )
        return list((await db.execute(stmt)).scalars().all())


async def run(limit: int, min_age_hours: int) -> None:
    logger = setup_logging("prefetch_videos")
    settings = get_settings()
    if not settings.youtube_api_key and not (
        settings.twitch_client_id and settings.twitch_client_secret
    ):
        logger.warning(
            "No YOUTUBE_API_KEY and no TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET "
            "configured — nothing to prefetch, exiting."
        )
        return

    appids = await select_stale(min_age_hours, limit)
    if not appids:
        logger.info("All approved games have a fresh video cache — nothing to do.")
        return
    logger.info(
        "Prefetching videos for %d approved games (cache older than %dh)",
        len(appids), min_age_hours,
    )

    statuses: Counter[str] = Counter()
    quota_streak = 0
    fetched = 0
    for appid in appids:
        async with async_session_factory() as db:
            result = await get_game_videos(db, appid)
        status = result.get("status", "unknown")
        statuses[status] += 1
        fetched += 1

        quota_streak = quota_streak + 1 if status == "quota_exhausted" else 0
        if quota_streak >= QUOTA_STOP_STREAK:
            logger.warning(
                "Daily API quota exhausted (%d games in a row) — stopping early "
                "at %d/%d. Re-run after the quota resets.",
                QUOTA_STOP_STREAK, fetched, len(appids),
            )
            break

        if fetched % PROGRESS_EVERY == 0 or fetched == len(appids):
            logger.info(
                "Fetched %d/%d — %s",
                fetched, len(appids),
                ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items())),
            )
        await asyncio.sleep(REQUEST_PAUSE_SECONDS)

    logger.info(
        "Done: %d games processed — %s",
        fetched, ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items())) or "none",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Warm the video cache for all approved games"
    )
    parser.add_argument(
        "--limit", type=int, default=200, help="max games this run"
    )
    parser.add_argument(
        "--min-age-hours", type=int, default=24,
        help="refetch only caches older than this (matches VIDEO_CACHE_TTL_HOURS)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.limit, args.min_age_hours))


if __name__ == "__main__":
    main()
