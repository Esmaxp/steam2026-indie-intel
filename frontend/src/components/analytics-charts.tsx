"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { API_BASE } from "@/lib/api";
import { fmtInt, labelFor } from "@/lib/format";
import { useChartTokens } from "@/hooks/use-chart-tokens";
import { Card } from "@/components/ui/card";
import { ChartCard } from "@/components/chart-card";
import { ClassificationSummaryCard } from "@/components/classification-summary";
import { GenreRevenuePie } from "@/components/genre-revenue-pie";

interface MonthPoint {
  month: number;
  released: number;
  upcoming: number;
}
interface BreakdownPoint {
  key: string;
  count: number;
}
interface ChartsOut {
  releases_by_month: MonthPoint[];
  by_dimension: BreakdownPoint[];
  by_engine: BreakdownPoint[];
  by_graphics_style: BreakdownPoint[];
  top_genres: BreakdownPoint[];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

async function fetchCharts(): Promise<ChartsOut> {
  const res = await fetch(`${API_BASE}/api/v1/dashboard/charts`);
  if (!res.ok) throw new Error("charts fetch failed");
  return res.json();
}

function tooltipStyle(tokens: ReturnType<typeof useChartTokens>) {
  return {
    background: tokens.surface,
    border: `1px solid ${tokens.grid}`,
    borderRadius: 6,
    fontSize: 12,
  } as const;
}

/** Horizontal single-measure breakdown: one series → one hue, no legend.
 *  The "unknown" bucket is muted gray + label (a status, not an identity).
 *  Pass onSelect to make the bars clickable (used by Top genres). */
function SimpleBreakdown({
  data,
  onSelect,
  selected,
}: {
  data: BreakdownPoint[];
  onSelect?: (key: string) => void;
  selected?: string | null;
}) {
  const tokens = useChartTokens();
  const rows = data.map((d) => ({
    ...d,
    label: labelFor(d.key),
    fill:
      d.key === "unknown"
        ? tokens.muted
        : selected && d.key !== selected
          ? tokens.series1
          : selected === d.key
            ? tokens.series2
            : tokens.series1,
  }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 24 }}>
        <CartesianGrid stroke={tokens.grid} horizontal={false} />
        <XAxis
          type="number"
          tick={{ fill: tokens.muted, fontSize: 11 }}
          stroke={tokens.grid}
          tickFormatter={(v: number) => fmtInt(v)}
        />
        <YAxis
          type="category"
          dataKey="label"
          width={92}
          tick={{ fill: tokens.ink2, fontSize: 11 }}
          stroke={tokens.grid}
        />
        <Tooltip
          formatter={(value) => [fmtInt(Number(value)), "Games"]}
          contentStyle={tooltipStyle(tokens)}
          cursor={{ fill: tokens.grid, opacity: 0.3 }}
        />
        <Bar
          dataKey="count"
          barSize={14}
          radius={[0, 4, 4, 0]}
          // recharts hands the bar's own datum, but nests the original row
          // under `payload` in some versions — read both.
          onClick={
            onSelect
              ? (entry: { key?: string; payload?: { key?: string } }) => {
                  const key = entry?.payload?.key ?? entry?.key;
                  if (key) onSelect(String(key));
                }
              : undefined
          }
          cursor={onSelect ? "pointer" : undefined}
        >
          {rows.map((row, i) => (
            <Cell key={i} fill={row.fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function AnalyticsCharts() {
  const tokens = useChartTokens();
  const [genre, setGenre] = useState<string | null>(null);
  const { data, isLoading } = useQuery({ queryKey: ["charts"], queryFn: fetchCharts });

  if (isLoading || !data) {
    return (
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Card key={i} className="h-72 animate-pulse" />
        ))}
      </div>
    );
  }

  const monthly = data.releases_by_month.map((p) => ({
    ...p,
    label: MONTHS[p.month - 1] ?? String(p.month),
  }));

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      <ChartCard title="2026 releases by month">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={monthly} margin={{ right: 8 }}>
            <CartesianGrid stroke={tokens.grid} vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: tokens.muted, fontSize: 11 }}
              stroke={tokens.grid}
            />
            <YAxis
              tick={{ fill: tokens.muted, fontSize: 11 }}
              stroke={tokens.grid}
              tickFormatter={(v: number) => fmtInt(v)}
            />
            <Tooltip
              formatter={(value, name) => [
                fmtInt(Number(value)),
                name === "released" ? "Released" : "Upcoming",
              ]}
              contentStyle={tooltipStyle(tokens)}
              cursor={{ fill: tokens.grid, opacity: 0.3 }}
            />
            <Legend
              formatter={(value: string) =>
                value === "released" ? "Released" : "Upcoming"
              }
              wrapperStyle={{ fontSize: 12 }}
            />
            <Bar dataKey="released" stackId="m" fill={tokens.series1} barSize={18} />
            <Bar
              dataKey="upcoming"
              stackId="m"
              fill={tokens.series2}
              barSize={18}
              radius={[4, 4, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <ChartCard title="Top genres (click a bar for its revenue breakdown)">
        <SimpleBreakdown
          data={data.top_genres}
          onSelect={(key) => setGenre((current) => (current === key ? null : key))}
          selected={genre}
        />
      </ChartCard>
      {/* One card for this concern, two modes: the all-genres pie until a
          genre bar is clicked, then that genre across every tier. */}
      <GenreRevenuePie genre={genre} onClose={() => setGenre(null)} />
      <ClassificationSummaryCard />
      <ChartCard title="Engine (Unknown = no public signal)">
        <SimpleBreakdown data={data.by_engine} />
      </ChartCard>
      <ChartCard title="Dimension">
        <SimpleBreakdown data={data.by_dimension} />
      </ChartCard>
      <ChartCard title="Graphics style">
        <SimpleBreakdown data={data.by_graphics_style} />
      </ChartCard>
    </div>
  );
}
