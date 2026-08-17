"""The revenue estimator — and the numbers it must refuse to produce.

Most of these tests exist to pin refusals rather than results. An estimate
that is merely imprecise is useful; one that invents a figure for a game we
know nothing about is worse than no estimate at all, and that is the failure
this module is designed around.
"""

import pytest

from app.services.revenue_estimate import (
    ASP_FACTOR,
    BAND_HIGH,
    BAND_LOW,
    CCU_FACTORS,
    EARLY_ACCESS_FACTOR,
    FOLLOWER_FACTORS,
    ESTIMATOR_DOC,
    MIN_FOLLOWERS,
    MIN_PEAK_CCU,
    MIN_REVIEWS,
    MULTIPLIER_ANCHORS,
    NET_OF_GROSS,
    RevenueInput,
    estimate_all,
    from_ccu,
    from_followers,
    from_reviews,
    multiplier_for_units,
    review_multipliers,
    solve_copies,
)


def game(**overrides) -> RevenueInput:
    base = dict(total_reviews=None, peak_ccu=None, followers=None,
                list_price_cents=1000, is_free=False, early_access=False,
                is_released=True)
    base.update(overrides)
    return RevenueInput(**base)


# --- the gates -------------------------------------------------------------

def test_no_estimate_below_the_review_floor():
    """Nine reviews is not a small number, it is an unusable one."""
    assert from_reviews(game(total_reviews=MIN_REVIEWS - 1)) is None
    assert from_reviews(game(total_reviews=MIN_REVIEWS)) is not None


def test_zero_reviews_produces_nothing_rather_than_zero_copies():
    """reviews x multiplier = 0 would read as a measured failure."""
    assert from_reviews(game(total_reviews=0)) is None


def test_missing_reviews_is_not_zero_reviews():
    assert from_reviews(game(total_reviews=None)) is None


def test_free_games_get_copies_but_never_revenue():
    """Their money is in items and passes, which we do not observe."""
    result = from_reviews(game(total_reviews=500, is_free=True, list_price_cents=0))
    assert result.copies_mid > 0
    assert result.gross_mid is None and result.net_mid is None


def test_a_priceless_game_gets_copies_but_no_money():
    result = from_reviews(game(total_reviews=500, list_price_cents=None))
    assert result.copies_mid > 0
    assert (result.gross_low, result.gross_mid, result.gross_high) == (None, None, None)


def test_ccu_needs_a_released_game():
    """An unreleased game cannot have concurrent players; a number there is a bug."""
    assert from_ccu(game(peak_ccu=500, is_released=False)) is None
    assert from_ccu(game(peak_ccu=500, is_released=True)) is not None


def test_ccu_and_follower_floors():
    assert from_ccu(game(peak_ccu=MIN_PEAK_CCU - 1)) is None
    assert from_followers(game(followers=MIN_FOLLOWERS - 1)) is None
    assert from_followers(game(followers=MIN_FOLLOWERS)) is not None


# --- the arithmetic --------------------------------------------------------

def test_the_multiplier_curve_has_no_cliffs():
    """One extra review cannot move a game's sales by a third.

    The tiered table this replaced did exactly that: 49 reviews were scored
    at 20x and 50 reviews at 27x. Any step function reintroduced here fails
    this test.
    """
    previous = None
    for reviews in range(MIN_REVIEWS, 30_001):
        mid = solve_copies(reviews) / reviews
        if previous is not None:
            assert abs(mid / previous - 1) < 0.05, reviews
        previous = mid


def test_the_multiplier_is_consistent_with_its_own_answer():
    """The whole point of solving rather than looking up: the units we report
    must be the units whose multiplier we used."""
    for reviews in (10, 55, 200, 900, 1500, 4000, 25_000):
        units = solve_copies(reviews)
        assert abs(units / reviews - multiplier_for_units(units)) < 0.5, reviews


def test_more_reviews_never_means_fewer_copies():
    previous = 0.0
    for reviews in range(MIN_REVIEWS, 30_001, 7):
        units = solve_copies(reviews)
        assert units >= previous, reviews
        previous = units


def test_the_solver_settles_where_naive_iteration_would_oscillate():
    """Above 100k units the research curve falls (59x -> 48x), so
    U <- reviews * M(U) ping-pongs for ~389 review counts around 1,700-2,100.
    Bisection has to return one finite, stable answer for every one of them."""
    for reviews in range(1_600, 2_201):
        units = solve_copies(reviews)
        assert units > 0 and units == solve_copies(reviews)


