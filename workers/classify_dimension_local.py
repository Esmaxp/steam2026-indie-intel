"""Free offline batch job: fill unknown 2D/3D dimensions by similarity.

Fourth rung of the dimension ladder and the only one that costs nothing:

    Steam's own tag  →  rule_based (camera/graphics/description)
      →  similarity (this worker — local TF-IDF, no API key, no network)
      →  vision_ai / similarity_ai (opt-in, paid, need ANTHROPIC_API_KEY)

It learns from the catalog itself: every game whose dimension came from a tag
or a rule becomes a labelled example, and each unresolved game is matched
against them by TF-IDF cosine similarity over tags + description. A dimension
is written only when a clear majority of the nearest neighbours agree, so a
game surrounded by contradictory examples stays unknown — the same rule the
tag and inference layers already follow.

Guarantees:

- Nothing else in the pipeline changes. This runs after the fact, only over
  rows still `dimension = unknown`, and the fill-only UPDATE is enforced in SQL
  so a tag-derived value can never be overwritten.
- Results are written with dimension_source = "similarity", distinct from
  "similarity_ai" (the paid LLM estimate) and from every other source, so the
  audit trail says exactly which layer decided.
- No network calls and no third-party AI service. scikit-learn and numpy run
  locally; the only I/O is PostgreSQL.

Usage:
    python -m workers.classify_dimension_local --dry-run
    python -m workers.classify_dimension_local [--k 5] [--threshold 0.7] [--limit 0]
    python -m workers.classify_dimension_local --self-check
    docker compose run --rm dimension_local
"""

import argparse
import asyncio
import random
from collections import defaultdict

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import Dimension, Game, Tag
from app.models.associations import game_tags
from scraper.classifiers.similarity_dimension import (
    DEFAULT_K,
    DEFAULT_MIN_NEIGHBOURS,
    DEFAULT_MIN_SIMILARITY,
    DEFAULT_THRESHOLD,
    LABEL_TAGS,
    DimensionSimilarityIndex,
    KnownGame,
    Neighbour,
    build_document,
    decide,
)
from scraper.common.logging import setup_logging

SOURCE_LABEL = "similarity"
# Sources whose games are trustworthy enough to learn from. Deliberately
# excludes every AI source: training on guesses would compound their errors.
LEARNABLE_SOURCES = ("tag", "rule_based")
PREDICT_CHUNK = 250  # bounds the (chunk × known) similarity matrix in memory


async def _tags_by_appid(db, appids: list[int]) -> dict[int, list[str]]:
    if not appids:
        return {}
    stmt = (
        sa.select(game_tags.c.appid, Tag.name)
        .join(Tag, Tag.id == game_tags.c.tag_id)
        .where(game_tags.c.appid.in_(appids))
        .order_by(game_tags.c.appid, game_tags.c.rank)
    )
    grouped: dict[int, list[str]] = defaultdict(list)
    for appid, name in (await db.execute(stmt)).all():
        grouped[appid].append(name)
    return grouped


async def load_known(db) -> list[KnownGame]:
    """Games whose dimension a tag or a rule already settled."""
    stmt = sa.select(Game.appid, Game.name, Game.dimension, Game.short_description).where(
        Game.dimension != Dimension.UNKNOWN,
        Game.dimension_source.in_(LEARNABLE_SOURCES),
        Game.last_synced_at.is_not(None),
    )
    rows = (await db.execute(stmt)).all()
    tags = await _tags_by_appid(db, [row[0] for row in rows])
    return [
        KnownGame(
            appid=appid,
            name=name,
            dimension=dimension,
            document=build_document(tags.get(appid, []), description),
        )
        for appid, name, dimension, description in rows
    ]


