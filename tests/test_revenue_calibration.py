"""Calibration against disclosed sales — mostly a test of restraint.

The dangerous failure here is not a wrong number, it is a confident one:
ten data points can make any factor look measured. These tests pin the
cases where the right answer is to change nothing.
"""

from app.services.revenue_calibration import (
    MIN_SAMPLE_TO_ACT,
    NEUTRAL_HIGH,
    NEUTRAL_LOW,
    DisclosedSale,
    calibrate,
)


def sale(actual, estimated, comparator="=", low=None, high=None, name="Game"):
    return DisclosedSale(
        appid=1, name=name, actual_copies=actual, comparator=comparator,
        estimated_copies=estimated,
        band_low=low if low is not None else int(estimated * 0.6),
        band_high=high if high is not None else int(estimated * 1.6),
    )


def test_no_disclosures_says_nothing():
    report = calibrate([])
    assert report.median_ratio is None
    assert report.proposed_factor == 1.0
    assert "cannot be measured" in report.verdict
    assert "no lower-bound disclosures" in report.bound_verdict


def test_a_centred_estimator_is_left_alone():
    report = calibrate([sale(1000, 1000), sale(2200, 2000), sale(900, 1000)])
    assert NEUTRAL_LOW <= report.median_ratio <= NEUTRAL_HIGH
    assert report.proposed_factor == 1.0
    assert "constants unchanged" in report.verdict


def test_a_small_biased_sample_reports_but_does_not_act():
    """Three points can show a direction; they cannot justify a correction."""
    report = calibrate([sale(3000, 1000), sale(2800, 1000), sale(3200, 1000)])
    assert report.median_ratio == 3.0
    assert report.proposed_factor == 1.0
    assert "too few to act on" in report.verdict


def test_a_large_biased_sample_proposes_one_global_scalar():
    rows = [sale(2000 + i, 1000) for i in range(MIN_SAMPLE_TO_ACT)]
    report = calibrate(rows)
    assert report.proposed_factor == report.median_ratio > NEUTRAL_HIGH
    assert "single global scalar" in report.verdict


def test_a_lower_bound_the_estimate_already_clears_is_not_comparable():
    """"over 5,000 copies" against an estimate of 20,000 proves nothing —
    the true figure could be anywhere above the bound."""
    report = calibrate([sale(5000, 20000, comparator=">=")])
    assert report.median_ratio is None
    assert report.bounds_checked == 1
    assert report.bound_violations == 0


def test_a_missed_lower_bound_is_a_violation_not_a_ratio():
    """"over 50,000" against an estimate of 10,000 proves an under-estimate.

    It must NOT feed the median: collecting only the bounds we failed and
    taking their median measures the subsample selected for failing, and
    would propose a correction the population never justified.
    """
    report = calibrate([sale(50000, 10000, comparator=">=")])
    assert report.median_ratio is None
    assert report.bound_violations == 1
    assert report.proposed_factor == 1.0
    assert "proven under-estimate" in report.bound_verdict


def test_bounds_never_leak_into_the_factor_even_in_bulk():
    """Sixteen missed bounds and no exact figures still propose nothing."""
    rows = [sale(50000, 10000, comparator=">=") for _ in range(16)]
    report = calibrate(rows)
    assert report.bound_violations == 16
    assert report.proposed_factor == 1.0
    assert report.median_ratio is None


def test_in_band_counts_disclosures_the_range_actually_contained():
    rows = [
        sale(1000, 1000, low=800, high=1200),    # inside
        sale(5000, 1000, low=800, high=1200),    # outside
    ]
    assert calibrate(rows).in_band == 1


def test_a_zero_estimate_cannot_produce_a_ratio():
    """Dividing by an estimate of zero would manufacture an infinite bias."""
    assert calibrate([sale(1000, 0)]).median_ratio is None
