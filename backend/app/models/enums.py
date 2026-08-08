import enum


class DataStatus(str, enum.Enum):
    """Provenance of any value Steam does not expose. Never fabricate data."""

    CONFIRMED = "confirmed"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class IndieConfidence(str, enum.Enum):
    """Multi-signal confidence that a game is genuinely indie."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Dimension(str, enum.Enum):
    TWO_D = "2d"
    TWO_HALF_D = "2.5d"
    THREE_D = "3d"
    UNKNOWN = "unknown"


class Camera(str, enum.Enum):
    TOP_DOWN = "top_down"
    ISOMETRIC = "isometric"
    FIRST_PERSON = "first_person"
    THIRD_PERSON = "third_person"
    SIDE_SCROLLER = "side_scroller"
    UNKNOWN = "unknown"


class GraphicsStyle(str, enum.Enum):
    PIXEL_ART = "pixel_art"
    HD_PIXEL_ART = "hd_pixel_art"
    VOXEL = "voxel"
    STYLIZED = "stylized"
    LOW_POLY = "low_poly"
    REALISTIC = "realistic"
    ANIME = "anime"
    HAND_PAINTED = "hand_painted"
    PS1_STYLE = "ps1_style"
    PS2_STYLE = "ps2_style"
    UNKNOWN = "unknown"


class GameEngine(str, enum.Enum):
    UNITY = "unity"
    UNREAL = "unreal"
    GODOT = "godot"
    GAMEMAKER = "gamemaker"
    CUSTOM = "custom"
    UNKNOWN = "unknown"


class ControllerSupport(str, enum.Enum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"
    UNKNOWN = "unknown"


class SteamDeckSupport(str, enum.Enum):
    VERIFIED = "verified"
    PLAYABLE = "playable"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class MediaType(str, enum.Enum):
    HEADER = "header"
    CAPSULE = "capsule"
    SCREENSHOT = "screenshot"
    MOVIE = "movie"


class SyncStage(str, enum.Enum):
    DISCOVERY = "discovery"
    STORE_DATA = "store_data"
    CLASSIFICATION = "classification"
    MARKET_DATA = "market_data"
    BUSINESS_DATA = "business_data"


class SyncStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