async def load_unknown(db, limit: int) -> list[tuple[int, str, str]]:
    """(appid, name, document) for games no earlier layer could settle.

    Games that carry a dimension tag of their own are excluded. If such a game
    is still unknown, it is because its tags contradicted each other (2D and
    3D both voted, see classify._best_tag_match) — strong evidence that the
    catalog itself cannot agree on. Overruling that with text similarity would
    be forcing exactly the guess the tag layer refused to make, and in practice
    those games are often 2.5D, which the neighbours almost never propose.
    """
    carries_label_tag = (
        sa.select(game_tags.c.appid)
        .join(Tag, Tag.id == game_tags.c.tag_id)
        .where(game_tags.c.appid == Game.appid, sa.func.lower(Tag.name).in_(LABEL_TAGS))
        .exists()
    )
    stmt = (
        sa.select(Game.appid, Game.name, Game.short_description)
        .where(
            Game.dimension == Dimension.UNKNOWN,
            sa.or_(Game.dimension_source.is_(None), Game.dimension_source == "unknown"),
            Game.last_synced_at.is_not(None),
            ~carries_label_tag,
        )
        .order_by(Game.appid)
    )
    if limit:
        stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).all()
    tags = await _tags_by_appid(db, [row[0] for row in rows])
    return [
        (appid, name, build_document(tags.get(appid, []), description))
        for appid, name, description in rows
    ]


def self_check() -> bool:
    """Exercise the pure logic on synthetic data — no database, no network."""
    known = [
        KnownGame(1, "Pixel Jump", Dimension.TWO_D,
                  build_document(["Platformer", "Pixel Graphics"], "A retro sprite platformer.")),
        KnownGame(2, "Sprite Quest", Dimension.TWO_D,
                  build_document(["Platformer", "Pixel Graphics"], "Hand-drawn sprite adventure.")),
        KnownGame(3, "Bit Runner", Dimension.TWO_D,
                  build_document(["Platformer", "Pixel Graphics"], "Sprite platformer, retro feel.")),
        KnownGame(4, "Space Sim", Dimension.THREE_D,
                  build_document(["Simulation", "Space"], "Fly a spaceship through 3D space stations.")),
        KnownGame(5, "Mech Arena", Dimension.THREE_D,
                  build_document(["Simulation", "Space"], "Pilot mechs in space arenas.")),
        KnownGame(6, "Orbit Lab", Dimension.THREE_D,
                  build_document(["Simulation", "Space"], "Space station simulation sandbox.")),
    ]
    index = DimensionSimilarityIndex(known, min_df=1)

    checks: list[tuple[str, bool]] = []

    agreeing = build_document(["Platformer", "Pixel Graphics"], "A retro sprite platformer romp.")
    prediction = index.predict([agreeing])[0]
    checks.append(("agreeing neighbours resolve to 2d", prediction.dimension is Dimension.TWO_D))

    unrelated = build_document(["Cooking"], "Bake bread with friends in a bakery.")
    prediction = index.predict([unrelated])[0]
    checks.append(("unrelated game stays unknown", prediction.dimension is None))

    # The vote itself, tested directly: a 3/2 split is below the 70% bar and
    # must stay unknown, while 4/1 clears it. This is the "never force a guess"
    # rule, independent of how the neighbours were retrieved.
    split = tuple(
        Neighbour(i, f"n{i}", dim, 0.5)
        for i, dim in enumerate(
            [Dimension.TWO_D] * 3 + [Dimension.THREE_D] * 2
        )
    )
    checks.append((
        "3/2 split stays unknown (60% < 70%)",
        decide(split, 0.7, 0.0, 3).dimension is None,
    ))
    majority = tuple(
        Neighbour(i, f"n{i}", dim, 0.5)
        for i, dim in enumerate([Dimension.TWO_D] * 4 + [Dimension.THREE_D])
    )
    checks.append((
        "4/1 majority resolves (80% >= 70%)",
        decide(majority, 0.7, 0.0, 3).dimension is Dimension.TWO_D,
    ))

    # Label tags must never enter the document.
    checks.append((
        "label tags stripped from documents",
        "2d" not in build_document(["2D", "Platformer"], "").split(),
    ))

    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    return all(passed for _, passed in checks)


