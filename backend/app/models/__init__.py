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
from app.models.stats import (
    FollowerSnapshot,
    PriceSnapshot,
    SteamStats,
    WishlistRankEntry,
    WishlistRankSweep,
)
from app.models.sweeps import SWEEP_KINDS, TERMINAL_STATUSES, SweepJob
from app.models.sync import SyncState
from app.models.taxonomy import Genre, Tag
from app.models.videos import (
    ApiUsageDaily,
    ChannelSubmission,
    GameChannels,
    VideoCache,
    WebsiteScan,
)

__all__ = [
    "ApiUsageDaily",
    "BudgetEstimate",
    "Camera",
    "ChannelSubmission",
    "ControllerSupport",
    "DataStatus",
    "Developer",
    "Dimension",
    "Festival",
    "FollowerSnapshot",
    "Game",
    "GameChannels",
    "GameEngine",
    "Genre",
    "GraphicsStyle",
    "IndieConfidence",
    "MarketingInfo",
    "MediaAsset",
    "MediaType",
    "PriceSnapshot",
    "Publisher",
    "RevenueEstimate",
    "RevenueRecord",
    "SteamDeckSupport",
    "SWEEP_KINDS",
    "SteamStats",
    "SweepJob",
    "SyncStage",
    "SyncState",
    "SyncStatus",
    "TERMINAL_STATUSES",
    "Tag",
    "VideoCache",
    "WebsiteScan",
    "WishlistRankEntry",
    "WishlistRankSweep",
    "WishlistRecord",
    "game_developers",
    "game_festivals",
    "game_genres",
    "game_publishers",
    "game_tags",
]
