"use client";

import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import type { OnChangeFn, VisibilityState } from "@tanstack/react-table";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronDown,
  ChevronRight,
  ExternalLink,
} from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";
import { fetchGame, fetchGames } from "@/lib/api";
import {
  DASH,
  fmtDate,
  fmtDelta,
  fmtInt,
  fmtMoney,
  fmtPct,
  fmtWishlist,
  labelFor,
} from "@/lib/format";
import type { GameListItem } from "@/lib/types";
import { useFilterParams } from "@/hooks/use-filter-params";
import { rememberListQuery } from "@/lib/last-list-query";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { ColumnPicker } from "@/components/column-picker";
import { Pagination } from "@/components/pagination";

const col = createColumnHelper<GameListItem>();

/** Passed via table meta so column cells can drive the inline row expansion. */
interface ExpandMeta {
  expandedAppid: number | null;
  toggleExpanded: (appid: number) => void;
}

const GENRES_SHOWN = 4;

/** Four-quadrant label, short enough to sit beside a game's name. Colour
 *  follows status-badge.tsx — green for the good outcome, the accent for the
 *  one worth acting on, muted for the rest — and never carries the meaning
 *  alone, since the words are always there too. */
const CLASSIFICATION_STYLE: Record<string, { label: string; tone: string }> = {
  HIGH_EFFORT_HIGH_TRACTION: {
    label: "Serious · found",
    tone: "border-status-good/40 text-good-text",
  },
  // This catalogue's reason for existing, so it gets the accent rather than a
  // neutral tone: real production effort that review counts alone would bury.
  HIGH_EFFORT_LOW_TRACTION: {
    label: "Serious · overlooked",
    tone: "border-accent/50 bg-accent/10 text-accent",
  },
  LOW_EFFORT_HIGH_TRACTION: { label: "Lucky", tone: "border-hairline text-ink2" },
  LOW_EFFORT_LOW_TRACTION: { label: "Low effort", tone: "border-hairline text-muted" },
};

const EFFORT_WORD: Record<string, string> = {
  serious: "Serious",
  mixed: "Mixed",
  hobby: "Hobby",
};

/** Why a game sits where the filters put it.
 *
 *  These signals used to be filter-only: you could hide flagged games but
 *  never see which ones they were, or why. The tooltip carries both axes and
 *  the effort breakdown behind them. INSUFFICIENT_DATA renders nothing — a
 *  game released three weeks ago has not earned a verdict. */
function ClassificationBadge({ game }: { game: GameListItem }) {
  const style = CLASSIFICATION_STYLE[game.classification];
  if (!style) return null;
  const signals = game.effort_signals?.signals ?? {};
  const detail = Object.entries(signals)
    .map(([name, weight]) => `${name} ${weight > 0 ? "+" : ""}${weight}`)
    .join(", ");
  const title = [
    `Effort ${game.effort_score ?? "?"}/100 (${EFFORT_WORD[game.effort_class] ?? game.effort_class})`,
    `traction ${game.traction_score ?? "?"}/100 (${game.traction_class})`,
    `${game.classification_confidence} confidence`,
  ].join(" · ");
  return (
    <Badge
      className={`shrink-0 px-1.5 py-0 text-[10px] ${style.tone}`}
      title={
        title +
        (detail ? ` — effort signals: ${detail}` : "") +
        (game.limited_profile ? " — Steam profile features still restricted." : "")
      }
    >
      {style.label}
    </Badge>
  );
}

/** Columns hidden on a first visit — the widest, least-scanned ones.
 *  Everything stays toggleable via the Columns menu. */
const DEFAULT_COLUMN_VISIBILITY: VisibilityState = {
  developer: false,
  publisher: false,
  tags: false,
  // Ships dark: day-over-day rank volatility is not yet measured, so a small
  // move cannot yet be distinguished from Valve's own reshuffling. Enable by
  // default only after running scripts/rank_delta_report.py on sweeps ~24h
  // apart. Still toggleable in the Columns menu meanwhile.
  rank_delta_7d: false,
};

