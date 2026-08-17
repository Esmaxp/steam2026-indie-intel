"""Guardrails on the market surface the analyst agent reads.

The failure mode this file targets is not a crash. It is an agent drawing a
confident commercial conclusion from a number that does not support it —
reading a thin sample as a trend, an empty list as an empty market, or a
descriptive comparison as a causal one. Those are invisible in a JSON payload
unless the payload says otherwise, so what is tested here is mostly whether it
still says otherwise.
"""

from app.api.v1 import market as market_api
from app.services import market
from workers import scheduler


def test_price_bands_do_not_overlap_or_gap():
    """A game must land in exactly one band, or the shares stop summing."""
    import itertools

    bands = [b for b in market.PRICE_BANDS if b[0] != "free"]
    for (_, _, high), (_, next_low, _) in itertools.pairwise(bands):
        assert high is not None
        assert next_low == high + 1


def test_facet_row_flags_a_sample_too_thin_to_read():
    """A tag with four rankable games can show a 50% top-decile share. Without
    the warning an agent reports that as the best-performing space on Steam."""
    thin = market._facet_row(
        _row(games=6, ranked_sample=4, top_decile=2),
    )
    assert thin["top_decile_share"] == 0.5
    assert thin["sample_warning"] is not None
    assert "4" in thin["sample_warning"]


def test_facet_row_leaves_a_healthy_sample_unflagged():
    healthy = market._facet_row(_row(games=900, ranked_sample=800, top_decile=80))
    assert healthy["top_decile_share"] == 0.1
    assert healthy["sample_warning"] is None


def test_facet_row_reports_no_share_rather_than_zero_when_nothing_is_rankable():
    """An all-unreleased tag has no outcomes. Zero would read as "everything
    here fails"; null reads as "not measurable", which is the truth."""
    unreleased = market._facet_row(_row(games=40, ranked_sample=0, top_decile=None))
    assert unreleased["top_decile_share"] is None
    assert unreleased["outcome_sample"] == 0


def test_coverage_notes_warn_when_momentum_cannot_be_measured():
    """The dangerous reading of an empty trending list is "the market is
    quiet". The note has to rule that out explicitly."""
    notes = " ".join(market._coverage_notes(follower_delta=0, rank_delta=0))
    assert "NOT that demand is flat" in notes
    assert "7 days old" in notes


def test_coverage_notes_drop_the_warnings_once_the_signal_exists():
    notes = " ".join(market._coverage_notes(follower_delta=900, rank_delta=4000))
    assert "NOT that demand is flat" not in notes
    assert "review" in notes.lower()  # the dense-signal note always stands


def test_every_design_axis_is_callable():
    """The axis list is advertised in the manifest and validated against, so a
    name that does not resolve is a 500 waiting for whoever tries it."""
    for name, factory in market.DESIGN_AXES.items():
        assert factory() is not None, name


def test_manifest_states_the_limits_on_the_derived_numbers():
    """The provenance model is the whole point: an agent optimising for a
    confident answer will state a derived figure as a fact unless told not to,
    in the payload, every time.

    Wishlists are never estimated. Revenue IS, since upstream added a
    first-party estimator — but only as a band, so the rule has to say "quote
    the band" rather than the older "no revenue figure exists", which the
    merge made false.
    """
    rules = " ".join(_manifest_rules()).lower()
    assert "no wishlist count is estimated" in rules
    assert "range" in rules and "never its midpoint" in rules
    assert "descriptive, not causal" in rules


def _manifest_rules() -> list[str]:
    """The rules block, read out of the endpoint's own source of truth rather
    than restated here — a copy would pass this test forever after the real
    text drifted."""
    import inspect

    source = inspect.getsource(market_api.manifest)
    start = source.index("rules=[")
    end = source.index("],", start)
    return [source[start:end]]


