"""Where a game stands among its peers, by measured review count.

Steam publishes no sales figures, so any absolute "this game sold N" tier is a
guess stacked on a guess: a sales-per-review multiplier nobody can validate
against this data, times thresholds somebody picked by feel. This module drops
both. It ranks games against each other and reports the *position*, which is
invariant to whatever the true multiplier happens to be.

Two properties make the ranking honest:

- The measure is `total_reviews` — counted and published by Valve, not derived.
- The comparison pool is the game's **release-month cohort**. A game out for
  three weeks has had three weeks to collect reviews; comparing it against
  January's releases would bury it for no reason other than the calendar.
  Measured across this catalogue: median reviews run 13 for January releases
  down to 6 for August ones.

What a band is NOT: a statement about revenue, quality, or profitability. "Top
10%" means nine out of ten 2026 indie releases from the same month have fewer
reviews — nothing more.
"""

from dataclasses import dataclass

MEASURE = "total_reviews"
COHORT = "release_month"
METHOD_NAME = "cohort_percentile_rank"
NOTES = (
    "Games are ranked by Steam's published review count against other 2026 "
    "indie releases from the same month (percentile rank). No sales figure is "
    "estimated. Unreleased games and games with no reviews yet are excluded "
    "rather than placed in a band."
)

# Percentile rank of the games below the minimum bar for the whole catalogue to
# fall in a cohort with too few peers to rank meaningfully.
MIN_COHORT_SIZE = 30


@dataclass(frozen=True)
class SuccessBand:
    key: str
    label: str
    min_percentile: float  # inclusive lower bound on percent_rank (0.0-1.0)


# Ordered best-first. percent_rank puts a tie group at the group's *lowest*
# position, so "top 10%" is the conservative reading: a game only lands there
# when enough games genuinely sit below it.
SUCCESS_BANDS: tuple[SuccessBand, ...] = (
    SuccessBand("top_1", "Top 1%", 0.99),
    SuccessBand("top_10", "Top 10%", 0.90),
    SuccessBand("top_25", "Top 25%", 0.75),
    SuccessBand("upper_half", "Upper half", 0.50),
    SuccessBand("lower_half", "Lower half", 0.0),
)

# What each band's share would be if a genre were exactly average — true by
# construction, which is what makes "this genre over-indexes" a real claim.
BASELINE_SHARE: dict[str, float] = {
    "top_1": 0.01,
    "top_10": 0.09,
    "top_25": 0.15,
    "upper_half": 0.25,
    "lower_half": 0.50,
}


def band_for(percent_rank: float) -> SuccessBand:
    """The band a percent_rank (0.0 = lowest, 1.0 = highest) falls in."""
    for band in SUCCESS_BANDS:
        if percent_rank >= band.min_percentile:
            return band
    return SUCCESS_BANDS[-1]


def over_index(share: float, band_key: str) -> float | None:
    """How many times the catalogue-average share this band's share is.

    None when the baseline is unknown — a caller should print nothing rather
    than a ratio it cannot justify.
    """
    baseline = BASELINE_SHARE.get(band_key)
    if not baseline:
        return None
    return round(share / baseline, 2)
