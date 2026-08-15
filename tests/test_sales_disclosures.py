"""The sales-disclosure extractor, and everything it must throw away.

A calibration set is only as good as its worst entry. One "1 million
players" counted as a million copies would move the fitted multiplier far
more than ten correct rows would move it back, so most of these tests pin
rejections rather than matches.
"""

import datetime

from scraper.collectors.sales_disclosures import (
    REASON_AMBIGUOUS,
    REASON_BELOW,
    REASON_CROSS_PLATFORM,
    REASON_TARGET,
    find_sales_disclosures,
)

EPOCH = int(datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc).timestamp())


def news(*sentences: str) -> list[dict]:
    return [{
        "title": "Update",
        "contents": " ".join(sentences),
        "date": EPOCH,
        "url": "https://steamcommunity.com/games/1/announcements/detail/1",
    }]


def found(*sentences: str):
    hits, _ = find_sales_disclosures(1, news(*sentences))
    return hits


def rejected(*sentences: str):
    _, rejects = find_sales_disclosures(1, news(*sentences))
    return rejects


# --- what it must catch ----------------------------------------------------

def test_sold_n_copies():
    hits = found("We sold 12,345 copies in the first month.")
    assert [h.copies for h in hits] == [12345]
    assert hits[0].comparator == "="


def test_n_copies_sold():
    assert [h.copies for h in found("50,000 copies sold!")] == [50000]


def test_units_and_suffixes():
    assert [h.copies for h in found("125.4K units sold.")] == [125400]


def test_sales_passed_a_figure():
    assert [h.copies for h in found("Sales have passed 30,000.")] == [30000]


def test_a_round_milestone_is_a_lower_bound():
    """'100,000 copies sold' is what you post after crossing it, not telemetry."""
    assert found("100,000 copies sold!")[0].comparator == ">="


def test_explicit_lower_bound_wording():
    assert found("We have sold over 12,345 copies.")[0].comparator == ">="


# --- what it must refuse ---------------------------------------------------

def test_players_are_not_copies():
    """Free weekends, giveaways and gifted keys all inflate player counts.

    A sentence that never says "copies" matches no pattern at all, so it is
    not even a candidate — nothing to reject.
    """
    assert found("1 million players have joined us!") == []
    assert rejected("1,000,000 players have joined us!") == []


def test_an_unnamed_figure_beside_a_player_count_is_rejected():
    """"sales passed N" does not say what N counts, so a player figure in the
    same sentence makes it unusable."""
    text = "Sales have passed 500,000 players since launch."
    assert found(text) == []
    assert rejected(text)[0].reason == REASON_AMBIGUOUS


def test_a_named_copies_figure_survives_a_nearby_player_count():
    """The figure says "copies" outright; a player number elsewhere in the
    sentence does not make it ambiguous, and dropping it would throw away a
    perfectly good data point."""
    hits = found("With 500,000 players on board, we have now sold 40,123 copies.")
    assert [h.copies for h in hits] == [40123]


def test_downloads_and_installs_are_not_copies():
    assert found("500,000 downloads so far.") == []
    assert found("We passed 200,000 installs.") == []


def test_a_player_figure_beside_a_sales_figure_does_not_leak_through():
    """Both numbers appear; only the one that says copies may be used."""
    hits = found("We hit 500,000 players. Separately, 40,123 copies sold.")
    assert [h.copies for h in hits] == [40123]


def test_cross_platform_totals_are_refused():
    """The multiplier maps Steam reviews to Steam sales."""
    assert found("We sold 80,000 copies across all platforms.") == []
    assert (
        rejected("We sold 80,000 copies across all platforms.")[0].reason
        == REASON_CROSS_PLATFORM
    )
    assert found("60,000 copies sold on Steam and Switch combined.") == []


def test_goals_are_not_achievements():
    assert found("Help us reach 100,000 copies sold!") == []
    assert rejected("Help us reach 100,000 copies sold!")[0].reason == REASON_TARGET


def test_approaching_a_figure_is_refused():
    """'almost 50,000' describes a value below it, which '=' and '>=' cannot say."""
    assert found("We are almost at 50,000 copies sold.") == []
    assert rejected("We are almost at 50,000 copies sold.")[0].reason == REASON_BELOW


def test_a_delta_is_not_a_total():
    assert found("We gained 2,500 copies sold this week.") == []


def test_implausible_numbers_are_refused():
    assert found("We sold 12 copies.") == []
    assert found("We sold 9,073,139,032,455 copies.") == []


def test_restatements_are_dropped():
    hits = found("40,123 copies sold!", "Still at 40,123 copies sold.")
    assert len(hits) == 1


def test_rejections_are_reported_rather_than_silently_dropped():
    """A silent filter is indistinguishable from a broken one."""
    rejects = rejected(
        "Sales have passed 500,000 players.", "Help us reach 100,000 copies sold!"
    )
    assert {r.reason for r in rejects} == {REASON_AMBIGUOUS, REASON_TARGET}
    assert all(r.excerpt and r.url for r in rejects)
