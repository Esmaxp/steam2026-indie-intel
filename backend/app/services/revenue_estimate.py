"""Copies sold, and what they were worth — three signals, always a range.

Steam publishes no sales figure, so any revenue number is inferred. This
module infers it the only honest way available: from signals we measure
ourselves, each converted independently, each carrying a low/mid/high band
wide enough to contain the disagreement in the public research.

Why a range rather than a number. The review multiplier — sales per public
review, the "Boxleiter number" — is not a constant. Steam started prompting
players to review in 2019 and roughly halved it; it varies by a factor of
two with how many copies a game sold; it moves with discount depth, review
sentiment and playtime. GameDiscoverCo's published medians by units sold
are 20x under 1,000 copies, 36x at 1k-10k, 49x at 10k-50k, 59x at 50k-100k
and 48x above that, against an all-games median of 29x. Any single number
picked out of that is wrong for most games.

Why the multiplier is solved rather than looked up. Those medians are keyed
on UNITS SOLD, which is the thing being estimated — so the multiplier cannot
simply be read off the review count. The curve is defined on units and the
answer is the fixed point U = reviews x M(U): the sales figure that agrees
with its own multiplier. See solve_copies for why that is done by bisection.

Why the low end. This catalogue is 2026 indie releases: post-prompt, median
list price $5.60, and overwhelmingly in the sub-1,000-copies band where the
multiplier is smallest. Cheap games earn more reviews per sale, which pushes
the multiplier down further. Applying the widely-quoted 60-80x from the 2014
SteamSpy era — those figures counted *owners*, including free keys and
bundles — would overstate this catalogue by a factor of three.

What is deliberately not here:

- No estimate below MIN_REVIEWS. A game with two reviews has a multiplier
  that swings 33% on a single extra review, and zero reviews times any
  multiplier is zero — which would be a fabricated failure, not a
  measurement.
- No revenue for free-to-play. Their money is in items and passes, which
  this project does not observe at all.
- No single point value anywhere in the module's output.

Every constant is documented in ESTIMATOR_DOC with its source and the way
it can be wrong, the same contract app.services.effort_score.SIGNAL_DOC
holds for its weights.
"""

import math
from dataclasses import dataclass, field

# --- copies: signal 1, review counts ---------------------------------------
MIN_REVIEWS = 10
EARLY_ACCESS_FACTOR = 1.25

# The published medians, on the axis they were published against: UNITS SOLD.
# GameDiscoverCo/Gamalytic report 20x under 1,000 units, 36x at 1k-10k, 49x
# at 10k-50k, 59x at 50k-100k and 48x above 100k. Each is placed at the
# geometric middle of its band, and the curve interpolates between them.
#
# Keying this on units rather than on review count matters more than it
# looks. An earlier version of this module tiered by review count, which is
# what we observe — but that applies the wrong band's multiplier to most
# games: 500 reviews at 36x implies 18,000 units, and the research says a
# game selling 18,000 units has a multiplier of 49x, not 36x. The two only
# agree by accident.
#
# Interpolating is an assumption, and an honest one to name: the research
# published band medians, not the shape of the curve between them. Log-linear
# is a smoothness assumption. It is a far weaker claim than the step function
# it replaces, which asserted that one extra review can move a game's sales
# by 35% — a discontinuity that certainly does not exist.
MULTIPLIER_ANCHORS: tuple[tuple[float, float], ...] = (
    (316, 20.0),
    (3_162, 36.0),
    (22_360, 49.0),
    (70_710, 59.0),
    (300_000, 48.0),
)

# The band around the central multiplier. The five tiers this replaced each
# carried their own low/high, but their ratios to the mid were effectively
# constant (0.69-0.75 and 1.33-1.50), so one pair says the same thing without
# pretending the width was measured per tier.
BAND_LOW = 0.72
BAND_HIGH = 1.41

# Bisection bounds for the fixed point below. The upper bound is generous:
# no anchor exceeds 59x, so 80x can never be the answer, only a safe ceiling.
_SOLVER_MAX_MULTIPLE = 80.0
_SOLVER_STEPS = 60

