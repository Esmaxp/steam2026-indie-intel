"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchSummary } from "@/lib/api";
import { fmtCompact, fmtInt, DASH } from "@/lib/format";
import { Card } from "@/components/ui/card";
import type { AverageStat } from "@/lib/types";

function Tile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card className="px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight">{value}</div>
      {hint ? <div className="mt-0.5 text-[11px] text-muted">{hint}</div> : null}
    </Card>
  );
}

function avgTile(stat: AverageStat | undefined): {
  value: string;
  hint?: string;
} {
  if (!stat || stat.value === null) {
    return { value: DASH, hint: "no public data yet" };
  }
  return {
    value: fmtCompact(stat.value),
    hint: `avg over ${fmtInt(stat.sample_size)} games with data`,
  };
}

export function DashboardCards() {
  const { data, isLoading } = useQuery({
    queryKey: ["summary"],
    queryFn: fetchSummary,
  });

  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        {Array.from({ length: 10 }).map((_, i) => (
          <Card key={i} className="h-[76px] animate-pulse" />
        ))}
      </div>
    );
  }

  const avgRev = avgTile(data.avg_reviews);

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      <Tile label="Total games" value={fmtInt(data.total_games)} />
      <Tile label="Released" value={fmtInt(data.released_games)} />
      <Tile label="Upcoming (2026)" value={fmtInt(data.coming_soon_games)} />
      <Tile label="2D games" value={fmtInt(data.two_d_games)} />
      <Tile label="3D games" value={fmtInt(data.three_d_games)} />
      <Tile label="With demo" value={fmtInt(data.games_with_demo)} />
      <Tile label="Next Fest" value={fmtInt(data.next_fest_games)} />
      <Tile label="Avg reviews" value={avgRev.value} hint={avgRev.hint} />
      {/* Coverage counters, not averages. Averaging a handful of disclosed
          lower bounds would invent a precision the data does not have. */}
      <Tile
        label="With followers"
        value={fmtInt(data.games_with_followers)}
        hint="measured from Steam hubs"
      />
      <Tile
        label="On wishlist chart"
        value={fmtInt(data.ranked_games)}
        hint="Valve Top Wishlists position"
      />
      <Tile
        label="Wishlists disclosed"
        value={fmtInt(data.confirmed_wishlist_games)}
        hint="confirmed by the developer"
      />
    </div>
  );
}
