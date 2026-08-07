"use client";

import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchGameStats } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { useChartTokens } from "@/hooks/use-chart-tokens";
import { Card } from "@/components/ui/card";

/** Two measures of different scale → two charts, never a dual axis. */
function SeriesChart({
  title,
  data,
  dataKey,
}: {
  title: string;
  data: { t: string; [k: string]: string | number | null }[];
  dataKey: string;
}) {
  const tokens = useChartTokens();
  return (
    <div>
      <h3 className="mb-1 text-xs font-medium text-ink2">{title}</h3>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ right: 12, top: 4 }}>
            <CartesianGrid stroke={tokens.grid} vertical={false} />
            <XAxis
              dataKey="t"
              tick={{ fill: tokens.muted, fontSize: 10 }}
              stroke={tokens.grid}
            />
            <YAxis
              tick={{ fill: tokens.muted, fontSize: 10 }}
              stroke={tokens.grid}
              tickFormatter={(v: number) => fmtInt(v)}
              width={44}
            />
            <Tooltip
              formatter={(value) => [fmtInt(Number(value)), title]}
              contentStyle={{
                background: tokens.surface,
                border: `1px solid ${tokens.grid}`,
                borderRadius: 6,
                fontSize: 12,
              }}
            />
            <Line
              type="monotone"
              dataKey={dataKey}
              stroke={tokens.series1}
              strokeWidth={2}
              dot={{ r: 2.5 }}
              activeDot={{ r: 4 }}
              connectNulls
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function StatsHistoryChart({ appid }: { appid: number }) {
  const { data } = useQuery({
    queryKey: ["game-stats", appid],
    queryFn: () => fetchGameStats(appid),
  });

  if (!data || data.length < 2) {
    return (
      <Card className="p-5">
        <h2 className="mb-2 text-sm font-medium text-muted">Stats over time</h2>
        <p className="text-sm text-muted">
          Not enough snapshots yet — history builds up as the market collector
          re-runs.
        </p>
      </Card>
    );
  }

  const rows = data.map((point) => ({
    t: new Date(point.captured_at).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
    }),
    reviews: point.total_reviews,
    ccu: point.peak_ccu,
  }));

  return (
    <Card className="p-5">
      <h2 className="mb-3 text-sm font-medium text-muted">Stats over time</h2>
      <div className="grid gap-4 md:grid-cols-2">
        <SeriesChart title="Total reviews" data={rows} dataKey="reviews" />
        <SeriesChart title="Peak CCU" data={rows} dataKey="ccu" />
      </div>
    </Card>
  );
}