/** Survives reloads; bumped suffix invalidates old shapes after a column rename.
 *  v2: budget column removed; followers/rank columns added. */
const VISIBILITY_STORAGE_KEY = "steam2026.games-table.columns.v2";

/** Columns whose header click drives server-side sorting.
 *  No wishlist or revenue key: both are all-NULL columns, and disclosed
 *  wishlist figures are mostly ">=" bounds that do not order meaningfully. */
const SORTABLE: Record<string, string> = {
  name: "name",
  release_date: "release_date",
  total_reviews: "reviews",
  positive_pct: "positive_pct",
  peak_ccu: "peak_ccu",
  followers: "followers",
  follower_delta_14d: "follower_delta_14d",
  wishlist_rank: "wishlist_rank",
  rank_delta_7d: "rank_delta_7d",
  video_count: "videos",
};

/** Sort keys where ascending is the better value (rank 1 = top of chart). */
const ASCENDING_IS_BETTER = new Set(["wishlist_rank"]);

const columns = [
  col.display({
    id: "expand",
    header: "",
    cell: (info) => {
      const meta = info.table.options.meta as ExpandMeta;
      const expanded = meta.expandedAppid === info.row.original.appid;
      return expanded ? (
        <ChevronDown size={14} className="text-accent" aria-hidden />
      ) : (
        <ChevronRight size={14} className="text-muted" aria-hidden />
      );
    },
  }),
  col.accessor("name", {
    id: "name",
    header: "Game",
    cell: (info) => {
      const game = info.row.original;
      return (
        <div className="flex items-center gap-2">
          <Link
            href={`/games/${game.appid}`}
            onClick={(e) => e.stopPropagation()}
            className="flex items-center gap-2 font-medium text-ink hover:text-accent"
          >
            {game.capsule_image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={game.capsule_image_url}
                alt=""
                className="h-8 w-auto rounded-sm border border-hairline"
                loading="lazy"
              />
            ) : null}
            <span className="max-w-56 truncate">{game.name}</span>
          </Link>
          <ClassificationBadge game={game} />
        </div>
      );
    },
  }),
  col.accessor((g) => g.developers.join(", "), {
    id: "developer",
    header: "Developer",
    cell: (info) => (
      <span className="block max-w-40 truncate text-ink2">{info.getValue() || DASH}</span>
    ),
  }),
  col.accessor((g) => g.publishers.join(", "), {
    id: "publisher",
    header: "Publisher",
    cell: (info) => (
      <span className="block max-w-40 truncate text-ink2">{info.getValue() || DASH}</span>
    ),
  }),
  col.accessor("release_date", {
    id: "release_date",
    header: "Release",
    cell: (info) => {
      const game = info.row.original;
      return (
        <span className="whitespace-nowrap tabular-nums">
          {fmtDate(game.release_date, game.release_date_raw)}
          {game.early_access ? (
            <span className="ml-1 text-[10px] text-muted">EA</span>
          ) : null}
        </span>
      );
    },
  }),
  col.accessor("demo_release_date", {
    id: "demo",
    header: "Demo",
    cell: (info) => {
      const game = info.row.original;
      if (!game.demo_available) return <span className="text-muted">{DASH}</span>;
      return (
        <span className="whitespace-nowrap tabular-nums">
          {game.demo_release_date ? fmtDate(game.demo_release_date) : "Yes"}
        </span>
      );
    },
  }),
  col.accessor("next_fest", {
    id: "next_fest",
    header: "Next Fest",
    cell: (info) =>
      info.getValue() ? (
        <Badge className="border-accent/40 text-accent">Next Fest</Badge>
      ) : (
        <span className="text-muted">{DASH}</span>
      ),
  }),
  col.accessor((g) => g.genres.join(", "), {
    id: "genres",
    header: "Genres",
    cell: (info) => {
      const genres = info.row.original.genres;
      if (genres.length === 0) return <span className="text-ink2">{DASH}</span>;
      // Server-ordered by rank, so the first 4 are Steam's most relevant.
      const extra = genres.length - GENRES_SHOWN;
      return (
        <span className="block max-w-40 text-ink2">
          {genres.slice(0, GENRES_SHOWN).join(", ")}
          {extra > 0 ? (
            <span className="ml-1 whitespace-nowrap text-xs text-accent">+{extra}</span>
          ) : null}
        </span>
      );
    },
  }),
  col.accessor((g) => g.tags.join(", "), {
    id: "tags",
    header: "Steam Tags",
    // Compact while collapsed; the full list lives in the expanded panel
    // (native title tooltips are unreliable and don't work on touch).
    cell: (info) => (
      <span className="block max-w-48 truncate text-ink2">
        {info.getValue() || DASH}
      </span>
    ),
  }),
  col.accessor("video_count", {
    id: "video_count",
    header: "Videos",
    cell: (info) =>
      info.getValue() > 0 ? (
        <span className="tabular-nums">{info.getValue()}</span>
      ) : (
        <span className="text-muted">{DASH}</span>
      ),
  }),
  col.accessor("dimension", {
    id: "dimension",
    header: "2D/3D",
    cell: (info) => labelFor(info.getValue()),
  }),
  col.accessor("engine", {
    id: "engine",
    header: "Engine",
    cell: (info) =>
      info.getValue() === "unknown" ? (
        <span className="text-muted">Unknown</span>
      ) : (
        labelFor(info.getValue())
      ),
  }),
  col.accessor("total_reviews", {
    id: "total_reviews",
    header: "Reviews",
    cell: (info) => <span className="tabular-nums">{fmtInt(info.getValue())}</span>,
  }),
  col.accessor("positive_pct", {
    id: "positive_pct",
    header: "Positive",
    cell: (info) => <span className="tabular-nums">{fmtPct(info.getValue())}</span>,
  }),
  col.accessor("peak_ccu", {
    id: "peak_ccu",
    header: () => (
      <span title="Source: steamcharts.com (third party)">Peak CCU</span>
    ),
    cell: (info) => <span className="tabular-nums">{fmtInt(info.getValue())}</span>,
  }),
  col.accessor("followers", {
    id: "followers",
    header: () => (
      <span title="Steam community-hub members — a value Valve publishes. Exact, not an estimate.">
        Followers
      </span>
    ),
    cell: (info) => {
      const game = info.row.original;
      if (game.followers === null) return <span className="text-muted">{DASH}</span>;
      return (
        <div className="flex flex-col">
          <span className="tabular-nums">{fmtInt(game.followers)}</span>
          <span className="text-[10px] text-muted">
            {fmtDate(game.followers_captured_at)}
          </span>
        </div>
      );
    },
  }),
  col.accessor("follower_delta_14d", {
    id: "follower_delta_14d",
    header: () => (
      <span title="Change in followers over the last 14 days, from our own snapshots. Blank until two snapshots exist — never shown as zero.">
        Followers Δ14d
      </span>
    ),
    cell: (info) => {
      const game = info.row.original;
      if (game.follower_delta_14d === null)
        return <span className="text-muted">{DASH}</span>;
      const up = game.follower_delta_14d > 0;
      return (
        <div className="flex flex-col">
          <span className={`tabular-nums ${up ? "text-good-text" : "text-ink2"}`}>
            {fmtDelta(game.follower_delta_14d)}
          </span>
          {game.follower_delta_14d_pct !== null ? (
            <span className="text-[10px] text-muted tabular-nums">
              {fmtPct(game.follower_delta_14d_pct)}
            </span>
          ) : null}
        </div>
      );
    },
  }),
  col.accessor("wishlist_rank", {
    id: "wishlist_rank",
    header: () => (
      <span title="Valve's Top Wishlists position; blends total wishlists and recent velocity — not a count.">
        Wishlist rank
      </span>
    ),
    cell: (info) => {
      const game = info.row.original;
      if (game.wishlist_rank !== null)
        return <span className="tabular-nums">#{game.wishlist_rank}</span>;
      // The chart covers only unreleased games, so "Not ranked" is only
      // meaningful for those; for a released game the concept doesn't apply.
      return game.is_released ? (
        <span className="text-muted">{DASH}</span>
      ) : (
        <span className="text-muted">Not ranked</span>
      );
    },
  }),
  col.accessor("rank_delta_7d", {
    id: "rank_delta_7d",
    header: () => (
      <span title="Change in Top Wishlists position over 7 days; positive = moved up. Noisy at the tail of the chart — interpret small moves with care.">
        Rank Δ7d
      </span>
    ),
    cell: (info) => {
      const value = info.getValue();
      if (value === null) return <span className="text-muted">{DASH}</span>;
      return (
        <span className={`tabular-nums ${value > 0 ? "text-good-text" : "text-ink2"}`}>
          {fmtDelta(value)}
        </span>
      );
    },
  }),
  col.accessor((g) => g.wishlist.value, {
    id: "wishlist",
    header: () => (
      <span title="Only shown when a developer publicly disclosed the figure. Steam publishes no wishlist counts, and this project never estimates one.">
        Wishlist
      </span>
    ),
    cell: (info) => {
      const wishlist = info.row.original.wishlist;
      // Confirmed disclosure or nothing. No "estimated" badge on this column,
      // ever — there is no defensible way to estimate a wishlist count.
      if (wishlist.status !== "confirmed" || wishlist.value === null)
        return <span className="text-muted">Unknown</span>;
      return (
        <div className="flex flex-col">
          <span className="tabular-nums">
            {fmtWishlist(wishlist.value, wishlist.comparator)}
          </span>
          <span className="text-[10px] text-muted">
            {wishlist.source_url ? (
              <a
                href={wishlist.source_url}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="text-accent hover:underline"
              >
                {fmtDate(wishlist.disclosed_on) || "source"}
              </a>
            ) : (
              fmtDate(wishlist.disclosed_on)
            )}
          </span>
        </div>
      );
    },
  }),
  col.accessor((g) => g.revenue.value, {
    id: "revenue",
    header: "Revenue",
    cell: (info) => {
      const revenue = info.row.original.revenue;
      return (
        <div className="flex flex-col">
          <span className="tabular-nums">{fmtMoney(revenue.value)}</span>
          <StatusBadge status={revenue.status} />
        </div>
      );
    },
  }),
  col.display({
    id: "links",
    header: "Links",
    cell: (info) => {
      const game = info.row.original;
      return (
        <span className="flex gap-2 whitespace-nowrap">
          {game.steam_store_url ? (
            <a
              href={game.steam_store_url}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-0.5 text-accent hover:underline"
            >
              Steam <ExternalLink size={11} aria-hidden />
            </a>
          ) : null}
          {game.steamdb_url ? (
            <a
              href={game.steamdb_url}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="inline-flex items-center gap-0.5 text-ink2 hover:underline"
            >
              SteamDB <ExternalLink size={11} aria-hidden />
            </a>
          ) : null}
        </span>
      );
    },
  }),
];

