"""Manually verified, publicly disclosed figures (promt.md §2.1 priority 1).

Developer blog posts, press releases, GDC talks and Kickstarter updates carry
exact figures, but they cannot be scraped reliably — a human verifies the
source and enters it here. Everything written by this CLI is CONFIRMED and
requires a source URL.

Examples:
  python -m scraper.collectors.disclosed_numbers_source --appid 123 \
      --revenue 250000 --sales 21000 \
      --source-url https://dev.blog/postmortem --source-name "Dev post-mortem"

  python -m scraper.collectors.disclosed_numbers_source --appid 123 \
      --budget 120000 --source-url https://kickstarter.com/... \
      --source-name "Kickstarter campaign total"

  python -m scraper.collectors.disclosed_numbers_source --appid 123 \
      --team-size 4 --region eastern_europe --dev-months 26 \
      --source-url https://interview... --source-name "Team interview"

After writing, revenue is re-merged into the summary (confirmed wins) and
budget heuristics are recomputed for that game.
"""

import argparse
import asyncio

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.session import async_session_factory
from app.models import (
    DataStatus,
    Game,
    MarketingInfo,
    RevenueEstimate,
    RevenueRecord,
    WishlistRecord,
)
from scraper.collectors.budget_cost_tables import MONTHLY_COST_PER_PERSON_USD
from scraper.collectors.budget_estimator import recompute_budgets
from scraper.collectors.revenue_merge import merge_estimates, record_values


async def apply(args: argparse.Namespace) -> None:
    async with async_session_factory() as db:
        exists = (
            await db.execute(sa.select(Game.appid).where(Game.appid == args.appid))
        ).scalar_one_or_none()
        if exists is None:
            raise SystemExit(f"appid {args.appid} is not in the catalog")

        if args.revenue is not None or args.sales is not None:
            db.add(
                RevenueEstimate(
                    appid=args.appid,
                    source_name="disclosed",
                    status=DataStatus.CONFIRMED,
                    revenue_usd=args.revenue,
                    estimated_sales=args.sales,
                    source_url=args.source_url,
                    # Most disclosures are round lower bounds ("over 1 million
                    # copies"), and recording one as an exact figure would
                    # overstate what was said AND bias any calibration
                    # downward — the estimator would look high against a floor
                    # it actually cleared. app.services.revenue_calibration
                    # reads this key and keeps bounds out of the ratio.
                    inputs={"comparator": args.comparator},
                )
            )
            await db.flush()
            rows = (
                (
                    await db.execute(
                        sa.select(RevenueEstimate).where(
                            RevenueEstimate.appid == args.appid
                        )
                    )
                )
                .scalars()
                .all()
            )
            merged = merge_estimates(rows)
            if merged:
                db.add(
                    RevenueRecord(appid=args.appid, **record_values(merged))
                )
            print(f"Confirmed revenue recorded for {args.appid}")

        if args.wishlist is not None:
            db.add(
                WishlistRecord(
                    appid=args.appid,
                    status=DataStatus.CONFIRMED,
                    wishlist_count=args.wishlist,
                    source_name=args.source_name,
                    source_url=args.source_url,
                    notes=args.notes,
                )
            )
            print(f"Confirmed wishlist recorded for {args.appid}")

        marketing_values: dict = {}
        if args.budget is not None:
            marketing_values.update(
                budget_estimate_usd=args.budget,
                budget_status=DataStatus.CONFIRMED,
            )
        if args.team_size is not None:
            marketing_values["team_size"] = args.team_size
        if args.region is not None:
            marketing_values["team_region"] = args.region
        if args.dev_months is not None:
            marketing_values["dev_duration_months"] = args.dev_months
        if args.notes:
            marketing_values["marketing_notes"] = args.notes
        if marketing_values:
            marketing_values.update(
                source_name=args.source_name, source_url=args.source_url
            )
            stmt = pg_insert(MarketingInfo).values(appid=args.appid, **marketing_values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[MarketingInfo.appid], set_=marketing_values
            )
            await db.execute(stmt)
            print(f"Marketing/budget info updated for {args.appid}")

        await db.commit()

    await recompute_budgets(args.appid)
    print("Budget heuristics recomputed.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enter a human-verified disclosed figure (always Confirmed)"
    )
    parser.add_argument("--appid", type=int, required=True)
    parser.add_argument("--revenue", type=float, help="gross revenue USD")
    parser.add_argument("--sales", type=int, help="units sold")
    parser.add_argument(
        "--comparator", choices=("=", ">="), default="=",
        help="'>=' when the source states a lower bound ('over 1 million'), "
        "which is how most milestone posts are phrased",
    )
    parser.add_argument("--wishlist", type=int, help="wishlist count")
    parser.add_argument("--budget", type=float, help="development budget USD")
    parser.add_argument("--team-size", type=int, dest="team_size")
    parser.add_argument(
        "--region", choices=sorted(MONTHLY_COST_PER_PERSON_USD), dest="region"
    )
    parser.add_argument("--dev-months", type=int, dest="dev_months")
    parser.add_argument("--source-url", required=True, dest="source_url")
    parser.add_argument("--source-name", required=True, dest="source_name")
    parser.add_argument("--notes", default=None)
    args = parser.parse_args()

    if not any(
        v is not None
        for v in (args.revenue, args.sales, args.wishlist, args.budget,
                  args.team_size, args.region, args.dev_months)
    ):
        parser.error("provide at least one figure to record")

    asyncio.run(apply(args))


if __name__ == "__main__":
    main()
