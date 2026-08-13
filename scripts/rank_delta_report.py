"""Measure Valve wishlist-rank volatility, so the noise floor is set from data.

Valve's Top-Wishlists position blends total wishlists with recent velocity,
so the ordering permutes on its own. Before the UI shows a "rank moved +N"
column it has to know how big a move has to be to mean anything — otherwise
it renders churn as signal.

This pairs consecutive COMPLETE sweeps and prints the |delta rank|
distribution by rank decile. Partial sweeps are excluded: an aborted run
holds only the head of the chart, so differencing against it reads as
"everything below rank N left the chart".

Run it against two sweeps roughly 24h apart before enabling the rank-delta
column by default. Intra-session churn does NOT predict day-over-day churn —
measured 2026-08-12, two sweeps 4 minutes apart moved 0.1% of rows at ranks
1-872 but 10% at ranks 4358-5228, so the floor is very likely rank-dependent.

Usage:
    docker compose run --rm rank_sweep python /srv/scripts/rank_delta_report.py
    python scripts/rank_delta_report.py [--deciles 10]
"""

import argparse
import asyncio

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import WishlistRankEntry, WishlistRankSweep


async def complete_sweeps() -> list[tuple[int, object, int]]:
    async with async_session_factory() as db:
        rows = await db.execute(
            sa.select(
                WishlistRankSweep.id,
                WishlistRankSweep.started_at,
                WishlistRankSweep.rows_ingested,
            )
            .where(WishlistRankSweep.status == "complete")
            .order_by(WishlistRankSweep.started_at)
        )
        return list(rows.all())


async def compare(older_id: int, newer_id: int, deciles: int) -> None:
    a = sa.orm.aliased(WishlistRankEntry, name="a")
    b = sa.orm.aliased(WishlistRankEntry, name="b")
    async with async_session_factory() as db:
        span = await db.execute(
            sa.select(
                sa.func.max(WishlistRankEntry.rank)
            ).where(WishlistRankEntry.sweep_id == older_id)
        )
        max_rank = span.scalar_one() or 1

        bucket = sa.func.width_bucket(a.rank, 1, max_rank + 1, deciles).label("bucket")
        delta = sa.func.abs(a.rank - b.rank)
        rows = await db.execute(
            sa.select(
                bucket,
                sa.func.min(a.rank),
                sa.func.max(a.rank),
                sa.func.count(),
                sa.func.count().filter(a.rank != b.rank),
                sa.func.round(sa.func.avg(delta), 2),
                sa.func.max(delta),
                sa.func.percentile_cont(0.95).within_group(delta.asc()),
            )
            .select_from(a)
            .join(b, sa.and_(b.appid == a.appid, b.sweep_id == newer_id))
            .where(a.sweep_id == older_id)
            .group_by(bucket)
            .order_by(bucket)
        )

        print(f"\n  {'ranks':>14} {'n':>6} {'moved':>7} {'%':>6} {'avg|d|':>7} {'p95':>6} {'max':>5}")
        print("  " + "-" * 56)
        for _, lo, hi, n, moved, avg_d, max_d, p95 in rows.all():
            pct = 100.0 * moved / n if n else 0.0
            print(
                f"  {lo:>6}-{hi:<7} {n:>6} {moved:>7} {pct:>5.1f}% "
                f"{float(avg_d):>7.2f} {float(p95 or 0):>6.1f} {max_d:>5}"
            )

        churn = await db.execute(
            sa.select(
                sa.func.count(),
                sa.func.count().filter(a.rank != b.rank),
                sa.func.max(delta),
            )
            .select_from(a)
            .join(b, sa.and_(b.appid == a.appid, b.sweep_id == newer_id))
            .where(a.sweep_id == older_id)
        )
        total, moved, worst = churn.one()
        left = await db.execute(
            sa.select(sa.func.count())
            .select_from(a)
            .where(
                a.sweep_id == older_id,
                ~sa.exists(
                    sa.select(1).select_from(b).where(
                        sa.and_(b.sweep_id == newer_id, b.appid == a.appid)
                    )
                ),
            )
        )
        print(
            f"\n  overall: {moved}/{total} moved ({100.0*moved/total:.1f}%), "
            f"max |delta| {worst}, {left.scalar_one()} left the chart"
        )
        print(
            "\n  Set RANK_DELTA_NOISE_FLOOR above the p95 of the band you intend to\n"
            "  display. A single global floor will over-suppress the head or\n"
            "  under-suppress the tail — prefer a per-band floor if they differ."
        )


async def main(deciles: int) -> None:
    sweeps = await complete_sweeps()
    if len(sweeps) < 2:
        print(
            f"Need 2 complete sweeps, found {len(sweeps)}.\n"
            "Run: docker compose run --rm rank_sweep  (then again ~24h later)"
        )
        return
    print(f"{len(sweeps)} complete sweeps available:")
    for sid, started, rows in sweeps:
        print(f"  id={sid}  {started:%Y-%m-%d %H:%M}  rows={rows}")

    for (older_id, older_at, _), (newer_id, newer_at, _) in zip(sweeps, sweeps[1:]):
        gap_h = (newer_at - older_at).total_seconds() / 3600
        print(f"\n=== sweep {older_id} -> {newer_id}  ({gap_h:.1f}h apart) ===")
        if gap_h < 12:
            print("  NOTE: under 12h apart — this does NOT predict day-over-day churn.")
        await compare(older_id, newer_id, deciles)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deciles", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(main(args.deciles))
