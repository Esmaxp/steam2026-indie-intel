"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { API_BASE } from "@/lib/api";
import { fmtInt, fmtMoneyShort } from "@/lib/format";
import { useChartTokens } from "@/hooks/use-chart-tokens";
import { ChartCard } from "@/components/chart-card";

interface GenreSlice {
  genre: string;
  count: number;
  pct: number;
}

interface RevenueMethod {
  formula: string;
  constants: Record<string, number>;
  calibration_factor: number;
  calibration_sample: number;
  min_reviews: number;
}

interface Distribution {
  tier: string;
  min_revenue: number;
  game_count: number;
  total_revenue_mid: number;
  estimable_total: number;
  catalogue_total: number;
  share_of_estimable: number;
  share_of_catalogue: number;
  sources_used: Record<string, number>;
  median_spread: number | null;
  method: RevenueMethod;
  genres: GenreSlice[];
}

interface RevenueBand {
  label: string;
  min_revenue: number;
  max_revenue: number | null;
  game_count: number;
  pct: number;
  // What the exclusive split throws away: the share earning at least this
  // band's floor. Kept because it is the number genres compare on.
  cumulative_count: number;
  cumulative_pct: number;
  total_revenue_mid: number;
}

interface GenreBreakdown {
  genre: string;
  total_games: number;
  genre_total: number;
  catalogue_total: number;
  method: RevenueMethod;
  bands: RevenueBand[];
}

/** The thresholds, mirroring REVENUE_TIERS in backend/app/api/v1/dashboard.py.
 *  Net revenue — what reaches the developer, not what the storefront takes. */
const TIERS: { label: string; min: number }[] = [
  { label: "All games", min: 0 },
  { label: "$10K+", min: 10_000 },
  { label: "$50K+", min: 50_000 },
  { label: "$100K+", min: 100_000 },
  { label: "$500K+", min: 500_000 },
  { label: "$1M+", min: 1_000_000 },
];

const SIGNAL_LABELS: Record<string, string> = {
  reviews: "review count",
  ccu: "concurrent players",
  followers: "followers",
  disclosed: "developer disclosure",
};

async function fetchDistribution(minRevenue: number): Promise<Distribution> {
  const res = await fetch(
    `${API_BASE}/api/v1/dashboard/genre-revenue-distribution?min_revenue=${minRevenue}`,
  );
  if (!res.ok) throw new Error("genre revenue distribution fetch failed");
  return res.json();
}

async function fetchGenreBreakdown(genre: string): Promise<GenreBreakdown> {
  const res = await fetch(
    `${API_BASE}/api/v1/dashboard/genre-revenue-distribution?genre=${encodeURIComponent(genre)}`,
  );
  if (!res.ok) throw new Error("genre tier breakdown fetch failed");
  return res.json();
}

/** Same walk as the genre-success pie, so the two read as one family. */
function sliceColors(tokens: ReturnType<typeof useChartTokens>): string[] {
  return [
    tokens.series1,
    tokens.series2,
    tokens.statusGood,
    tokens.statusWarn,
    tokens.ink2,
    tokens.statusCritical,
    tokens.muted,
  ];
}

/** Every number here comes from the response — the constants are not repeated
 *  in the frontend. A second copy of a number is a second number to keep
 *  correct, and this one would go stale the day the estimator is calibrated. */
function Explanation({
  heading,
  method,
  children,
}: {
  heading: string;
  method: RevenueMethod;
  children?: React.ReactNode;
}) {
  const c = method.constants;
  return (
    <div className="space-y-2 text-xs leading-relaxed text-muted">
      <p className="font-medium text-ink2">How this is calculated — {heading}</p>
      {children}
      <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-grid/30 p-2 font-mono text-[11px] text-ink2">
        {`copies solves  U = reviews × multiplier(U)   × ${c.early_access} if Early Access
net    = copies × list price × ${c.asp} × ${c.steam_share} × ${c.refunds} × ${c.regional}
       = copies × list price × ${(c.asp * c.net_of_gross).toFixed(3)}`}
      </pre>
      <p>
        The multiplier — sales per public review — is not a constant: the
        published medians run from 20× for games under 1,000 copies to 59× at
        50–100K. They are indexed by copies sold, which is the unknown, so the
        answer is the sales figure that agrees with its own multiplier rather
        than one read off the review count.
      </p>
      <p>
        {c.asp} is the average selling price against list — most units move
        during sales. The rest is Valve&apos;s {((1 - c.steam_share) * 100).toFixed(0)}%
        cut, ~{((1 - c.refunds) * 100).toFixed(0)}% refunds, and regional
        pricing plus VAT already inside the listed price.
      </p>
      <p>
        <span className="font-medium text-ink2">These are estimates, not measurements.</span>{" "}
        No estimate is produced below {method.min_reviews} reviews — a game with
        fewer has a multiplier that swings by a third on a single review, and
        zero reviews times any multiplier would read as a measured failure.
        Each game&apos;s own low–high band is on its detail page.
        {method.calibration_sample > 0
          ? ` Calibrated against ${method.calibration_sample} disclosed figures (×${method.calibration_factor}).`
          : " Nothing has been calibrated against real disclosed sales yet, so the absolute error is unmeasured."}
      </p>
    </div>
  );
}

