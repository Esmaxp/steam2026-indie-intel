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
    # Axis 1: 0-100 and its class, plus the signals that earned it — a score
    # without its reasoning is not reviewable.
    effort_score: int | None = None
    effort_class: str = "unknown"
    effort_signals: dict | None = None
    # The production-only view of the same signals. Separate field because
    # the combined score above is 60% marketing and pricing decisions.
    craft_score: int | None = None
    craft_class: str = "unknown"
    # Axis 2: what players did. traction_status says why a score is absent.
    traction_score: int | None = None
    traction_class: str = "unknown"
    traction_status: str = "insufficient_data_no_signals"
    classification: str = "INSUFFICIENT_DATA"
    classification_confidence: str = "low"
    # None = the store page has not been read yet, not "unrestricted".
    limited_profile: bool | None = None
    ai_disclosure: bool | None = None

    is_free: bool = False
    currency: str | None = None
    current_price_cents: int | None = None

    total_reviews: int | None = None
    positive_pct: float | None = None
    review_score_desc: str | None = None
    peak_ccu: int | None = None
    avg_ccu: float | None = None

    # --- first-party measured demand signals ---------------------------------
    # Followers and rank are MEASURED — Valve publishes both — so they are
    # plain fields, deliberately not Provenanced. That wrapper exists for
    # values Steam does not expose and which therefore carry a trust status.
    followers: int | None = None
    followers_captured_at: datetime.datetime | None = None
    follower_delta_14d: int | None = None
    follower_delta_14d_pct: float | None = None
    # Valve's Top-Wishlists position. Blends total wishlists with recent
    # velocity — an ORDER, never a count, and no count may be derived from it.
    # None means "not on the chart", which is the common case: the chart holds
    # ~5.2k games across all of Steam.
    wishlist_rank: int | None = None
    wishlist_ranked: bool = False
    # Positive = moved UP the chart. Ships hidden until day-over-day rank
    # volatility is measured (scripts/rank_delta_report.py).
    rank_delta_7d: int | None = None

    # Only ever `confirmed` (a developer disclosed it) or `unknown`. No
    # estimate is ever computed for this field — see the wishlist plan.
    wishlist: Provenanced = Provenanced()
    revenue: Provenanced = Provenanced()
    estimated_sales: int | None = None
    # Cached community-video clip count (0 = none fetched/found).
    video_count: int = 0


class BudgetEstimateOut(BaseModel):
    """One heuristic budget estimate with its full audit trail."""

    method: str  # team_cost | revenue_ratio
    budget_min_usd: float | None = None
    budget_max_usd: float | None = None
    formula: str
    inputs: dict
    source_name: str | None = None
    source_url: str | None = None
    computed_at: datetime.datetime


class MarketingOut(BaseModel):
    budget: Provenanced = Provenanced()
    marketing_notes: str | None = None
    developer_interview_url: str | None = None
    publisher_interview_url: str | None = None
    kickstarter_url: str | None = None


class WishlistRecordOut(BaseModel):
    status: str
    wishlist_count: int | None = None
    # '>=' for a disclosed lower bound; see Provenanced.comparator.
    comparator: str = "="
    disclosed_on: datetime.date | None = None
    source_name: str | None = None
    source_url: str | None = None
    recorded_at: datetime.datetime
    notes: str | None = None


class FollowerPoint(BaseModel):
    """One community-hub follower measurement. Exact, first-party."""

    captured_at: datetime.datetime
    followers: int
    source_name: str | None = None
    source_url: str | None = None


class RankPoint(BaseModel):
    """One Top-Wishlists position from a COMPLETE sweep.

    Partial sweeps are excluded: they hold only the head of the chart, so
    including them would read as a game dropping off it.
    """

    swept_at: datetime.datetime
    rank: int
    total_ranked: int | None = None
    cc: str = "us"


class RevenueRecordOut(BaseModel):
    """The merged summary. Every *_min/_max pair is None for a disclosed
    figure: a developer's own number is a figure, not a band, and rendering
    it with zero width would present it as an estimate that happened to be
    precise."""

    status: str
    gross_revenue_usd: float | None = None
    gross_min_usd: float | None = None
    gross_max_usd: float | None = None
    net_revenue_usd: float | None = None
    net_min_usd: float | None = None
    net_max_usd: float | None = None
    sales_min: int | None = None
    sales_max: int | None = None
    sources_used: int | None = None
    estimated_sales: int | None = None
    estimated_owners_min: int | None = None
    estimated_owners_max: int | None = None
    estimate_spread: float | None = None
    source_name: str | None = None
    source_url: str | None = None
    recorded_at: datetime.datetime
    notes: str | None = None


class RevenueEstimateOut(BaseModel):
    """One raw estimate from one source — always with link and date."""

    source_name: str
    status: str
    method: str | None = None
    revenue_usd: float | None = None
    revenue_min_usd: float | None = None
    revenue_max_usd: float | None = None
    net_revenue_usd: float | None = None
    net_min_usd: float | None = None
    net_max_usd: float | None = None
    estimated_sales: int | None = None
    copies_min: int | None = None
    copies_max: int | None = None
    owners_min: int | None = None
    owners_max: int | None = None
    wishlist_count: int | None = None
    # The arithmetic and the exact values fed into it, so a reader who
    # disagrees can redo it without reading the code.
    formula: str | None = None
    inputs: dict | None = None
    confidence: str | None = None
    source_url: str
    retrieved_at: datetime.datetime


class GameDetail(GameListItem):
    short_description: str | None = None
    website: str | None = None
    # indie_tag | self_published_no_tag | boutique_label_no_tag
    discovery_method: str = "indie_tag"
    # tag | rule_based | vision_ai | unknown
    dimension_source: str = "unknown"
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
    revenue_estimates: list[RevenueEstimateOut] = []
    budget_estimates: list[BudgetEstimateOut] = []
    marketing: MarketingOut | None = None


class GameSearchResult(BaseModel):
    """Lightweight pair for the similar-games autocomplete."""

    appid: int
    name: str


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
    # Coverage counters, not averages. There is no wishlist average to report:
    # a wishlist figure exists only where a developer disclosed one, and those
    # are mostly lower bounds ("over 100,000"), so averaging them would invent
    # a precision the data does not have.
    games_with_followers: int
    ranked_games: int
    confirmed_wishlist_games: int


class FilterOptions(BaseModel):
    genres: list[str]
    tags: list[str]
    engines: list[str]
    dimensions: list[str]
    cameras: list[str]
    graphics_styles: list[str]
    data_statuses: list[str]
    release_months: list[int]
