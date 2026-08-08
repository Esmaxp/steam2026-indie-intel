"""Wishlist, revenue and marketing data.

Steam exposes none of these numbers. Every record therefore carries a
`data_status` (confirmed / estimated / unknown) plus its public source.
Values are never invented; missing data stays NULL with status "unknown".
"""

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._types import TimestampMixin, pg_enum
from app.models.enums import DataStatus


class WishlistRecord(Base):
    __tablename__ = "wishlist_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), index=True
    )
    status: Mapped[DataStatus] = mapped_column(
        pg_enum(DataStatus, "data_status"), default=DataStatus.UNKNOWN, index=True
    )
    wishlist_count: Mapped[int | None] = mapped_column(BigInteger)
    source_name: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text)

    game: Mapped["Game"] = relationship(back_populates="wishlist_records")  # noqa: F821


class RevenueEstimate(Base):
    """One row per (game, source) collection — the raw multi-source layer.

    RevenueRecord remains the primary/summary view; it is now derived from
    these rows (Confirmed wins; otherwise the median of Estimated values,
    with status=conflicting when sources spread more than 50%)."""

    __tablename__ = "revenue_estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), index=True
    )
    source_name: Mapped[str] = mapped_column(Text)  # gamalytic|steamspy|vginsights|disclosed
    status: Mapped[DataStatus] = mapped_column(
        pg_enum(DataStatus, "data_status"), default=DataStatus.ESTIMATED
    )
    revenue_usd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    estimated_sales: Mapped[int | None] = mapped_column(BigInteger)
    owners_min: Mapped[int | None] = mapped_column(BigInteger)
    owners_max: Mapped[int | None] = mapped_column(BigInteger)
    wishlist_count: Mapped[int | None] = mapped_column(BigInteger)
    source_url: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    game: Mapped["Game"] = relationship()  # noqa: F821


class RevenueRecord(Base):
    __tablename__ = "revenue_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), index=True
    )
    status: Mapped[DataStatus] = mapped_column(
        pg_enum(DataStatus, "data_status"), default=DataStatus.UNKNOWN, index=True
    )
    gross_revenue_usd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    net_revenue_usd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    estimated_sales: Mapped[int | None] = mapped_column(BigInteger)
    estimated_owners_min: Mapped[int | None] = mapped_column(BigInteger)
    estimated_owners_max: Mapped[int | None] = mapped_column(BigInteger)
    # (max-min)/median across the sources merged into this summary row.
    estimate_spread: Mapped[float | None] = mapped_column(Numeric(6, 3))
    source_name: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text)

    game: Mapped["Game"] = relationship(back_populates="revenue_records")  # noqa: F821


class MarketingInfo(Base, TimestampMixin):
    __tablename__ = "marketing_info"

    id: Mapped[int] = mapped_column(primary_key=True)
    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), unique=True
    )
    budget_estimate_usd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    budget_status: Mapped[DataStatus] = mapped_column(
        pg_enum(DataStatus, "data_status"), default=DataStatus.UNKNOWN
    )
    marketing_notes: Mapped[str | None] = mapped_column(Text)
    developer_interview_url: Mapped[str | None] = mapped_column(Text)
    publisher_interview_url: Mapped[str | None] = mapped_column(Text)
    kickstarter_url: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    # Team-cost budget inputs — only from disclosed, human-verified sources.
    team_size: Mapped[int | None] = mapped_column(Integer)
    team_region: Mapped[str | None] = mapped_column(Text)
    dev_duration_months: Mapped[int | None] = mapped_column(Integer)

    game: Mapped["Game"] = relationship(back_populates="marketing_info")  # noqa: F821


class BudgetEstimate(Base):
    """Auditable budget heuristics — never presented as fact.

    Each row stores the method, the resulting range, the formula text and the
    exact inputs used, so every number can be traced and re-derived."""

    __tablename__ = "budget_estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(Text)  # team_cost | revenue_ratio
    budget_min_usd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    budget_max_usd: Mapped[float | None] = mapped_column(Numeric(14, 2))
    formula: Mapped[str] = mapped_column(Text)
    inputs: Mapped[dict] = mapped_column(JSONB)
    source_name: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    game: Mapped["Game"] = relationship()  # noqa: F821