# --- copies: signal 2, peak concurrent players -----------------------------
# All-time peak, as SteamCharts reports it (market_data stores peak_all_time).
#
# These factors are NOT independent of the review estimator: they were fitted
# against it. On the 1,826 games in this catalogue where both signals fire,
# the copies the review curve implies divided by peak CCU has a median of
# 65.8 and a quartile range of 33.3 to 129.9. Those three numbers are the
# factors below. See the CCU entry in ESTIMATOR_DOC for what that costs.
#
# Refit whenever the review curve changes. These were 25/50/100 while the
# review side was tiered on review count; moving it onto the units axis
# raised the implied copies, so leaving the old anchor in place would have
# manufactured disagreement between the two signals and made estimate_spread
# report a conflict that is really a stale constant.
MIN_PEAK_CCU = 5
CCU_FACTORS = (33, 66, 130)
CCU_ANCHOR_SAMPLE = 1826

# --- copies: signal 3, community-hub followers -----------------------------
MIN_FOLLOWERS = 20
# The chain is followers -> wishlists (8/10/12) -> sales (0.15/0.20/0.25),
# which multiplies out to 1.2/2.0/3.0. Both links are rules of thumb nobody
# published a study on, and once the follower sweep covered the catalogue the
# error showed: on the 5,834 games where reviews and followers both fire, the
# review estimator implies 2.75x more copies (quartiles 1.39 and 5.11).
#
# So the factors below are the raw chain re-centred on the review estimator —
# 2.0 x 2.75 for the middle, and the quartiles for the band. Before this, the
# systematic gap alone flagged 3,587 games as "conflicting", which read as
# per-game disagreement when it was one stale constant.
#
# The cost is the same one CCU_FACTORS pays and it has to be said plainly:
# followers are no longer independent evidence of the LEVEL. When the two
# agree, that is arithmetic, not confirmation. They stay level-setting anyway
# because for roughly eight thousand games — the ones under the 10-review
# gate — followers are the only signal there is, and a borrowed centring
# beats refusing to answer.
FOLLOWER_FACTORS = (2.8, 5.5, 10.2)
FOLLOWER_ANCHOR_SAMPLE = 5834

# --- copies -> money -------------------------------------------------------
# Average selling price as a fraction of list. Most units move during sales;
# this is the one constant that price_snapshots will eventually measure.
ASP_FACTOR = 0.65
STEAM_SHARE = 0.70      # Valve keeps 30% below $10M
REFUND_FACTOR = 0.95    # ~5% refunded
REGIONAL_FACTOR = 0.90  # cheaper regions plus VAT already inside the list price
NET_OF_GROSS = STEAM_SHARE * REFUND_FACTOR * REGIONAL_FACTOR  # 0.5985

SOURCE_REVIEWS = "reviews"
SOURCE_CCU = "ccu"
SOURCE_FOLLOWERS = "followers"

CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

# A global correction fitted against developer-disclosed sales figures.
# 1.0 until such a set exists; workers/estimate_revenue.py records the
# sample size alongside any value other than 1.0, because a factor measured
# on ten games is a sanity check, not a calibration.
CALIBRATION_FACTOR = 1.0
CALIBRATION_SAMPLE = 0

