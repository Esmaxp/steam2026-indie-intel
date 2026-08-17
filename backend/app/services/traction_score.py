"""Axis 2 — did the game find an audience (0-100)? Kept apart from effort.

Traction is measured only from what players did: review counts, concurrent
players, Valve's Top-Wishlists position, follower counts. None of it says
anything about how the game was made, and nothing from app.services.effort_score
is allowed in here. The separation is the whole point — "serious game, no
audience" has to be a describable state, because it is the category worth
finding.

Two rules keep the number honest:

- **Position, not magnitude.** Each signal is converted to a percentile against
  the game's release-month cohort before it is combined, because raw counts are
  incomparable (a January release has had seven more months to collect reviews)
  and because a sales estimate would just be a guess with extra steps.
- **Absent signals are absent, not zero.** The score averages the signals a
  game actually has. A game with no follower sweep yet is not a game with zero
  followers, and scoring it as such would manufacture failure.

The 90-day grace period sits on top: for a game released less than 90 days ago,
low traction is age, not outcome, so its status is reported as
`insufficient_data` and it is kept out of the four-way classification. Its
effort score is still computed — effort does not need time to pass.
"""

from dataclasses import dataclass, field

GRACE_PERIOD_DAYS = 90

STRONG_AT = 60
MODEST_AT = 25

CLASS_STRONG = "strong"
CLASS_MODEST = "modest"
CLASS_WEAK = "weak"
CLASS_UNKNOWN = "unknown"

STATUS_MEASURED = "measured"
STATUS_TOO_EARLY = "insufficient_data_too_early"
STATUS_NO_SIGNALS = "insufficient_data_no_signals"

# Relative weight of each signal when a game has more than one. Reviews carry
# the most because they have by far the best coverage (52% of the catalogue)
# and are the hardest to manufacture; wishlist rank is scarce (Valve publishes
# only ~5,200 positions across all of Steam) but is a direct demand statement.
WEIGHTS: dict[str, float] = {
    "reviews": 1.0,
    "wishlist_rank": 0.9,
    "peak_ccu": 0.7,
    "followers": 0.8,
}


@dataclass(frozen=True)
class TractionInput:
    """Percentiles (0.0-1.0) against the release-month cohort, or None.

    None always means "not observed". The caller computes the percentiles in
    SQL — see workers/classify_games.py — so this module stays pure.
    """

    reviews_pct: float | None = None
    wishlist_rank_pct: float | None = None
    peak_ccu_pct: float | None = None
    followers_pct: float | None = None
    days_since_release: int | None = None
    is_released: bool = True


@dataclass(frozen=True)
class TractionResult:
    score: int | None          # 0-100, None when nothing could be measured
    traction_class: str
    status: str
    observed: int
    signals: dict[str, float] = field(default_factory=dict)


def score(data: TractionInput) -> TractionResult:
    # percent_rank() comes back as Decimal over asyncpg; float() here keeps the
    # arithmetic below from mixing types.
    present = {
        name: float(value)
        for name, value in (
            ("reviews", data.reviews_pct),
            ("wishlist_rank", data.wishlist_rank_pct),
            ("peak_ccu", data.peak_ccu_pct),
            ("followers", data.followers_pct),
        )
        if value is not None
    }

    too_early = (
        data.is_released
        and data.days_since_release is not None
        and data.days_since_release < GRACE_PERIOD_DAYS
    )

    if not present:
        # An unreleased game with no wishlist position is not a failure; it is
        # a game nobody has had the chance to react to.
        return TractionResult(
            score=None,
            traction_class=CLASS_UNKNOWN,
            status=STATUS_TOO_EARLY if too_early else STATUS_NO_SIGNALS,
            observed=0,
        )

    weighted = sum(WEIGHTS[name] * value for name, value in present.items())
    total_weight = sum(WEIGHTS[name] for name in present)
    scaled = max(0, min(100, round(100 * weighted / total_weight)))

    if too_early:
        # The number is reported for information, but it is not a verdict: a
        # three-week-old game has not had time to succeed or fail.
        return TractionResult(
            score=scaled,
            traction_class=CLASS_UNKNOWN,
            status=STATUS_TOO_EARLY,
            observed=len(present),
            signals={name: round(value, 4) for name, value in present.items()},
        )

    if scaled >= STRONG_AT:
        traction_class = CLASS_STRONG
    elif scaled >= MODEST_AT:
        traction_class = CLASS_MODEST
    else:
        traction_class = CLASS_WEAK
    return TractionResult(
        score=scaled,
        traction_class=traction_class,
        status=STATUS_MEASURED,
        observed=len(present),
        signals={name: round(value, 4) for name, value in present.items()},
    )
