"""Cross-validation of multi-source revenue estimates (promt.md Section 2.2).

Rules:
- A Confirmed figure (developer/publisher disclosure) always wins outright.
- One Estimated source → passed through as-is (status=estimated).
- Two or more Estimated sources → the median of their revenue values becomes
  the summary; spread = (max - min) / median. Spread > 0.5 means the sources
  genuinely disagree → status=conflicting, and every source stays visible in
  the revenue_estimates table for the reader to judge.
- Owners are merged as a range: min of mins, max of maxes.
- Pure functions only — fully unit-testable without a database.
"""

import statistics
from dataclasses import dataclass

from app.models import DataStatus, RevenueEstimate

CONFLICT_SPREAD_THRESHOLD = 0.5


@dataclass(frozen=True)
class MergedRevenue:
    status: DataStatus
    gross_revenue_usd: float | None
    estimated_sales: int | None
    owners_min: int | None
    owners_max: int | None
    source_name: str
    source_url: str | None
    estimate_spread: float | None  # (max-min)/median over revenue values
    notes: str | None


def _median_int(values: list[int]) -> int | None:
    return int(statistics.median(values)) if values else None


def merge_estimates(estimates: list[RevenueEstimate]) -> MergedRevenue | None:
    """Merge one game's estimate rows (typically from a single collector run)."""
    if not estimates:
        return None

    confirmed = [
        e for e in estimates
        if e.status == DataStatus.CONFIRMED and e.revenue_usd is not None
    ]
    if confirmed:
        best = confirmed[0]
        return MergedRevenue(
            status=DataStatus.CONFIRMED,
            gross_revenue_usd=float(best.revenue_usd),
            estimated_sales=best.estimated_sales,
            owners_min=best.owners_min,
            owners_max=best.owners_max,
            source_name=best.source_name,
            source_url=best.source_url,
            estimate_spread=None,
            notes="confirmed disclosure overrides estimates",
        )

    names = sorted({e.source_name for e in estimates})
    revenues = sorted(float(e.revenue_usd) for e in estimates if e.revenue_usd is not None)
    sales = [e.estimated_sales for e in estimates if e.estimated_sales is not None]
    owners_mins = [e.owners_min for e in estimates if e.owners_min is not None]
    owners_maxs = [e.owners_max for e in estimates if e.owners_max is not None]
    first_url = next((e.source_url for e in estimates if e.source_url), None)

    owners_min = min(owners_mins) if owners_mins else None
    owners_max = max(owners_maxs) if owners_maxs else None

    if not revenues:
        if owners_min is None and owners_max is None and not sales:
            return None
        return MergedRevenue(
            status=DataStatus.ESTIMATED,
            gross_revenue_usd=None,
            estimated_sales=_median_int(sales),
            owners_min=owners_min,
            owners_max=owners_max,
            source_name=" + ".join(names),
            source_url=first_url,
            estimate_spread=None,
            notes="owners/sales only — no revenue estimate from any source",
        )

    median_revenue = statistics.median(revenues)
    spread = None
    status = DataStatus.ESTIMATED
    if len(revenues) >= 2 and median_revenue > 0:
        spread = round((revenues[-1] - revenues[0]) / median_revenue, 3)
        if spread > CONFLICT_SPREAD_THRESHOLD:
            status = DataStatus.CONFLICTING

    label = " + ".join(names)
    if status == DataStatus.CONFLICTING:
        label += " (conflicting)"

    return MergedRevenue(
        status=status,
        gross_revenue_usd=float(median_revenue),
        estimated_sales=_median_int(sales),
        owners_min=owners_min,
        owners_max=owners_max,
        source_name=label,
        source_url=first_url,
        estimate_spread=spread,
        notes=(
            f"median of {len(revenues)} revenue estimates"
            + (f"; spread={spread:.0%}" if spread is not None else "")
        ),
    )
