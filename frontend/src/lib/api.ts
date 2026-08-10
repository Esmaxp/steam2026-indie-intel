import type {
  DashboardSummary,
  FilterOptions,
  GameDetail,
  GameListItem,
  Page,
  StatsPoint,
} from "@/lib/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function getJson<T>(path: string, params?: URLSearchParams): Promise<T> {
  const qs = params && params.size > 0 ? `?${params.toString()}` : "";
  const res = await fetch(`${API_BASE}${path}${qs}`);
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${path}`);
  }
  return res.json() as Promise<T>;
}

export function fetchGames(params: URLSearchParams) {
  return getJson<Page<GameListItem>>("/api/v1/games", params);
}

export function fetchGame(appid: number) {
  return getJson<GameDetail>(`/api/v1/games/${appid}`);
}

export function fetchGameSearch(q: string, limit = 8) {
  const params = new URLSearchParams({ q, limit: String(limit) });
  return getJson<{ appid: number; name: string }[]>("/api/v1/games/search", params);
}

export function fetchSimilarGames(appid: number, limit = 10) {
  const params = new URLSearchParams({ limit: String(limit) });
  return getJson<GameListItem[]>(`/api/v1/games/${appid}/similar`, params);
}

export function fetchGameStats(appid: number) {
  return getJson<StatsPoint[]>(`/api/v1/games/${appid}/stats`);
}

export function fetchSummary() {
  return getJson<DashboardSummary>("/api/v1/dashboard/summary");
}

export function fetchFilterOptions() {
  return getJson<FilterOptions>("/api/v1/filters/options");
}