def _row(*, games: int, ranked_sample: int, top_decile: int | None):
    """A stand-in for one SQLAlchemy result row."""

    class Row:
        key = "test"
        released = games
        upcoming = 0
        median_reviews = 10
        p90_reviews = 100
        median_price_cents = 999
        with_followers = 0
        median_followers = None
        on_chart = 0
        best_rank = None

    row = Row()
    row.games = games
    row.ranked_sample = ranked_sample
    row.top_decile = top_decile
    return row


# --- trending ranking ------------------------------------------------------
#
# The released ranking multiplies velocity by a Wilson lower bound. Both terms
# earn their place, and these pin why: without the divisor the list is a
# leaderboard of the biggest games, and without the bound a fast, badly
# received game outranks a slower, well-received one.


def test_wilson_discounts_a_tiny_sample_far_below_its_raw_rate():
    """5 reviews, all positive, is not evidence of a 100% game."""
    assert market.wilson_lower_bound(5, 5) < 0.6
    assert market.wilson_lower_bound(5, 5) > 0.4


def test_wilson_lets_a_large_sample_keep_almost_all_of_its_rate():
    assert market.wilson_lower_bound(1840, 2000) > 0.90  # 92% raw


def test_a_perfect_tiny_sample_cannot_outrank_a_large_strong_one():
    """The ordering this protects: a 5-review game must not head the trending
    list ahead of a 2,000-review game at 92%."""
    assert market.wilson_lower_bound(5, 5) < market.wilson_lower_bound(1840, 2000)


def test_wilson_is_zero_when_there_is_nothing_to_measure():
    assert market.wilson_lower_bound(0, 0) == 0.0


def test_wilson_punishes_a_poorly_received_game():
    """~50% positive should roughly halve a game's velocity, which is what
    keeps a fast but disliked launch off the top of the list."""
    assert 0.45 < market.wilson_lower_bound(500, 1000) < 0.53


def test_smoothing_stops_a_launch_day_game_dominating_on_one_day_of_noise():
    """20 reviews on day one is 20/day undivided — enough to outrank a game
    doing 15/day sustained. The smoothing term makes it 2.5."""
    raw = 20 / 1
    smoothed = 20 / (1 + market.SMOOTHING_DAYS)
    assert raw > 15 > smoothed


# --- scheduled collection --------------------------------------------------
#
# rank_delta_7d differences two sweeps a week apart. Nothing produced a second
# sweep until the scheduler existed, so the column was structurally empty —
# which reads identically to "no game moved".


def test_schedule_parses_kinds_and_intervals():
    assert scheduler.parse_schedule("rank:24") == {"rank": 24.0}
    assert scheduler.parse_schedule("rank:24,disclosures:168") == {
        "rank": 24.0,
        "disclosures": 168.0,
    }


def test_a_kind_without_an_interval_defaults_to_daily():
    assert scheduler.parse_schedule("rank") == {"rank": 24.0}


def test_an_empty_schedule_disables_rather_than_falling_back():
    """Setting SWEEP_SCHEDULE="" has to mean off. Treating it as "use the
    default" would restart collection on a host that deliberately stopped it."""
    assert scheduler.parse_schedule("") == {}
    assert scheduler.parse_schedule("   ") == {}


def test_an_unset_schedule_uses_the_default():
    assert scheduler.parse_schedule(None) == scheduler.DEFAULT_SCHEDULE


def test_followers_are_not_on_the_default_clock():
    """A full follower pass is 23,078 games at 4s — about 26 hours. Scheduling
    it daily would queue a second pass before the first finished, so that
    series is built by a long-running loop instead."""
    assert "followers" not in scheduler.DEFAULT_SCHEDULE


def test_the_scheduler_can_run_every_kind_it_accepts():
    """parse_schedule takes any name, and the README advertises
    "rank:24,disclosures:168". A kind the runner cannot execute would register
    a job row and fail it on every cycle — a broken promise that only shows up
    as a red card days later."""
    import inspect

    source = inspect.getsource(scheduler._run)
    for kind in ("rank", "disclosures"):
        assert f'kind == "{kind}"' in source, kind
