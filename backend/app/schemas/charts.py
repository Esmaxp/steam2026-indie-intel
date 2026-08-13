from pydantic import BaseModel


class MonthPoint(BaseModel):
    month: int  # 1–12 (2026)
    released: int
    upcoming: int


class BreakdownPoint(BaseModel):
    key: str
    count: int


class ChartsOut(BaseModel):
    """Aggregations for the analytics section. Counts only — never invented
    values; 'unknown' buckets are shown as such, not hidden."""

    releases_by_month: list[MonthPoint]
    by_dimension: list[BreakdownPoint]
    by_engine: list[BreakdownPoint]
    by_graphics_style: list[BreakdownPoint]
    top_genres: list[BreakdownPoint]


class SuccessBandPoint(BaseModel):
    key: str
    label: str
    count: int
    share: float           # count / games_scored
    baseline_share: float  # what an average genre would show — true by construction
    min_percentile: float


class GenreSuccessOut(BaseModel):
    """Where one genre's games sit among their release-month peers.

    A ranking of a measured value (Steam's own review count), not an estimate:
    no sales figure is derived, so there is no multiplier to disagree with.
    Games that cannot be ranked are counted in the two exclusion fields rather
    than placed in a band.
    """

    genre: str
    games_in_genre: int
    games_scored: int
    games_excluded_unreleased: int
    games_excluded_no_reviews: int
    measure: str
    cohort: str
    method: str
    notes: str
    bands: list[SuccessBandPoint]
