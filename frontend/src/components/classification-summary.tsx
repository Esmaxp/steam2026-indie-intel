"use client";

import { useQuery } from "@tanstack/react-query";
import { API_BASE } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { ChartCard } from "@/components/chart-card";

interface ClassificationRow {
  label: string;
  count: number;
  share: number;
  released_count: number;
  upcoming_count: number;
  total_count: number;
  released_share: number;
  upcoming_share: number;
  highlight: boolean;
  by_confidence: Record<string, number>;
}

interface ClassificationSummary {
  total: number;
  released_total: number;
  upcoming_total: number;
  rows: ClassificationRow[];
}

async function fetchSummary(): Promise<ClassificationSummary> {
  const res = await fetch(`${API_BASE}/api/v1/dashboard/classification-summary`);
  if (!res.ok) throw new Error("classification summary fetch failed");
  return res.json();
}

/** Same wording as the Classification filter, so a row here and the filter
 *  that selects it read identically. */
const ROW_LABEL: Record<string, string> = {
  HIGH_EFFORT_HIGH_TRACTION: "Serious & found an audience",
  HIGH_EFFORT_LOW_TRACTION: "Serious but overlooked",
  LOW_EFFORT_HIGH_TRACTION: "Low effort, got lucky",
  LOW_EFFORT_LOW_TRACTION: "Low effort, no traction",
  INSUFFICIENT_DATA: "Not enough data yet",
};

export function ClassificationSummaryCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["classification-summary"],
    queryFn: fetchSummary,
  });

  const title = "Effort × traction";

  if (isLoading) {
    return (
      <ChartCard title={title}>
        <div className="h-full animate-pulse rounded bg-grid/40" />
      </ChartCard>
    );
  }
  if (isError || !data) {
    return (
      <ChartCard title={title}>
        <p className="pt-8 text-center text-sm text-muted">
          Could not load the classification breakdown.
        </p>
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title={title}
      subtitle={
        <>
          Every game in the catalogue, split by how much production effort its
          store page evidences against whether players found it.
        </>
      }
      footer={
        <p className="text-xs leading-relaxed text-muted">
          &quot;Serious but overlooked&quot; is the group worth digging through:
          real production effort that review counts alone would bury. Games too
          new to judge (under 90 days) or with no store data are counted as
          &quot;not enough data yet&quot; rather than as failures. Released and
          upcoming use the same flag as the Released / Upcoming toggle, so a
          row matches what the Classification filter returns for it.
        </p>
      }
    >
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-grid text-xs text-muted">
            <th className="pb-1 text-left font-normal">Group</th>
            <th className="pb-1 text-right font-normal">Released</th>
            <th className="pb-1 text-right font-normal">Upcoming</th>
            <th className="pb-1 text-right font-normal">Total</th>
            <th className="pb-1 text-right font-normal">Share</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr
              key={row.label}
              className="border-b border-grid/60 last:border-0"
              title={
                Object.keys(row.by_confidence).length
                  ? `Confidence: ${Object.entries(row.by_confidence)
                      .map(([level, n]) => `${level} ${fmtInt(n)}`)
                      .join(", ")}`
                  : undefined
              }
            >
              <td className="py-2 pr-2 text-ink2">{ROW_LABEL[row.label] ?? row.label}</td>
              <td
                className="w-20 py-2 text-right tabular-nums text-ink2"
                title={`${(row.released_share * 100).toFixed(1)}% of released games`}
              >
                {fmtInt(row.released_count)}
              </td>
              <td
                className="w-20 py-2 text-right tabular-nums text-ink2"
                title={`${(row.upcoming_share * 100).toFixed(1)}% of upcoming games`}
              >
                {fmtInt(row.upcoming_count)}
              </td>
              <td className="w-20 py-2 text-right tabular-nums text-ink2">
                {fmtInt(row.total_count)}
              </td>
              <td className="w-16 py-2 text-right tabular-nums text-ink2">
                {(row.share * 100).toFixed(1)}%
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-grid text-xs text-muted">
            <td className="pt-2">All groups</td>
            <td className="pt-2 text-right tabular-nums">{fmtInt(data.released_total)}</td>
            <td className="pt-2 text-right tabular-nums">{fmtInt(data.upcoming_total)}</td>
            <td className="pt-2 text-right tabular-nums">{fmtInt(data.total)}</td>
            <td className="pt-2 text-right tabular-nums">100.0%</td>
          </tr>
        </tfoot>
      </table>
    </ChartCard>
  );
}
