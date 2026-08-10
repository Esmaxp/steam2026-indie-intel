"use client";

import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { fetchGameSearch, fetchSimilarGames } from "@/lib/api";
import { DASH, fmtInt, fmtPct, labelFor } from "@/lib/format";
import type { GameListItem } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

/** Compact result cards shared by the dashboard search and the detail panel. */
export function SimilarGamesList({ appid, limit = 10 }: { appid: number; limit?: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["similar", appid, limit],
    queryFn: () => fetchSimilarGames(appid, limit),
  });

  if (isLoading) {
    return (
      <div className="grid gap-2 md:grid-cols-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} className="h-16 animate-pulse" />
        ))}
      </div>
    );
  }
  if (!data || data.length === 0) {
    return (
      <p className="text-sm text-muted">
        No similar games found — similarity needs shared genres or tags, which
        fill in as the collector processes the catalog.
      </p>
    );
  }
  return (
    <div className="grid gap-2 md:grid-cols-2">
      {data.map((game: GameListItem) => (
        <Link key={game.appid} href={`/games/${game.appid}`}>
          <Card className="flex items-center gap-3 p-2.5 transition-colors hover:border-accent/50">
            {game.capsule_image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={game.capsule_image_url}
                alt=""
                className="h-10 w-auto rounded-sm border border-hairline"
                loading="lazy"
              />
            ) : null}
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium">{game.name}</div>
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                <span>{game.genres.slice(0, 2).join(", ") || DASH}</span>
                {game.engine !== "unknown" ? (
                  <Badge className="px-1.5 py-0">{labelFor(game.engine)}</Badge>
                ) : null}
                {game.total_reviews !== null ? (
                  <span className="tabular-nums">
                    {fmtInt(game.total_reviews)} reviews · {fmtPct(game.positive_pct)}
                  </span>
                ) : null}
              </div>
            </div>
          </Card>
        </Link>
      ))}
    </div>
  );
}

/** Dashboard section: pick a game by name, see its closest neighbours. */
export function SimilarGamesSearch() {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [selected, setSelected] = useState<{ appid: number; name: string } | null>(null);
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handle = setTimeout(() => setDebounced(query.trim()), 350);
    return () => clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const { data: suggestions } = useQuery({
    queryKey: ["game-search", debounced],
    queryFn: () => fetchGameSearch(debounced),
    enabled: debounced.length >= 2,
  });

  return (
    <Card className="p-4">
      <h2 className="mb-2 text-sm font-medium text-ink2">Find similar games</h2>
      <div ref={boxRef} className="relative max-w-md">
        <div className="relative">
          <Search
            size={14}
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted"
          />
          <Input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            placeholder="Type a game name…"
            className="w-full pl-8"
            aria-label="Search a game to find similar titles"
          />
        </div>
        {open && suggestions && suggestions.length > 0 ? (
          <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded-md border border-hairline bg-surface shadow-md">
            {suggestions.map((game) => (
              <li key={game.appid}>
                <button
                  className="w-full px-3 py-2 text-left text-sm hover:bg-grid/40"
                  onClick={() => {
                    setSelected(game);
                    setQuery(game.name);
                    setOpen(false);
                  }}
                >
                  {game.name}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      {selected ? (
        <div className="mt-3">
          <div className="mb-2 text-xs text-muted">
            Games similar to <span className="font-medium text-ink">{selected.name}</span>{" "}
            (shared genres/tags weighted most; flagged games excluded)
          </div>
          <SimilarGamesList appid={selected.appid} />
        </div>
      ) : null}
    </Card>
  );
}