/** The all-genres view's lead paragraphs, on top of the shared arithmetic. */
function AllGenresExplanation({ data }: { data: Distribution }) {
  return (
    <Explanation heading={data.tier} method={data.method}>
      <p>
        {fmtInt(data.game_count)} games clear this threshold:{" "}
        {(data.share_of_estimable * 100).toFixed(1)}% of the{" "}
        {fmtInt(data.estimable_total)} games we can estimate at all, and{" "}
        {(data.share_of_catalogue * 100).toFixed(1)}% of the{" "}
        {fmtInt(data.catalogue_total)} in the catalogue.
      </p>
      <p>
        Slices are <span className="text-ink2">genre tags, not games</span> — a
        game carrying three genres appears under all three, so the counts add
        up past {fmtInt(data.game_count)} while the percentages still divide
        the tag total.
      </p>
      <p>
        Signals behind this tier:{" "}
        {Object.entries(data.sources_used)
          .map(([name, n]) => `${fmtInt(n)} from ${SIGNAL_LABELS[name] ?? name}`)
          .join(", ") || "none"}
        {data.median_spread !== null
          ? `. Median disagreement between signals: ${(data.median_spread * 100).toFixed(0)}%.`
          : "."}
      </p>
    </Explanation>
  );
}

/** A single genre split into exclusive revenue bands — the view a genre bar
 *  opens. Exclusive rather than cumulative because these are pie slices;
 *  the cumulative share rides along in the tooltip, since that is the number
 *  two genres can actually be compared on. */