/** Inline detail panel — fetches full game data only when its row is expanded. */
function ExpandedRow({ game }: { game: GameListItem }) {
  const { data: detail, isLoading } = useQuery({
    queryKey: ["game", game.appid],
    queryFn: () => fetchGame(game.appid),
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading || !detail) {
    return (
      <div className="flex flex-col gap-2 p-4">
        <div className="h-3 w-2/3 animate-pulse rounded bg-grid" />
        <div className="h-3 w-1/2 animate-pulse rounded bg-grid" />
      </div>
    );
  }

  const screenshots = detail.media
    .filter((m) => m.media_type === "screenshot")
    .slice(0, 4);

  return (
    <div className="flex flex-col gap-3 p-4">
      {detail.short_description ? (
        <p className="max-w-4xl text-sm text-ink2">{detail.short_description}</p>
      ) : null}

      <div className="flex flex-wrap items-start gap-x-8 gap-y-2 text-sm">
        <div>
          <div className="text-xs text-muted">Genres ({detail.genres.length})</div>
          <div className="mt-1 flex max-w-md flex-wrap gap-1">
            {detail.genres.length > 0
              ? detail.genres.map((genre) => <Badge key={genre}>{genre}</Badge>)
              : DASH}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted">Steam Tags ({detail.tags_full.length})</div>
          <div className="mt-1 flex max-w-2xl flex-wrap gap-1">
            {detail.tags_full.length > 0
              ? detail.tags_full.map((tag) => (
                  <Badge key={tag.name}>{tag.name}</Badge>
                ))
              : DASH}
          </div>
        </div>
        <div className="flex gap-6">
          <div>
            <div className="text-xs text-muted">Camera</div>
            <div className="mt-1">{labelFor(detail.camera)}</div>
          </div>
          <div>
            <div className="text-xs text-muted">Graphics</div>
            <div className="mt-1">{labelFor(detail.graphics_style)}</div>
          </div>
          <div>
            <div className="text-xs text-muted">Steam Deck</div>
            <div className="mt-1">{labelFor(detail.steam_deck_support)}</div>
          </div>
        </div>
      </div>

      {screenshots.length > 0 ? (
        <div className="flex gap-2">
          {screenshots.map((shot) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={shot.url}
              src={shot.thumbnail_url ?? shot.url}
              alt=""
              loading="lazy"
              className="h-20 rounded-md border border-hairline"
            />
          ))}
        </div>
      ) : null}

      <div className="flex items-center gap-4 text-sm">
        <Link
          href={`/games/${game.appid}`}
          onClick={(e) => e.stopPropagation()}
          className="text-accent hover:underline"
        >
          Full details →
        </Link>
        {detail.website ? (
          <a
            href={detail.website}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 text-ink2 hover:underline"
          >
            Official Website <ExternalLink size={12} aria-hidden />
          </a>
        ) : null}
      </div>
    </div>
  );
}

