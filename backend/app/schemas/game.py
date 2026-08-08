import datetime

from pydantic import BaseModel

from app.schemas.common import Provenanced


class CompanyOut(BaseModel):
    id: int
    name: str
    country: str | None = None
    country_status: str = "unknown"
    website: str | None = None


class TagOut(BaseModel):
    name: str
    rank: int | None = None
    votes: int | None = None


class MediaOut(BaseModel):
    media_type: str
    url: str
    thumbnail_url: str | None = None
    position: int | None = None


class FestivalOut(BaseModel):
    name: str
    is_next_fest: bool
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    source_url: str | None = None
    notes: str | None = None


class StatsPoint(BaseModel):
    captured_at: datetime.datetime
    positive_reviews: int | None = None
    negative_reviews: int | None = None
    total_reviews: int | None = None
    positive_pct: float | None = None
    review_score: int | None = None
    review_score_desc: str | None = None
    peak_ccu: int | None = None
    avg_ccu: float | None = None
    followers: int | None = None
    source_name: str | None = None


class GameListItem(BaseModel):
    appid: int
    name: str
    header_image_url: str | None = None
    capsule_image_url: str | None = None
    steam_store_url: str | None = None
    steamdb_url: str | None = None

    developers: list[str] = []
    publishers: list[str] = []

    release_date: datetime.date | None = None
    release_date_raw: str | None = None
    is_released: bool = False
    coming_soon: bool = False
    early_access: bool = False
    demo_available: bool = False
    demo_release_date: datetime.date | None = None
    next_fest: bool = False

    genres: list[str] = []
    tags: list[str] = []

    dimension: str = "unknown"
    camera: str = "unknown"
    graphics_style: str = "unknown"
    engine: str = "unknown"

    indie_confidence: str = "medium"
    low_quality_signal: bool = False

    is_free: bool = False
    currency: str | None = None
    current_price_cents: int | None = None

    total_reviews: int | None = None
    positive_pct: float | None = None
    review_score_desc: str | None = None
    peak_ccu: int | None = None
    avg_ccu: float | None = None

    wishlist: Provenanced = Provenanced()
    revenue: Provenanced = Provenanced()
    estimated_sales: int | None = None
    budget: Provenanced = Provenanced()


class MarketingOut(BaseModel):
    budget: Provenanced = Provenanced()
    marketing_notes: str | None = None
    developer_interview_url: str | None = None
    publisher_interview_url: str | None = None
    kickstarter_url: str | None = None


class WishlistRecordOut(BaseModel):
    status: str
    wishlist_count: int | None = None
    source_name: str | None = None
    source_url: str | None = None
    recorded_at: datetime.datetime
    notes: str | None = None


class RevenueRecordOut(BaseModel):
    status: str
    gross_revenue_usd: float | None = None
    net_revenue_usd: float | None = None
    estimated_sales: int | None = None
    estimated_owners_min: int | None = None
    estimated_owners_max: int | None = None
    source_name: str | None = None
    source_url: str | None = None
    recorded_at: datetime.datetime
    notes: str | None = None


class GameDetail(GameListItem):
    short_description: str | None = None
    supported_languages: list[str] = []
    controller_support: str = "unknown"
    steam_deck_support: str = "unknown"
    launch_price_cents: int | None = None
    launch_discount_pct: int | None = None
    page_creation_date: datetime.date | None = None
    page_creation_source: str | None = None
    demo_appid: int | None = None
    last_synced_at: datetime.datetime | None = None

    developers_full: list[CompanyOut] = []
    publishers_full: list[CompanyOut] = []
    tags_full: list[TagOut] = []
    media: list[MediaOut] = []
    festivals: list[FestivalOut] = []
    latest_stats: StatsPoint | None = None
    wishlist_history: list[WishlistRecordOut] = []
    revenue_history: list[RevenueRecordOut] = []
    marketing: MarketingOut | None = None


class AverageStat(BaseModel):
    """Average over games that actually have the value; sample_size says how
    many that is — never an average over invented zeros."""

    value: float | None = None
    sample_size: int = 0


class DashboardSummary(BaseModel):
    total_games: int
    released_games: int
    coming_soon_games: int
    two_d_games: int
    three_d_games: int
    games_with_demo: int
    next_fest_games: int
    avg_reviews: AverageStat
    avg_wishlist: AverageStat
    avg_revenue: AverageStat


class FilterOptions(BaseModel):
    genres: list[str]
    tags: list[str]
    engines: list[str]
    dimensions: list[str]
    cameras: list[str]
    graphics_styles: list[str]
    data_statuses: list[str]
    release_months: list[int]
