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


class SuccessTierPoint(BaseModel):
    key: str
    label: str
    count: int
    min_sales: int
    max_sales: int | None  # None = open-ended top tier


class GenreSuccessOut(BaseModel):
    """Estimated success spread for one genre — a heuristic, never a fact.

    The formula, the multiplier actually used and its source travel with the
    numbers so the reader can recompute or discount them, the same way budget
    and revenue estimates carry their inputs. Games with no review count are
    reported in `games_without_reviews` and left out of the tiers rather than
    guessed into one.
    """

    genre: str
    games_in_genre: int
    games_scored: int
    games_without_reviews: int
    multiplier: float
    formula: str
    method: str
    source: str
    tiers: list[SuccessTierPoint]
