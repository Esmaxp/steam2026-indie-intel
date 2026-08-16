"""Cross-validation of multi-source revenue estimates (promt.md Section 2.2).

Rules:
- A Confirmed figure (developer/publisher disclosure) always wins outright.
- One Estimated source → passed through as-is (status=estimated).
- Two or more Estimated sources → the median of their revenue values becomes
  the summary; spread = (max - min) / median. Spread > 0.5 means the sources
  genuinely disagree → status=conflicting, and every source stays visible in
  the revenue_estimates table for the reader to judge.
- Owners are merged as a range: min of mins, max of maxes.
- Since 0017 each estimate is itself a band. The merged band is the widest
  one any source claimed (min of the lows, max of the highs) while the
  summary value stays the median of the mids: narrowing the band because
  two signals happened to agree would be a confidence nobody measured.
- Pure functions only — fully unit-testable without a database.
"""

import statistics
from dataclasses import dataclass

from app.models import DataStatus, RevenueEstimate

CONFLICT_SPREAD_THRESHOLD = 0.5

# Sources whose centring was borrowed from another signal rather than
# measured on its own. They widen the band and they count towards the
# reported spread, but they do not move the summary value: averaging in a
# number that was fitted to agree with another number adds no information
# about the level, and it lets a genre artefact drag the result around. Peak
# concurrency runs high for multiplayer and low for short narrative games at
# identical sales, so letting it set the level would systematically inflate
# one genre and deflate another.
#
# When a cross-check source is all a game has, it sets the level anyway —
# a weak estimate beats refusing to answer for a game we do have data on.
# That fallback is what makes this safe for followers: they are the only
# signal for roughly eight thousand games under the 10-review gate, and those
# games keep their estimate. What changes is that where reviews exist,
# reviews decide.
#
# Followers joined this set once the sweep covered the catalogue and the
# numbers could be compared. Their chain (followers -> wishlists -> sales) is
# two rules of thumb multiplied together, and re-centring it on the review
# estimator still left the two disagreeing by 1.39x-5.11x across the
# quartiles. A source whose centring is borrowed and whose per-game spread is
# nearly 4x cannot be allowed to pull the summary around; it can widen the
# band and show up in the spread, which is what it is good for.
CROSS_CHECK_SOURCES = frozenset({"ccu", "followers"})


@dataclass(frozen=True)
class MergedRevenue:
    status: DataStatus
    gross_revenue_usd: float | None
    gross_min_usd: float | None
    gross_max_usd: float | None
    net_revenue_usd: float | None
    net_min_usd: float | None
    net_max_usd: float | None
    estimated_sales: int | None
    sales_min: int | None
    sales_max: int | None
    owners_min: int | None
    owners_max: int | None
    sources_used: int
    source_name: str
    source_url: str | None
    estimate_spread: float | None  # (max-min)/median over revenue values
    notes: str | None


def record_values(merged: "MergedRevenue") -> dict:
    """MergedRevenue -> RevenueRecord column values.

    Shared so the disclosure CLI and the estimator worker cannot drift into
    writing the summary row two different ways.
    """
    return {
        "status": merged.status,
        "gross_revenue_usd": merged.gross_revenue_usd,
        "gross_min_usd": merged.gross_min_usd,
        "gross_max_usd": merged.gross_max_usd,
        "net_revenue_usd": merged.net_revenue_usd,
        "net_min_usd": merged.net_min_usd,
        "net_max_usd": merged.net_max_usd,
        "estimated_sales": merged.estimated_sales,
        "sales_min": merged.sales_min,
        "sales_max": merged.sales_max,
        "sources_used": merged.sources_used,
        "estimated_owners_min": merged.owners_min,
        "estimated_owners_max": merged.owners_max,
        "estimate_spread": merged.estimate_spread,
        "source_name": merged.source_name,
        "source_url": merged.source_url,
        "notes": merged.notes,
    }


def _median_int(values: list[int]) -> int | None:
    return int(statistics.median(values)) if values else None


def _median_float(values: list[float]) -> float | None:
    return round(float(statistics.median(values)), 2) if values else None


