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
