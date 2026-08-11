"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, PlayCircle } from "lucide-react";
import { useState } from "react";
import { configuredAccounts } from "@/config/social";
import { DASH, fmtDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

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

const TABS = [
  { key: "all", label: "All" },
  { key: "youtube", label: "YouTube" },
  { key: "twitch", label: "Twitch" },
  { key: "tiktok", label: "TikTok" },
  { key: "instagram", label: "Instagram" },
  { key: "x", label: "X" },
] as const;

const MAX_SHOWN = 12;

async function fetchClips(): Promise<ClipsPayload> {
  // Same-origin Next.js route — API keys stay on the server.
  const res = await fetch("/api/clips");
  if (!res.ok) throw new Error(`clips HTTP ${res.status}`);
  return res.json();
}

function platformUrl(platform: string): string | null {
  return configuredAccounts().find((a) => a.platform === platform)?.url ?? null;
}

export function CommunityClips() {
  const [tab, setTab] = useState<(typeof TABS)[number]["key"]>("all");
  const { data, isLoading, isError } = useQuery({
    queryKey: ["clips"],
    queryFn: fetchClips,
    staleTime: 5 * 60 * 1000,
  });

  const clips =
    data?.clips.filter((clip) => tab === "all" || clip.platform === tab) ?? [];
  const shown = clips.slice(0, MAX_SHOWN);
  const seeMoreUrl = tab !== "all" ? platformUrl(tab) : null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1.5">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            aria-pressed={tab === t.key}
            className={`h-8 rounded-md border border-hairline px-3 text-sm transition-colors ${
              tab === t.key
                ? "bg-accent/10 font-medium text-accent"
                : "bg-surface text-ink2 hover:bg-grid/40"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {data && data.unavailable.length > 0 ? (
        <p className="text-xs text-muted">
          {data.unavailable.map((u) => {
            const url = platformUrl(u.platform);
            return (
              <span key={u.platform} className="mr-3">
                {u.platform} videos couldn&apos;t load
                {url ? (
                  <>
                    {" — "}
                    <a href={url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                      visit the channel
                    </a>
                  </>
                ) : null}
              </span>
            );
          })}
        </p>
      ) : null}

      {isLoading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Card key={i} className="h-40 animate-pulse" />
          ))}
        </div>
      ) : isError || shown.length === 0 ? (
        <Card className="p-8 text-center text-sm text-muted">
          No videos here yet. API-driven platforms need keys in .env
          (YOUTUBE_API_KEY…, TWITCH_…); TikTok/Instagram/X entries are added by
          hand in <code>src/data/videos.json</code> — see frontend/README.md.
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {shown.map((clip) => (
            <a
              key={clip.url}
              href={clip.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group"
            >
              <Card className="overflow-hidden transition-colors group-hover:border-accent/50">
                {clip.thumbnail ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={clip.thumbnail}
                    alt=""
                    loading="lazy"
                    className="aspect-video w-full object-cover"
                  />
                ) : (
                  <div className="flex aspect-video w-full items-center justify-center bg-grid/30">
                    <PlayCircle size={28} className="text-muted" aria-hidden />
                  </div>
                )}
                <div className="p-2.5">
                  <div className="line-clamp-2 text-sm font-medium">{clip.title}</div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-muted">
                    <Badge className="px-1.5 py-0 capitalize">{clip.platform}</Badge>
                    <span className="tabular-nums">
                      {clip.published_at ? fmtDate(clip.published_at.slice(0, 10)) : DASH}
                    </span>
                  </div>
                </div>
              </Card>
            </a>
          ))}
        </div>
      )}

      {seeMoreUrl ? (
        <a
          href={seeMoreUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex w-fit items-center gap-1 text-sm text-accent hover:underline"
        >
          See more on {TABS.find((t) => t.key === tab)?.label}
          <ExternalLink size={12} aria-hidden />
        </a>
      ) : null}
    </div>
  );
}
