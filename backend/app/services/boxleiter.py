"""Review-count sales heuristic (the "Boxleiter number") and its tiers.

estimated_sales ≈ total_reviews * MULTIPLIER

Where the number comes from, and why it is a range rather than a fact:

- Mike Boxleiter's 2014 analysis of Steam sales-vs-reviews popularised the
  method; his era's ratio was roughly 50-70 sales per review.
- Jake Birkett (Grey Alien Games) and later GameDiscoverCo commentary tracked
  the ratio *down* through the late 2010s and 2020s: Steam began prompting for
  reviews, review-leaving became more common, so each review represents fewer
  sales than it used to.
- VG Insights and Gamalytic publish review-to-sales ratios in the ~25-60 band
  for recent years, varying by price, genre, region mix and how long a game has
  been out. Free-to-play and heavily-discounted titles sit far outside it.

So: a single "true" multiplier does not exist. DEFAULT_MULTIPLIER is a
midpoint, MULTIPLIER_RANGE documents the credible spread, and every API
response repeats the formula and the exact multiplier used so a reader can
recompute or override it. This mirrors how budget_estimator.py and
revenue_merge.py expose their inputs rather than presenting a bare number.

Nothing here is a measurement. Games with no review data are never bucketed —
the caller excludes them, it does not guess them into a tier.
"""

from dataclasses import dataclass

DEFAULT_MULTIPLIER = 35.0
MULTIPLIER_RANGE = (25.0, 60.0)
MULTIPLIER_SOURCE = (
    "Boxleiter method (Mike Boxleiter 2014, ~50-70 sales/review), revised down "
    "by Jake Birkett / GameDiscoverCo commentary and VG Insights & Gamalytic "
    "review-to-sales ratios for the 2020s (~25-60, varying by price and genre)"
)
FORMULA = "estimated_sales = total_reviews * multiplier"
METHOD_NAME = "boxleiter_review_multiplier"


@dataclass(frozen=True)
class SuccessTier:
    key: str
    label: str
    min_sales: int          # inclusive
    max_sales: int | None   # exclusive; None = open-ended


# Thresholds are for *indie* releases and are deliberately coarse — they answer
# "which order of magnitude", not "how much". Edit here, not at the call site.
SUCCESS_TIERS: tuple[SuccessTier, ...] = (
    SuccessTier("breakout_hit", "Breakout hit", 200_000, None),
    SuccessTier("solid", "Solid", 20_000, 200_000),
    SuccessTier("modest", "Modest", 2_000, 20_000),
    SuccessTier("underperformed", "Underperformed", 0, 2_000),
)


def clamp_multiplier(value: float | None) -> float:
    """Callers may override the multiplier, but not into nonsense."""
    if value is None:
        return DEFAULT_MULTIPLIER
    low, high = MULTIPLIER_RANGE
    return min(max(value, low), high)


def estimate_sales(total_reviews: int, multiplier: float) -> int:
    return int(round(total_reviews * multiplier))


def tier_for(estimated_sales: int) -> SuccessTier:
    for tier in SUCCESS_TIERS:
        if estimated_sales >= tier.min_sales and (
            tier.max_sales is None or estimated_sales < tier.max_sales
        ):
            return tier
    return SUCCESS_TIERS[-1]
