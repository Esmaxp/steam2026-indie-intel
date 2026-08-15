"""Offline pass: turn measured signals into copies-sold and revenue bands.

Reads only columns already in the database — latest review count, latest peak
CCU, latest follower snapshot, list price, Early Access and release flags —
runs each estimator in app/services/revenue_estimate.py, and writes one
revenue_estimates row per signal that cleared its gate. The per-game summary
in revenue_records is then rebuilt from those rows by the same
merge_estimates() the disclosure CLI uses.

revenue_records is DERIVED, entirely and always: this worker deletes a
game's summary and rebuilds it from revenue_estimates. That is safe because
developer disclosures live in revenue_estimates too (written by
disclosed_numbers_source.py with source_name='disclosed'), and the merge
gives them outright priority. Disclosed rows are never deleted here; only
the estimator's own rows are replaced, which is what makes re-running after
a constant change cheap and lossless.

No network. No cost. Re-run it after any change to the multipliers.

Usage:
    python -m workers.estimate_revenue --dry-run
    python -m workers.estimate_revenue [--limit 0] [--examples 5]
    python -m workers.estimate_revenue --appid 123456
    docker compose run --rm estimate-revenue
"""

import argparse
import asyncio
from collections import defaultdict

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import (
    DataStatus,
    FollowerSnapshot,
    Game,
    RevenueEstimate,
    RevenueRecord,
)
from app.services import revenue_estimate as est
from app.services.games_query import latest_stats_sq
from scraper.collectors.revenue_merge import merge_estimates, record_values
from scraper.common.logging import setup_logging

BATCH_SIZE = 500
PROGRESS_EVERY = 5000
DISCLOSED = "disclosed"

# Where each signal was observed. The estimate is ours; the measurement is
# Steam's, and the row should point at the latter.
SOURCE_URLS = {
    est.SOURCE_REVIEWS: "https://store.steampowered.com/app/{appid}/",
    est.SOURCE_CCU: "https://steamcharts.com/app/{appid}",
    est.SOURCE_FOLLOWERS: "https://steamcommunity.com/app/{appid}",
}


def latest_followers_sq():
    """One row per game: the most recent follower snapshot."""
    return (
        sa.select(FollowerSnapshot.appid, FollowerSnapshot.followers)
        .distinct(FollowerSnapshot.appid)
        .order_by(FollowerSnapshot.appid, FollowerSnapshot.captured_at.desc())
        .subquery("latest_followers")
    )


def _rows_query(limit: int, only_appid: int | None):
    ls = latest_stats_sq()
    lf = latest_followers_sq()
    stmt = (
        sa.select(
            Game.appid,
            Game.name,
            Game.list_price_cents,
            Game.is_free,
            Game.early_access,
            Game.is_released,
            ls.c.total_reviews,
            ls.c.peak_ccu,
            lf.c.followers,
        )
        .select_from(Game)
        .outerjoin(ls, ls.c.appid == Game.appid)
        .outerjoin(lf, lf.c.appid == Game.appid)
        .order_by(Game.appid)
    )
    if only_appid is not None:
        stmt = stmt.where(Game.appid == only_appid)
    if limit:
        stmt = stmt.limit(limit)
    return stmt


def _estimate_row(appid: int, e: est.Estimate) -> RevenueEstimate:
    """One signal's answer as a database row, formula and inputs attached."""
    return RevenueEstimate(
        appid=appid,
        source_name=e.source,
        method=e.source,
        status=DataStatus.ESTIMATED,
        revenue_usd=e.gross_mid,
        revenue_min_usd=e.gross_low,
        revenue_max_usd=e.gross_high,
        net_revenue_usd=e.net_mid,
        net_min_usd=e.net_low,
        net_max_usd=e.net_high,
        estimated_sales=e.copies_mid,
        copies_min=e.copies_low,
        copies_max=e.copies_high,
        formula=e.formula,
        inputs=e.inputs,
        confidence=e.confidence,
        source_url=SOURCE_URLS[e.source].format(appid=appid),
    )


async def _disclosed_rows(db) -> dict[int, list[RevenueEstimate]]:
    """Developer disclosures, kept out of the delete-and-rebuild cycle."""
    rows = (
        await db.execute(
            sa.select(RevenueEstimate).where(RevenueEstimate.source_name == DISCLOSED)
        )
    ).scalars().all()
    by_appid: dict[int, list[RevenueEstimate]] = defaultdict(list)
    for row in rows:
        by_appid[row.appid].append(row)
    return by_appid


