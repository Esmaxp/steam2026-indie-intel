import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, Text, func
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
