"""merge_estimates — pinning the module that has claimed since day one to be
"fully unit-testable without a database" and had never been tested.

It still matters after the vendor retirement: disclosed_numbers_source.py
routes human-verified developer disclosures through this same function, and
the confirmed-wins branch is exactly the semantics the first-party policy
depends on.
"""

import pytest

from app.models import DataStatus, RevenueEstimate
from scraper.collectors.revenue_merge import CONFLICT_SPREAD_THRESHOLD, merge_estimates


def est(source, revenue=None, sales=None, omin=None, omax=None, status=DataStatus.ESTIMATED):
    """A RevenueEstimate built in memory — never flushed, no DB involved."""
    return RevenueEstimate(
        appid=1, source_name=source, status=status, revenue_usd=revenue,
        estimated_sales=sales, owners_min=omin, owners_max=omax,
        source_url=f"https://{source}.tld/1",
    )


def test_empty_returns_none():
    assert merge_estimates([]) is None


def test_confirmed_wins_outright():
    merged = merge_estimates([
        est("vendor", revenue=100.0),
        est("disclosed", revenue=999.0, status=DataStatus.CONFIRMED),
    ])
    assert merged.status is DataStatus.CONFIRMED
    assert merged.gross_revenue_usd == 999.0
    assert merged.estimate_spread is None
    assert "confirmed disclosure overrides" in merged.notes


def test_confirmed_without_a_revenue_value_does_not_win():
    """The confirmed branch requires an actual figure; otherwise the estimates
    still have to be merged."""
    merged = merge_estimates([
        est("disclosed", revenue=None, status=DataStatus.CONFIRMED),
        est("vendor", revenue=50.0),
    ])
    assert merged.status is DataStatus.ESTIMATED
    assert merged.gross_revenue_usd == 50.0


def test_single_estimate_passthrough():
    merged = merge_estimates([est("a", revenue=1000.0, sales=10)])
    assert merged.status is DataStatus.ESTIMATED
    assert merged.gross_revenue_usd == 1000.0
    assert merged.estimate_spread is None  # a lone source cannot disagree


def test_median_of_three():
    merged = merge_estimates([
        est("a", revenue=100.0), est("b", revenue=200.0), est("c", revenue=300.0),
    ])
    assert merged.gross_revenue_usd == 200.0
    assert merged.status is DataStatus.CONFLICTING  # spread 1.0 > 0.5


def test_agreeing_sources_stay_estimated():
    merged = merge_estimates([est("a", revenue=100.0), est("b", revenue=110.0)])
    assert merged.status is DataStatus.ESTIMATED
    assert merged.estimate_spread == pytest.approx(0.095, abs=0.001)
    assert "(conflicting)" not in merged.source_name


def test_spread_at_the_threshold_is_not_conflicting():
    """Boundary: the rule is spread > threshold, not >=."""
    # median 100, min 75, max 125 -> spread exactly 0.5
    merged = merge_estimates([
        est("a", revenue=75.0), est("b", revenue=100.0), est("c", revenue=125.0),
    ])
    assert merged.estimate_spread == CONFLICT_SPREAD_THRESHOLD
    assert merged.status is DataStatus.ESTIMATED


def test_spread_just_past_the_threshold_conflicts():
    merged = merge_estimates([
        est("a", revenue=74.0), est("b", revenue=100.0), est("c", revenue=126.0),
    ])
    assert merged.estimate_spread > CONFLICT_SPREAD_THRESHOLD
    assert merged.status is DataStatus.CONFLICTING
    assert merged.source_name.endswith("(conflicting)")


def test_owners_merge_as_a_range():
    merged = merge_estimates([
        est("a", revenue=10.0, omin=0, omax=20000),
        est("b", revenue=10.0, omin=5000, omax=50000),
    ])
    assert (merged.owners_min, merged.owners_max) == (0, 50000)


def test_owners_only_rows_produce_a_summary_without_revenue():
    """The branch that produced every revenue_record in the shipped database:
    SteamSpy supplied owner buckets and nothing else."""
    merged = merge_estimates([est("steamspy", omin=0, omax=20000)])
    assert merged.status is DataStatus.ESTIMATED
    assert merged.gross_revenue_usd is None
    assert (merged.owners_min, merged.owners_max) == (0, 20000)
    assert "owners/sales only" in merged.notes


def test_rows_with_no_usable_values_return_none():
    assert merge_estimates([est("a")]) is None
