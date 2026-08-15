"""Offline pass: score both axes and label every game, with its reasoning.

Reads only columns already in the database, writes the two scores, the two
classes, the four-way classification and the confidence. No network, no cost,
re-runnable after any weight change — which is the point, because the weights
are a judgement call and the only honest way to hold one is to be able to
re-measure it.

Traction percentiles are computed in SQL against each game's release-month
cohort, for the same reason the genre chart does it (app/services/
success_bands.py): raw counts across months are not comparable.

This worker overwrites its own previous verdict — a classification is a derived
opinion, not an observation. It never touches a raw signal.

Usage:
    python -m workers.classify_games --dry-run
    python -m workers.classify_games [--limit 0] [--examples 5]
    docker compose run --rm classify
"""

import argparse
import asyncio
import datetime
from collections import defaultdict

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import (
    Game,
    GameChannels,
    MediaAsset,
    MediaType,
    SteamStats,
    game_developers,
    game_festivals,
)
from app.services import classification, effort_score, traction_score
from app.services.games_query import latest_rank_sq, latest_stats_sq
from scraper.common.logging import setup_logging

PROGRESS_EVERY = 5000


def _percentile(column, cohort):
    """Position within the release-month cohort; NULL rows stay NULL."""
    return sa.func.percent_rank().over(partition_by=cohort, order_by=column)


def _rows_query(limit: int):
    ls = latest_stats_sq()
    lrk = latest_rank_sq()
    cohort = sa.func.date_trunc("month", Game.release_date)

    trailers = (
        sa.select(sa.func.count())
        .select_from(MediaAsset)
        .where(MediaAsset.appid == Game.appid, MediaAsset.media_type == MediaType.MOVIE)
        .scalar_subquery()
    )
    screenshots = (
        sa.select(sa.func.count())
        .select_from(MediaAsset)
        .where(MediaAsset.appid == Game.appid, MediaAsset.media_type == MediaType.SCREENSHOT)
        .scalar_subquery()
    )
    next_fest = (
        sa.select(sa.func.count())
        .select_from(game_festivals)
        .where(game_festivals.c.appid == Game.appid)
        .scalar_subquery()
    )
    channels = (
        sa.select(sa.func.count())
        .select_from(GameChannels)
        .where(GameChannels.appid == Game.appid)
        .scalar_subquery()
    )

    stmt = (
        sa.select(
            Game.appid,
            Game.name,
            Game.is_released,
            Game.release_date,
            Game.list_price_cents,
            Game.is_free,
            Game.supported_languages,
            Game.website,
            Game.demo_available,
            Game.achievements_count,
            Game.short_description,
            Game.low_quality_signal,
            Game.limited_profile,
            Game.effort_class,
            trailers.label("trailers"),
            screenshots.label("screenshots"),
            next_fest.label("next_fest"),
            channels.label("channels"),
            # Traction: percentile against the same month's releases. A NULL
            # measure yields a NULL percentile, which the scorer reads as
            # "not observed" rather than "zero".
            _percentile(ls.c.total_reviews, cohort).label("reviews_pct"),
            _percentile(ls.c.peak_ccu, cohort).label("ccu_pct"),
            # Rank 1 is the best position, so invert: a low rank must map to a
            # high percentile.
            _percentile(sa.desc(lrk.c.rank), cohort).label("rank_pct"),
            ls.c.total_reviews,
            ls.c.peak_ccu,
            lrk.c.rank.label("wishlist_rank"),
        )
        .select_from(Game)
        .outerjoin(ls, ls.c.appid == Game.appid)
        .outerjoin(lrk, lrk.c.appid == Game.appid)
        .order_by(Game.appid)
    )
    if limit:
        stmt = stmt.limit(limit)
    return stmt


async def _developer_release_counts(db) -> dict[int, int]:
    """appid → releases by its busiest developer, in one query."""
    per_dev = (
        sa.select(
            game_developers.c.developer_id.label("developer_id"),
            sa.func.count().label("releases"),
        )
        .group_by(game_developers.c.developer_id)
        .subquery("per_dev")
    )
    rows = await db.execute(
        sa.select(game_developers.c.appid, sa.func.max(per_dev.c.releases))
        .join(per_dev, per_dev.c.developer_id == game_developers.c.developer_id)
        .group_by(game_developers.c.appid)
    )
    return {appid: releases for appid, releases in rows}


