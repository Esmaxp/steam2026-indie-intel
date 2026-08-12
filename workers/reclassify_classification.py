"""Offline replay of the rule-based classifier over already-collected games.

The classifier in scraper/classifiers/classify.py only runs when the store
collector processes a game — and store_data is never re-run once DONE (the
refresher re-queues market_data only). So every improvement to the tag maps or
the inference rules is invisible to games collected before it shipped, forever,
unless this pass runs.

This worker replays the exact same `classify()` the collector uses — imported,
not reimplemented — fed from data already in the database (the game's tags with
their vote counts, plus its short description). Fully offline: no HTTP, just a
DB read and a write.

It only ever FILLS: a field is written when the stored value is `unknown`, and
never otherwise. That rule is enforced in SQL (a per-field CASE), so a value
another source settled — Steam's own tag, the vision pass, a human — cannot be
clobbered even if the collector re-ran between selection and write. Games whose
signals are missing or contradictory are left untouched, per the pipeline-wide
"never guess" rule.

Replaces the older reclassify_dimension.py, which replayed only _infer_dimension
from stored column values and therefore could not see the tags at all.

Two limitations worth knowing, both inherent to replaying offline:
- Only `short_description` is stored, not the full about/detailed corpus the
  collector classified against, so the description-based graphics refinements
  (HD pixel art, PS1/PS2-style, low poly) are under-powered here.
- `engine` is not replayed: its patterns run mostly over the store legal notice,
  which older rows never persisted.

Usage:
    python -m workers.reclassify_classification --dry-run
    python -m workers.reclassify_classification [--limit 0]
    docker compose run --rm reclassify
"""

import argparse
import asyncio
from collections import defaultdict

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import Camera, Dimension, Game, GraphicsStyle, Tag
from app.models.associations import game_tags
from scraper.classifiers.classify import classify
from scraper.common.logging import setup_logging

BATCH_SIZE = 500
PROGRESS_EVERY = 2000


def _fillable(value_col, unknown):
    """A field is fillable exactly when nothing has settled it yet."""
    return value_col == unknown


async def select_candidates(db, limit: int) -> list[tuple]:
    stmt = (
        sa.select(
            Game.appid,
            Game.short_description,
            Game.dimension,
            Game.camera,
            Game.graphics_style,
        )
        .where(
            # Uncollected games have no tags and no description — nothing to
            # replay against; they get classified by the collector instead.
            Game.last_synced_at.is_not(None),
            sa.or_(
                _fillable(Game.dimension, Dimension.UNKNOWN),
                _fillable(Game.camera, Camera.UNKNOWN),
                _fillable(Game.graphics_style, GraphicsStyle.UNKNOWN),
            ),
        )
        .order_by(Game.appid)
    )
    if limit:
        stmt = stmt.limit(limit)
    return list((await db.execute(stmt)).all())


async def load_tags(db, appids: list[int]) -> dict[int, list[tuple[str, int]]]:
    """(name, votes) pairs per appid, in Steam's rank order."""
    stmt = (
        sa.select(
            game_tags.c.appid,
            Tag.name,
            sa.func.coalesce(game_tags.c.votes, 0),
        )
        .join(Tag, Tag.id == game_tags.c.tag_id)
        .where(game_tags.c.appid.in_(appids))
        .order_by(game_tags.c.appid, game_tags.c.rank)
    )
    grouped: dict[int, list[tuple[str, int]]] = defaultdict(list)
    for appid, name, votes in (await db.execute(stmt)).all():
        grouped[appid].append((name, votes))
    return grouped


def _plan_update(row, result) -> dict:
    """Per-field CASE assignments — fill only, never overwrite.

    Postgres evaluates every right-hand side of one UPDATE against the OLD
    row, so a `_source` column can safely test its own value column in the
    same statement that assigns it.
    """
    _, _, dimension, camera, graphics = row
    values: dict = {}
    if dimension is Dimension.UNKNOWN and result.dimension is not Dimension.UNKNOWN:
        values["dimension"] = sa.case(
            (Game.dimension == Dimension.UNKNOWN, result.dimension), else_=Game.dimension
        )
        values["dimension_source"] = sa.case(
            (Game.dimension == Dimension.UNKNOWN, result.dimension_source),
            else_=Game.dimension_source,
        )
    if camera is Camera.UNKNOWN and result.camera is not Camera.UNKNOWN:
        values["camera"] = sa.case(
            (Game.camera == Camera.UNKNOWN, result.camera), else_=Game.camera
        )
    if graphics is GraphicsStyle.UNKNOWN and result.graphics_style is not GraphicsStyle.UNKNOWN:
        values["graphics_style"] = sa.case(
            (Game.graphics_style == GraphicsStyle.UNKNOWN, result.graphics_style),
            else_=Game.graphics_style,
        )
    return values


async def run(limit: int, dry_run: bool) -> None:
    logger = setup_logging("reclassify_classification")
    async with async_session_factory() as db:
        candidates = await select_candidates(db, limit)
        if not candidates:
            logger.info("Nothing to reclassify — no fillable games left.")
            return
        logger.info(
            "Replaying the rule-based classifier over %d games (offline, DB-only%s)",
            len(candidates), ", DRY RUN — nothing will be written" if dry_run else "",
        )

        changed = {"dimension": 0, "camera": 0, "graphics_style": 0}
        games_touched = 0
        for start in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[start : start + BATCH_SIZE]
            tags_by_appid = await load_tags(db, [row[0] for row in batch])

            for row in batch:
                appid, short_description = row[0], row[1]
                result = classify(
                    tags_by_appid.get(appid, []), description=short_description or ""
                )
                values = _plan_update(row, result)
                if not values:
                    continue
                for field in changed:
                    if field in values:
                        changed[field] += 1
                games_touched += 1
                if not dry_run:
                    await db.execute(
                        sa.update(Game).where(Game.appid == appid).values(**values)
                    )

            if not dry_run:
                await db.commit()
            processed = min(start + BATCH_SIZE, len(candidates))
            if processed % PROGRESS_EVERY == 0 or processed == len(candidates):
                logger.info(
                    "Progress %d/%d — %d games would change" if dry_run
                    else "Progress %d/%d — %d games changed",
                    processed, len(candidates), games_touched,
                )

        verb = "would be filled" if dry_run else "filled"
        logger.info(
            "Done: %d games %s — dimension %d, camera %d, graphics_style %d. "
            "%d games left untouched (no signal or contradictory signals).",
            games_touched, verb, changed["dimension"], changed["camera"],
            changed["graphics_style"], len(candidates) - games_touched,
        )
        if dry_run:
            logger.info("Dry run — no rows were written. Re-run without --dry-run to apply.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline replay of the rule-based classifier (dimension, "
        "camera, graphics style) over already-collected games"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="max games this run; 0 = all (default)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report how many rows each field would gain, without writing anything",
    )
    args = parser.parse_args()
    asyncio.run(run(args.limit, args.dry_run))


if __name__ == "__main__":
    main()
