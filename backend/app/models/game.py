import datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._types import TimestampMixin, pg_enum
from app.models.associations import (
    game_developers,
    game_festivals,
    game_genres,
    game_publishers,
    game_tags,
)
from app.models.enums import (
    Camera,
    ControllerSupport,
    Dimension,
    GameEngine,
    GraphicsStyle,
    IndieConfidence,
    SteamDeckSupport,
)


class Game(Base, TimestampMixin):
    """One row per Steam app. Steam AppID is the primary key (no surrogate)."""

    __tablename__ = "games"

    appid: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text, index=True)
    short_description: Mapped[str | None] = mapped_column(Text)

    steam_store_url: Mapped[str | None] = mapped_column(Text)
    steamdb_url: Mapped[str | None] = mapped_column(Text)
    # Official website from Steam appdetails. NULL = never checked,
    # '' = checked and Steam reports none (stops the backfill re-fetching it).
    website: Mapped[str | None] = mapped_column(Text)

    # Release info. Steam returns free-form strings ("Q1 2026", "Coming soon"),
    # so the raw value is kept next to the parsed date.
    release_date: Mapped[datetime.date | None] = mapped_column(Date, index=True)
    release_date_raw: Mapped[str | None] = mapped_column(Text)
    is_released: Mapped[bool] = mapped_column(Boolean, default=False)
    coming_soon: Mapped[bool] = mapped_column(Boolean, default=False)
    early_access: Mapped[bool] = mapped_column(Boolean, default=False)

    page_creation_date: Mapped[datetime.date | None] = mapped_column(Date)
    page_creation_source: Mapped[str | None] = mapped_column(Text)

    demo_available: Mapped[bool] = mapped_column(Boolean, default=False)
    demo_appid: Mapped[int | None] = mapped_column(BigInteger)
    demo_release_date: Mapped[datetime.date | None] = mapped_column(Date)

    # Prices are stored in minor units (cents) exactly as Steam reports them.
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)
    currency: Mapped[str | None] = mapped_column(Text)
    launch_price_cents: Mapped[int | None] = mapped_column(Integer)
    current_price_cents: Mapped[int | None] = mapped_column(Integer)
    launch_discount_pct: Mapped[int | None] = mapped_column(Integer)

    controller_support: Mapped[ControllerSupport] = mapped_column(
        pg_enum(ControllerSupport, "controller_support"), default=ControllerSupport.UNKNOWN
    )
    steam_deck_support: Mapped[SteamDeckSupport] = mapped_column(
        pg_enum(SteamDeckSupport, "steam_deck_support"), default=SteamDeckSupport.UNKNOWN
    )

    supported_languages: Mapped[list | None] = mapped_column(JSONB)

    header_image_url: Mapped[str | None] = mapped_column(Text)
    capsule_image_url: Mapped[str | None] = mapped_column(Text)

    # Classification (Phase 3). Stays "unknown" unless the classifier is confident.
    dimension: Mapped[Dimension] = mapped_column(
        pg_enum(Dimension, "dimension"), default=Dimension.UNKNOWN, index=True
    )
    # Where the 2D/3D value came from: tag (Steam's own 2d/2.5d/3d tag) |
    # rule_based (camera/graphics/description fallback) | vision_ai | unknown.
    dimension_source: Mapped[str] = mapped_column(Text, default="unknown")
    camera: Mapped[Camera] = mapped_column(pg_enum(Camera, "camera"), default=Camera.UNKNOWN)
    graphics_style: Mapped[GraphicsStyle] = mapped_column(
        pg_enum(GraphicsStyle, "graphics_style"), default=GraphicsStyle.UNKNOWN
    )
    engine: Mapped[GameEngine] = mapped_column(
        pg_enum(GameEngine, "game_engine"), default=GameEngine.UNKNOWN, index=True
    )

    # Discovery bookkeeping.
    is_indie: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Multi-signal indie score: genre is the base filter; publisher size and
    # self-publishing move the needle. Low = flagged for review, never deleted.
    indie_confidence: Mapped[IndieConfidence] = mapped_column(
        pg_enum(IndieConfidence, "indie_confidence"),
        default=IndieConfidence.MEDIUM,
        index=True,
    )
    # Mass-publishing pattern (same company, 5+ releases in 30 days).
    low_quality_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    # How the game entered the catalog: indie_tag (Steam Indie genre/tag) |
    # self_published_no_tag | boutique_label_no_tag (opt-in applist fallback).
    discovery_method: Mapped[str] = mapped_column(Text, default="indie_tag", index=True)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_synced_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    developers: Mapped[list["Developer"]] = relationship(  # noqa: F821
        secondary=game_developers, back_populates="games"
    )
    publishers: Mapped[list["Publisher"]] = relationship(  # noqa: F821
        secondary=game_publishers, back_populates="games"
    )
    genres: Mapped[list["Genre"]] = relationship(  # noqa: F821
        secondary=game_genres, back_populates="games", order_by=game_genres.c.rank
    )
    tags: Mapped[list["Tag"]] = relationship(  # noqa: F821
        secondary=game_tags, back_populates="games", order_by=game_tags.c.rank
    )
    festivals: Mapped[list["Festival"]] = relationship(  # noqa: F821
        secondary=game_festivals, back_populates="games"
    )
    stats: Mapped[list["SteamStats"]] = relationship(  # noqa: F821
        back_populates="game", cascade="all, delete-orphan"
    )
    wishlist_records: Mapped[list["WishlistRecord"]] = relationship(  # noqa: F821
        back_populates="game", cascade="all, delete-orphan"
    )
    revenue_records: Mapped[list["RevenueRecord"]] = relationship(  # noqa: F821
        back_populates="game", cascade="all, delete-orphan"
    )
    marketing_info: Mapped["MarketingInfo | None"] = relationship(  # noqa: F821
        back_populates="game", cascade="all, delete-orphan", uselist=False
    )
    media_assets: Mapped[list["MediaAsset"]] = relationship(  # noqa: F821
        back_populates="game", cascade="all, delete-orphan"
    )
