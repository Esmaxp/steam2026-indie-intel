import type {
  ChannelSubmissionBody,
  ChannelSubmissionOut,
  DashboardSummary,
  FilterOptions,
  FollowerPoint,
  GameDetail,
  GameListItem,
  GameVideosPayload,
  Page,
  RankPoint,
  StatsPoint,
  SweepOut,
  SweepRequestBody,
} from "@/lib/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:9100";

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

export function fetchGameFollowers(appid: number) {
  return getJson<FollowerPoint[]>(`/api/v1/games/${appid}/followers`);
}

export function fetchGameRankHistory(appid: number) {
  return getJson<RankPoint[]>(`/api/v1/games/${appid}/rank-history`);
}

export function fetchSummary() {
  return getJson<DashboardSummary>("/api/v1/dashboard/summary");
}

export function fetchFilterOptions() {
  return getJson<FilterOptions>("/api/v1/filters/options");
}

export function fetchGameVideos(appid: number) {
  return getJson<GameVideosPayload>(`/api/v1/games/${appid}/videos`);
}

async function postJson<T>(path: string, body: unknown, headers?: Record<string, string>): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `API ${res.status}`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export function submitGameChannels(appid: number, body: ChannelSubmissionBody) {
  return postJson<{ status: string }>(`/api/v1/games/${appid}/channel-submissions`, body);
}

export function fetchSubmissions(token: string, status = "pending") {
  return fetch(`${API_BASE}/api/v1/admin/channel-submissions?status=${status}`, {
    headers: { "X-Admin-Token": token },
  }).then(async (res) => {
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `API ${res.status}`);
    return res.json() as Promise<ChannelSubmissionOut[]>;
  });
}

export function reviewSubmission(token: string, id: number, action: "approve" | "reject", note = "") {
  return postJson<ChannelSubmissionOut>(
    `/api/v1/admin/channel-submissions/${id}/${action}`,
    { note },
    { "X-Admin-Token": token },
  );
}

export function bulkReviewSubmissions(
  token: string,
  ids: number[],
  action: "approve" | "reject",
  note = "",
) {
  return postJson<{ processed: number[]; skipped: number[] }>(
    "/api/v1/admin/channel-submissions/bulk-review",
    { ids, action, note },
    { "X-Admin-Token": token },
  );
}

export function fetchSweeps(token: string) {
  return fetch(`${API_BASE}/api/v1/admin/sweeps`, {
    headers: { "X-Admin-Token": token },
  }).then(async (res) => {
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `API ${res.status}`);
    return res.json() as Promise<SweepOut[]>;
  });
}

export function startSweep(token: string, body: SweepRequestBody) {
  return postJson<SweepOut>("/api/v1/admin/sweeps", body, { "X-Admin-Token": token });
}

export function cancelSweep(token: string, id: number) {
  return postJson<SweepOut>(`/api/v1/admin/sweeps/${id}/cancel`, {}, { "X-Admin-Token": token });
}
