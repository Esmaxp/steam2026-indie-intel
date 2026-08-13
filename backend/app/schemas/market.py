"""Response shapes for the market-intelligence surface.

Field descriptions are not decoration here. The consumer is an agent reading
JSON without the README, so each one says what the number is and — where it
matters — what it is not.
"""

import datetime

from pydantic import BaseModel, Field


class CoverageOut(BaseModel):
    """How much signal exists right now. Read before trusting a short list."""

    games: int
    released_games: int
    with_reviews: int
    with_followers: int
    with_follower_delta: int = Field(
        description="Games with two follower snapshots at least 14 days apart. Zero "
        "means momentum cannot be measured yet — not that nothing is moving."
    )
    on_wishlist_chart: int
    with_rank_delta: int = Field(
        description="Games comparable against a complete chart sweep at least 7 days "
        "old. Zero means rank movement is unavailable."
    )
    with_confirmed_wishlist_disclosure: int = Field(
        description="Games where a developer publicly stated a wishlist figure. The "
        "only wishlist numbers in this dataset."
    )
    momentum_ready: bool
    notes: list[str]


class FacetOut(BaseModel):
    """One slice of the catalogue — a genre, a tag, a design choice, or a
    whole competitive field."""

    key: str
    games: int
    released: int
    upcoming: int
    median_reviews: float | int | None
    p90_reviews: float | int | None
    top_decile_share: float | None = Field(
        default=None,
        description="Share of this slice's RANKABLE games in the top decile of their "
        "release-month cohort. Denominator is `outcome_sample`, which excludes "
        "unreleased games and games with no reviews — not a success rate for the "
        "slice as a whole.",
    )
    outcome_sample: int = Field(
        description="Games behind the outcome figures. Small samples make shares "
        "meaningless; see `sample_warning`."
    )
    median_price_cents: float | int | None
    games_with_followers: int
    median_followers: float | int | None
    games_on_wishlist_chart: int | None = None
    best_wishlist_rank: int | None = None
    sample_warning: str | None = None


class TrendingItem(BaseModel):
    """One ranked game. Which fields are populated depends on the segment —
    a released game has reviews and no chart position; an upcoming one has the
    reverse."""

    appid: int
    name: str
    release_date: datetime.date | None
    is_released: bool
    price_cents: int | None

    # --- released segment ---
    total_reviews: int | None = None
    positive_reviews: int | None = None
    positive_pct: float | None = None
    peak_ccu: int | None = None
    days_on_sale: int | None = None
    reviews_per_day: float | None = Field(
        default=None,
        description="Lifetime average, not current velocity: total reviews over days "
        "on sale (plus a 7-day smoothing term so a launch-week game is not divided by "
        "one noisy day). Measured recent velocity does not exist for this catalogue.",
    )
    quality: float | None = Field(
        default=None,
        description="Wilson lower bound of the positive rate at 95%. Discounts small "
        "samples: 5 reviews at 100% scores about 0.48.",
    )
    score: float | None = Field(
        default=None, description="reviews_per_day x quality. The released ranking."
    )

    # --- upcoming segment ---
    wishlist_rank: int | None = None
    rank_delta_7d: int | None = Field(
        default=None, description="Chart positions gained. Positive = moved up."
    )
    followers: int | None = None
    follower_delta_14d: int | None = None
    rank_basis: str | None = Field(
        default=None,
        description="'wishlist_chart' = ranked by Valve's chart position. 'followers' "
        "= not on the chart, ranked by community-hub followers instead.",
    )


class TrendingOut(BaseModel):
    segment: str
    algorithm: str = Field(
        description="The ranking, restated in the payload so a consumer that only "
        "sees JSON knows what produced the order."
    )
    basis: str | None = Field(
        default=None,
        description="Upcoming only. 'chart_movement' = ranked by measured chart "
        "climbing. 'chart_position' = nothing has moved measurably yet, so this is "
        "current standing. Do not describe a chart_position list as 'rising'.",
    )
    items: list[TrendingItem]
    coverage: CoverageOut


class DesignAxisOut(BaseModel):
    axis: str
    buckets: list[FacetOut]
    caveat: str


class Competitor(BaseModel):
    appid: int
    name: str
    release_date: datetime.date | None
    is_released: bool
    price_cents: int | None
    total_reviews: int | None
    cohort_percentile: float | None = Field(
        default=None, description="Position among same-month releases. 0.9 = top decile."
    )
    followers: int | None
    wishlist_rank: int | None


class AdjacentTag(BaseModel):
    tag: str
    games: int


class LandscapeOut(BaseModel):
    genres: list[str]
    tags: list[str]
    field: FacetOut
    competitors: list[Competitor] = Field(
        description="Best-performing games in the field by review count — who a "
        "concept would be measured against."
    )
    adjacent_tags: list[AdjacentTag] = Field(
        description="What games in this field ALSO carry, most common first. The "
        "requested tags are excluded. Evidence of what pairs with the space."
    )


class EndpointHint(BaseModel):
    path: str
    use_when: str


class SuccessBandOut(BaseModel):
    key: str
    label: str
    min_percentile: float


class ManifestOut(BaseModel):
    """The agent's entry point: capabilities, vocabulary, and hard limits."""

    purpose: str
    rules: list[str] = Field(
        description="Constraints on what may be concluded from this data. These are "
        "not style preferences — breaking them produces claims the data cannot support."
    )
    metrics: dict[str, str]
    endpoints: list[EndpointHint]
    success_bands: list[SuccessBandOut]
    method_notes: str
    coverage: CoverageOut
