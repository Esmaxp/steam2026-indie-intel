"""The hobby/serious split, and the things it must refuse to count."""

import pytest

from app.services.effort_score import (
    CLASS_HOBBY,
    CLASS_MIXED,
    CRAFT_MAX_POSITIVE,
    CLASS_SERIOUS,
    CLASS_UNKNOWN,
    MAX_POSITIVE,
    SIGNAL_DOC,
    EffortInput,
    craft_score,
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


# --- craft: production evidence only ---------------------------------------

def test_craft_ignores_marketing_and_price():
    """The whole point: a game that was built and never marketed must not
    read as a hobby project. Under the combined score this lands near hobby,
    because 60% of its weight is website/demo/Next Fest/socials/price."""
    built_but_unmarketed = game(
        screenshot_count=14,
        language_count=6,
        achievements_count=20,
        description_length=300,
        has_website=False,
        demo_available=False,
        next_fest=False,
        has_social_channels=False,
        list_price_cents=399,
    )
    assert craft_score(built_but_unmarketed).craft_class == CLASS_SERIOUS
    assert score(built_but_unmarketed).effort_class != CLASS_SERIOUS


def test_craft_is_blind_to_price_and_release_status():
    """None of the craft signals touch price, so free-to-play and unreleased
    games are not structurally capped the way the combined score caps them."""
    signals = dict(screenshot_count=14, language_count=6, achievements_count=20,
                   description_length=300)
    paid = craft_score(game(list_price_cents=2999, **signals))
    free = craft_score(game(is_free=True, list_price_cents=0, **signals))
    cheap = craft_score(game(list_price_cents=99, **signals))
    assert paid.score == free.score == cheap.score


def test_publisher_behaviour_never_touches_craft():
    """mass_published and developer_volume describe the scale of an operation,
    not the care in one game. They stay on the combined score."""
    plain = craft_score(game(screenshot_count=14, language_count=6))
    prolific = craft_score(
        game(screenshot_count=14, language_count=6, mass_published=True,
             developer_releases=40)
    )
    assert plain.score == prolific.score
    assert "mass_published" not in prolific.signals
    assert "developer_volume" not in prolific.signals


def test_an_asset_flip_reads_as_noise_whatever_it_costs():
    flip = dict(screenshot_count=3, language_count=1, description_length=40,
                achievements_count=None)
    for price in (99, 1999, None):
        assert craft_score(game(list_price_cents=price, **flip)).craft_class == CLASS_HOBBY


def test_craft_thresholds_sit_where_the_signal_counts_change():
    """55 = three signals, 32 = two. One signal alone is the catalogue's
    largest pile and is not evidence of much."""
    one = craft_score(game(description_length=300))            # 10 raw
    two = craft_score(game(description_length=300, achievements_count=5))   # 20
    three = craft_score(game(description_length=300, achievements_count=5,
                             screenshot_count=14))             # 30
    assert one.craft_class == CLASS_HOBBY
    assert two.craft_class == CLASS_MIXED
    assert three.craft_class == CLASS_SERIOUS


def test_craft_is_unknown_when_the_page_was_never_read():
    result = craft_score(game(store_data_seen=False))
    assert result.craft_class == CLASS_UNKNOWN
    assert result.signals == {}


def test_craft_max_is_the_sum_of_its_positive_signals():
    assert CRAFT_MAX_POSITIVE == 44
    best = craft_score(
        game(screenshot_count=14, language_count=6, achievements_count=20,
             description_length=300)
    )
    assert best.score == 100
