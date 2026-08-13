"""Seconds-per-game, the pace behind every sweep ETA.

The estimate is remaining-games x seconds-per-game. Remaining comes from the
database; this file covers the other half.

It is reported by the worker rather than inferred, and that is the whole point.
An earlier version derived the pace from the rows the follower collector
wrote, which forced a division by the share of games that have a community
hub — a small, noisy sample early in a run. On a sweep whose real pace never
moved off 3.97s per game, that divisor reported anything from 13h to 26h.
"""

from app.services.sweep_eta import MIN_TIMING_SAMPLES, seconds_per_game


def test_pace_is_elapsed_over_games():
    assert seconds_per_game({"processed": 100, "elapsed": 397.0}) == 3.97


def test_pace_is_unknown_until_enough_games_are_timed():
    """One slow request out of three would set the pace for a 17-hour job."""
    assert seconds_per_game({"processed": 3, "elapsed": 30.0}) is None
    assert seconds_per_game({"processed": MIN_TIMING_SAMPLES, "elapsed": 100.0}) == 4.0


def test_pace_is_unknown_without_a_timing():
    """Runs from before the worker reported elapsed still have counters, and
    must fall back to the configured interval rather than divide by zero."""
    assert seconds_per_game({"processed": 400}) is None
    assert seconds_per_game({"processed": 400, "elapsed": 0}) is None
    assert seconds_per_game({}) is None


def test_a_batch_that_slowed_down_reports_the_slower_pace():
    """The point of measuring: if Steam throttles, the ETA has to follow it
    rather than keep quoting the configured interval."""
    assert seconds_per_game({"processed": 100, "elapsed": 1200.0}) == 12.0


def test_pace_ignores_time_parked_at_a_pause():
    """`elapsed` is the worker's active time, not wall-clock. A run paused for
    an hour mid-batch must not come back reporting an hour per game — the
    worker subtracts the parked duration before reporting."""
    active = {"processed": 100, "elapsed": 400.0}
    wall_clock_with_a_1h_pause = {"processed": 100, "elapsed": 400.0 + 3600}
    assert seconds_per_game(active) == 4.0
    assert seconds_per_game(wall_clock_with_a_1h_pause) == 40.0  # what NOT to report
