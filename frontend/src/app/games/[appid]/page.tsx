"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { use } from "react";
import { fetchGame } from "@/lib/api";
import {
  DASH,
  fmtCompact,
  fmtDate,
  fmtInt,
  fmtMoney,
  fmtPct,
  fmtPriceCents,
  labelFor,
} from "@/lib/format";
import type { GameDetail, Provenanced } from "@/lib/types";
import { StatsHistoryChart } from "@/components/stats-history-chart";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-ink">{children}</dd>
    </div>
  );
}

function ProvenancedFact({
  label,
  data,
  money,
}: {
  label: string;
  data: Provenanced;
  money?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 flex flex-col gap-0.5 text-sm">
        <span className="text-lg font-semibold tabular-nums">
          {money ? fmtMoney(data.value) : fmtCompact(data.value)}
        </span>
        <StatusBadge status={data.status} />
        {data.estimate_spread !== null && data.estimate_spread !== undefined ? (
          <span className="text-xs text-muted">
            spread {(data.estimate_spread * 100).toFixed(0)}% between sources
          </span>
        ) : null}
        {data.source_name ? (
          data.source_url ? (
            <a
              href={data.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-xs text-accent hover:underline"
            >
              {data.source_name}
            </a>
          ) : (
            <span className="text-xs text-muted">{data.source_name}</span>
          )
        ) : null}
      </dd>
    </div>
  );
}

function Timeline({ game }: { game: GameDetail }) {
  const events: { date: string; label: string }[] = [];
  if (game.page_creation_date)
    events.push({ date: game.page_creation_date, label: "Steam page created" });
  if (game.demo_release_date)
    events.push({ date: game.demo_release_date, label: "Demo released" });
  if (game.release_date)
    events.push({
      date: game.release_date,
      label: game.is_released ? "Released" : "Planned release",
    });
  for (const fest of game.festivals) {
    if (fest.start_date) events.push({ date: fest.start_date, label: fest.name });
  }
  events.sort((a, b) => a.date.localeCompare(b.date));
  if (events.length === 0)
    return <p className="text-sm text-muted">No dated events known.</p>;
  return (
    <ol className="relative ml-2 flex flex-col gap-3 border-l border-grid pl-4">
      {events.map((event, i) => (
        <li key={i} className="relative">
          <span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-accent" />
          <div className="text-xs text-muted tabular-nums">{fmtDate(event.date)}</div>
          <div className="text-sm">{event.label}</div>
        </li>
      ))}
    </ol>
  );
}

export default function GamePage({
  params,
}: {
  params: Promise<{ appid: string }>;
}) {
  const { appid } = use(params);
  const { data: game, isLoading, isError } = useQuery({
    queryKey: ["game", appid],
    queryFn: () => fetchGame(Number(appid)),
  });

  if (isLoading) {
    return <Card className="h-96 animate-pulse" />;
  }
  if (isError || !game) {
    return (
      <Card className="p-10 text-center text-muted">
        Game not found.{" "}
        <Link href="/" className="text-accent hover:underline">
          Back to dashboard
        </Link>
      </Card>
    );
  }

  const screenshots = game.media.filter((m) => m.media_type === "screenshot");
  const movies = game.media.filter((m) => m.media_type === "movie");

  return (
    <div className="flex flex-col gap-4">
      <Link
        href="/"
        className="inline-flex w-fit items-center gap-1 text-sm text-ink2 hover:text-ink"
      >
        <ArrowLeft size={14} aria-hidden /> All games
      </Link>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card className="overflow-hidden">
          {game.header_image_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={game.header_image_url}
              alt={game.name}
              className="w-full border-b border-hairline"
            />
          ) : null}
          <div className="flex flex-col gap-3 p-5">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">{game.name}</h1>
              {game.early_access ? <Badge>Early Access</Badge> : null}
              {game.coming_soon ? <Badge>Coming Soon</Badge> : null}
              {game.next_fest ? (
                <Badge className="border-accent/40 text-accent">Next Fest</Badge>
              ) : null}
            </div>
            {game.short_description ? (
              <p className="text-sm text-ink2">{game.short_description}</p>
            ) : null}
            <div className="flex flex-wrap gap-1.5">
              {game.tags_full.slice(0, 14).map((tag) => (
                <Badge key={tag.name} title={tag.votes ? `${tag.votes} votes` : undefined}>
                  {tag.name}
                </Badge>
              ))}
            </div>
            <div className="flex gap-3 text-sm">
              {game.steam_store_url ? (
                <a
                  href={game.steam_store_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-accent hover:underline"
                >
                  Steam Store <ExternalLink size={12} aria-hidden />
                </a>
              ) : null}
              {game.steamdb_url ? (
                <a
                  href={game.steamdb_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-ink2 hover:underline"
                >
                  SteamDB <ExternalLink size={12} aria-hidden />
                </a>
              ) : null}
            </div>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 border-t border-grid pt-4 md:grid-cols-3">
              <Fact label="Developer">
                {game.developers_full.map((d) => d.name).join(", ") || DASH}
              </Fact>
              <Fact label="Publisher">
                {game.publishers_full.map((p) => p.name).join(", ") || DASH}
              </Fact>
              <Fact label="Release date">
                {fmtDate(game.release_date, game.release_date_raw)}
              </Fact>
              <Fact label="Genres">{game.genres.join(", ") || DASH}</Fact>
              <Fact label="Price">
                {fmtPriceCents(game.current_price_cents, game.currency, game.is_free)}
              </Fact>
              <Fact label="Demo">
                {game.demo_available
                  ? game.demo_release_date
                    ? `Yes — ${fmtDate(game.demo_release_date)}`
                    : "Yes"
                  : "No"}
              </Fact>
              <Fact label="Dimension">{labelFor(game.dimension)}</Fact>
              <Fact label="Camera">{labelFor(game.camera)}</Fact>
              <Fact label="Graphics">{labelFor(game.graphics_style)}</Fact>
              <Fact label="Engine">{labelFor(game.engine)}</Fact>
              <Fact label="Controller">{labelFor(game.controller_support)}</Fact>
              <Fact label="Steam Deck">{labelFor(game.steam_deck_support)}</Fact>
            </dl>
            {game.supported_languages.length > 0 ? (
              <p className="text-xs text-muted">
                Languages: {game.supported_languages.join(", ")}
              </p>
            ) : null}
          </div>
        </Card>

        <div className="flex flex-col gap-4">
          <Card className="p-5">
            <h2 className="mb-3 text-sm font-medium text-muted">Business data</h2>
            <div className="grid grid-cols-2 gap-4">
              <ProvenancedFact label="Wishlist" data={game.wishlist} />
              <ProvenancedFact label="Gross revenue" data={game.revenue} money />
              <Fact label="Est. sales">
                <span className="tabular-nums">{fmtCompact(game.estimated_sales)}</span>
              </Fact>
              <ProvenancedFact label="Budget" data={game.budget} money />
            </div>
            {game.budget_estimates.length > 0 ? (
              <details className="mt-3 border-t border-grid pt-3">
                <summary className="cursor-pointer text-xs font-medium text-accent">
                  How was the budget estimated?
                </summary>
                <div className="mt-2 flex flex-col gap-3">
                  {game.budget_estimates.map((estimate, i) => (
                    <div key={i} className="rounded-md border border-hairline p-3 text-xs">
                      <div className="font-medium">
                        {estimate.method === "team_cost"
                          ? "Method A — team size × duration × regional cost"
                          : "Method B — industry revenue-to-budget ratio"}
                        :{" "}
                        <span className="tabular-nums">
                          {estimate.budget_min_usd === estimate.budget_max_usd
                            ? fmtMoney(estimate.budget_min_usd)
                            : `${fmtMoney(estimate.budget_min_usd)} – ${fmtMoney(estimate.budget_max_usd)}`}
                        </span>
                      </div>
                      <div className="mt-1 text-muted">
                        Formula: <code>{estimate.formula}</code>
                      </div>
                      <ul className="mt-1 text-muted">
                        {Object.entries(estimate.inputs).map(([key, value]) => (
                          <li key={key}>
                            {key}: <span className="text-ink2">{String(value)}</span>
                          </li>
                        ))}
                      </ul>
                      <div className="mt-1 text-muted">
                        This is an explicitly labeled heuristic — not a fact.
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            ) : null}
          </Card>

          {game.revenue_estimates.length > 0 ? (
            <Card className="p-5">
              <h2 className="mb-3 text-sm font-medium text-muted">
                Estimate sources (each with link + date)
              </h2>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-grid text-left text-muted">
                    <th className="py-1 pr-2">Source</th>
                    <th className="py-1 pr-2">Revenue</th>
                    <th className="py-1 pr-2">Sales</th>
                    <th className="py-1">Owners</th>
                  </tr>
                </thead>
                <tbody>
                  {game.revenue_estimates.map((estimate, i) => (
                    <tr key={i} className="border-b border-grid/60 last:border-0">
                      <td className="py-1.5 pr-2">
                        <a
                          href={estimate.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-accent hover:underline"
                        >
                          {estimate.source_name}
                        </a>
                        <span className="ml-1 text-muted">
                          {new Date(estimate.retrieved_at).toLocaleDateString("en-GB")}
                        </span>
                      </td>
                      <td className="py-1.5 pr-2 tabular-nums">
                        {fmtMoney(estimate.revenue_usd)}
                      </td>
                      <td className="py-1.5 pr-2 tabular-nums">
                        {fmtCompact(estimate.estimated_sales)}
                      </td>
                      <td className="py-1.5 tabular-nums">
                        {estimate.owners_min !== null || estimate.owners_max !== null
                          ? `${fmtCompact(estimate.owners_min)}–${fmtCompact(estimate.owners_max)}`
                          : DASH}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ) : null}

          <Card className="p-5">
            <h2 className="mb-3 text-sm font-medium text-muted">Review statistics</h2>
            {game.latest_stats ? (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
                <Fact label="Total reviews">
                  <span className="tabular-nums">
                    {fmtInt(game.latest_stats.total_reviews)}
                  </span>
                </Fact>
                <Fact label="Positive">
                  <span className="tabular-nums">
                    {fmtPct(game.latest_stats.positive_pct)}
                  </span>
                  {game.latest_stats.review_score_desc ? (
                    <span className="ml-1 text-xs text-muted">
                      ({game.latest_stats.review_score_desc})
                    </span>
                  ) : null}
                </Fact>
                <Fact label="Peak CCU (all-time)">
                  <span className="tabular-nums">{fmtInt(game.latest_stats.peak_ccu)}</span>
                </Fact>
                <Fact label="Avg CCU (30d)">
                  <span className="tabular-nums">
                    {game.latest_stats.avg_ccu !== null
                      ? fmtInt(Math.round(game.latest_stats.avg_ccu))
                      : DASH}
                  </span>
                </Fact>
              </dl>
            ) : (
              <p className="text-sm text-muted">No stats collected yet.</p>
            )}
          </Card>

          <Card className="p-5">
            <h2 className="mb-3 text-sm font-medium text-muted">Timeline</h2>
            <Timeline game={game} />
          </Card>
        </div>
      </div>

      <StatsHistoryChart appid={game.appid} />

      {screenshots.length > 0 ? (
        <Card className="p-5">
          <h2 className="mb-3 text-sm font-medium text-muted">Screenshots</h2>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {screenshots.slice(0, 8).map((shot) => (
              <a key={shot.url} href={shot.url} target="_blank" rel="noreferrer">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={shot.thumbnail_url ?? shot.url}
                  alt=""
                  loading="lazy"
                  className="w-full rounded-md border border-hairline"
                />
              </a>
            ))}
          </div>
        </Card>
      ) : null}

      {movies.length > 0 ? (
        <Card className="p-5">
          <h2 className="mb-3 text-sm font-medium text-muted">Videos</h2>
          <div className="grid gap-3 md:grid-cols-2">
            {movies.slice(0, 2).map((movie) => (
              <video
                key={movie.url}
                src={movie.url}
                poster={movie.thumbnail_url ?? undefined}
                controls
                preload="none"
                className="w-full rounded-md border border-hairline"
              />
            ))}
          </div>
        </Card>
      ) : null}

      {(game.wishlist_history.length > 0 || game.revenue_history.length > 0) && (
        <Card className="p-5">
          <h2 className="mb-3 text-sm font-medium text-muted">
            Business data history (all records carry status + source)
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-grid text-left text-xs text-muted">
                  <th className="py-1.5 pr-4">Recorded</th>
                  <th className="py-1.5 pr-4">Metric</th>
                  <th className="py-1.5 pr-4">Value</th>
                  <th className="py-1.5 pr-4">Status</th>
                  <th className="py-1.5">Source</th>
                </tr>
              </thead>
              <tbody>
                {game.wishlist_history.map((w, i) => (
                  <tr key={`w${i}`} className="border-b border-grid/60">
                    <td className="py-1.5 pr-4 tabular-nums">
                      {new Date(w.recorded_at).toLocaleDateString("en-GB")}
                    </td>
                    <td className="py-1.5 pr-4">Wishlist</td>
                    <td className="py-1.5 pr-4 tabular-nums">{fmtCompact(w.wishlist_count)}</td>
                    <td className="py-1.5 pr-4"><StatusBadge status={w.status} /></td>
                    <td className="py-1.5">
                      {w.source_url ? (
                        <a href={w.source_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                          {w.source_name ?? w.source_url}
                        </a>
                      ) : (
                        w.source_name ?? DASH
                      )}
                    </td>
                  </tr>
                ))}
                {game.revenue_history.map((r, i) => (
                  <tr key={`r${i}`} className="border-b border-grid/60 last:border-0">
                    <td className="py-1.5 pr-4 tabular-nums">
                      {new Date(r.recorded_at).toLocaleDateString("en-GB")}
                    </td>
                    <td className="py-1.5 pr-4">Revenue</td>
                    <td className="py-1.5 pr-4 tabular-nums">{fmtMoney(r.gross_revenue_usd)}</td>
                    <td className="py-1.5 pr-4"><StatusBadge status={r.status} /></td>
                    <td className="py-1.5">
                      {r.source_url ? (
                        <a href={r.source_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                          {r.source_name ?? r.source_url}
                        </a>
                      ) : (
                        r.source_name ?? DASH
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
