"""Report how the estimator did against developer-disclosed copies sold.

Reads the CONFIRMED rows that disclosed_numbers_source.py writes (a human
read the announcement and supplied the URL), re-runs the estimator from the
game's stored signals, and prints the comparison. Writes nothing.

It writes nothing on purpose. The output is a proposal — "estimates read
under by a median factor of 1.8 across 9 disclosures" — and changing
CALIBRATION_FACTOR in app/services/revenue_estimate.py is a deliberate edit
by a person who has seen the table, not a side effect of running a script.

Usage:
    python -m workers.calibrate_revenue
    docker compose run --rm estimate-revenue python -m workers.calibrate_revenue
"""

import asyncio

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import DataStatus, Game, RevenueEstimate
from app.services import revenue_estimate as est
from app.services.revenue_calibration import DisclosedSale, calibrate
from app.services.games_query import latest_stats_sq
from scraper.common.logging import setup_logging
from workers.estimate_revenue import latest_followers_sq

DISCLOSED = "disclosed"


async def _load(db) -> list[DisclosedSale]:
    ls = latest_stats_sq()
    lf = latest_followers_sq()
    rows = await db.execute(
        sa.select(
            Game.appid,
            Game.name,
            Game.list_price_cents,
            Game.is_free,
            Game.early_access,
            Game.is_released,
            RevenueEstimate.estimated_sales,
            RevenueEstimate.inputs,
            ls.c.total_reviews,
            ls.c.peak_ccu,
            lf.c.followers,
        )
        .select_from(RevenueEstimate)
        .join(Game, Game.appid == RevenueEstimate.appid)
        .outerjoin(ls, ls.c.appid == Game.appid)
        .outerjoin(lf, lf.c.appid == Game.appid)
        .where(
            RevenueEstimate.source_name == DISCLOSED,
            RevenueEstimate.status == DataStatus.CONFIRMED,
            RevenueEstimate.estimated_sales.is_not(None),
        )
        .order_by(Game.appid)
    )

    out: list[DisclosedSale] = []
    for row in rows:
        estimate = est.from_reviews(
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
        if estimate is None:
            continue
        # The CLI stores the comparator in notes only for wishlists; a sales
        # row carries it in inputs when the harvester supplied one, and an
        # exact figure is the safe default.
        comparator = (row.inputs or {}).get("comparator", "=")
        out.append(
            DisclosedSale(
                appid=row.appid,
                name=row.name,
                actual_copies=int(row.estimated_sales),
                comparator=comparator,
                estimated_copies=estimate.copies_mid,
                band_low=estimate.copies_low,
                band_high=estimate.copies_high,
            )
        )
    return out


async def run() -> None:
    logger = setup_logging("calibrate_revenue")
    async with async_session_factory() as db:
        rows = await _load(db)

    if not rows:
        logger.info(
            "No disclosed sales figures yet. Add them with:\n"
            "  python -m scraper.collectors.disclosed_numbers_source --appid X "
            "--sales 50000 --source-url https://... --source-name 'Dev post'\n"
            "Candidates are in the sales_disclosures_*.csv written by "
            "workers.harvest_disclosures."
        )
        return

    report = calibrate(rows)
    logger.info("Disclosed sales compared: %d", report.sample)
    for name, ratio, in_band in report.rows:
        logger.info(
            "  %-40s actual/estimate = %.2f  %s",
            name[:40], ratio, "in band" if in_band else "OUTSIDE band",
        )
    logger.info(
        "Median ratio: %s (from %d exact disclosures) | inside their own band: %d/%d",
        report.median_ratio, report.exact_sample, report.in_band, report.sample,
    )
    logger.info("Verdict: %s", report.verdict)
    logger.info("Floor test: %s", report.bound_verdict)
    if report.proposed_factor != 1.0:
        logger.info(
            "To apply: set CALIBRATION_FACTOR = %s and CALIBRATION_SAMPLE = %d "
            "in app/services/revenue_estimate.py, then re-run "
            "workers.estimate_revenue.",
            report.proposed_factor, len(report.ratios),
        )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
