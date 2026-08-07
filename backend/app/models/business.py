"""Wishlist, revenue and marketing data.

Steam exposes none of these numbers. Every record therefore carries a
`data_status` (confirmed / estimated / unknown) plus its public source.
Values are never invented; missing data stays NULL with status "unknown".
"""

import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, Text, func
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

    game: Mapped["Game"] = relationship(back_populates="marketing_info")  # noqa: F821