# name -> (what it measures, where the constants come from, strength, how it fails)
ESTIMATOR_DOC: dict[str, tuple[str, str, str, str]] = {
    SOURCE_REVIEWS: (
        "public review count, solved against a multiplier curve defined on "
        "units sold",
        "GameDiscoverCo/Gamalytic medians by units sold (20x/36x/49x/59x/48x), "
        "all-games median 29x for 2022, interpolated log-linearly between the "
        "geometric middle of each band",
        "medium",
        "two separate failure modes. (1) The interpolation is a smoothness "
        "assumption: only the band medians were measured, never the shape "
        "between them. (2) Heavily discounted games and games with large "
        "non-English audiences review far less per sale, so their true "
        "multiplier can exceed 100x — above anything this curve produces. "
        "Moving to the units axis raised most estimates; that corrects a "
        "logical error, and is NOT evidence the new level is more accurate",
    ),
    SOURCE_CCU: (
        "all-time peak concurrent players x 33/66/130",
        f"fitted against the review estimator on the {CCU_ANCHOR_SAMPLE} games "
        "in this catalogue where both signals fire (median 65.8, quartiles "
        "33.3 and 129.9) — borrowed centring, not an outside measurement",
        "weak",
        "because it is anchored to the review estimator, agreement between the "
        "two is NOT independent confirmation of a game's sales level; it only "
        "detects games whose concurrency is unusual FOR their review count. "
        "Session length drives the true ratio, so multiplayer and live-service "
        "games sit far above the median and short narrative games far below",
    ),
    SOURCE_FOLLOWERS: (
        "community-hub followers x 2.8/5.5/10.2",
        "followers-to-wishlists of roughly 1:10 and first-year wishlist "
        f"conversion of 15-25%, then re-centred on the review estimator over "
        f"the {FOLLOWER_ANCHOR_SAMPLE} games where both fire (median ratio "
        "2.75, quartiles 1.39 and 5.11)",
        "medium",
        "the centring is borrowed, so agreement with the review estimator is "
        "arithmetic rather than confirmation — the same caveat CCU carries. "
        "Beyond that: a game that ran a giveaway or was bundled collects "
        "followers who never bought it, and a game selling on a storefront "
        "push can have almost no hub following",
    ),
    "asp": (
        f"average selling price as {ASP_FACTOR:.2f} of list price",
        "most units on Steam move during discount windows",
        "medium",
        "a game that never discounts is understated by a third; a permanently "
        "-75% game is overstated",
    ),
    "net": (
        f"net to the developer as {NET_OF_GROSS:.4f} of gross store revenue",
        f"Valve's {1 - STEAM_SHARE:.0%} cut, ~{1 - REFUND_FACTOR:.0%} refunds, "
        "and regional pricing plus VAT already inside the listed price",
        "strong",
        "publisher splits, platform-key sales and tax residency are invisible "
        "here, and all three move the real figure down further",
    ),
}


@dataclass(frozen=True)
class RevenueInput:
    """Everything the estimators read. All of it is measured, none derived."""

    total_reviews: int | None = None
    peak_ccu: int | None = None
    followers: int | None = None
    list_price_cents: int | None = None
    is_free: bool = False
    early_access: bool = False
    is_released: bool = True


@dataclass(frozen=True)
class Estimate:
    """One signal's answer. Money fields are None when price is unknown."""

    source: str
    copies_low: int
    copies_mid: int
    copies_high: int
    gross_low: float | None
    gross_mid: float | None
    gross_high: float | None
    net_low: float | None
    net_mid: float | None
    net_high: float | None
    confidence: str
    formula: str
    inputs: dict = field(default_factory=dict)


def multiplier_for_units(units: float) -> float:
    """Sales per review at a given number of units sold.

    Log-linear between the anchors, flat outside them — a game selling 50
    copies and one selling 300 are both in territory the research summarised
    with a single median, and extrapolating past the ends would invent a
    trend nobody measured.
    """
    units = max(units, 1.0)
    if units <= MULTIPLIER_ANCHORS[0][0]:
        return MULTIPLIER_ANCHORS[0][1]
    if units >= MULTIPLIER_ANCHORS[-1][0]:
        return MULTIPLIER_ANCHORS[-1][1]
    for (u0, m0), (u1, m1) in zip(MULTIPLIER_ANCHORS, MULTIPLIER_ANCHORS[1:]):
        if units <= u1:
            span = math.log(u1) - math.log(u0)
            t = (math.log(units) - math.log(u0)) / span
            return m0 + t * (m1 - m0)
    return MULTIPLIER_ANCHORS[-1][1]


def solve_copies(reviews: int) -> float:
    """The units U consistent with its own multiplier: U = reviews x M(U).

    Solved by bisection on f(U) = reviews * M(U) - U, NOT by iterating
    U <- reviews * M(U). The naive loop looks obvious and is wrong: the
    research curve falls from 59x to 48x above 100,000 units, so between
    roughly 1,695 and 2,083 reviews the iteration ping-pongs between two
    values forever — 389 review counts in the 10-30,000 range never settle.
    Bisection returns a single stable answer everywhere, including there.

    f is positive at the low end and negative at the high end, so a crossing
    always exists; taking the first one keeps the answer conservative where
    the non-monotone top of the curve admits more than one.
    """
    lo, hi = 1.0, max(reviews * _SOLVER_MAX_MULTIPLE, 100.0)
    for _ in range(_SOLVER_STEPS):
        mid = (lo + hi) / 2
        if reviews * multiplier_for_units(mid) - mid > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def review_multipliers(total_reviews: int) -> tuple[float, float, float]:
    """The (low, mid, high) multiplier implied for a review count."""
    mid = solve_copies(total_reviews) / total_reviews
    return round(mid * BAND_LOW, 3), round(mid, 3), round(mid * BAND_HIGH, 3)


