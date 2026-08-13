"""The band boundaries, which decide what "top 10%" is allowed to mean."""

import pytest

from app.services.success_bands import (
    BASELINE_SHARE,
    SUCCESS_BANDS,
    band_for,
    over_index,
)


@pytest.mark.parametrize(
    ("label", "percent_rank", "expected"),
    [
        ("the very top", 1.0, "top_1"),
        ("exactly at the top-1% bar", 0.99, "top_1"),
        ("just below the top-1% bar", 0.9899, "top_10"),
        ("exactly at the top-10% bar", 0.90, "top_10"),
        ("just below the top-10% bar", 0.8999, "top_25"),
        ("exactly at the top-25% bar", 0.75, "top_25"),
        ("exactly at the median", 0.50, "upper_half"),
        ("just below the median", 0.4999, "lower_half"),
        ("the very bottom", 0.0, "lower_half"),
    ],
)
def test_boundaries_are_inclusive_at_the_lower_bound(label, percent_rank, expected):
    assert band_for(percent_rank).key == expected, label


def test_every_band_is_reachable():
    reached = {band_for(pr).key for pr in (1.0, 0.95, 0.8, 0.6, 0.1)}
    assert reached == {band.key for band in SUCCESS_BANDS}


def test_bands_are_ordered_best_first():
    thresholds = [band.min_percentile for band in SUCCESS_BANDS]
    assert thresholds == sorted(thresholds, reverse=True)


def test_baselines_cover_every_band_and_sum_to_one():
    assert set(BASELINE_SHARE) == {band.key for band in SUCCESS_BANDS}
    assert sum(BASELINE_SHARE.values()) == pytest.approx(1.0)


def test_baseline_matches_the_band_width():
    """A band's expected share is the gap between its bar and the next one up.

    If these ever drift apart, "over-indexes" becomes a lie: the comparison
    would be against a baseline the bands cannot actually produce.
    """
    upper = 1.0
    for band in SUCCESS_BANDS:
        assert BASELINE_SHARE[band.key] == pytest.approx(upper - band.min_percentile)
        upper = band.min_percentile


def test_over_index_reports_multiples_of_the_average():
    assert over_index(0.169, "top_10") == pytest.approx(1.88, abs=0.01)
    assert over_index(0.09, "top_10") == pytest.approx(1.0)
    assert over_index(0.045, "top_10") == pytest.approx(0.5)


def test_over_index_is_none_for_an_unknown_band():
    assert over_index(0.5, "not_a_band") is None