def test_the_curve_is_flat_outside_its_anchors():
    """Extrapolating past the ends would invent a trend nobody measured."""
    assert multiplier_for_units(1) == MULTIPLIER_ANCHORS[0][1]
    assert multiplier_for_units(10_000_000) == MULTIPLIER_ANCHORS[-1][1]


def test_the_band_keeps_one_documented_width():
    low, mid, high = review_multipliers(200)
    assert low == pytest.approx(mid * BAND_LOW, abs=0.01)
    assert high == pytest.approx(mid * BAND_HIGH, abs=0.01)


def test_copies_follow_the_stated_formula():
    low, mid, high = review_multipliers(200)
    result = from_reviews(game(total_reviews=200))
    assert (result.copies_low, result.copies_mid, result.copies_high) == (
        round(200 * low), round(200 * mid), round(200 * high),
    )


def test_early_access_raises_the_multiplier():
    """EA games collect 20-30% fewer reviews per sale, so the same review
    count implies more copies."""
    plain = from_reviews(game(total_reviews=200))
    ea = from_reviews(game(total_reviews=200, early_access=True))
    assert ea.copies_mid == round(plain.copies_mid * EARLY_ACCESS_FACTOR)


def test_the_band_is_ordered_at_every_level():
    for result in estimate_all(game(total_reviews=300, peak_ccu=40, followers=900)):
        assert result.copies_low <= result.copies_mid <= result.copies_high
        assert result.gross_low <= result.gross_mid <= result.gross_high
        assert result.net_low <= result.net_mid <= result.net_high


def test_net_is_a_fraction_of_gross_at_every_level():
    result = from_reviews(game(total_reviews=200, list_price_cents=1999))
    assert result.net_mid < result.gross_mid
    assert result.net_mid == round(result.gross_mid * NET_OF_GROSS, 2)


def test_gross_uses_the_average_selling_price_not_the_list_price():
    """A game is not sold at its list price for its whole life."""
    result = from_reviews(game(total_reviews=100, list_price_cents=2000))
    assert result.gross_mid == round(result.copies_mid * 20.0 * ASP_FACTOR, 2)


def test_ccu_follows_its_fitted_factors():
    low, mid, high = CCU_FACTORS
    assert low < mid < high
    assert from_ccu(game(peak_ccu=100)).copies_mid == 100 * mid


def test_ccu_is_centred_on_the_review_estimator():
    """The CCU factors are fitted so the two signals agree on a typical game.

    This is the guard that catches a half-done change: move the review curve
    without refitting CCU_FACTORS and the two signals start disagreeing for
    no reason, which would show up as a conflict in estimate_spread that is
    really a stale constant.
    """
    reviews = from_reviews(game(total_reviews=1000))
    ccu = from_ccu(game(peak_ccu=round(reviews.copies_mid / CCU_FACTORS[1])))
    assert abs(ccu.copies_mid - reviews.copies_mid) / reviews.copies_mid < 0.05


# --- provenance ------------------------------------------------------------

def test_every_estimate_carries_its_formula_and_inputs():
    for result in estimate_all(game(total_reviews=300, peak_ccu=40, followers=900)):
        assert result.formula
        assert result.inputs["list_price_cents"] == 1000
        assert result.inputs["asp_factor"] == ASP_FACTOR


def test_a_pre_launch_follower_estimate_is_labelled_a_forecast():
    result = from_followers(game(followers=1000, is_released=False))
    assert result.inputs["forecast"] is True


def test_every_constant_is_documented():
    """A multiplier nobody can source is a multiplier nobody should trust."""
    for name, entry in ESTIMATOR_DOC.items():
        measures, source, strength, failure = entry
        assert measures and source and failure, name
        assert strength in {"strong", "medium", "weak"}, name


def test_estimate_all_returns_only_signals_that_cleared_their_gate():
    assert estimate_all(game()) == []
    assert len(estimate_all(game(total_reviews=100))) == 1
    assert len(estimate_all(game(total_reviews=100, peak_ccu=50, followers=500))) == 3


def test_followers_are_centred_on_the_review_estimator():
    """Like CCU, the follower chain's centring is borrowed rather than
    measured. This guards the half-done change: move the review curve without
    refitting FOLLOWER_FACTORS and thousands of games start reporting a
    conflict that is really a stale constant — which is exactly what a full
    follower sweep exposed the first time."""
    reviews = from_reviews(game(total_reviews=1000))
    followers = from_followers(
        game(followers=round(reviews.copies_mid / FOLLOWER_FACTORS[1]))
    )
    assert abs(followers.copies_mid - reviews.copies_mid) / reviews.copies_mid < 0.05
