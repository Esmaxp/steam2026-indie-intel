"""Import every model so Base.metadata is complete (Alembic autogenerate, create_all)."""

from app.models.associations import (
    game_developers,
    game_festivals,
    game_genres,
    game_publishers,
    game_tags,
)
from app.models.business import (
    BudgetEstimate,
    MarketingInfo,
    RevenueEstimate,
    RevenueRecord,
    WishlistRecord,
)
from app.models.company import Developer, Publisher
from app.models.enums import (
    Camera,
    ControllerSupport,
    DataStatus,
    Dimension,
    GameEngine,
    GraphicsStyle,
    IndieConfidence,
    MediaType,
    SteamDeckSupport,
    SyncStage,
    SyncStatus,
)
from app.models.festival import Festival
from app.models.game import Game
from app.models.media import MediaAsset
from app.models.stats import SteamStats
from app.models.sync import SyncState
from app.models.taxonomy import Genre, Tag

__all__ = [
    "BudgetEstimate",
    "Camera",
    "ControllerSupport",
    "DataStatus",
    "Developer",
    "Dimension",
    "Festival",
    "Game",
    "GameEngine",
    "Genre",
    "GraphicsStyle",
    "IndieConfidence",
    "MarketingInfo",
    "MediaAsset",
    "MediaType",
    "Publisher",
    "RevenueEstimate",
    "RevenueRecord",
    "SteamDeckSupport",
    "SteamStats",
    "SyncStage",
    "SyncState",
    "SyncStatus",
    "Tag",
    "WishlistRecord",
    "game_developers",
    "game_festivals",
    "game_genres",
    "game_publishers",
    "game_tags",
]
