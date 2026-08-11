"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PlayCircle, Plus, X } from "lucide-react";
import { useState } from "react";
import { fetchGameVideos, submitGameChannels } from "@/lib/api";
import { DASH, fmtCompact, fmtDate } from "@/lib/format";
import type { GameClip } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const MAX_SHOWN = 8;

function ClipGrid({ clips }: { clips: GameClip[] }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {clips.slice(0, MAX_SHOWN).map((clip) => (
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
                {clip.views != null ? (
                  <span className="tabular-nums">· {fmtCompact(clip.views)} views</span>
                ) : null}
              </div>
            </div>
          </Card>
        </a>
      ))}
    </div>
  );
}

function AddChannelForm({ appid, onClose }: { appid: number; onClose: () => void }) {
  const [youtube, setYoutube] = useState("");
  const [twitch, setTwitch] = useState("");
  const [links, setLinks] = useState("");
  const [honeypot, setHoneypot] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      submitGameChannels(appid, {
        youtube_url: youtube,
        twitch_login: twitch,
        links: links
          .split("\n")
          .map((l) => l.trim())
          .filter(Boolean)
          .slice(0, 5),
        nickname: honeypot,
      }),
  });

  if (mutation.isSuccess) {
    return (
      <div className="flex flex-col gap-2 text-sm">
        <p className="font-medium text-ink">Thanks — submission received.</p>
        <p className="text-muted">
          Channels go live after a manual review; videos appear here once approved.
        </p>
        <Button onClick={onClose} className="w-fit">Close</Button>
      </div>
    );
  }

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
    >
      <label className="flex flex-col gap-1 text-xs text-muted">
        YouTube channel URL or @handle
        <Input
          value={youtube}
          onChange={(e) => setYoutube(e.target.value)}
          placeholder="https://www.youtube.com/@yourstudio"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        Twitch username or channel URL
        <Input
          value={twitch}
          onChange={(e) => setTwitch(e.target.value)}
          placeholder="yourstudio"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-muted">
        TikTok / Instagram / X profile URLs (one per line, max 5)
        <textarea
          value={links}
          onChange={(e) => setLinks(e.target.value)}
          rows={3}
          placeholder={"https://www.tiktok.com/@yourstudio\nhttps://x.com/yourstudio"}
          className="rounded-md border border-hairline bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-accent/40"
        />
      </label>
      {/* Honeypot: invisible to humans, bots fill it and get silently dropped. */}
      <input
        type="text"
        name="nickname"
        value={honeypot}
        onChange={(e) => setHoneypot(e.target.value)}
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        className="absolute -left-[9999px] h-0 w-0 opacity-0"
      />
      {mutation.isError ? (
        <p className="text-xs text-red-500">{(mutation.error as Error).message}</p>
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" disabled={mutation.isPending} className="bg-accent/10 text-accent">
          {mutation.isPending ? "Submitting…" : "Submit for review"}
        </Button>
        <Button type="button" onClick={onClose}>Cancel</Button>
      </div>
      <p className="text-xs text-muted">
        Submissions are reviewed by hand before going live.
      </p>
    </form>
  );
}

export function GameVideos({ appid }: { appid: number }) {
  const [formOpen, setFormOpen] = useState(false);
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["game-videos", appid],
    queryFn: () => fetchGameVideos(appid),
    staleTime: 5 * 60 * 1000,
  });

  const closeForm = () => {
    setFormOpen(false);
    queryClient.invalidateQueries({ queryKey: ["game-videos", appid] });
  };

  return (
    <Card className="p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-muted">Community videos</h2>
        {!formOpen ? (
          <button
            onClick={() => setFormOpen(true)}
            className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
          >
            <Plus size={12} aria-hidden /> Is this your game? Add your channel(s)
          </button>
        ) : (
          <button
            onClick={() => setFormOpen(false)}
            className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink"
            aria-label="Close form"
          >
            <X size={14} aria-hidden />
          </button>
        )}
      </div>

      {formOpen ? (
        <div className="mb-4 rounded-md border border-hairline p-4">
          <AddChannelForm appid={appid} onClose={closeForm} />
        </div>
      ) : null}

      {isLoading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i} className="h-36 animate-pulse" />
          ))}
        </div>
      ) : isError ? (
        <p className="text-sm text-muted">Videos couldn&apos;t load right now.</p>
      ) : !data || data.status === "no_channels" ? (
        <p className="text-sm text-muted">
          No videos yet — this game has no channel info.{" "}
          <button onClick={() => setFormOpen(true)} className="text-accent hover:underline">
            Add your channel
          </button>{" "}
          to show your YouTube/Twitch content here.
        </p>
      ) : data.status === "quota_exhausted" ? (
        <p className="text-sm text-muted">
          Videos are temporarily unavailable (daily API budget spent) — check back later.
        </p>
      ) : data.clips.length === 0 ? (
        <p className="text-sm text-muted">
          Channels are linked, but no videos were found yet.
        </p>
      ) : (
        <>
          {data.status === "stale" ? (
            <p className="mb-2 text-xs text-muted">
              Showing cached videos{data.fetched_at ? ` from ${fmtDate(data.fetched_at.slice(0, 10))}` : ""}.
            </p>
          ) : null}
          <ClipGrid clips={data.clips} />
        </>
      )}
    </Card>
  );
}