async def validate(
    sample_size: int, k: int, threshold: float,
    min_similarity: float, min_neighbours: int, seed: int,
) -> None:
    """Hold out games whose dimension IS known, predict them, score the result.

    The honest way to decide whether this fallback is good enough to write:
    hide the answer for a random sample, run the same code path, and compare.
    Coverage is how often it dares to answer; accuracy is how often that
    answer matches the tag/rule-derived truth.
    """
    logger = setup_logging("classify_dimension_local")
    async with async_session_factory() as db:
        known = await load_known(db)
    if len(known) < sample_size * 2:
        logger.warning("Not enough settled games (%d) to hold out %d.", len(known), sample_size)
        return

    rng = random.Random(seed)
    holdout_idx = set(rng.sample(range(len(known)), sample_size))
    holdout = [known[i] for i in sorted(holdout_idx)]
    training = [g for i, g in enumerate(known) if i not in holdout_idx]

    logger.info(
        "Holdout validation: %d training games, %d held out (k=%d, agreement>=%.0f%%)",
        len(training), len(holdout), k, threshold * 100,
    )
    index = DimensionSimilarityIndex(training)
    answered = correct = 0
    confusion: dict[tuple[str, str], int] = defaultdict(int)

    for start in range(0, len(holdout), PREDICT_CHUNK):
        chunk = holdout[start : start + PREDICT_CHUNK]
        predictions = index.predict(
            [g.document for g in chunk],
            k=k, threshold=threshold,
            min_similarity=min_similarity, min_neighbours=min_neighbours,
        )
        for game, prediction in zip(chunk, predictions):
            if prediction.dimension is None:
                continue
            answered += 1
            confusion[(game.dimension.value, prediction.dimension.value)] += 1
            if prediction.dimension is game.dimension:
                correct += 1

    coverage = answered / len(holdout) if holdout else 0.0
    accuracy = correct / answered if answered else 0.0
    logger.info(
        "Coverage %.1f%% (%d of %d answered) — accuracy %.1f%% (%d correct, %d wrong)",
        coverage * 100, answered, len(holdout), accuracy * 100, correct, answered - correct,
    )
    for (truth, predicted), count in sorted(confusion.items(), key=lambda kv: -kv[1]):
        marker = "ok " if truth == predicted else "MISS"
        logger.info("  %s truth=%-5s predicted=%-5s  %d", marker, truth, predicted, count)