async def _flush(db, appids: list[int], estimates: list[RevenueEstimate], records: list[dict]):
    if not appids:
        return
    await db.execute(
        sa.delete(RevenueEstimate).where(
            RevenueEstimate.appid.in_(appids), RevenueEstimate.source_name != DISCLOSED
        )
    )
    await db.execute(sa.delete(RevenueRecord).where(RevenueRecord.appid.in_(appids)))
    db.add_all(estimates)
    if records:
        await db.execute(sa.insert(RevenueRecord), records)
    await db.commit()


async def run(limit: int, dry_run: bool, examples: int, only_appid: int | None) -> None:
    logger = setup_logging("estimate_revenue")

    async with async_session_factory() as db:
        rows = (await db.execute(_rows_query(limit, only_appid))).all()
        if not rows:
            logger.info("No games to estimate.")
            return
        disclosed = await _disclosed_rows(db)

        logger.info(
            "Estimating revenue for %d games%s", len(rows),
            " — DRY RUN, nothing will be written" if dry_run else "",
        )

        by_source: dict[str, int] = defaultdict(int)
        with_money = multi_signal = conflicting = 0
        spreads: list[float] = []
        pending_appids: list[int] = []
        pending_estimates: list[RevenueEstimate] = []
        pending_records: list[dict] = []
        shown = 0

        for index, row in enumerate(rows, start=1):
            estimates = est.estimate_all(
                est.RevenueInput(
                    total_reviews=row.total_reviews,
                    peak_ccu=row.peak_ccu,
                    followers=row.followers,
                    list_price_cents=row.list_price_cents,
                    is_free=bool(row.is_free),
                    early_access=bool(row.early_access),
                    is_released=bool(row.is_released),
                )
            )
            if not estimates and row.appid not in disclosed:
                # Nothing to say about this game. The delete below still runs
                # so a game that loses its signals also loses its estimate.
                pending_appids.append(row.appid)
                continue

            orm_rows = [_estimate_row(row.appid, e) for e in estimates]
            for e in estimates:
                by_source[e.source] += 1
            if len(estimates) > 1:
                multi_signal += 1

            merged = merge_estimates(orm_rows + disclosed.get(row.appid, []))
            pending_appids.append(row.appid)
            pending_estimates.extend(orm_rows)
            if merged is not None:
                pending_records.append({"appid": row.appid, **record_values(merged)})
                if merged.net_revenue_usd is not None:
                    with_money += 1
                if merged.estimate_spread is not None:
                    spreads.append(merged.estimate_spread)
                if merged.status is DataStatus.CONFLICTING:
                    conflicting += 1

                if shown < examples and merged.net_revenue_usd:
                    shown += 1
                    logger.info(
                        "example %d — %s (%s): %s copies, net $%s–$%s (mid $%s), %d signal(s)",
                        shown, row.name[:38], row.appid, merged.estimated_sales,
                        merged.net_min_usd, merged.net_max_usd,
                        merged.net_revenue_usd, merged.sources_used,
                    )

            if not dry_run and len(pending_appids) >= BATCH_SIZE:
                await _flush(db, pending_appids, pending_estimates, pending_records)
                pending_appids, pending_estimates, pending_records = [], [], []

            if index % PROGRESS_EVERY == 0:
                logger.info("Progress %d/%d", index, len(rows))

        if not dry_run:
            await _flush(db, pending_appids, pending_estimates, pending_records)

        spreads.sort()
        median_spread = spreads[len(spreads) // 2] if spreads else None
        logger.info("Estimates by signal: %s", dict(sorted(by_source.items())))
        logger.info(
            "Games with a revenue figure: %d | cross-checked by 2+ signals: %d "
            "| conflicting: %d | median spread: %s",
            with_money, multi_signal, conflicting,
            f"{median_spread:.0%}" if median_spread is not None else "n/a",
        )
        if dry_run:
            logger.info("Dry run — nothing written. Re-run without --dry-run to apply.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estimate copies sold and revenue from measured signals"
    )
    parser.add_argument("--limit", type=int, default=0, help="max games; 0 = all (default)")
    parser.add_argument("--appid", type=int, default=None, help="a single game")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the distribution without writing")
    parser.add_argument("--examples", type=int, default=5,
                        help="how many worked examples to log")
    args = parser.parse_args()
    asyncio.run(run(args.limit, args.dry_run, args.examples, args.appid))


if __name__ == "__main__":
    main()