function GenreTierView({
  genre,
  palette,
  surface,
  grid,
  onClose,
}: {
  genre: string;
  palette: string[];
  surface: string;
  grid: string;
  onClose: () => void;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["genre-tier-breakdown", genre],
    queryFn: () => fetchGenreBreakdown(genre),
  });

  const title = `${genre} — estimated revenue bands`;
  const closeButton = (
    <button
      onClick={onClose}
      className="shrink-0 text-xs text-muted hover:text-ink2"
      aria-label={`Close ${genre} breakdown`}
    >
      Close
    </button>
  );

  if (isLoading || !data) {
    return (
      <ChartCard title={title} action={closeButton}>
        {isError ? (
          <p className="pt-8 text-center text-sm text-muted">
            Could not load the breakdown for {genre}.
          </p>
        ) : (
          <div className="h-full animate-pulse rounded bg-grid/40" />
        )}
      </ChartCard>
    );
  }

  // No tier selector in this view — every band is on screen — so the corner
  // states the pie's denominator instead of a threshold nobody chose.
  const counter = (
    <div className="flex shrink-0 items-center gap-3 whitespace-nowrap text-xs text-muted">
      <span>
        {fmtInt(data.total_games)} estimable of {fmtInt(data.genre_total)}{" "}
        {genre} games
      </span>
      {closeButton}
    </div>
  );

  if (data.total_games === 0) {
    return (
      <ChartCard title={title} action={counter}>
        <p className="pt-8 text-center text-sm text-muted">
          None of the {fmtInt(data.genre_total)} {genre} games can be estimated
          yet — they have fewer than {data.method.min_reviews} reviews, no
          price, or both.
        </p>
      </ChartCard>
    );
  }

  const slices = data.bands.filter((b) => b.game_count > 0);

  return (
    <ChartCard
      title={title}
      action={counter}
      footer={
        <Explanation heading={genre} method={data.method}>
          <p>
            Slices are <span className="text-ink2">exclusive bands</span>, not
            thresholds: each game sits in exactly one, so they sum to 100% of
            the {fmtInt(data.total_games)} {genre} games that can be estimated
            — not all {fmtInt(data.genre_total)} of them. Using the larger
            number would report a coverage rate dressed up as a success rate.
          </p>
          <p>
            Hovering a slice also shows the cumulative share earning at least
            that band&apos;s floor. That is the figure to compare genres on: a
            band chart shows one genre&apos;s shape, while &quot;
            {(data.bands.find((b) => b.min_revenue === 10000)?.cumulative_pct ?? 0) * 100 > 0
              ? `${((data.bands.find((b) => b.min_revenue === 10000)?.cumulative_pct ?? 0) * 100).toFixed(1)}% of ${genre} games clear $10K`
              : "x% clear $10K"}
            &quot; can be held against any other genre.
          </p>
        </Explanation>
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={slices}
            dataKey="game_count"
            nameKey="label"
            innerRadius={44}
            outerRadius={92}
            paddingAngle={2}
            stroke={surface}
            isAnimationActive={false}
          >
            {slices.map((band) => (
              <Cell
                key={band.label}
                // Indexed by the band's position in the FULL list, so an
                // empty band does not shift every colour after it and break
                // the legend's mapping.
                fill={palette[data.bands.indexOf(band) % palette.length]}
              />
            ))}
          </Pie>
          <Tooltip
            formatter={(value, _name, entry) => {
              const band = entry?.payload as RevenueBand;
              return [
                `${fmtInt(Number(value))} games — ${(band.pct * 100).toFixed(1)}% of ${genre}'s estimable games; ` +
                  `${(band.cumulative_pct * 100).toFixed(1)}% earn ${fmtMoneyShort(band.min_revenue)} or more`,
                band.label,
              ];
            }}
            contentStyle={{
              background: surface,
              border: `1px solid ${grid}`,
              borderRadius: 6,
              fontSize: 12,
              maxWidth: 320,
            }}
          />
          {/* Same legend component as the all-genres pie, so the two views
              read as one card rather than two designs. It replaces the tier
              buttons here: with every band on screen there is nothing left
              for a threshold selector to select. */}
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

export function GenreRevenuePie({
  genre = null,
  onClose,
}: {
  genre?: string | null;
  onClose?: () => void;
}) {
  const tokens = useChartTokens();
  const [tier, setTier] = useState(TIERS[0]);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["genre-revenue-distribution", tier.min],
    queryFn: () => fetchDistribution(tier.min),
    // Keeps the previous pie on screen while the next tier loads, so
    // clicking through the buttons does not flash an empty card.
    placeholderData: (previous) => previous,
    enabled: !genre,
  });

  const palette = sliceColors(tokens);
  const title = "Genre mix by estimated revenue";

  const buttons = (
    <div className="flex flex-wrap gap-1">
      {TIERS.map((t) => (
        <button
          key={t.label}
          onClick={() => setTier(t)}
          aria-pressed={t.min === tier.min}
          className={
            t.min === tier.min
              ? "rounded border border-accent px-2 py-0.5 text-xs text-accent"
              : "rounded border border-grid px-2 py-0.5 text-xs text-muted hover:text-ink2"
          }
        >
          {t.label}
        </button>
      ))}
    </div>
  );

  // One card, two modes: clicking a genre bar swaps this card in place
  // rather than opening a second one beside it.
  if (genre) {
    return (
      <GenreTierView
        genre={genre}
        palette={palette}
        surface={tokens.surface}
        grid={tokens.grid}
        onClose={onClose ?? (() => undefined)}
      />
    );
  }

  const counter = data ? (
    <span className="shrink-0 whitespace-nowrap text-xs text-muted">
      {fmtInt(data.game_count)} games · {fmtMoneyShort(data.total_revenue_mid)} net
    </span>
  ) : null;

  if (isLoading || !data) {
    return (
      <ChartCard title={title} subtitle={buttons} action={counter}>
        {isError ? (
          <p className="pt-8 text-center text-sm text-muted">
            Could not load the revenue distribution.
          </p>
        ) : (
          <div className="h-full animate-pulse rounded bg-grid/40" />
        )}
      </ChartCard>
    );
  }

  if (data.game_count === 0 || data.genres.length === 0) {
    return (
      <ChartCard
        title={title}
        subtitle={buttons}
        action={counter}
        footer={<AllGenresExplanation data={data} />}
      >
        <p className="pt-8 text-center text-sm text-muted">
          No games meet this threshold.
        </p>
      </ChartCard>
    );
  }

  return (
    <ChartCard
      title={title}
      subtitle={buttons}
      action={counter}
      footer={<AllGenresExplanation data={data} />}
    >
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data.genres}
            dataKey="count"
            nameKey="genre"
            innerRadius={44}
            outerRadius={92}
            paddingAngle={2}
            stroke={tokens.surface}
            isAnimationActive={false}
          >
            {data.genres.map((slice, i) => (
              <Cell key={slice.genre} fill={palette[i % palette.length]} />
            ))}
          </Pie>
          <Tooltip
            formatter={(value, _name, entry) => {
              const slice = entry?.payload as GenreSlice;
              return [
                `${fmtInt(Number(value))} games — ${(slice.pct * 100).toFixed(1)}% of genre tags`,
                slice.genre,
              ];
            }}
            contentStyle={{
              background: tokens.surface,
              border: `1px solid ${tokens.grid}`,
              borderRadius: 6,
              fontSize: 12,
              maxWidth: 320,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
