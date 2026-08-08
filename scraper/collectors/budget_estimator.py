"""Budget estimation — two independent, auditable heuristics (promt.md §3).

No storefront exposes development budgets, so a budget is either:
- CONFIRMED: publicly disclosed, entered via the disclosed_numbers CLI, or
- an explicitly labeled heuristic estimate with its formula and inputs stored
  in budget_estimates (both methods shown; the reader judges).

Method a (team_cost):    team_size x dev_duration_months x regional_cost
  Inputs come only from disclosed sources (marketing_info.team_size/region/
  duration, entered by a human with a link). Any missing input -> no
  calculation, budget stays unknown.

Method b (revenue_ratio): gross_revenue x [0.20 .. 0.40]
  Only when the game's merged revenue status is confirmed or estimated
  (conflicting/unknown -> skipped).

CLI:  python -m scraper.collectors.budget_estimator [--appid X]
"""

import argparse
import asyncio
import logging
from dataclasses import dataclass

import sqlalchemy as sa

from app.db.session import async_session_factory
from app.models import BudgetEstimate, DataStatus, MarketingInfo, RevenueRecord
from scraper.collectors.budget_cost_tables import (
    COST_TABLE_SOURCE,
    MONTHLY_COST_PER_PERSON_USD,
    RATIO_SOURCE,
    REVENUE_TO_BUDGET_MAX_RATIO,
    REVENUE_TO_BUDGET_MIN_RATIO,
)

logger = logging.getLogger(__name__)

TEAM_COST_FORMULA = "team_size * dev_duration_months * monthly_cost_per_person(region)"
REVENUE_RATIO_FORMULA = (
    f"gross_revenue_usd * [{REVENUE_TO_BUDGET_MIN_RATIO}, {REVENUE_TO_BUDGET_MAX_RATIO}]"
)


@dataclass(frozen=True)
class BudgetResult:
    method: str
    budget_min_usd: float
    budget_max_usd: float
    formula: str
    inputs: dict
    source_name: str


def compute_team_cost(
    team_size: int | None, duration_months: int | None, region: str | None
) -> BudgetResult | None:
    """None unless every input is present — missing data is never guessed."""
    if not team_size or not duration_months or not region:
        return None
    monthly = MONTHLY_COST_PER_PERSON_USD.get(region.strip().lower())
    if monthly is None:
        return None
    total = float(team_size * duration_months * monthly)
    return BudgetResult(
        method="team_cost",
        budget_min_usd=total,
        budget_max_usd=total,
        formula=TEAM_COST_FORMULA,
        inputs={
            "team_size": team_size,
            "dev_duration_months": duration_months,
            "region": region,
            "monthly_cost_per_person_usd": monthly,
            "cost_table_source": COST_TABLE_SOURCE,
        },
        source_name="heuristic: team cost",
    )


def compute_revenue_ratio(
    gross_revenue_usd: float | None, revenue_status: DataStatus | None
) -> BudgetResult | None:
    if gross_revenue_usd is None or gross_revenue_usd <= 0:
        return None
    if revenue_status not in (DataStatus.CONFIRMED, DataStatus.ESTIMATED):
        return None  # conflicting/unknown revenue is no basis for a budget guess
    return BudgetResult(
        method="revenue_ratio",
        budget_min_usd=round(gross_revenue_usd * REVENUE_TO_BUDGET_MIN_RATIO, 2),
        budget_max_usd=round(gross_revenue_usd * REVENUE_TO_BUDGET_MAX_RATIO, 2),
        formula=REVENUE_RATIO_FORMULA,
        inputs={
            "gross_revenue_usd": gross_revenue_usd,
            "revenue_status": revenue_status.value,
            "min_ratio": REVENUE_TO_BUDGET_MIN_RATIO,
            "max_ratio": REVENUE_TO_BUDGET_MAX_RATIO,
            "ratio_source": RATIO_SOURCE,
        },
        source_name="heuristic: revenue ratio",
    )


async def recompute_budgets(only_appid: int | None = None) -> dict:
    computed = 0
    async with async_session_factory() as db:
        # Latest revenue summary per game (confirmed preferred, then newest).
        latest_revenue = (
            sa.select(RevenueRecord)
            .distinct(RevenueRecord.appid)
            .order_by(
                RevenueRecord.appid, RevenueRecord.status, RevenueRecord.recorded_at.desc()
            )
            .subquery()
        )
        stmt = sa.select(
            latest_revenue.c.appid,
            latest_revenue.c.gross_revenue_usd,
            latest_revenue.c.status,
        )
        if only_appid is not None:
            stmt = stmt.where(latest_revenue.c.appid == only_appid)
        revenue_rows = {
            appid: (gross, status)
            for appid, gross, status in (await db.execute(stmt)).all()
        }

        marketing_stmt = sa.select(
            MarketingInfo.appid,
            MarketingInfo.team_size,
            MarketingInfo.team_region,
            MarketingInfo.dev_duration_months,
        )
        if only_appid is not None:
            marketing_stmt = marketing_stmt.where(MarketingInfo.appid == only_appid)
        marketing_rows = {
            appid: (size, region, months)
            for appid, size, region, months in (await db.execute(marketing_stmt)).all()
        }

        appids = set(revenue_rows) | set(marketing_rows)
        for appid in sorted(appids):
            results: list[BudgetResult] = []
            if appid in marketing_rows:
                size, region, months = marketing_rows[appid]
                team_cost = compute_team_cost(size, months, region)
                if team_cost:
                    results.append(team_cost)
            if appid in revenue_rows:
                gross, status = revenue_rows[appid]
                ratio = compute_revenue_ratio(
                    float(gross) if gross is not None else None, status
                )
                if ratio:
                    results.append(ratio)
            if not results:
                continue
            # Recompute wholesale: heuristics are derived data, not history.
            await db.execute(
                sa.delete(BudgetEstimate).where(BudgetEstimate.appid == appid)
            )
            for result in results:
                db.add(
                    BudgetEstimate(
                        appid=appid,
                        method=result.method,
                        budget_min_usd=result.budget_min_usd,
                        budget_max_usd=result.budget_max_usd,
                        formula=result.formula,
                        inputs=result.inputs,
                        source_name=result.source_name,
                    )
                )
            computed += 1
        await db.commit()

    logger.info("Budget heuristics computed for %d games", computed)
    return {"games_with_budget_estimates": computed}


def main() -> None:
    from scraper.common.logging import setup_logging

    parser = argparse.ArgumentParser(description="Recompute budget heuristics")
    parser.add_argument("--appid", type=int, default=None)
    args = parser.parse_args()
    setup_logging("budget")
    asyncio.run(recompute_budgets(args.appid))


if __name__ == "__main__":
    main()
