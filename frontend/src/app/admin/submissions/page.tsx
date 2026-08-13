"use client";

/** Minimal review queue for "add your channel" submissions.
 *  Auth: none yet — the backend's require_admin() is a no-op pending real
 *  admin authentication, so this page is open to anyone who can reach it. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ExternalLink, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { bulkReviewSubmissions, fetchSubmissions, reviewSubmission } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export default function SubmissionsAdminPage() {
  const [status, setStatus] = useState<"pending" | "approved" | "rejected">("pending");
  const [sourceFilter, setSourceFilter] = useState<
    "all" | "auto_detected" | "developer_submitted"
  >("all");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const queryClient = useQueryClient();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["admin-submissions", status],
    queryFn: () => fetchSubmissions(status),
    retry: false,
  });

  const review = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "approve" | "reject" }) =>
      reviewSubmission(id, action),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin-submissions"] }),
  });

  const bulkReview = useMutation({
    mutationFn: ({ ids, action }: { ids: number[]; action: "approve" | "reject" }) =>
      bulkReviewSubmissions(ids, action),
    onSuccess: () => {
      setSelected(new Set());
      queryClient.invalidateQueries({ queryKey: ["admin-submissions"] });
    },
  });

  const visible = (data ?? []).filter(
    (sub) => sourceFilter === "all" || sub.source === sourceFilter,
  );
  const visibleIds = visible.filter((s) => s.status === "pending").map((s) => s.id);
  const allSelected = visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));

  const toggleOne = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold">Channel submissions</h1>
          <Link href="/admin/sweeps" className="text-sm text-accent hover:underline">
            Data sweeps →
          </Link>
        </div>
        <div className="flex items-center gap-2">
          {(["pending", "approved", "rejected"] as const).map((s) => (
            <button
              key={s}
              onClick={() => {
                setStatus(s);
                setSelected(new Set());
              }}
              aria-pressed={status === s}
              className={`h-8 rounded-md border border-hairline px-3 text-sm capitalize ${
                status === s ? "bg-accent/10 font-medium text-accent" : "text-ink2 hover:bg-grid/40"
              }`}
            >
              {s}
            </button>
          ))}
          <select
            value={sourceFilter}
            onChange={(e) => {
              setSourceFilter(e.target.value as typeof sourceFilter);
              setSelected(new Set());
            }}
            className="h-8 rounded-md border border-hairline bg-surface px-2 text-sm text-ink2"
            aria-label="Filter by source"
          >
            <option value="all">All sources</option>
            <option value="auto_detected">Auto-detected</option>
            <option value="developer_submitted">Developer</option>
          </select>
        </div>
      </div>

      {status === "pending" && visibleIds.length > 0 ? (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-hairline bg-surface px-3 py-2">
          <label className="flex items-center gap-2 text-sm text-ink2">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={() =>
                setSelected(allSelected ? new Set() : new Set(visibleIds))
              }
            />
            Select all ({visibleIds.length})
          </label>
          {selected.size > 0 ? (
            <>
              <Button
                disabled={bulkReview.isPending}
                onClick={() =>
                  bulkReview.mutate({ ids: [...selected], action: "approve" })
                }
                className="h-8 text-green-600"
              >
                <Check size={14} aria-hidden /> Approve selected ({selected.size})
              </Button>
              <Button
                disabled={bulkReview.isPending}
                onClick={() =>
                  bulkReview.mutate({ ids: [...selected], action: "reject" })
                }
                className="h-8 text-red-500"
              >
                <X size={14} aria-hidden /> Reject selected ({selected.size})
              </Button>
            </>
          ) : null}
          {bulkReview.isError ? (
            <span className="text-xs text-red-500">
              {(bulkReview.error as Error).message}
            </span>
          ) : null}
        </div>
      ) : null}

      {isLoading ? (
        <Card className="h-40 animate-pulse" />
      ) : isError ? (
        <Card className="p-6 text-sm text-red-500">{(error as Error).message}</Card>
      ) : visible.length === 0 ? (
        <Card className="p-8 text-center text-sm text-muted">No {status} submissions.</Card>
      ) : (
        <div className="flex flex-col gap-3">
          {visible.map((sub) => (
            <Card key={sub.id} className="flex flex-col gap-2 p-4">
              <div className="flex flex-wrap items-center gap-2">
                {sub.status === "pending" ? (
                  <input
                    type="checkbox"
                    checked={selected.has(sub.id)}
                    onChange={() => toggleOne(sub.id)}
                    aria-label={`Select submission ${sub.id}`}
                  />
                ) : null}
                <Link
                  href={`/games/${sub.appid}`}
                  className="font-medium text-accent hover:underline"
                >
                  {sub.game_name ?? `app ${sub.appid}`}
                </Link>
                <Badge className="capitalize">{sub.status}</Badge>
                <Badge
                  className={
                    sub.source === "auto_detected"
                      ? "border-amber-500/40 text-amber-600"
                      : "border-accent/40 text-accent"
                  }
                >
                  {sub.source === "auto_detected" ? "auto-detected" : "developer"}
                </Badge>
                <span className="text-xs text-muted tabular-nums">
                  {fmtDate(sub.created_at.slice(0, 10))}
                </span>
              </div>
              {sub.found_on ? (
                <p className="text-xs text-muted">
                  Found on{" "}
                  <a
                    href={sub.found_on}
                    target="_blank"
                    rel="noreferrer"
                    className="text-accent hover:underline"
                  >
                    {sub.found_on} <ExternalLink size={11} className="inline" aria-hidden />
                  </a>
                </p>
              ) : null}
              <ul className="flex flex-col gap-1 text-sm">
                {sub.youtube_url ? (
                  <li>
                    YouTube:{" "}
                    <a href={sub.youtube_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                      {sub.youtube_url} <ExternalLink size={11} className="inline" aria-hidden />
                    </a>
                  </li>
                ) : null}
                {sub.twitch_login ? (
                  <li>
                    Twitch:{" "}
                    <a
                      href={`https://www.twitch.tv/${sub.twitch_login}`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent hover:underline"
                    >
                      {sub.twitch_login} <ExternalLink size={11} className="inline" aria-hidden />
                    </a>
                  </li>
                ) : null}
                {sub.other_links.map((link) => (
                  <li key={link.url} className="capitalize">
                    {link.platform}:{" "}
                    <a href={link.url} target="_blank" rel="noreferrer" className="text-accent hover:underline normal-case">
                      {link.url} <ExternalLink size={11} className="inline" aria-hidden />
                    </a>
                  </li>
                ))}
              </ul>
              {sub.status === "pending" ? (
                <div className="flex gap-2">
                  <Button
                    disabled={review.isPending}
                    onClick={() => review.mutate({ id: sub.id, action: "approve" })}
                    className="text-green-600"
                  >
                    <Check size={14} aria-hidden /> Approve
                  </Button>
                  <Button
                    disabled={review.isPending}
                    onClick={() => review.mutate({ id: sub.id, action: "reject" })}
                    className="text-red-500"
                  >
                    <X size={14} aria-hidden /> Reject
                  </Button>
                </div>
              ) : sub.review_note ? (
                <p className="text-xs text-muted">Note: {sub.review_note}</p>
              ) : null}
              {review.isError ? (
                <p className="text-xs text-red-500">{(review.error as Error).message}</p>
              ) : null}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
