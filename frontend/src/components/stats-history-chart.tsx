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
import { fetchGameFollowers, fetchGameRankHistory, fetchGameStats } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { useChartTokens } from "@/hooks/use-chart-tokens";
import { Card } from "@/components/ui/card";

/** Two measures of different scale → two charts, never a dual axis. */
function SeriesChart({
  title,
  data,
  dataKey,
  subtitle,
  reversed = false,
  formatValue = fmtInt,
}: {
  title: string;
  data: { t: string; [k: string]: string | number | null }[];
  dataKey: string;
  subtitle?: string;
  /** Rank charts invert the axis so position 1 sits at the top. */
  reversed?: boolean;
  formatValue?: (value: number) => string;
}) {
  const tokens = useChartTokens();
  return (
    <div>
      <h3 className="mb-1 text-xs font-medium text-ink2">{title}</h3>
      {subtitle ? <p className="mb-1 text-[10px] text-muted">{subtitle}</p> : null}
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
              tickFormatter={formatValue}
              width={44}
              reversed={reversed}
              domain={reversed ? [1, "dataMax"] : undefined}
            />
            <Tooltip
              formatter={(value) => [formatValue(Number(value)), title]}
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

const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });

export function StatsHistoryChart({ appid }: { appid: number }) {
  const { data } = useQuery({
    queryKey: ["game-stats", appid],
    queryFn: () => fetchGameStats(appid),
  });
  const { data: followers } = useQuery({
    queryKey: ["game-followers", appid],
    queryFn: () => fetchGameFollowers(appid),
  });
  const { data: ranks } = useQuery({
    queryKey: ["game-rank-history", appid],
    queryFn: () => fetchGameRankHistory(appid),
  });

  const statRows = (data ?? []).map((point) => ({
    t: shortDate(point.captured_at),
    reviews: point.total_reviews,
    ccu: point.peak_ccu,
  }));
  const followerRows = (followers ?? []).map((point) => ({
    t: shortDate(point.captured_at),
    followers: point.followers,
  }));
  const rankRows = (ranks ?? []).map((point) => ({
    t: shortDate(point.swept_at),
    rank: point.rank,
  }));

  // Each series needs two points to be a line. They fill up on different
  // cadences, so each chart appears independently rather than gating the
  // whole card on the slowest one.
  const hasStats = statRows.length >= 2;
  const hasFollowers = followerRows.length >= 2;
  const hasRanks = rankRows.length >= 2;

  if (!hasStats && !hasFollowers && !hasRanks) {
    return (
      <Card className="p-5">
        <h2 className="mb-2 text-sm font-medium text-muted">Signals over time</h2>
        <p className="text-sm text-muted">
          Not enough snapshots yet — history builds up as the collectors re-run.
        </p>
      </Card>
    );
  }

  return (
    <Card className="p-5">
      <h2 className="mb-3 text-sm font-medium text-muted">Signals over time</h2>
      <div className="grid gap-4 md:grid-cols-2">
        {hasFollowers ? (
          <SeriesChart
            title="Followers"
            subtitle="Steam community-hub members — measured"
            data={followerRows}
            dataKey="followers"
          />
        ) : null}
        {hasRanks ? (
          <SeriesChart
            title="Wishlist rank"
            subtitle="Valve Top Wishlists position — an order, not a count"
            data={rankRows}
            dataKey="rank"
            reversed
            formatValue={(v) => `#${fmtInt(v)}`}
          />
        ) : null}
        {hasStats ? (
          <>
            <SeriesChart title="Total reviews" data={statRows} dataKey="reviews" />
            <SeriesChart
              title="Peak CCU"
              subtitle="Source: steamcharts.com (third party)"
              data={statRows}
              dataKey="ccu"
            />
          </>
        ) : null}
      </div>
    </Card>
  );
}
