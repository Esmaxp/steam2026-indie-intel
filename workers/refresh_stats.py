"""Scheduled worker: refresh public market stats for released games.

steam_stats is append-only — every collector pass adds a fresh snapshot, so
running this worker on a schedule (e.g. daily) builds the review/CCU time
series shown on the game detail pages.

It re-queues market_data for released games whose last collection is older
than --min-age-hours, then runs the Phase 4 market collector over the queue.

Usage:
    python -m workers.refresh_stats [--min-age-hours 20] [--limit 0]
    docker compose run --rm refresher
"""

import argparse
import asyncio

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import Game, SyncStage, SyncState, SyncStatus
from scraper.collectors.market_data import run_market_collector
from scraper.common.logging import setup_logging


async def requeue_released(min_age_hours: int) -> int:
    async with async_session_factory() as db:
        stmt = (
            sa.update(SyncState)
            .where(
                SyncState.stage == SyncStage.MARKET_DATA,
                SyncState.status.in_([SyncStatus.DONE, SyncStatus.FAILED]),
                SyncState.appid.in_(
                    sa.select(Game.appid).where(Game.is_released.is_(True))
                ),
                sa.or_(
                    SyncState.last_attempt_at.is_(None),
                    SyncState.last_attempt_at
                    < sa.func.now() - sa.text(f"interval '{int(min_age_hours)} hours'"),
                ),
            )
            .values(status=SyncStatus.PENDING)
        )
        result = await db.execute(stmt)
        await db.commit()
        return result.rowcount or 0


async def run(min_age_hours: int, limit: int) -> None:
    logger = setup_logging("refresh_stats")
    requeued = await requeue_released(min_age_hours)
    logger.info("Re-queued %d released games for a fresh stats snapshot", requeued)
    summary = await run_market_collector(limit=limit)
    logger.info("Refresh finished: %s", summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh market stats snapshots")
    parser.add_argument(
        "--min-age-hours", type=int, default=20,
        help="only refresh games whose last snapshot is older than this",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="max games this run; 0 = all queued"
    )
    args = parser.parse_args()
    asyncio.run(run(args.min_age_hours, args.limit))


if __name__ == "__main__":
    main()
