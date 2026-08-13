"""Throughput measurement for sweep ETAs.

Both behaviours pinned here were shipped wrong first, and both produced an ETA
that looked authoritative while being off by a factor of two or more. The
underlying awkwardness is that the follower worker commits every 50 rows, so
its timestamped trail is a series of spikes, not a smooth series — and every
naive reading of a spiky trail is biased.
"""

import datetime

from app.services.sweep_eta import _hit_ratio, rate_from_batches

T0 = datetime.datetime(2026, 8, 13, 12, 0, tzinfo=datetime.timezone.utc)


def batches(gaps_seconds: list[float], rows: int = 50):
    """A commit trail: `rows` written every gap. The first entry anchors the
    series and contributes no rate of its own."""
    out = [(T0, rows)]
    at = T0
    for gap in gaps_seconds:
        at = at + datetime.timedelta(seconds=gap)
        out.append((at, rows))
    return out


def test_steady_sweep_measures_its_true_rate():
    """50 rows every 200s is 0.25 rows/s, however the rows clump."""
    assert rate_from_batches(batches([200, 200, 200, 200])) == 0.25


def test_rows_are_charged_to_the_gap_that_produced_them():
    """The bug this replaced divided total rows by the span from first to last
    timestamp. That ignores the 200s which produced the first batch, so 250
    rows over an 800s span read as 0.31/s — a quarter too fast."""
    trail = batches([200, 200, 200, 200])
    total_rows = sum(rows for _, rows in trail)
    span = (trail[-1][0] - trail[0][0]).total_seconds()
    naive = total_rows / span

    assert naive > 0.3  # the old reading
    assert rate_from_batches(trail) == 0.25  # the true rate


def test_a_pause_inside_the_window_does_not_drag_the_rate_down():
    """A sweep paused for 20 minutes leaves one enormous gap. Averaging would
    report a rate several times too slow and an ETA of days; the median
    discards the idle stretch as the outlier it is."""
    paused = rate_from_batches(batches([200, 200, 1200, 200, 200]))
    assert paused == 0.25


def test_a_single_slow_batch_does_not_spike_the_rate():
    """Symmetric to the pause case: one unusually fast batch (a run of games
    with no hub, committed together) must not make the sweep look quick."""
    assert rate_from_batches(batches([200, 200, 20, 200, 200])) == 0.25


def test_too_few_batches_is_not_a_measurement():
    """Two commits is one interval. Reporting a 'measured' rate from it would
    dress up a single sample as throughput."""
    assert rate_from_batches(batches([200])) is None
    assert rate_from_batches([]) is None


def test_simultaneous_commits_are_skipped_not_divided_by_zero():
    trail = [(T0, 50), (T0, 50), (T0, 50), (T0, 50), (T0, 50)]
    assert rate_from_batches(trail) is None


def test_hit_ratio_converts_writes_to_visits():
    """Games with no community hub write nothing, so a write rate understates
    how fast the sweep is moving through the catalogue."""
    assert _hit_ratio({"processed": 100, "written": 76}) == 0.76


def test_hit_ratio_falls_back_before_the_run_has_evidence():
    """Not 1.0: assuming every game has a hub makes the sweep look slower than
    it is, and the fallback should not be the pessimistic end of the range."""
    assert _hit_ratio({}) == 0.75
    assert _hit_ratio({"processed": 3, "written": 3}) == 0.75
