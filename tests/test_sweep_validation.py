"""Rank-sweep validation and rank derivation.

The dangerous failure this guards: a Valve markup change makes the parser
return zero rows without raising. An empty sweep marked 'complete' would flip
the whole catalogue to "Not ranked" overnight and manufacture enormous fake
rank deltas, because Step E differences against the newest complete sweep.
"""

from scraper.collectors.wishlist_rank import (
    MIN_PLAUSIBLE_ROWS,
    TOTAL_TOLERANCE,
    RankedApp,
    SweepResult,
    parse_rank_page,
    validate,
)


def result(entries, total, complete=True, dropped=0, dupes=0) -> SweepResult:
    return SweepResult(
        entries=entries, total_count=total, pages_fetched=1,
        dropped_non_app=dropped, dropped_duplicate=dupes,
        complete=complete, notes="",
    )


def rows(n: int, start: int = 1) -> list[RankedApp]:
    return [RankedApp(appid=1000 + i, rank=start + i, name=f"g{i}") for i in range(n)]


def test_full_sweep_is_complete():
    ok, problems = validate(result(rows(5228), 5228))
    assert ok, problems


def test_short_sweep_is_not_complete():
    """900 rows against total_count=5229 must not pass."""
    ok, problems = validate(result(rows(900), 5229))
    assert not ok
    assert "5229" in problems or "tolerance" in problems


def test_empty_sweep_is_rejected():
    """The markup-change case: zero rows, no exception."""
    ok, problems = validate(result([], 5228))
    assert not ok
    assert "data-ds-itemkey" in problems or str(MIN_PLAUSIBLE_ROWS) in problems


def test_incomplete_flag_alone_fails_validation():
    ok, _ = validate(result(rows(5228), 5228, complete=False))
    assert not ok


def test_small_drift_within_tolerance_passes():
    """The chart shifts under a multi-minute sweep; an exact match is not
    achievable and must not be required."""
    entries = rows(5228 - TOTAL_TOLERANCE + 1)
    ok, problems = validate(result(entries, 5228))
    assert ok, problems


def test_dropped_rows_count_toward_the_total():
    """Package rows and mid-sweep duplicates are legitimately absent from
    `entries` but still occupied a position, so they must be accounted for or
    a clean sweep looks short."""
    entries = rows(5220)
    ok, problems = validate(result(entries, 5228, dropped=5, dupes=3))
    assert ok, problems


# ------------------------------------------------------------ rank derivation --

PAGE = (
    '<a class="search_result_row" data-ds-itemkey="App_11"><span class="title">A</span></a>'
    '<a class="search_result_row" data-ds-itemkey="Sub_99"><span class="title">Pack</span></a>'
    '<a class="search_result_row" data-ds-itemkey="App_22"><span class="title">B</span></a>'
)


def test_rank_uses_the_echoed_start_not_the_requested_one():
    """The endpoint floors `start` to a multiple of `count`: requesting 150
    with count=100 returns start=100. Trusting the request misranks a page."""
    ranked, dropped = parse_rank_page(PAGE, returned_start=100)
    assert [r.rank for r in ranked] == [101, 103]
    assert dropped == 1


def test_package_row_leaves_a_gap_rather_than_shifting_ranks():
    """Sub_ rows occupy an ordinal on Valve's side, so positions after one
    must keep their true rank — compacting would shift every later game up."""
    ranked, _ = parse_rank_page(PAGE, returned_start=0)
    assert [(r.appid, r.rank) for r in ranked] == [(11, 1), (22, 3)]


def test_first_page_ranks_start_at_one():
    ranked, _ = parse_rank_page(PAGE, returned_start=0)
    assert ranked[0].rank == 1


def test_empty_html_yields_nothing_without_raising():
    ranked, dropped = parse_rank_page("", returned_start=0)
    assert ranked == [] and dropped == 0