def _days_since(release_date, today: datetime.date) -> int | None:
    if release_date is None:
        return None
    return (today - release_date).days


async def run(limit: int, dry_run: bool, examples: int) -> None:
    logger = setup_logging("classify_games")
    today = datetime.date.today()

    async with async_session_factory() as db:
        rows = (await db.execute(_rows_query(limit))).all()
        if not rows:
            logger.info("No games to classify.")
            return
        dev_counts = await _developer_release_counts(db)

        logger.info(
            "Classifying %d games%s", len(rows),
            " — DRY RUN, nothing will be written" if dry_run else "",
        )

        labels: dict[str, int] = defaultdict(int)
        effort_classes: dict[str, int] = defaultdict(int)
        traction_classes: dict[str, int] = defaultdict(int)
        shown = 0

        for index, row in enumerate(rows, start=1):
            languages = row.supported_languages or []
            effort = effort_score.score(
                effort_score.EffortInput(
                    has_trailer=row.trailers > 0,
                    screenshot_count=row.screenshots,
                    list_price_cents=row.list_price_cents,
                    is_free=bool(row.is_free),
                    language_count=len(languages) if isinstance(languages, list) else 0,
                    has_website=bool((row.website or "").strip()),
                    demo_available=bool(row.demo_available),
                    achievements_count=row.achievements_count,
                    description_length=len(row.short_description or ""),
                    next_fest=row.next_fest > 0,
                    has_social_channels=row.channels > 0,
                    mass_published=bool(row.low_quality_signal),
                    developer_releases=dev_counts.get(row.appid, 0),
                    store_data_seen=row.limited_profile is not None,
                )
            )
            traction = traction_score.score(
                traction_score.TractionInput(
                    reviews_pct=row.reviews_pct if row.total_reviews else None,
                    wishlist_rank_pct=row.rank_pct if row.wishlist_rank else None,
                    peak_ccu_pct=row.ccu_pct if row.peak_ccu else None,
                    followers_pct=None,  # no follower sweep has run yet
                    days_since_release=_days_since(row.release_date, today),
                    is_released=bool(row.is_released),
                )
            )
            label = classification.classify(effort, traction)

            labels[label.label] += 1
            effort_classes[effort.effort_class] += 1
            traction_classes[traction.traction_class] += 1

            if shown < examples and label.label == classification.HIGH_EFFORT_LOW_TRACTION:
                shown += 1
                logger.info(
                    "overlooked %d — %s (%s): effort %d %s, traction %d, %s confidence",
                    shown, row.name[:38], row.appid, effort.score,
                    effort.signals, traction.score or 0, label.confidence,
                )

            if not dry_run:
                await db.execute(
                    sa.update(Game)
                    .where(Game.appid == row.appid)
                    .values(
                        effort_score=effort.score,
                        effort_class=effort.effort_class,
                        effort_signals={"score": effort.score, "signals": effort.signals},
                        traction_score=traction.score,
                        traction_class=traction.traction_class,
                        traction_status=traction.status,
                        traction_signals=traction.signals or None,
                        classification=label.label,
                        classification_confidence=label.confidence,
                    )
                )
            if index % PROGRESS_EVERY == 0:
                if not dry_run:
                    await db.commit()
                logger.info("Progress %d/%d", index, len(rows))

        if not dry_run:
            await db.commit()

        logger.info("Effort: %s", dict(sorted(effort_classes.items())))
        logger.info("Traction: %s", dict(sorted(traction_classes.items())))
        logger.info("Classification: %s", dict(sorted(labels.items())))
        if dry_run:
            logger.info("Dry run — nothing written. Re-run without --dry-run to apply.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score production effort and market traction, then label each game"
    )
    parser.add_argument("--limit", type=int, default=0, help="max games; 0 = all (default)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the distribution without writing")
    parser.add_argument("--examples", type=int, default=5,
                        help="how many serious-but-overlooked games to log (default 5)")
    args = parser.parse_args()
    asyncio.run(run(args.limit, args.dry_run, args.examples))


if __name__ == "__main__":
    main()
