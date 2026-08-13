"""Scheduled worker: refresh community-hub follower counts.

follower_snapshots is append-only, so running this daily builds the time
series that makes follower VELOCITY computable — the signal that actually
distinguishes a game building momentum from one that has stalled. Until two
snapshots exist for a game, velocity is honestly unknown (never zero).

This deliberately targets the population workers/refresh_stats.py never
touches: that worker re-queues released games only, so upcoming titles have
exactly one steam_stats snapshot, forever. Upcoming games are precisely
where follower movement matters, hence a separate worker rather than
widening that one, whose review/CCU cadence is tuned for released titles.

Sizing: at 4s spacing a full 5.6k-game upcoming sweep is ~6 hours, so this
is resumable and limit-driven by design — run it in bounded batches rather
than as one long job. Never-fetched games come first, then the oldest.

Usage:
    python -m workers.refresh_followers [--limit 500] [--min-age-hours 20]
    python -m workers.refresh_followers --limit 20 --dry-run
    docker compose run --rm followers
"""

import argparse
import asyncio
import datetime
import os

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import FollowerSnapshot, Game
from scraper.collectors.followers import DEFAULT_MIN_INTERVAL, fetch_followers
from scraper.common.http import SteamClient, make_session
from scraper.common.logging import setup_logging

SOURCE_NAME = "steamcommunity.com (hub members)"
# Flush to the database this often so a multi-hour sweep is crash-safe.
COMMIT_EVERY = 50
PROGRESS_EVERY = 100


def latest_follower_sq():
    return (
        sa.select(FollowerSnapshot.appid, FollowerSnapshot.captured_at)
        .distinct(FollowerSnapshot.appid)
        .order_by(FollowerSnapshot.appid, FollowerSnapshot.captured_at.desc())
        .subquery("latest_follower")
    )


async def select_stale(
    min_age_hours: int, limit: int, include_released: bool
) -> list[int]:
    """Games with no follower snapshot or one older than min_age_hours —
    never-fetched first, then oldest first."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        hours=min_age_hours
    )
    lf = latest_follower_sq()
    async with async_session_factory() as db:
        stmt = (
            sa.select(Game.appid)
            .outerjoin(lf, lf.c.appid == Game.appid)
            .where(sa.or_(lf.c.appid.is_(None), lf.c.captured_at < cutoff))
            .order_by(sa.nulls_first(lf.c.captured_at.asc()), Game.appid)
        )
        if not include_released:
            stmt = stmt.where(Game.is_released.is_(False))
        if limit:
            stmt = stmt.limit(limit)
        return list((await db.execute(stmt)).scalars().all())


async def run(
    limit: int, min_age_hours: int, include_released: bool, dry_run: bool, interval: float
) -> dict:
    logger = setup_logging("refresh_followers")
    appids = await select_stale(min_age_hours, limit, include_released)
    if not appids:
        logger.info("Nothing stale to refresh.")
        return {"selected": 0, "written": 0, "no_group": 0, "failed": 0}

    logger.info(
        "Refreshing followers for %s games at %.1fs spacing (~%.0f min)%s",
        len(appids), interval, len(appids) * interval / 60, " [dry-run]" if dry_run else "",
    )

    written = no_group = failed = 0
    async with make_session() as http:
        client = SteamClient(http, min_interval=interval)
        async with async_session_factory() as db:
            for index, appid in enumerate(appids, start=1):
                try:
                    result = await fetch_followers(client, appid)
                except Exception as exc:  # noqa: BLE001 — one bad game must not end the run
                    failed += 1
                    logger.warning("followers failed for %s: %s", appid, exc)
                    continue
                if result is None:
                    # No community hub, or the page shape changed. Recording
                    # nothing is correct: absence of a hub is not zero followers.
                    no_group += 1
                    continue
                written += 1
                if not dry_run:
                    db.add(
                        FollowerSnapshot(
                            appid=result.appid,
                            followers=result.followers,
                            source_name=SOURCE_NAME,
                            source_url=result.source_url,
                        )
                    )
                    # Commit in batches, not once at the end. A full catalogue
                    # sweep runs for hours; a single trailing commit would
                    # discard every row if the run were interrupted at any
                    # point, and the next run would start from zero. With
                    # periodic commits an interrupted sweep simply resumes —
                    # select_stale() skips whatever already has a fresh
                    # snapshot.
                    if written % COMMIT_EVERY == 0:
                        await db.commit()
                if index % PROGRESS_EVERY == 0:
                    logger.info(
                        "%s/%s scanned — %s written, %s no hub, %s failed",
                        index, len(appids), written, no_group, failed,
                    )
            if not dry_run:
                await db.commit()

    summary = {
        "selected": len(appids),
        "written": written,
        "no_group": no_group,
        "failed": failed,
        "persisted": not dry_run,
    }
    logger.info("Summary: %s", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh Steam community follower counts")
    parser.add_argument(
        "--limit", type=int, default=500,
        help="max games this run; 0 = every stale game (default 500)",
    )
    parser.add_argument(
        "--min-age-hours", type=int, default=20,
        help="re-fetch a game only if its newest snapshot is older than this",
    )
    parser.add_argument(
        "--include-released", action="store_true",
        help="also refresh released games (default: upcoming only)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch and report, but write nothing"
    )
    parser.add_argument(
        "--interval", type=float,
        default=float(os.environ.get("FOLLOWERS_MIN_INTERVAL", DEFAULT_MIN_INTERVAL)),
        help="seconds between requests (default 4.0, or FOLLOWERS_MIN_INTERVAL)",
    )
    args = parser.parse_args()
    asyncio.run(
        run(
            limit=args.limit,
            min_age_hours=args.min_age_hours,
            include_released=args.include_released,
            dry_run=args.dry_run,
            interval=args.interval,
        )
    )


if __name__ == "__main__":
    main()
