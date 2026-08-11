import { NextResponse } from "next/server";
import manualData from "@/data/videos.json";

/** Server-side aggregation of social clips.
 *
 * - YouTube / Twitch: real API integrations (keys live ONLY in server env,
 *   never shipped to the browser). Missing keys → platform skipped and
 *   reported in `unavailable` so the UI can render a fallback link.
 * - TikTok / Instagram / X: no usable public listing APIs (restricted or
 *   paid), so entries come from the hand-maintained src/data/videos.json.
 * - Results cached in-process for 1 hour — no API hit per page load.
 */

export const dynamic = "force-dynamic";

interface Clip {
  platform: string;
  title: string;
  url: string;
  thumbnail: string | null;
  published_at: string | null;
  source: "api" | "manual";
}

interface ClipsPayload {
  clips: Clip[];
  unavailable: { platform: string; reason: string }[];
  fetched_at: string;
}

const CACHE_TTL_MS = 60 * 60 * 1000; // 1 hour
let cache: { payload: ClipsPayload; at: number } | null = null;
let twitchToken: { token: string; expiresAt: number } | null = null;

async function fetchYouTube(): Promise<Clip[] | { error: string }> {
  const key = process.env.YOUTUBE_API_KEY;
  const channelId = process.env.YOUTUBE_CHANNEL_ID;
  if (!key || !channelId) return { error: "not configured" };
  try {
    const channelRes = await fetch(
      `https://www.googleapis.com/youtube/v3/channels?part=contentDetails&id=${channelId}&key=${key}`,
    );
    if (!channelRes.ok) return { error: `channels.list HTTP ${channelRes.status}` };
    const channelJson = await channelRes.json();
    const uploads =
      channelJson.items?.[0]?.contentDetails?.relatedPlaylists?.uploads;
    if (!uploads) return { error: "uploads playlist not found" };

    const itemsRes = await fetch(
      `https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&playlistId=${uploads}&maxResults=12&key=${key}`,
    );
    if (!itemsRes.ok) return { error: `playlistItems HTTP ${itemsRes.status}` };
    const itemsJson = await itemsRes.json();
    return (itemsJson.items ?? []).map(
      (item: {
        snippet: {
          title: string;
          publishedAt: string;
          resourceId: { videoId: string };
          thumbnails?: { medium?: { url?: string } };
        };
      }) => ({
        platform: "youtube",
        title: item.snippet.title,
        url: `https://www.youtube.com/watch?v=${item.snippet.resourceId.videoId}`,
        thumbnail: item.snippet.thumbnails?.medium?.url ?? null,
        published_at: item.snippet.publishedAt ?? null,
        source: "api" as const,
      }),
    );
  } catch (error) {
    return { error: String(error) };
  }
}

async function twitchAppToken(): Promise<string | null> {
  const clientId = process.env.TWITCH_CLIENT_ID;
  const secret = process.env.TWITCH_CLIENT_SECRET;
  if (!clientId || !secret) return null;
  if (twitchToken && twitchToken.expiresAt > Date.now()) return twitchToken.token;
  const res = await fetch(
    `https://id.twitch.tv/oauth2/token?client_id=${clientId}&client_secret=${secret}&grant_type=client_credentials`,
    { method: "POST" },
  );
  if (!res.ok) return null;
  const json = await res.json();
  twitchToken = {
    token: json.access_token,
    expiresAt: Date.now() + (json.expires_in - 60) * 1000,
  };
  return twitchToken.token;
}

async function fetchTwitch(): Promise<Clip[] | { error: string }> {
  const clientId = process.env.TWITCH_CLIENT_ID;
  const login = process.env.TWITCH_USER_LOGIN;
  if (!clientId || !process.env.TWITCH_CLIENT_SECRET || !login)
    return { error: "not configured" };
  try {
    const token = await twitchAppToken();
    if (!token) return { error: "token request failed" };
    const headers = { "Client-ID": clientId, Authorization: `Bearer ${token}` };

    const userRes = await fetch(
      `https://api.twitch.tv/helix/users?login=${login}`,
      { headers },
    );
    if (!userRes.ok) return { error: `users HTTP ${userRes.status}` };
    const userId = (await userRes.json()).data?.[0]?.id;
    if (!userId) return { error: `user '${login}' not found` };

    const clipsRes = await fetch(
      `https://api.twitch.tv/helix/clips?broadcaster_id=${userId}&first=12`,
      { headers },
    );
    if (!clipsRes.ok) return { error: `clips HTTP ${clipsRes.status}` };
    const clipsJson = await clipsRes.json();
    return (clipsJson.data ?? []).map(
      (clip: {
        title: string;
        url: string;
        thumbnail_url: string;
        created_at: string;
      }) => ({
        platform: "twitch",
        title: clip.title,
        url: clip.url,
        thumbnail: clip.thumbnail_url ?? null,
        published_at: clip.created_at ?? null,
        source: "api" as const,
      }),
    );
  } catch (error) {
    return { error: String(error) };
  }
}

function manualClips(): Clip[] {
  const entries = (manualData as { videos: Partial<Clip>[] }).videos ?? [];
  return entries
    .filter((video) => video.url && video.title && video.platform)
    .map((video) => ({
      platform: video.platform as string,
      title: video.title as string,
      url: video.url as string,
      thumbnail: video.thumbnail ?? null,
      published_at: video.published_at ?? null,
      source: "manual" as const,
    }));
}

export async function GET() {
  if (cache && Date.now() - cache.at < CACHE_TTL_MS) {
    return NextResponse.json(cache.payload);
  }

  const unavailable: ClipsPayload["unavailable"] = [];
  const clips: Clip[] = [...manualClips()];

  const [youtube, twitch] = await Promise.all([fetchYouTube(), fetchTwitch()]);
  if (Array.isArray(youtube)) clips.push(...youtube);
  else if (youtube.error !== "not configured")
    unavailable.push({ platform: "youtube", reason: youtube.error });
  if (Array.isArray(twitch)) clips.push(...twitch);
  else if (twitch.error !== "not configured")
    unavailable.push({ platform: "twitch", reason: twitch.error });

  clips.sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""));

  const payload: ClipsPayload = {
    clips,
    unavailable,
    fetched_at: new Date().toISOString(),
  };
  cache = { payload, at: Date.now() };
  return NextResponse.json(payload);
}
