"use client";

import { useQuery } from "@tanstack/react-query";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { API_BASE } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { useChartTokens } from "@/hooks/use-chart-tokens";
import { Card } from "@/components/ui/card";

interface SuccessTierPoint {
  key: string;
  label: string;
  count: number;
  min_sales: number;
  max_sales: number | null;
}

export interface GenreSuccess {
  genre: string;
  games_in_genre: number;
  games_scored: number;
  games_without_reviews: number;
  multiplier: number;
  formula: string;
  method: string;
  source: string;
  tiers: SuccessTierPoint[];
}

async function fetchGenreSuccess(genre: string): Promise<GenreSuccess> {
  const res = await fetch(
    `${API_BASE}/api/v1/dashboard/genre-success?genre=${encodeURIComponent(genre)}`,
  );
  if (!res.ok) throw new Error("genre success fetch failed");
  return res.json();
}

/** Tier → semantic status colour, so the pie reads the same way the
 *  Confirmed/Estimated/Unknown badges elsewhere do. */
function tierColors(tokens: ReturnType<typeof useChartTokens>): Record<string, string> {
  return {
    breakout_hit: tokens.statusGood,
    solid: tokens.series1,
    modest: tokens.statusWarn,
    underperformed: tokens.statusCritical,
  };
}

function salesRange(tier: SuccessTierPoint): string {
  if (tier.max_sales === null) return `${fmtInt(tier.min_sales)}+ est. sales`;
  if (tier.min_sales === 0) return `under ${fmtInt(tier.max_sales)} est. sales`;
  return `${fmtInt(tier.min_sales)}–${fmtInt(tier.max_sales)} est. sales`;
}

export function GenreSuccessPie({
  genre,
  onClose,
}: {
  genre: string;
  onClose: () => void;
}) {
  const tokens = useChartTokens();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["genre-success", genre],
    queryFn: () => fetchGenreSuccess(genre),
  });

  const colors = tierColors(tokens);

  return (
    <Card className="p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium text-ink2">
          Estimated success — {genre}
        </h3>
        <button
          onClick={onClose}
          className="text-xs text-muted hover:text-ink2"
          aria-label="Close genre breakdown"
        >
          Close
        </button>
      </div>

      {isLoading ? (
        <div className="h-56 animate-pulse rounded bg-grid/40" />
      ) : isError || !data ? (
        <p className="py-8 text-center text-sm text-muted">
          Could not load the breakdown for {genre}.
        </p>
      ) : data.games_scored === 0 ? (
        <p className="py-8 text-center text-sm text-muted">
          None of the {fmtInt(data.games_in_genre)} {genre} games has a review
          count yet, so there is nothing to estimate from.
        </p>
      ) : (
        <>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data.tiers.filter((t) => t.count > 0)}
                  dataKey="count"
                  nameKey="label"
                  innerRadius={38}
                  outerRadius={72}
                  paddingAngle={2}
                  stroke={tokens.surface}
                >
                  {data.tiers
                    .filter((t) => t.count > 0)
                    .map((tier) => (
                      <Cell key={tier.key} fill={colors[tier.key] ?? tokens.muted} />
                    ))}
                </Pie>
                <Tooltip
                  formatter={(value, _name, entry) => {
                    const tier = entry?.payload as SuccessTierPoint;
                    return [
                      `${fmtInt(Number(value))} games — ${salesRange(tier)}`,
                      tier.label,
                    ];
                  }}
                  contentStyle={{
                    background: tokens.surface,
                    border: `1px solid ${tokens.grid}`,
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Same spirit as the header's "Steam never exposes wishlists" note:
              say what the number is before someone treats it as a fact. */}
          <p className="mt-2 text-xs leading-relaxed text-muted">
            <span className="font-medium text-ink2">Estimated, not confirmed.</span>{" "}
            Steam publishes no sales figures. These tiers apply the Boxleiter
            method — <code>{data.formula}</code> with multiplier{" "}
            <span className="tabular-nums">{data.multiplier}</span> — to each
            game&apos;s latest review count. The real ratio varies by price,
            genre and age, so treat this as an order of magnitude.{" "}
            <span title={data.source} className="underline decoration-dotted">
              Source
            </span>
            .
          </p>
          <p className="mt-1 text-xs text-muted">
            {fmtInt(data.games_scored)} of {fmtInt(data.games_in_genre)} {genre}{" "}
            games scored;{" "}
            <span title="No review count yet — excluded rather than guessed into a tier">
              {fmtInt(data.games_without_reviews)} excluded for having no reviews
            </span>
            .
          </p>
        </>
      )}
    </Card>
  );
}