def _money(copies: tuple[int, int, int], list_price_cents: int | None, is_free: bool):
    """(gross, net) triples, or (None, None) when the game has no price.

    Free-to-play returns nothing rather than zero: their revenue exists, we
    simply cannot see it.
    """
    if is_free or not list_price_cents:
        return (None, None, None), (None, None, None)
    asp = (list_price_cents / 100) * ASP_FACTOR
    gross = tuple(round(c * asp, 2) for c in copies)
    net = tuple(round(g * NET_OF_GROSS, 2) for g in gross)
    return gross, net


def _build(
    source: str,
    copies: tuple[float, float, float],
    data: RevenueInput,
    confidence: str,
    formula: str,
    inputs: dict,
) -> Estimate:
    scaled = tuple(max(0, round(c * CALIBRATION_FACTOR)) for c in copies)
    gross, net = _money(scaled, data.list_price_cents, data.is_free)
    if CALIBRATION_FACTOR != 1.0:
        inputs = {**inputs, "calibration": CALIBRATION_FACTOR, "calibration_n": CALIBRATION_SAMPLE}
    return Estimate(
        source=source,
        copies_low=scaled[0],
        copies_mid=scaled[1],
        copies_high=scaled[2],
        gross_low=gross[0],
        gross_mid=gross[1],
        gross_high=gross[2],
        net_low=net[0],
        net_mid=net[1],
        net_high=net[2],
        confidence=confidence,
        formula=formula,
        inputs={
            **inputs,
            "asp_factor": ASP_FACTOR,
            "net_of_gross": round(NET_OF_GROSS, 4),
            "list_price_cents": data.list_price_cents,
        },
    )


def from_reviews(data: RevenueInput) -> Estimate | None:
    """Boxleiter, solved on the units axis. None below MIN_REVIEWS."""
    reviews = data.total_reviews
    if reviews is None or reviews < MIN_REVIEWS:
        return None
    low, mid, high = review_multipliers(reviews)
    ea = EARLY_ACCESS_FACTOR if data.early_access else 1.0
    return _build(
        SOURCE_REVIEWS,
        (reviews * low * ea, reviews * mid * ea, reviews * high * ea),
        data,
        CONFIDENCE_MEDIUM,
        "copies solves U = reviews x multiplier(U), then x early_access_factor",
        {
            "total_reviews": reviews,
            "multipliers": [low, mid, high],
            "early_access_factor": ea,
        },
    )


def from_ccu(data: RevenueInput) -> Estimate | None:
    """Concurrency, centred on the review estimator — a disagreement detector.

    Unreleased games have no concurrent players, so this never fires for them.
    """
    ccu = data.peak_ccu
    if not data.is_released or ccu is None or ccu < MIN_PEAK_CCU:
        return None
    low, mid, high = CCU_FACTORS
    return _build(
        SOURCE_CCU,
        (ccu * low, ccu * mid, ccu * high),
        data,
        CONFIDENCE_LOW,
        "copies = peak_ccu x factor",
        {"peak_ccu": ccu, "factors": list(CCU_FACTORS)},
    )


def from_followers(data: RevenueInput) -> Estimate | None:
    """Hub followers, via wishlists. The only signal that works pre-launch."""
    followers = data.followers
    if followers is None or followers < MIN_FOLLOWERS:
        return None
    low, mid, high = FOLLOWER_FACTORS
    return _build(
        SOURCE_FOLLOWERS,
        (followers * low, followers * mid, followers * high),
        data,
        CONFIDENCE_MEDIUM,
        "copies = followers x (followers_to_wishlists x wishlist_conversion)",
        {
            "followers": followers,
            "factors": list(FOLLOWER_FACTORS),
            # An unreleased game has not sold anything yet; the same formula
            # is a forecast there, and is labelled as one.
            "forecast": not data.is_released,
        },
    )


ESTIMATORS = (from_reviews, from_ccu, from_followers)


def estimate_all(data: RevenueInput) -> list[Estimate]:
    """Every signal that clears its gate, in a stable order."""
    return [e for e in (fn(data) for fn in ESTIMATORS) if e is not None]
