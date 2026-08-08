import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Provenanced(BaseModel):
    """A value Steam does not expose. status tells how trustworthy it is:
    confirmed / estimated / unknown / conflicting. Unknown values are None,
    never guessed; conflicting means independent sources disagree >50% and
    estimate_spread carries (max-min)/median."""

    value: float | None = None
    status: str = "unknown"
    source_name: str | None = None
    source_url: str | None = None
    recorded_at: datetime.datetime | None = None
    estimate_spread: float | None = None


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int
