"""The hobby/serious split, and the things it must refuse to count."""

import pytest

from app.services.effort_score import (
    CLASS_HOBBY,
    CLASS_SERIOUS,
    CLASS_UNKNOWN,
    MAX_POSITIVE,
    SIGNAL_DOC,
    EffortInput,
    score,
)


def game(**overrides) -> EffortInput:
    """A bare upload that still has the near-universal basics."""
    base = dict(
        has_trailer=True,
        screenshot_count=0,
        list_price_cents=None,
        is_free=False,
        language_count=1,
        has_website=False,
        demo_available=False,
        achievements_count=None,
        description_length=150,
        next_fest=False,
        has_social_channels=False,
        mass_published=False,
        developer_releases=1,
    )
    base.update(overrides)
    return EffortInput(**base)


def test_a_bare_upload_is_hobby():
    assert score(game(has_trailer=False)).effort_class == CLASS_HOBBY


def test_a_trailer_earns_nothing_but_its_absence_costs():
    """94.8% of a random sample has one, so having one cannot be a signal."""
    assert "no_trailer" not in score(game(has_trailer=True)).signals
    assert score(game(has_trailer=False)).signals["no_trailer"] == -15


def test_a_produced_game_is_serious():
    result = score(
        game(
            screenshot_count=14,
            list_price_cents=1499,
            language_count=6,
            has_website=True,
            demo_available=True,
            description_length=260,
        )
    )
    assert result.effort_class == CLASS_SERIOUS
    assert result.signals["price_positioned"] == 20
    assert 0 <= result.score <= 100


def test_free_games_are_not_penalised_for_being_free():
    """Free-to-play is a business model, not an absence of effort."""
    paid_floor = score(game(is_free=False, list_price_cents=99))
    free = score(game(is_free=True, list_price_cents=0))
    assert "price_below_floor" in paid_floor.signals
    assert not any(key.startswith("price") for key in free.signals)


def test_a_sub_three_dollar_price_counts_against():
    assert score(game(list_price_cents=199)).signals["price_below_floor"] == -15


def test_mass_publishing_outweighs_a_produced_page():
    """Five releases in thirty days describes an operation, not a project."""
    result = score(game(screenshot_count=14, list_price_cents=1499, mass_published=True))
    assert result.effort_class == CLASS_HOBBY


def test_a_prolific_developer_is_docked():
    assert score(game(developer_releases=9)).signals["developer_volume"] == -15
    assert "developer_volume" not in score(game(developer_releases=3)).signals


def test_never_looked_is_not_the_same_as_no_signals():
    """A game whose store page could not be read must not be called hobby."""
    result = score(game(store_data_seen=False))
    assert result.effort_class == CLASS_UNKNOWN
    assert result.signals == {}


def test_the_score_is_bounded_and_scaled_from_the_breakdown():
    result = score(
        game(
            screenshot_count=12,
            list_price_cents=999,
            has_website=True,
            next_fest=True,
            achievements_count=20,
        )
    )
    assert sum(result.signals.values()) == result.raw
    assert result.score == round(100 * result.raw / MAX_POSITIVE)
    assert 0 <= result.score <= 100


def test_negatives_cannot_push_the_score_below_zero():
    worst = score(
        game(
            has_trailer=False,
            list_price_cents=99,
            description_length=10,
            mass_published=True,
            developer_releases=40,
        )
    )
    assert worst.score == 0
    assert worst.raw < 0


def test_every_signal_carries_its_own_documentation():
    """A weight nobody can justify is a weight nobody should trust."""
    for name, entry in SIGNAL_DOC.items():
        points, measures, why, strength, failure = entry
        assert points != 0, name
        assert measures and why and failure, name
        assert strength in {"strong", "medium", "weak"}, name


def test_traction_is_not_an_input():
    """Effort is what the developer did; traction is what players did.

    EffortInput has no field for either, and this test exists so that adding
    one is a deliberate act rather than a quiet drift back to counting sales.
    """
    for field in ("total_reviews", "followers", "wishlist_rank", "peak_ccu"):
        assert field not in EffortInput.__dataclass_fields__
