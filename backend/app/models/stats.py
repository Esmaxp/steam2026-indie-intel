import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SteamStats(Base):
    """Append-only snapshots of publicly visible Steam statistics."""

    __tablename__ = "steam_stats"
    __table_args__ = (Index("ix_steam_stats_appid_captured_at", "appid", "captured_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), index=True
    )
    captured_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    positive_reviews: Mapped[int | None] = mapped_column(Integer)
    negative_reviews: Mapped[int | None] = mapped_column(Integer)
    total_reviews: Mapped[int | None] = mapped_column(Integer)
    positive_pct: Mapped[float | None] = mapped_column(Numeric(5, 2))
    review_score: Mapped[int | None] = mapped_column(Integer)
    review_score_desc: Mapped[str | None] = mapped_column(Text)

    # NULL when the value is not publicly available — never guessed.
    peak_ccu: Mapped[int | None] = mapped_column(Integer)
    avg_ccu: Mapped[float | None] = mapped_column(Numeric(12, 2))
    followers: Mapped[int | None] = mapped_column(Integer)

    source_name: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)

    game: Mapped["Game"] = relationship(back_populates="stats")  # noqa: F821


class FollowerSnapshot(Base):
    """Append-only community-hub follower counts — a MEASURED value.

    Separate from steam_stats.followers on purpose: latest_stats_sq() takes
    DISTINCT ON (appid) ORDER BY captured_at DESC, so a follower-only row on
    the daily follower cadence would become the "latest stats" row and blank
    reviews/CCU for that game. The two run on different cadences and cannot
    share a DISTINCT-ON table.

    A follower count is the number of accounts following the game's hub. It
    is NOT a wishlist count and must never be presented as one.
    """

    __tablename__ = "follower_snapshots"
    __table_args__ = (
        Index("ix_follower_snapshots_appid_captured_at", "appid", "captured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), nullable=False
    )
    captured_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    followers: Mapped[int] = mapped_column(Integer, nullable=False)
    source_name: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)


class WishlistRankSweep(Base):
    """One run of the Valve Top-Wishlists sweep.

    The header exists so a truncated sweep cannot be mistaken for a complete
    one: consumers must read rank only from sweeps with status='complete',
    otherwise an aborted run reads as "everything below rank N dropped off
    the chart".
    """

    __tablename__ = "wishlist_rank_sweeps"
    __table_args__ = (
        # Bare suffix — NAMING_CONVENTION adds the ck_<table>_ prefix.
        CheckConstraint("status in ('complete','partial','failed')", name="status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    # Region is part of the observation — listings are region-scoped.
    cc: Mapped[str] = mapped_column(Text, server_default="us", nullable=False)
    total_count: Mapped[int | None] = mapped_column(Integer)
    rows_ingested: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="partial", nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    entries: Mapped[list["WishlistRankEntry"]] = relationship(
        back_populates="sweep", cascade="all, delete-orphan"
    )


class WishlistRankEntry(Base):
    """One game's ordinal position in a sweep.

    Valve's Top-Wishlists position blends total wishlists with recent
    velocity — it is an ORDER, not a count, and no count may be derived
    from it.

    `appid` intentionally has NO foreign key to games.appid: the chart is a
    global list spanning all of Steam while this catalogue is indie-only, so
    an FK would discard most rows and prevent backfilling rank history for a
    game discovered later. Consumers INNER JOIN to games.
    """

    __tablename__ = "wishlist_rank_entries"
    __table_args__ = (
        UniqueConstraint("sweep_id", "appid", name="uq_wishlist_rank_entries_sweep_appid"),
        Index("ix_wishlist_rank_entries_appid_sweep", "appid", "sweep_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sweep_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("wishlist_rank_sweeps.id", ondelete="CASCADE"), nullable=False
    )
    appid: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)

    sweep: Mapped["WishlistRankSweep"] = relationship(back_populates="entries")
