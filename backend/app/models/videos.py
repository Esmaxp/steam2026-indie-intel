"""Per-game community video support: channels, lazy cache, submissions, quota.

Videos are never pre-fetched for the whole catalog. The fetcher runs only when
a game page is opened, reads channel info from `game_channels` (populated by
approved submissions), caches the result in `video_cache` and counts every
third-party API call in `api_usage_daily` so a traffic spike cannot exhaust
the daily quota.
"""

import datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GameChannels(Base):
    __tablename__ = "game_channels"

    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"),
        primary_key=True, autoincrement=False,
    )
    youtube_url: Mapped[str | None] = mapped_column(Text)
    # Resolved from youtube_url on first fetch and cached to save quota.
    youtube_channel_id: Mapped[str | None] = mapped_column(Text)
    twitch_login: Mapped[str | None] = mapped_column(Text)
    # Manual-list platforms (tiktok/instagram/x): [{platform, url, title?}]
    manual_links: Mapped[list | None] = mapped_column(JSONB)
    source: Mapped[str | None] = mapped_column(Text)  # submission | admin
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class VideoCache(Base):
    __tablename__ = "video_cache"

    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"),
        primary_key=True, autoincrement=False,
    )
    payload: Mapped[dict] = mapped_column(JSONB)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChannelSubmission(Base):
    __tablename__ = "channel_submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"), index=True
    )
    youtube_url: Mapped[str | None] = mapped_column(Text)
    twitch_login: Mapped[str | None] = mapped_column(Text)
    other_links: Mapped[list | None] = mapped_column(JSONB)
    submitter_ip: Mapped[str | None] = mapped_column(Text)
    # developer_submitted (form) | auto_detected (website scanner)
    source: Mapped[str] = mapped_column(Text, default="developer_submitted")
    # Auto-detected only: the official website the links were found on.
    found_on: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending", index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)


class WebsiteScan(Base):
    """Scanner bookkeeping: one row per checked game website (resume support)."""

    __tablename__ = "website_scans"

    appid: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("games.appid", ondelete="CASCADE"),
        primary_key=True, autoincrement=False,
    )
    scanned_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # found | none | fetch_error | robots_disallowed | not_html
    outcome: Mapped[str] = mapped_column(Text)
    links_found: Mapped[int] = mapped_column(Integer, default=0)


class ApiUsageDaily(Base):
    __tablename__ = "api_usage_daily"

    day: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    platform: Mapped[str] = mapped_column(Text, primary_key=True)
    units: Mapped[int] = mapped_column(Integer, default=0)
