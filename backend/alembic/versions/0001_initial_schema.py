"""Initial schema — games, companies, taxonomy, stats, business data, media, sync.

Revision ID: 0001
Revises:
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

data_status = postgresql.ENUM(
    "confirmed", "estimated", "unknown", name="data_status", create_type=False
)
dimension = postgresql.ENUM("2d", "2.5d", "3d", "unknown", name="dimension", create_type=False)
camera = postgresql.ENUM(
    "top_down",
    "isometric",
    "first_person",
    "third_person",
    "side_scroller",
    "unknown",
    name="camera",
    create_type=False,
)
graphics_style = postgresql.ENUM(
    "pixel_art",
    "hd_pixel_art",
    "voxel",
    "stylized",
    "low_poly",
    "realistic",
    "anime",
    "hand_painted",
    "ps1_style",
    "ps2_style",
    "unknown",
    name="graphics_style",
    create_type=False,
)
game_engine = postgresql.ENUM(
    "unity", "unreal", "godot", "gamemaker", "custom", "unknown",
    name="game_engine",
    create_type=False,
)
controller_support = postgresql.ENUM(
    "full", "partial", "none", "unknown", name="controller_support", create_type=False
)
steam_deck_support = postgresql.ENUM(
    "verified", "playable", "unsupported", "unknown",
    name="steam_deck_support",
    create_type=False,
)
media_type = postgresql.ENUM(
    "header", "capsule", "screenshot", "movie", name="media_type", create_type=False
)
sync_stage = postgresql.ENUM(
    "discovery", "store_data", "classification", "market_data", "business_data",
    name="sync_stage",
    create_type=False,
)
sync_status = postgresql.ENUM(
    "pending", "in_progress", "done", "failed", "skipped",
    name="sync_status",
    create_type=False,
)

ALL_ENUMS = (
    data_status,
    dimension,
    camera,
    graphics_style,
    game_engine,
    controller_support,
    steam_deck_support,
    media_type,
    sync_stage,
    sync_status,
)

NOW = sa.text("now()")


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ALL_ENUMS:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "developers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("country", sa.Text),
        sa.Column("country_status", data_status, nullable=False, server_default="unknown"),
        sa.Column("website", sa.Text),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_developers_name", "developers", ["name"], unique=True)

    op.create_table(
        "publishers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("country", sa.Text),
        sa.Column("country_status", data_status, nullable=False, server_default="unknown"),
        sa.Column("website", sa.Text),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_publishers_name", "publishers", ["name"], unique=True)

    op.create_table(
        "genres",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("steam_genre_id", sa.Text, unique=True),
        sa.Column("name", sa.Text, nullable=False),
    )
    op.create_index("ix_genres_name", "genres", ["name"], unique=True)

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
    )
    op.create_index("ix_tags_name", "tags", ["name"], unique=True)

    op.create_table(
        "festivals",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("is_next_fest", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("start_date", sa.Date),
        sa.Column("end_date", sa.Date),
    )
    op.create_index("ix_festivals_is_next_fest", "festivals", ["is_next_fest"])

    op.create_table(
        "games",
        sa.Column("appid", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("short_description", sa.Text),
        sa.Column("steam_store_url", sa.Text),
        sa.Column("steamdb_url", sa.Text),
        sa.Column("release_date", sa.Date),
        sa.Column("release_date_raw", sa.Text),
        sa.Column("is_released", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("coming_soon", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("early_access", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("page_creation_date", sa.Date),
        sa.Column("page_creation_source", sa.Text),
        sa.Column("demo_available", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("demo_appid", sa.BigInteger),
        sa.Column("demo_release_date", sa.Date),
        sa.Column("is_free", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("currency", sa.Text),
        sa.Column("launch_price_cents", sa.Integer),
        sa.Column("current_price_cents", sa.Integer),
        sa.Column("launch_discount_pct", sa.Integer),
        sa.Column(
            "controller_support", controller_support, nullable=False, server_default="unknown"
        ),
        sa.Column(
            "steam_deck_support", steam_deck_support, nullable=False, server_default="unknown"
        ),
        sa.Column("supported_languages", postgresql.JSONB),
        sa.Column("header_image_url", sa.Text),
        sa.Column("capsule_image_url", sa.Text),
        sa.Column("dimension", dimension, nullable=False, server_default="unknown"),
        sa.Column("camera", camera, nullable=False, server_default="unknown"),
        sa.Column("graphics_style", graphics_style, nullable=False, server_default="unknown"),
        sa.Column("engine", game_engine, nullable=False, server_default="unknown"),
        sa.Column("is_indie", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_games_name", "games", ["name"])
    op.create_index("ix_games_release_date", "games", ["release_date"])
    op.create_index("ix_games_dimension", "games", ["dimension"])
    op.create_index("ix_games_engine", "games", ["engine"])
    op.create_index("ix_games_is_indie", "games", ["is_indie"])
    # Fast ILIKE search on game names (pg_trgm created in database/init).
    op.execute(
        "CREATE INDEX ix_games_name_trgm ON games USING gin (name gin_trgm_ops)"
    )

    op.create_table(
        "game_developers",
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "developer_id",
            sa.Integer,
            sa.ForeignKey("developers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "game_publishers",
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "publisher_id",
            sa.Integer,
            sa.ForeignKey("publishers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "game_genres",
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "genre_id",
            sa.Integer,
            sa.ForeignKey("genres.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "game_tags",
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            sa.Integer,
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("rank", sa.Integer),
        sa.Column("votes", sa.Integer),
    )

    op.create_table(
        "game_festivals",
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "festival_id",
            sa.Integer,
            sa.ForeignKey("festivals.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("source_url", sa.Text),
        sa.Column("notes", sa.Text),
    )

    op.create_table(
        "steam_stats",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "appid", sa.BigInteger, sa.ForeignKey("games.appid", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("positive_reviews", sa.Integer),
        sa.Column("negative_reviews", sa.Integer),
        sa.Column("total_reviews", sa.Integer),
        sa.Column("positive_pct", sa.Numeric(5, 2)),
        sa.Column("review_score", sa.Integer),
        sa.Column("review_score_desc", sa.Text),
        sa.Column("peak_ccu", sa.Integer),
        sa.Column("avg_ccu", sa.Numeric(12, 2)),
        sa.Column("followers", sa.Integer),
        sa.Column("source_name", sa.Text),
        sa.Column("source_url", sa.Text),
    )
    op.create_index("ix_steam_stats_appid", "steam_stats", ["appid"])
    op.create_index("ix_steam_stats_appid_captured_at", "steam_stats", ["appid", "captured_at"])

    op.create_table(
        "wishlist_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "appid", sa.BigInteger, sa.ForeignKey("games.appid", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", data_status, nullable=False, server_default="unknown"),
        sa.Column("wishlist_count", sa.BigInteger),
        sa.Column("source_name", sa.Text),
        sa.Column("source_url", sa.Text),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("notes", sa.Text),
    )
    op.create_index("ix_wishlist_records_appid", "wishlist_records", ["appid"])
    op.create_index("ix_wishlist_records_status", "wishlist_records", ["status"])

    op.create_table(
        "revenue_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "appid", sa.BigInteger, sa.ForeignKey("games.appid", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", data_status, nullable=False, server_default="unknown"),
        sa.Column("gross_revenue_usd", sa.Numeric(14, 2)),
        sa.Column("net_revenue_usd", sa.Numeric(14, 2)),
        sa.Column("estimated_sales", sa.BigInteger),
        sa.Column("estimated_owners_min", sa.BigInteger),
        sa.Column("estimated_owners_max", sa.BigInteger),
        sa.Column("source_name", sa.Text),
        sa.Column("source_url", sa.Text),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("notes", sa.Text),
    )
    op.create_index("ix_revenue_records_appid", "revenue_records", ["appid"])
    op.create_index("ix_revenue_records_status", "revenue_records", ["status"])

    op.create_table(
        "marketing_info",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "appid",
            sa.BigInteger,
            sa.ForeignKey("games.appid", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("budget_estimate_usd", sa.Numeric(14, 2)),
        sa.Column("budget_status", data_status, nullable=False, server_default="unknown"),
        sa.Column("marketing_notes", sa.Text),
        sa.Column("developer_interview_url", sa.Text),
        sa.Column("publisher_interview_url", sa.Text),
        sa.Column("kickstarter_url", sa.Text),
        sa.Column("source_name", sa.Text),
        sa.Column("source_url", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "appid", sa.BigInteger, sa.ForeignKey("games.appid", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("media_type", media_type, nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("thumbnail_url", sa.Text),
        sa.Column("position", sa.Integer),
        sa.Column("local_path", sa.Text),
    )
    op.create_index("ix_media_assets_appid", "media_assets", ["appid"])

    op.create_table(
        "sync_states",
        sa.Column("appid", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("stage", sync_stage, primary_key=True),
        sa.Column("status", sync_status, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
    )
    op.create_index("ix_sync_states_status", "sync_states", ["status"])


def downgrade() -> None:
    for table in (
        "sync_states",
        "media_assets",
        "marketing_info",
        "revenue_records",
        "wishlist_records",
        "steam_stats",
        "game_festivals",
        "game_tags",
        "game_genres",
        "game_publishers",
        "game_developers",
        "games",
        "festivals",
        "tags",
        "genres",
        "publishers",
        "developers",
    ):
        op.drop_table(table)

    bind = op.get_bind()
    for enum_type in ALL_ENUMS:
        enum_type.drop(bind, checkfirst=True)
