/** Mirrors the FastAPI response schemas (backend/app/schemas). */

export type DataStatus = "confirmed" | "estimated" | "unknown";

export interface Provenanced {
  value: number | null;
  status: DataStatus;
  source_name: string | null;
  source_url: string | null;
  recorded_at: string | null;
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
  is_free: boolean;
  currency: string | null;
  current_price_cents: number | null;
  total_reviews: number | null;
  positive_pct: number | null;
  review_score_desc: string | null;
  peak_ccu: number | null;
  avg_ccu: number | null;
  wishlist: Provenanced;
  revenue: Provenanced;
  estimated_sales: number | null;
  budget: Provenanced;
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
  marketing: MarketingOut | null;
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
  avg_wishlist: AverageStat;
  avg_revenue: AverageStat;
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
