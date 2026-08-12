"use client";

import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
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
import { Fragment, useMemo, useState } from "react";
import { fetchGame, fetchGames } from "@/lib/api";
import {
  DASH,
  fmtCompact,
  fmtDate,
  fmtInt,
  fmtMoney,
  fmtPct,
  labelFor,
} from "@/lib/format";
import type { GameListItem } from "@/lib/types";
import { useFilterParams } from "@/hooks/use-filter-params";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Pagination } from "@/components/pagination";

const col = createColumnHelper<GameListItem>();

/** Passed via table meta so column cells can drive the inline row expansion. */
interface ExpandMeta {
  expandedAppid: number | null;
  toggleExpanded: (appid: number) => void;
}

const GENRES_SHOWN = 4;

/** Columns whose header click drives server-side sorting. */
const SORTABLE: Record<string, string> = {
  name: "name",
  release_date: "release_date",
  total_reviews: "reviews",
  positive_pct: "positive_pct",
  peak_ccu: "peak_ccu",
  wishlist: "wishlist",
  revenue: "revenue",
};

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
    header: "Peak CCU",
    cell: (info) => <span className="tabular-nums">{fmtInt(info.getValue())}</span>,
  }),
  col.accessor((g) => g.wishlist.value, {
    id: "wishlist",
    header: "Wishlist",
    cell: (info) => {
      const wishlist = info.row.original.wishlist;
      return (
        <div className="flex flex-col">
          <span className="tabular-nums">{fmtCompact(wishlist.value)}</span>
          <StatusBadge status={wishlist.status} />
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
  col.accessor((g) => g.budget.value, {
    id: "budget",
    header: "Budget",
    cell: (info) => {
      const budget = info.row.original.budget;
      if (budget.value === null)
        return <span className="text-muted">{DASH}</span>;
      return (
        <div className="flex flex-col">
          <span className="tabular-nums">{fmtMoney(budget.value)}</span>
          <StatusBadge status={budget.status} />
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

      <Link
        href={`/games/${game.appid}`}
        onClick={(e) => e.stopPropagation()}
        className="w-fit text-sm text-accent hover:underline"
      >
        Full details →
      </Link>
    </div>
  );
}

export function GamesTable() {
  const { searchParams, setParams } = useFilterParams();
  const [expandedAppid, setExpandedAppid] = useState<number | null>(null);

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
    meta: { expandedAppid, toggleExpanded } satisfies ExpandMeta,
  });

  const currentSort = searchParams.get("sort") ?? "-release_date";

  function onSort(columnId: string) {
    const key = SORTABLE[columnId];
    if (!key) return;
    const next =
      currentSort === `-${key}` ? key : currentSort === key ? `-${key}` : `-${key}`;
    setParams({ sort: next }, false);
  }

  if (isError) {
    return (
      <Card className="p-8 text-center text-sm text-muted">
        API is unreachable — is the backend running on{" "}
        <code>localhost:8000</code>?
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <Card className="overflow-x-auto">
        <table className="w-full min-w-[1500px] border-collapse text-sm">
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
                    <td colSpan={columns.length} className="px-3 py-4">
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
                        <td colSpan={columns.length}>
                          <ExpandedRow game={row.original} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
            {!isLoading && data && data.items.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
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