export function GamesTable() {
  const { searchParams, setParams } = useFilterParams();
  const [expandedAppid, setExpandedAppid] = useState<number | null>(null);
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>(
    DEFAULT_COLUMN_VISIBILITY,
  );

  // Restored after mount, never during render: localStorage doesn't exist on the
  // server, and seeding initial state from it would break hydration.
  useEffect(() => {
    const saved = window.localStorage.getItem(VISIBILITY_STORAGE_KEY);
    if (!saved) return;
    try {
      setColumnVisibility(JSON.parse(saved) as VisibilityState);
    } catch {
      // Malformed (hand-edited or stale shape) — silently keep the defaults.
    }
  }, []);

  const handleVisibilityChange: OnChangeFn<VisibilityState> = (updater) => {
    const next =
      typeof updater === "function" ? updater(columnVisibility) : updater;
    setColumnVisibility(next);
    window.localStorage.setItem(VISIBILITY_STORAGE_KEY, JSON.stringify(next));
  };

  const resetColumns = () => {
    setColumnVisibility(DEFAULT_COLUMN_VISIBILITY);
    window.localStorage.removeItem(VISIBILITY_STORAGE_KEY);
  };

  // Stash the filters on every change, so leaving for a game and coming back
  // through "All games" lands on this list rather than the whole catalogue.
  useEffect(() => {
    rememberListQuery(searchParams.toString());
  }, [searchParams]);

  const apiParams = useMemo(() => {
    const params = new URLSearchParams(searchParams.toString());
    if (!params.has("page_size")) params.set("page_size", "25");
    return params;
  }, [searchParams]);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["games", apiParams.toString()],
    queryFn: () => fetchGames(apiParams),
    placeholderData: keepPreviousData,
  });

  const toggleExpanded = (appid: number) =>
    setExpandedAppid((current) => (current === appid ? null : appid));

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    state: { columnVisibility },
    onColumnVisibilityChange: handleVisibilityChange,
    meta: { expandedAppid, toggleExpanded } satisfies ExpandMeta,
  });

  // Full-width rows (skeleton, expanded panel, empty state) must track the
  // VISIBLE column count, not the full column list.
  const visibleColumnCount = table.getVisibleLeafColumns().length;

  const currentSort = searchParams.get("sort") ?? "-release_date";

  function onSort(columnId: string) {
    const key = SORTABLE[columnId];
    if (!key) return;
    // First click should show the BEST values first. For rank that means
    // ascending (rank 1 is the top of the chart); for everything else,
    // descending.
    const preferred = ASCENDING_IS_BETTER.has(key) ? key : `-${key}`;
    const opposite = preferred.startsWith("-") ? key : `-${key}`;
    const next = currentSort === preferred ? opposite : preferred;
    setParams({ sort: next }, false);
  }

  if (isError) {
    return (
      <Card className="p-8 text-center text-sm text-muted">
        API is unreachable — is the backend running on{" "}
        <code>localhost:9100</code>?
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center">
        <ColumnPicker table={table} onReset={resetColumns} />
      </div>
      <Card className="overflow-x-auto">
        {/* No fixed min-width: the column set is user-controlled now, so the
            table sizes to whatever is visible and scrolls only when it must. */}
        <table className="w-full border-collapse text-sm">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="border-b border-grid">
                {headerGroup.headers.map((header) => {
                  const sortKey = SORTABLE[header.column.id];
                  const active =
                    sortKey &&
                    (currentSort === sortKey || currentSort === `-${sortKey}`);
                  return (
                    <th
                      key={header.id}
                      className={`px-3 py-2.5 text-left text-xs font-medium text-muted ${
                        sortKey ? "cursor-pointer select-none hover:text-ink" : ""
                      }`}
                      onClick={() => onSort(header.column.id)}
                    >
                      <span className="inline-flex items-center gap-1 whitespace-nowrap">
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext(),
                        )}
                        {sortKey ? (
                          active ? (
                            currentSort.startsWith("-") ? (
                              <ArrowDown size={12} aria-hidden />
                            ) : (
                              <ArrowUp size={12} aria-hidden />
                            )
                          ) : (
                            <ArrowUpDown size={12} className="opacity-40" aria-hidden />
                          )
                        ) : null}
                      </span>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {isLoading
              ? Array.from({ length: 10 }).map((_, i) => (
                  <tr key={i} className="border-b border-grid/60">
                    <td colSpan={visibleColumnCount} className="px-3 py-4">
                      <div className="h-4 animate-pulse rounded bg-grid" />
                    </td>
                  </tr>
                ))
              : table.getRowModel().rows.map((row) => (
                  <Fragment key={row.id}>
                    <tr
                      onClick={() => toggleExpanded(row.original.appid)}
                      className="cursor-pointer border-b border-grid/60 last:border-0 hover:bg-grid/20"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-3 py-2 align-top">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                    {expandedAppid === row.original.appid ? (
                      <tr className="border-b border-grid/60 bg-grid/10">
                        <td colSpan={visibleColumnCount}>
                          <ExpandedRow game={row.original} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
            {!isLoading && data && data.items.length === 0 ? (
              <tr>
                <td
                  colSpan={visibleColumnCount}
                  className="px-3 py-10 text-center text-muted"
                >
                  No games match these filters.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </Card>
      {data ? <Pagination page={data.page} pages={data.pages} total={data.total} /> : null}
    </div>
  );
}
