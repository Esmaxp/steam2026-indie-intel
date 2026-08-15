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


# --- bands (0017) ----------------------------------------------------------

def banded(source, low, mid, high, net_mid=None, copies=None):
    """An estimator row as workers/estimate_revenue.py writes it."""
    return RevenueEstimate(
        appid=1, source_name=source, status=DataStatus.ESTIMATED,
        revenue_usd=mid, revenue_min_usd=low, revenue_max_usd=high,
        net_revenue_usd=net_mid,
        net_min_usd=None if net_mid is None else net_mid / 2,
        net_max_usd=None if net_mid is None else net_mid * 2,
        estimated_sales=copies, copies_min=None if copies is None else copies // 2,
        copies_max=None if copies is None else copies * 2,
        source_url=f"https://{source}.tld/1",
    )


def test_the_merged_band_is_the_widest_any_source_claimed():
    """Two signals agreeing does not narrow an uncertainty nobody measured."""
    merged = merge_estimates([
        banded("reviews", 800, 1000, 1500),
        banded("followers", 600, 1100, 1300),
    ])
    assert (merged.gross_min_usd, merged.gross_max_usd) == (600.0, 1500.0)
    assert merged.gross_revenue_usd == 1050.0  # median of the mids, unchanged


def test_a_source_without_a_band_still_widens_the_span():
    """A legacy or disclosed row contributes its single value at both ends
    rather than dropping out of the span entirely."""
    merged = merge_estimates([banded("reviews", 800, 1000, 1200), est("legacy", revenue=5000.0)])
    assert merged.gross_max_usd == 5000.0


def test_net_and_copies_merge_the_same_way():
    merged = merge_estimates([
        banded("reviews", 800, 1000, 1200, net_mid=400, copies=100),
        banded("followers", 900, 1200, 1400, net_mid=600, copies=200),
    ])
    assert merged.net_revenue_usd == 500.0
    assert (merged.net_min_usd, merged.net_max_usd) == (200.0, 1200.0)
    assert (merged.sales_min, merged.estimated_sales, merged.sales_max) == (50, 150, 400)


def test_sources_used_counts_the_signals_behind_the_summary():
    assert merge_estimates([banded("reviews", 1, 2, 3)]).sources_used == 1
    assert merge_estimates([
        banded("reviews", 1, 2, 3), banded("ccu", 1, 2, 3), banded("followers", 1, 2, 3),
    ]).sources_used == 3


def test_a_cross_check_source_widens_the_band_without_moving_the_value():
    """CCU is fitted against the review estimator, so averaging it in would
    add no information about the level — only genre noise."""
    merged = merge_estimates([
        banded("reviews", 800, 1000, 1200),
        banded("ccu", 100, 4000, 9000),
    ])
    assert merged.gross_revenue_usd == 1000.0        # reviews alone
    assert (merged.gross_min_usd, merged.gross_max_usd) == (100.0, 9000.0)
    assert merged.sources_used == 2


def test_a_cross_check_moves_neither_gross_nor_net():
    """Regression: net was averaged across every source while gross used only
    the level-setting ones, so the two money columns disagreed about their own
    method. Palworld reported $440M gross and $940M net from the same row —
    its 2.1M peak concurrents put the CCU signal at 138M copies, and net (the
    column the revenue pie filters on) silently took half of that."""
    merged = merge_estimates([
        banded("reviews", 800, 1000, 1200, net_mid=600),
        banded("ccu", 100, 4000, 9000, net_mid=2400),
    ])
    assert merged.gross_revenue_usd == 1000.0
    assert merged.net_revenue_usd == 600.0


def test_a_disagreeing_cross_check_shows_in_the_spread_but_not_the_status():
    merged = merge_estimates([
        banded("reviews", 800, 1000, 1200),
        banded("ccu", 100, 4000, 9000),
    ])
    assert merged.estimate_spread == 3.0             # (4000-1000)/1000
    assert merged.status is DataStatus.ESTIMATED     # not a conflict


def test_a_cross_check_sets_the_level_when_it_is_all_there_is():
    """A weak estimate beats refusing to answer for a game we do have data on."""
    merged = merge_estimates([banded("ccu", 100, 500, 900)])
    assert merged.gross_revenue_usd == 500.0


def test_a_disclosure_reports_no_band_at_all():
    """Zero-width uncertainty would render as a measured range; None says
    plainly that this figure was not estimated."""
    merged = merge_estimates([
        est("disclosed", revenue=999.0, status=DataStatus.CONFIRMED),
        banded("reviews", 100, 200, 300),
    ])
    assert merged.status is DataStatus.CONFIRMED
    assert (merged.gross_min_usd, merged.gross_max_usd) == (None, None)