def _span(estimates: list[RevenueEstimate], low_attr: str, high_attr: str, mid_attr: str):
    """(min low, max high) across sources.

    A source that carries no band contributes its mid to both ends, so a
    disclosed figure or a legacy row still widens the span honestly instead
    of dropping out of it.
    """
    lows, highs = [], []
    for e in estimates:
        mid = getattr(e, mid_attr, None)
        low = getattr(e, low_attr, None)
        high = getattr(e, high_attr, None)
        if low is None:
            low = mid
        if high is None:
            high = mid
        if low is not None:
            lows.append(float(low))
        if high is not None:
            highs.append(float(high))
    return (min(lows) if lows else None, max(highs) if highs else None)


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
        # A disclosure is a figure, not a band: min and max stay None rather
        # than collapsing to the same number, so nothing downstream can plot
        # a zero-width uncertainty as if it had been estimated.
        return MergedRevenue(
            status=DataStatus.CONFIRMED,
            gross_revenue_usd=float(best.revenue_usd),
            gross_min_usd=None,
            gross_max_usd=None,
            net_revenue_usd=float(best.net_revenue_usd) if best.net_revenue_usd else None,
            net_min_usd=None,
            net_max_usd=None,
            estimated_sales=best.estimated_sales,
            sales_min=None,
            sales_max=None,
            owners_min=best.owners_min,
            owners_max=best.owners_max,
            sources_used=1,
            source_name=best.source_name,
            source_url=best.source_url,
            estimate_spread=None,
            notes="confirmed disclosure overrides estimates",
        )

    names = sorted({e.source_name for e in estimates})
    # Level-setting sources decide the summary value; everything with a
    # revenue figure decides the reported spread. They differ only when a
    # cross-check source is present alongside a measured one.
    level = [e for e in estimates if e.source_name not in CROSS_CHECK_SOURCES] or estimates
    revenues = sorted(float(e.revenue_usd) for e in level if e.revenue_usd is not None)
    all_revenues = sorted(
        float(e.revenue_usd) for e in estimates if e.revenue_usd is not None
    )
    sales = [e.estimated_sales for e in level if e.estimated_sales is not None]
    owners_mins = [e.owners_min for e in estimates if e.owners_min is not None]
    owners_maxs = [e.owners_max for e in estimates if e.owners_max is not None]
    first_url = next((e.source_url for e in estimates if e.source_url), None)

    owners_min = min(owners_mins) if owners_mins else None
    owners_max = max(owners_maxs) if owners_maxs else None
    # From `level`, exactly like revenues and sales. Reading this from every
    # source instead was a real bug: gross came out right while net was the
    # average of the level-setting value and the cross-check's, so the two
    # money columns disagreed about their own method. Palworld showed it —
    # $440M gross from reviews, but $940M net, because its 2.1M peak
    # concurrents put the CCU signal at 138M copies and that dragged the
    # median. net_revenue_usd is what the revenue pie filters on, so the
    # error was reaching the UI while gross looked correct beside it.
    nets = sorted(
        float(e.net_revenue_usd) for e in level if e.net_revenue_usd is not None
    )
    gross_span = _span(estimates, "revenue_min_usd", "revenue_max_usd", "revenue_usd")
    net_span = _span(estimates, "net_min_usd", "net_max_usd", "net_revenue_usd")
    sales_span = _span(estimates, "copies_min", "copies_max", "estimated_sales")
    sales_min = int(sales_span[0]) if sales_span[0] is not None else None
    sales_max = int(sales_span[1]) if sales_span[1] is not None else None

    if not revenues:
        if owners_min is None and owners_max is None and not sales:
            return None
        return MergedRevenue(
            status=DataStatus.ESTIMATED,
            gross_revenue_usd=None,
            gross_min_usd=None,
            gross_max_usd=None,
            net_revenue_usd=None,
            net_min_usd=None,
            net_max_usd=None,
            estimated_sales=_median_int(sales),
            sales_min=sales_min,
            sales_max=sales_max,
            owners_min=owners_min,
            owners_max=owners_max,
            sources_used=len(estimates),
            source_name=" + ".join(names),
            source_url=first_url,
            estimate_spread=None,
            notes="owners/sales only — no revenue estimate from any source",
        )

    median_revenue = statistics.median(revenues)
    spread = None
    status = DataStatus.ESTIMATED
    if len(all_revenues) >= 2 and median_revenue > 0:
        # Reported over every source, so a cross-check that disagrees is
        # visible in the number even though it did not move the value.
        spread = round((all_revenues[-1] - all_revenues[0]) / median_revenue, 3)
    if len(revenues) >= 2 and median_revenue > 0:
        # But only sources that actually set the level can put the summary
        # into conflict — a cross-check disagreeing is expected, not a fault.
        level_spread = (revenues[-1] - revenues[0]) / median_revenue
        if level_spread > CONFLICT_SPREAD_THRESHOLD:
            status = DataStatus.CONFLICTING

    label = " + ".join(names)
    if status == DataStatus.CONFLICTING:
        label += " (conflicting)"

    return MergedRevenue(
        status=status,
        gross_revenue_usd=float(median_revenue),
        gross_min_usd=gross_span[0],
        gross_max_usd=gross_span[1],
        net_revenue_usd=_median_float(nets),
        net_min_usd=net_span[0],
        net_max_usd=net_span[1],
        estimated_sales=_median_int(sales),
        sales_min=sales_min,
        sales_max=sales_max,
        owners_min=owners_min,
        owners_max=owners_max,
        sources_used=len(estimates),
        source_name=label,
        source_url=first_url,
        estimate_spread=spread,
        notes=(
            f"median of {len(revenues)} level-setting estimate(s)"
            + (
                f", cross-checked by {len(all_revenues) - len(revenues)}"
                if len(all_revenues) > len(revenues)
                else ""
            )
            + (f"; spread={spread:.0%}" if spread is not None else "")
        ),
    )
