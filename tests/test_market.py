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


def test_manifest_forbids_the_two_numbers_that_do_not_exist():
    """Wishlist and revenue estimates are the whole reason this project keeps a
    provenance model. An agent optimising for a confident answer will invent
    them unless told not to, in the payload, every time."""
    rules = " ".join(_manifest_rules()).lower()
    assert "no wishlist count is estimated" in rules
    assert "no revenue or sales figure" in rules
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
