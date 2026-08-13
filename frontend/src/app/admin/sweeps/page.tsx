"use client";

/** Run the data collectors on demand.
 *  Auth: none yet — the backend's require_admin() is a no-op pending real
 *  admin authentication, so this page is open to anyone who can reach it. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pause, Play, RotateCw, Square } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import {
  cancelSweep,
  fetchSweeps,
  pauseSweep,
  rerunSweep,
  resumeSweep,
  startSweep,
} from "@/lib/api";
import { fmtDateTime, fmtDuration, fmtInt } from "@/lib/format";
import type { SweepKind, SweepOut } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const ACTIVE = new Set(["queued", "running", "paused"]);
/** Finished one way or another. Every collector is resumable, so all four are
 *  worth continuing — a completed sweep re-run picks up whatever has gone
 *  stale since. */
const TERMINAL = new Set(["done", "failed", "cancelled", "interrupted"]);

/** How long without a heartbeat before a job is treated as dead. A CLI sweep
 *  checks in once per batch, and the follower batch is the slowest at ~400
 *  games x 4s, so the threshold has to clear that with room to spare. */
const STALE_AFTER_MS = 45 * 60 * 1000;

function isStale(job: SweepOut): boolean {
  if (!ACTIVE.has(job.status)) return false;
  const last = job.heartbeat_at ?? job.started_at;
  if (!last) return false;
  return Date.now() - new Date(last).getTime() > STALE_AFTER_MS;
}

const SWEEPERS: {
  kind: SweepKind;
  label: string;
  detail: string;
  respectsDates: boolean;
}[] = [
  {
    kind: "rank",
    label: "Wishlist rank",
    detail:
      "Valve's Top-Wishlists chart, ~53 requests / ~3 min. Ignores the date range — it is one global list Valve orders itself.",
    respectsDates: false,
  },
  {
    kind: "followers",
    label: "Followers",
    detail:
      "Community-hub member counts. ~4s per game, so the whole catalogue is ~6h. Resumable: it skips anything checked in the last 20h.",
    respectsDates: true,
  },
  {
    kind: "disclosures",
    label: "Wishlist disclosures",
    detail:
      "Scans Steam news for developer-announced wishlist counts. ~1.5s per game. Only ~5% of games ever announce one, so most stay Unknown.",
    respectsDates: true,
  },
];

function statusTone(status: SweepOut["status"]): string {
  if (status === "done") return "border-good-text/40 text-good-text";
  if (status === "running" || status === "queued") return "border-accent/40 text-accent";
  if (status === "paused") return "border-status-warn/40 text-status-warn";
  if (status === "failed") return "border-status-critical/40 text-status-critical";
  return "border-hairline text-muted";
}

/** When it started, how long it has been going, and how much longer.
 *  Elapsed is measured from `started_at` and keeps ticking while paused —
 *  wall-clock is what the operator is actually waiting on. */
function Timing({ job }: { job: SweepOut }) {
  const started = job.started_at ? new Date(job.started_at).getTime() : null;
  const ended = job.finished_at ? new Date(job.finished_at).getTime() : Date.now();
  const elapsed = started !== null ? (ended - started) / 1000 : null;
  const live = ACTIVE.has(job.status);

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      <span>
        {job.started_at ? "Started " : "Queued "}
        <span className="text-ink">
          {fmtDateTime(job.started_at ?? job.created_at)}
        </span>
      </span>
      {elapsed !== null ? (
        <span>
          {live ? "Running for" : "Took"}{" "}
          <span className="tabular-nums text-ink">{fmtDuration(elapsed)}</span>
        </span>
      ) : null}
      {live && job.eta_seconds !== null ? (
        <span>
          {job.status === "paused" ? "Remaining work" : "ETA"}{" "}
          <span className="tabular-nums text-ink">{fmtDuration(job.eta_seconds)}</span>
          {job.remaining !== null ? ` (${fmtInt(job.remaining)} games)` : ""}
          {/* Say where the number came from: a measured rate is worth
              trusting, a nominal one is arithmetic on the request interval. */}
          {job.eta_basis === "estimated" ? " · assumed rate" : ""}
          {job.eta_basis === "measured" ? " · measured rate" : ""}
        </span>
      ) : null}
      {live && job.active_kind ? <span>Now: {job.active_kind}</span> : null}
      {isStale(job) ? (
        <span className="text-status-critical">
          No heartbeat since {fmtDateTime(job.heartbeat_at ?? job.started_at)} — the
          worker is probably gone. Stop it and run again.
        </span>
      ) : null}
    </div>
  );
}

/** Collector summaries differ in shape, so render whatever counters came back
 *  rather than assuming a fixed set.
 *
 *  `batch` matters: a CLI sweep runs as a series of 400-game containers, so
 *  its counters describe the batch in flight, not the job. Rendering that as
 *  a bare "50%" would claim the sweep is half done when it has hours to go. */
