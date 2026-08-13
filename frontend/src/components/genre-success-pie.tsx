"use client";

import { useQuery } from "@tanstack/react-query";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { API_BASE } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { useChartTokens } from "@/hooks/use-chart-tokens";
import { Card } from "@/components/ui/card";

interface SuccessBandPoint {
  key: string;
  label: string;
  count: number;
  share: number;
  baseline_share: number;
  min_percentile: number;
}

export interface GenreSuccess {
  genre: string;
  games_in_genre: number;
  games_scored: number;
  games_excluded_unreleased: number;
  games_excluded_no_reviews: number;
  measure: string;
  cohort: string;
  method: string;
  notes: string;
  bands: SuccessBandPoint[];
}

async function fetchGenreSuccess(genre: string): Promise<GenreSuccess> {
  const res = await fetch(
    `${API_BASE}/api/v1/dashboard/genre-success?genre=${encodeURIComponent(genre)}`,
  );
  if (!res.ok) throw new Error("genre success fetch failed");
  return res.json();
}

/** Best band → best status colour, so the pie reads top-to-bottom the way the
 *  Confirmed/Estimated/Unknown badges elsewhere do. */
function bandColors(tokens: ReturnType<typeof useChartTokens>): Record<string, string> {
  return {
    top_1: tokens.statusGood,
    top_10: tokens.series1,
    top_25: tokens.series2,
    upper_half: tokens.ink2,
    lower_half: tokens.muted,
  };
}

/** The one sentence worth reading: how this genre's top decile compares with
 *  what an average genre would show. Null when the band is empty — no claim. */
function headline(data: GenreSuccess): string | null {
  const band = data.bands.find((b) => b.key === "top_10");
  if (!band || band.count === 0 || !band.baseline_share) return null;
  const ratio = band.share / band.baseline_share;
  const pct = (band.share * 100).toFixed(1);
  if (ratio >= 1.15)
    return `${pct}% of ranked ${data.genre} games land in the top 10% — ${ratio.toFixed(1)}× the catalogue average.`;
  if (ratio <= 0.85)
    return `${pct}% of ranked ${data.genre} games land in the top 10% — ${ratio.toFixed(1)}× the catalogue average, below par.`;
  return `${pct}% of ranked ${data.genre} games land in the top 10% — about the catalogue average.`;
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

  const colors = bandColors(tokens);
  const line = data ? headline(data) : null;

  return (
    <Card className="p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="text-sm font-medium text-ink2">
          {genre} — standing among 2026 indies
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
          None of the {fmtInt(data.games_in_genre)} {genre} games can be ranked
          yet — they are unreleased or have no reviews.
        </p>
      ) : (
        <>
          {line ? <p className="mb-1 text-sm text-ink">{line}</p> : null}
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data.bands.filter((b) => b.count > 0)}
                  dataKey="count"
                  nameKey="label"
                  innerRadius={38}
                  outerRadius={72}
                  paddingAngle={2}
                  stroke={tokens.surface}
                >
                  {data.bands
                    .filter((b) => b.count > 0)
                    .map((band) => (
                      <Cell key={band.key} fill={colors[band.key] ?? tokens.muted} />
                    ))}
                </Pie>
                <Tooltip
                  formatter={(value, _name, entry) => {
                    const band = entry?.payload as SuccessBandPoint;
                    return [
                      `${fmtInt(Number(value))} games — ${(band.share * 100).toFixed(1)}% of ranked (average genre: ${(band.baseline_share * 100).toFixed(0)}%)`,
                      band.label,
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
              say exactly what the number is, and what it leaves out. */}
          <p className="mt-2 text-xs leading-relaxed text-muted">
            <span className="font-medium text-ink2">Measured, not estimated.</span>{" "}
            Steam publishes no sales figures, so games are ranked by their
            published review count against other 2026 indies released the{" "}
            <span title="A game out for three weeks has had three weeks to collect reviews — comparing it against January releases would bury it for no reason.">
              same month
            </span>
            . No sales number is derived, so no multiplier is involved.
          </p>
          <p className="mt-1 text-xs text-muted">
            {fmtInt(data.games_scored)} of {fmtInt(data.games_in_genre)} {genre}{" "}
            games ranked; {fmtInt(data.games_excluded_unreleased)} unreleased and{" "}
            {fmtInt(data.games_excluded_no_reviews)} with no reviews yet are left
            out rather than placed in a band.
          </p>
        </>
      )}
    </Card>
  );
}