async def run(
    limit: int, k: int, threshold: float, min_similarity: float,
    min_neighbours: int, dry_run: bool, examples: int,
) -> None:
    logger = setup_logging("classify_dimension_local")
    async with async_session_factory() as db:
        known = await load_known(db)
        if len(known) < 50:
            logger.warning(
                "Only %d games have a tag/rule-derived dimension — too few to "
                "learn from. Run the collector and reclassify passes first.",
                len(known),
            )
            return
        unknown = await load_unknown(db, limit)
        if not unknown:
            logger.info("No unknown-dimension games left — nothing to do.")
            return

        logger.info(
            "Learning from %d settled games; %d unknown to resolve "
            "(k=%d, agreement>=%.0f%%, min similarity %.2f)%s",
            len(known), len(unknown), k, threshold * 100, min_similarity,
            " — DRY RUN, nothing will be written" if dry_run else "",
        )
        index = DimensionSimilarityIndex(known)
        logger.info(
            "TF-IDF index: %d documents × %d features",
            index.matrix.shape[0], index.matrix.shape[1],
        )

        resolved_by_dimension: dict[str, int] = defaultdict(int)
        disagreed = too_few = 0
        shown = 0

        for start in range(0, len(unknown), PREDICT_CHUNK):
            chunk = unknown[start : start + PREDICT_CHUNK]
            predictions = index.predict(
                [document for _, _, document in chunk],
                k=k, threshold=threshold,
                min_similarity=min_similarity, min_neighbours=min_neighbours,
            )
            for (appid, name, _), prediction in zip(chunk, predictions):
                if prediction.dimension is None:
                    if "disagree" in prediction.reason:
                        disagreed += 1
                    else:
                        too_few += 1
                    continue

                resolved_by_dimension[prediction.dimension.value] += 1
                if shown < examples:
                    shown += 1
                    neighbours = ", ".join(
                        f"{n.name[:28]} [{n.dimension.value}] {n.similarity:.2f}"
                        for n in prediction.neighbours
                    )
                    logger.info(
                        "example %d — %s (%s): unknown -> %s | %s | neighbours: %s",
                        shown, name[:40], appid, prediction.dimension.value,
                        prediction.reason, neighbours,
                    )
                if not dry_run:
                    await db.execute(
                        sa.update(Game)
                        .where(Game.appid == appid)
                        .values(
                            # Fill only: a value settled between selection and
                            # write (collector re-run, vision pass) wins.
                            dimension=sa.case(
                                (Game.dimension == Dimension.UNKNOWN, prediction.dimension),
                                else_=Game.dimension,
                            ),
                            dimension_source=sa.case(
                                (Game.dimension == Dimension.UNKNOWN, SOURCE_LABEL),
                                else_=Game.dimension_source,
                            ),
                        )
                    )
            if not dry_run:
                await db.commit()

        resolved = sum(resolved_by_dimension.values())
        breakdown = ", ".join(f"{d}: {n}" for d, n in sorted(resolved_by_dimension.items()))
        logger.info(
            "%s %d of %d unknown games (%s). Left unknown: %d neighbours "
            "disagreed, %d had no close enough neighbours.",
            "Would resolve" if dry_run else "Resolved",
            resolved, len(unknown), breakdown or "none", disagreed, too_few,
        )
        if dry_run:
            logger.info("Dry run — no rows were written. Re-run without --dry-run to apply.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill unknown 2D/3D dimensions from catalog similarity "
        "(offline TF-IDF; no API key, no network)"
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="max unknown games this run; 0 = all (default)")
    parser.add_argument("--k", type=int, default=DEFAULT_K,
                        help=f"nearest neighbours to consult (default {DEFAULT_K})")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"share of neighbours that must agree (default {DEFAULT_THRESHOLD})")
    parser.add_argument("--min-similarity", type=float, default=DEFAULT_MIN_SIMILARITY,
                        help=f"ignore neighbours below this cosine similarity "
                             f"(default {DEFAULT_MIN_SIMILARITY})")
    parser.add_argument("--min-neighbours", type=int, default=DEFAULT_MIN_NEIGHBOURS,
                        help=f"minimum close neighbours needed to decide "
                             f"(default {DEFAULT_MIN_NEIGHBOURS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, with examples, without writing")
    parser.add_argument("--examples", type=int, default=5,
                        help="how many before/after examples to log (default 5)")
    parser.add_argument("--self-check", action="store_true",
                        help="run the offline logic checks and exit (no database needed)")
    parser.add_argument("--validate", type=int, metavar="N", default=0,
                        help="hold out N games whose dimension is already known, "
                             "predict them and report coverage/accuracy instead of writing")
    parser.add_argument("--seed", type=int, default=20260813,
                        help="random seed for --validate sampling (reproducible runs)")
    args = parser.parse_args()

    if args.self_check:
        print("Self-check (synthetic data, no database, no network):")
        raise SystemExit(0 if self_check() else 1)

    if args.validate:
        asyncio.run(validate(
            args.validate, args.k, args.threshold,
            args.min_similarity, args.min_neighbours, args.seed,
        ))
        return

    asyncio.run(run(
        args.limit, args.k, args.threshold, args.min_similarity,
        args.min_neighbours, args.dry_run, args.examples,
    ))


if __name__ == "__main__":
    main()
