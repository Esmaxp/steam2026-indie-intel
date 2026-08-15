/** Mirrors the FastAPI response schemas (backend/app/schemas). */

export type DataStatus = "confirmed" | "estimated" | "unknown" | "conflicting";

export interface Provenanced {
  value: number | null;
  status: DataStatus;
  source_name: string | null;
  source_url: string | null;
  recorded_at: string | null;
  estimate_spread: number | null;
  /** ">=" when the source stated a lower bound ("over 100,000 wishlists"). */
  comparator: string;
  /** When the source published it, vs recorded_at = when we ingested it. */
  disclosed_on: string | null;
}

export interface RevenueEstimateOut {
  source_name: string;
  status: DataStatus;
  revenue_usd: number | null;
  estimated_sales: number | null;
  owners_min: number | null;
  owners_max: number | null;
  wishlist_count: number | null;
  source_url: string;
  retrieved_at: string;
}

export interface GameListItem {
  appid: number;
  name: string;
  header_image_url: string | null;
  capsule_image_url: string | null;
  steam_store_url: string | null;
  steamdb_url: string | null;
  developers: string[];
  publishers: string[];
  release_date: string | null;
  release_date_raw: string | null;
  is_released: boolean;
  coming_soon: boolean;
  early_access: boolean;
  demo_available: boolean;
  demo_release_date: string | null;
  next_fest: boolean;
  genres: string[];
  tags: string[];
  dimension: string;
  camera: string;
  graphics_style: string;
  engine: string;
  indie_confidence: "high" | "medium" | "low";
  low_quality_signal: boolean;
  /** Axis 1: production effort the store page evidences (0-100) — not sales. */
  effort_score: number | null;
  effort_class: "serious" | "mixed" | "hobby" | "unknown";
  /** Which signals earned the score, and what each was worth. */
  effort_signals: { score: number; signals: Record<string, number> } | null;
  /** The production-only view of those same signals: no marketing, no price,
   *  no release status. What the "Craft level" filter reads. */
  craft_score: number | null;
  craft_class: "serious" | "mixed" | "hobby" | "unknown";
  /** Axis 2: what players did. traction_status says why a score is absent. */
  traction_score: number | null;
  traction_class: "strong" | "modest" | "weak" | "unknown";
  traction_status: string;
  /** The two axes crossed; HIGH_EFFORT_LOW_TRACTION is the overlooked group. */
  classification:
    | "HIGH_EFFORT_HIGH_TRACTION"
    | "HIGH_EFFORT_LOW_TRACTION"
    | "LOW_EFFORT_HIGH_TRACTION"
    | "LOW_EFFORT_LOW_TRACTION"
    | "INSUFFICIENT_DATA";
  classification_confidence: "high" | "medium" | "low";
  /** null = store page not read yet, which is not the same as "unrestricted". */
  limited_profile: boolean | null;
  ai_disclosure: boolean | null;
  is_free: boolean;
  currency: string | null;
  current_price_cents: number | null;
  total_reviews: number | null;
  positive_pct: number | null;
  review_score_desc: string | null;
  peak_ccu: number | null;
  avg_ccu: number | null;
  // Measured first-party values Valve publishes — deliberately NOT Provenanced.
  followers: number | null;
  followers_captured_at: string | null;
  follower_delta_14d: number | null;
  follower_delta_14d_pct: number | null;
  /** Valve's Top-Wishlists position: an ORDER, not a count. null = not on the
   *  chart, which is the common case (~5.2k games across all of Steam). */
  wishlist_rank: number | null;
  wishlist_ranked: boolean;
  /** Positive = moved up the chart. Hidden by default until day-over-day
   *  volatility is measured — see scripts/rank_delta_report.py. */
  rank_delta_7d: number | null;
  /** Only ever `confirmed` (a developer disclosed it) or `unknown`. */
  wishlist: Provenanced;
  revenue: Provenanced;
  estimated_sales: number | null;
  /** Cached community-video clip count (0 = none fetched/found). */
  video_count: number;
}

export interface FollowerPoint {
  captured_at: string;
  followers: number;
  source_name: string | null;
  source_url: string | null;
}

export interface RankPoint {
  swept_at: string;
  rank: number;
  total_ranked: number | null;
  cc: string;
}

export interface StatsPoint {
  captured_at: string;
  positive_reviews: number | null;
  negative_reviews: number | null;
  total_reviews: number | null;
  positive_pct: number | null;
  review_score: number | null;
  review_score_desc: string | null;
  peak_ccu: number | null;
  avg_ccu: number | null;
  followers: number | null;
  source_name: string | null;
}

export interface CompanyOut {
  id: number;
  name: string;
  country: string | null;
  country_status: DataStatus;
  website: string | null;
}

export interface MediaOut {
  media_type: "header" | "capsule" | "screenshot" | "movie";
  url: string;
  thumbnail_url: string | null;
  position: number | null;
}

export interface FestivalOut {
  name: string;
  is_next_fest: boolean;
  start_date: string | null;
  end_date: string | null;
  source_url: string | null;
  notes: string | null;
}

