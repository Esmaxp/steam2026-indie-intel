"""One-time offline backfill: rule-based dimension for pre-existing games.

The 2D/3D fallback in scraper/classifiers/classify.py only runs when the
store collector processes a game — and store_data is never re-run once DONE
(refresher re-queues market_data only). Games collected before the fallback
shipped therefore stay `dimension = unknown` forever unless this pass runs.

This worker applies the exact same `_infer_dimension()` the collector uses —
imported, not reimplemented — fed from fields already in the database
(camera, graphics_style, short_description). Fully offline: no HTTP, just a
DB read + write. Games with no signal or conflicting signals are left
untouched (the pipeline-wide "never guess" rule); whatever remains unknown
afterwards is the true target population for the vision worker.

Idempotent: only rows with dimension_source NULL/'unknown' are considered,
and successful updates set dimension_source = 'rule_based', so a second run
finds nothing left to change.

Usage:
    python -m workers.reclassify_dimension [--limit 0]
"""

import argparse
import asyncio

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import Dimension, Game
from scraper.classifiers.classify import _infer_dimension
from scraper.common.logging import setup_logging

PROGRESS_EVERY = 500


async def run(limit: int) -> None:
    logger = setup_logging("reclassify_dimension")
    async with async_session_factory() as db:
        stmt = (
            sa.select(
                Game.appid, Game.camera, Game.graphics_style, Game.short_description
            )
            .where(
                Game.dimension == Dimension.UNKNOWN,
                # Belt and suspenders: never touch rows another source already
                # classified (tag / rule_based / vision_ai) — idempotency.
                sa.or_(
                    Game.dimension_source.is_(None),
                    Game.dimension_source == "unknown",
                ),
            )
            .order_by(Game.appid)
        )
        if limit:
            stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).all()
        if not rows:
            logger.info("Nothing to reclassify — no unknown-dimension games left.")
            return
        logger.info("Reclassifying %d games (offline, DB-only — no HTTP)", len(rows))

        moved = 0
        for index, (appid, camera, graphics, short_description) in enumerate(rows, 1):
            inferred = _infer_dimension(camera, graphics, short_description or "")
            if inferred is not Dimension.UNKNOWN:
                await db.execute(
                    sa.update(Game)
                    .where(Game.appid == appid)
                    .values(dimension=inferred, dimension_source="rule_based")
                )
                moved += 1
            if index % PROGRESS_EVERY == 0:
                logger.info(
                    "Progress %d/%d — %d moved to rule_based", index, len(rows), moved
                )
        await db.commit()

        logger.info(
            "Done: %d moved to rule_based; %d still unknown — that remainder is "
            "exactly the population the vision worker (dimension_vision) is for.",
            moved, len(rows) - moved,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline rule-based dimension backfill for pre-existing games"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="max games this run; 0 = all (default)"
    )
    args = parser.parse_args()
    asyncio.run(run(args.limit))


if __name__ == "__main__":
    main()