function ProgressLine({
  kind,
  data,
  batch,
}: {
  kind: string;
  data: Record<string, unknown>;
  batch: boolean;
}) {
  const entries = Object.entries(data).filter(
    ([key, value]) =>
      key !== "done" && key !== "notes" && (typeof value === "number" || typeof value === "string"),
  );
  const total = Number(data.total ?? 0);
  const processed = Number(data.processed ?? 0);
  const pct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : null;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2 text-xs">
        <span className="font-medium">{kind}</span>
        {pct !== null ? (
          <span className="tabular-nums text-muted">
            {batch ? "current batch " : ""}
            {fmtInt(processed)} / {fmtInt(total)} ({pct}%)
          </span>
        ) : null}
        {data.done ? <Badge className="border-good-text/40 text-good-text">done</Badge> : null}
      </div>
      {pct !== null ? (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-grid">
          <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
        </div>
      ) : null}
      <div className="flex flex-wrap gap-x-3 text-[11px] text-muted">
        {entries
          .filter(
            ([key]) =>
              key !== "total" && key !== "processed" && key !== "include_released",
          )
          .map(([key, value]) => (
            <span key={key} className="tabular-nums">
              {key}: {String(value)}
            </span>
          ))}
      </div>
    </div>
  );
}

export default function SweepsAdminPage() {
  const [kinds, setKinds] = useState<Set<SweepKind>>(new Set(["rank"]));
  const [releaseFrom, setReleaseFrom] = useState("");
  const [releaseTo, setReleaseTo] = useState("");
  const [limit, setLimit] = useState("");
  const queryClient = useQueryClient();

  const { data, isError, error } = useQuery({
    queryKey: ["admin-sweeps"],
    queryFn: fetchSweeps,
    retry: false,
    // A sweep runs for minutes to hours; poll while one is active so the
    // page reflects it without a manual refresh.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((job) => ACTIVE.has(job.status)) ? 5000 : false,
  });

  const start = useMutation({
    mutationFn: () =>
      startSweep({
        kinds: [...kinds],
        release_from: releaseFrom || null,
        release_to: releaseTo || null,
        limit_per_kind: limit ? Number(limit) : null,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-sweeps"] }),
  });

  const stop = useMutation({
    mutationFn: (id: number) => cancelSweep(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-sweeps"] }),
  });

  const hold = useMutation({
    mutationFn: ({ id, paused }: { id: number; paused: boolean }) =>
      paused ? resumeSweep(id) : pauseSweep(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-sweeps"] }),
  });

  const rerun = useMutation({
    mutationFn: (id: number) => rerunSweep(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-sweeps"] }),
  });

  const running = (data ?? []).find((job) => ACTIVE.has(job.status));
  const datesApply = [...kinds].some(
    (k) => SWEEPERS.find((s) => s.kind === k)?.respectsDates,
  );

  const toggle = (kind: SweepKind) =>
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">Data sweeps</h1>
        <Link href="/admin/submissions" className="text-sm text-accent hover:underline">
          Channel submissions →
        </Link>
      </div>

      <Card className="flex flex-col gap-4 p-5">
        <div>
          <h2 className="mb-2 text-sm font-medium text-muted">Sweepers to run</h2>
          <div className="flex flex-col gap-2">
            {SWEEPERS.map((sweeper) => (
              <label
                key={sweeper.kind}
                className="flex cursor-pointer items-start gap-2.5 rounded-md border border-hairline p-3 transition-colors hover:bg-grid/30"
              >
                <input
                  type="checkbox"
                  checked={kinds.has(sweeper.kind)}
                  onChange={() => toggle(sweeper.kind)}
                  className="mt-0.5 h-4 w-4 accent-[color:var(--accent)]"
                />
                <span>
                  <span className="text-sm font-medium">{sweeper.label}</span>
                  {!sweeper.respectsDates ? (
                    <Badge className="ml-2 border-hairline text-muted">ignores dates</Badge>
                  ) : null}
                  <span className="block text-xs text-muted">{sweeper.detail}</span>
                </span>
              </label>
            ))}
          </div>
        </div>

        <div>
          <h2 className="mb-2 text-sm font-medium text-muted">
            Release-date range{" "}
            <span className="font-normal">
              — which games get scanned. Leave empty for the whole catalogue.
            </span>
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              type="date"
              value={releaseFrom}
              onChange={(e) => setReleaseFrom(e.target.value)}
              className="w-44"
              aria-label="Release date from"
            />
            <span className="text-muted">→</span>
            <Input
              type="date"
              value={releaseTo}
              onChange={(e) => setReleaseTo(e.target.value)}
              className="w-44"
              aria-label="Release date to"
            />
            <Input
              type="number"
              min={0}
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              placeholder="Max games (optional)"
              className="w-48"
              aria-label="Max games per sweeper"
            />
          </div>
          {!datesApply && (releaseFrom || releaseTo) ? (
            <p className="mt-1.5 text-xs text-muted">
              The date range has no effect on the sweepers you selected.
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => start.mutate()}
            disabled={kinds.size === 0 || start.isPending || running !== undefined}
            className="gap-2"
          >
            {start.isPending ? (
              <Loader2 size={14} className="animate-spin" aria-hidden />
            ) : (
              <Play size={14} aria-hidden />
            )}
            Run {kinds.size > 0 ? `${kinds.size} sweeper${kinds.size > 1 ? "s" : ""}` : "…"}
          </Button>
          {running ? (
            <span className="text-xs text-muted">
              A sweep is already running — only one at a time, so concurrent runs
              cannot multiply the request rate against Steam.
            </span>
          ) : null}
          {start.isError ? (
            <span className="text-xs text-status-critical">
              {(start.error as Error).message}
            </span>
          ) : null}
        </div>
      </Card>

      {isError ? (
        <Card className="p-4 text-sm text-status-critical">
          {(error as Error).message}
        </Card>
      ) : null}

      <Card className="flex flex-col gap-3 p-5">
        <h2 className="text-sm font-medium text-muted">Recent runs</h2>
        {(data ?? []).length === 0 ? (
          <p className="text-sm text-muted">No sweeps yet.</p>
        ) : (
          (data ?? []).map((job) => (
            <div key={job.id} className="rounded-md border border-hairline p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={statusTone(job.status)}>{job.status}</Badge>
                <span className="text-sm font-medium">{job.kinds.join(" + ")}</span>
                {job.release_from || job.release_to ? (
                  <span className="text-xs text-muted">
                    {job.release_from ?? "…"} → {job.release_to ?? "…"}
                  </span>
                ) : null}
                {job.limit_per_kind ? (
                  <span className="text-xs text-muted">max {job.limit_per_kind}</span>
                ) : null}
                <span className="ml-auto" />
                {ACTIVE.has(job.status) ? (
                  <>
                    <Button
                      onClick={() => hold.mutate({ id: job.id, paused: job.paused })}
                      disabled={job.cancel_requested || hold.isPending}
                      className="h-7 gap-1.5 px-2 text-xs"
                    >
                      {job.paused ? (
                        <Play size={11} aria-hidden />
                      ) : (
                        <Pause size={11} aria-hidden />
                      )}
                      {/* The flag and the status disagree until the worker
                          notices, so the label reports which of the two it is
                          rather than pretending the click took effect. */}
                      {job.paused
                        ? job.status === "paused"
                          ? "Continue"
                          : "Pausing…"
                        : job.status === "paused"
                          ? "Continuing…"
                          : "Pause"}
                    </Button>
                    <Button
                      onClick={() => stop.mutate(job.id)}
                      disabled={job.cancel_requested || stop.isPending}
                      className="h-7 gap-1.5 px-2 text-xs"
                    >
                      <Square size={11} aria-hidden />
                      {job.cancel_requested ? "Stopping…" : "Stop"}
                    </Button>
                  </>
                ) : TERMINAL.has(job.status) ? (
                  <Button
                    onClick={() => rerun.mutate(job.id)}
                    // Same one-at-a-time rule as the Run button: a second
                    // sweep would double the request rate against Steam.
                    disabled={rerun.isPending || running !== undefined}
                    className="h-7 gap-1.5 px-2 text-xs"
                  >
                    <RotateCw size={11} aria-hidden />
                    {job.status === "done" ? "Run again" : "Continue"}
                  </Button>
                ) : null}
              </div>

              <Timing job={job} />

              {Object.keys(job.progress).length > 0 ? (
                <div className="mt-2 flex flex-col gap-2">
                  {Object.entries(job.progress).map(([kind, payload]) => (
                    <ProgressLine
                      key={kind}
                      kind={kind}
                      data={payload}
                      batch={job.runner === "cli"}
                    />
                  ))}
                </div>
              ) : ACTIVE.has(job.status) ? (
                <p className="mt-2 text-xs text-muted">
                  Starting… counters appear once the first batch completes.
                </p>
              ) : null}

              {job.error ? (
                <p className="mt-2 text-xs text-status-critical">{job.error}</p>
              ) : null}
              {job.status === "paused" ? (
                <p className="mt-2 text-xs text-muted">
                  Holding position between games. Everything collected so far is
                  saved — Continue picks up where it stopped.
                </p>
              ) : null}
              {job.paused && job.status === "running" ? (
                <p className="mt-2 text-xs text-muted">
                  Pause requested — the worker parks after the game it is on.
                </p>
              ) : null}
              {job.status === "interrupted" ? (
                <p className="mt-2 text-xs text-muted">
                  The backend restarted mid-run. Whatever was collected is saved —
                  Continue starts a new run from where this one stopped.
                </p>
              ) : null}
              {job.start_appid ? (
                <p className="mt-2 text-xs text-muted">
                  Continuing an earlier run — skips ahead to appid{" "}
                  {fmtInt(job.start_appid)}.
                </p>
              ) : null}
              {rerun.isError ? (
                <p className="mt-2 text-xs text-status-critical">
                  {(rerun.error as Error).message}
                </p>
              ) : null}
            </div>
          ))
        )}
      </Card>
    </div>
  );
}