export interface WishlistRecordOut {
  status: DataStatus;
  wishlist_count: number | null;
  /** ">=" when the developer stated a lower bound ("over 100,000"). */
  comparator: string;
  /** The announcement's date; recorded_at is only when we ingested it. */
  disclosed_on: string | null;
  source_name: string | null;
  source_url: string | null;
  recorded_at: string;
  notes: string | null;
}

export interface RevenueRecordOut {
  status: DataStatus;
  gross_revenue_usd: number | null;
  net_revenue_usd: number | null;
  estimated_sales: number | null;
  estimated_owners_min: number | null;
  estimated_owners_max: number | null;
  estimate_spread: number | null;
  source_name: string | null;
  source_url: string | null;
  recorded_at: string;
  notes: string | null;
}

export interface MarketingOut {
  budget: Provenanced;
  marketing_notes: string | null;
  developer_interview_url: string | null;
  publisher_interview_url: string | null;
  kickstarter_url: string | null;
}

export interface GameDetail extends GameListItem {
  short_description: string | null;
  website: string | null;
  /** How the game entered the catalog — indie_tag, or a tag-less signal. */
  discovery_method: "indie_tag" | "self_published_no_tag" | "boutique_label_no_tag";
  /** Where the 2D/3D value came from. */
  dimension_source:
    | "tag"
    | "rule_based"
    | "similarity" // offline TF-IDF neighbours (free)
    | "vision_ai"
    | "similarity_ai" // paid LLM estimate
    | "unknown";
  supported_languages: string[];
  controller_support: string;
  steam_deck_support: string;
  launch_price_cents: number | null;
  launch_discount_pct: number | null;
  page_creation_date: string | null;
  page_creation_source: string | null;
  demo_appid: number | null;
  last_synced_at: string | null;
  developers_full: CompanyOut[];
  publishers_full: CompanyOut[];
  tags_full: { name: string; rank: number | null; votes: number | null }[];
  media: MediaOut[];
  festivals: FestivalOut[];
  latest_stats: StatsPoint | null;
  wishlist_history: WishlistRecordOut[];
  revenue_history: RevenueRecordOut[];
  revenue_estimates: RevenueEstimateOut[];
  budget_estimates: BudgetEstimateOut[];
  marketing: MarketingOut | null;
}

export interface BudgetEstimateOut {
  method: "team_cost" | "revenue_ratio";
  budget_min_usd: number | null;
  budget_max_usd: number | null;
  formula: string;
  inputs: Record<string, string | number>;
  source_name: string | null;
  source_url: string | null;
  computed_at: string;
}

export interface GameClip {
  platform: string;
  title: string;
  url: string;
  thumbnail: string | null;
  published_at: string | null;
  views: number | null;
  source: "api" | "manual";
}

export interface GameVideosPayload {
  /** stale = expired cache served because the API quota/fetch was blocked. */
  status: "ok" | "stale" | "no_channels" | "quota_exhausted";
  clips: GameClip[];
  unavailable: { platform: string; reason?: string; error?: string }[];
  fetched_at: string | null;
  channels: {
    youtube_url: string | null;
    twitch_login: string | null;
    manual_links: { platform: string; url: string }[];
  } | null;
}

export interface ChannelSubmissionBody {
  youtube_url: string;
  twitch_login: string;
  links: string[];
  /** Honeypot — must stay empty; the field is visually hidden. */
  nickname: string;
}

export interface ChannelSubmissionOut {
  id: number;
  appid: number;
  game_name: string | null;
  youtube_url: string | null;
  twitch_login: string | null;
  other_links: { platform: string; url: string }[];
  source: "developer_submitted" | "auto_detected";
  /** Auto-detected only: the official website the links were found on. */
  found_on: string | null;
  status: "pending" | "approved" | "rejected";
  created_at: string;
  reviewed_at: string | null;
  review_note: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface AverageStat {
  value: number | null;
  sample_size: number;
}

export interface DashboardSummary {
  total_games: number;
  released_games: number;
  coming_soon_games: number;
  two_d_games: number;
  three_d_games: number;
  games_with_demo: number;
  next_fest_games: number;
  avg_reviews: AverageStat;
  // Coverage counters, not averages — there is no meaningful average of a
  // handful of developer-disclosed lower bounds.
  games_with_followers: number;
  ranked_games: number;
  confirmed_wishlist_games: number;
}

export interface FilterOptions {
  genres: string[];
  tags: string[];
  engines: string[];
  dimensions: string[];
  cameras: string[];
  graphics_styles: string[];
  data_statuses: string[];
  release_months: number[];
}

/** An admin-triggered collector run. */
export type SweepKind = "disclosures" | "followers" | "rank";

export interface SweepOut {
  id: number;
  kinds: SweepKind[];
  /** Release-date window limiting WHICH GAMES are scanned. The rank sweep
   *  ignores it — that chart is a single global list Valve orders itself. */
  release_from: string | null;
  release_to: string | null;
  limit_per_kind: number | null;
  status: "queued" | "running" | "done" | "failed" | "cancelled" | "interrupted";
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Per-kind counters, shape depends on the collector. */
  progress: Record<string, Record<string, number | string | boolean>>;
  error: string | null;
}

export interface SweepRequestBody {
  kinds: SweepKind[];
  release_from?: string | null;
  release_to?: string | null;
  limit_per_kind?: number | null;
}
