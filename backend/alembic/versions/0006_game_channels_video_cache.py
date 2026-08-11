"""Per-game channels, lazy video cache, channel submissions, API quota, game website.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOW = sa.text("now()")


def upgrade() -> None:
    # Official website from Steam appdetails. NULL = never checked,
    # '' = checked and Steam reports none (prevents re-fetching forever).
    op.add_column("games", sa.Column("website", sa.Text))

    # Approved channel info per game — the only source the video fetcher reads.
    op.create_table(
        "game_channels",
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("youtube_url", sa.Text),
        # Resolved from youtube_url on first fetch and cached to save quota.
        sa.Column("youtube_channel_id", sa.Text),
        sa.Column("twitch_login", sa.Text),
        # Manual-list platforms (tiktok/instagram/x): [{platform, url, title?}]
        sa.Column("manual_links", postgresql.JSONB),
        sa.Column("source", sa.Text),  # submission | admin
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    # Lazy per-game video cache; payload mirrors the API response body.
    op.create_table(
        "video_cache",
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    # Developer self-service submissions — never applied without review.
    op.create_table(
        "channel_submissions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("youtube_url", sa.Text),
        sa.Column("twitch_login", sa.Text),
        sa.Column("other_links", postgresql.JSONB),  # tiktok/instagram/x profile URLs
        sa.Column("submitter_ip", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text),
    )
    op.create_index("ix_channel_submissions_appid", "channel_submissions", ["appid"])
    op.create_index("ix_channel_submissions_status", "channel_submissions", ["status"])
    op.create_index("ix_channel_submissions_created_at", "channel_submissions", ["created_at"])

    # Daily third-party API usage counter — the quota safety net.
    op.create_table(
        "api_usage_daily",
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("platform", sa.Text, primary_key=True),
        sa.Column("units", sa.Integer, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("api_usage_daily")
    op.drop_index("ix_channel_submissions_created_at", table_name="channel_submissions")
    op.drop_index("ix_channel_submissions_status", table_name="channel_submissions")
    op.drop_index("ix_channel_submissions_appid", table_name="channel_submissions")
    op.drop_table("channel_submissions")
    op.drop_table("video_cache")
    op.drop_table("game_channels")
    op.drop_column("games", "website")
