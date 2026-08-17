"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, SlidersHorizontal } from "lucide-react";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { API_BASE } from "@/lib/api";
import { fmtInt, fmtMoneyShort } from "@/lib/format";
import { tooltipStyles, useChartTokens } from "@/hooks/use-chart-tokens";
import { ChartCard } from "@/components/chart-card";
import {
  DEFAULT_FLOORS,
  RevenueBandEditor,
  loadFloors,
} from "@/components/revenue-band-editor";

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
  /** Released games covered by the bands — including those with no estimate. */
  total_games: number;
  genre_total: number;
  catalogue_total: number;
  /** Of total_games, how many carry a computed figure. */
  estimated_games: number;
  /** In the bottom band because they fall under the estimator's review floor,
   *  not because a figure was computed for them. */
  unestimated_in_bottom: number;
  /** Free-to-play, left out of the bands: their money is in items this
   *  project never observes. */
  free_not_estimated: number;
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

/** `null` asks for the whole estimable catalogue rather than one genre — the
 *  baseline a genre's bands are read against. */
async function fetchGenreBreakdown(
  genre: string | null,
  floors: number[],
): Promise<GenreBreakdown> {
  const query = genre ? `genre=${encodeURIComponent(genre)}` : "bands=true";
  const custom = `&floors=${floors.join(",")}`;
  const res = await fetch(
    `${API_BASE}/api/v1/dashboard/genre-revenue-distribution?${query}${custom}`,
  );
  if (!res.ok) throw new Error("revenue band breakdown fetch failed");
  return res.json();
}

/** The three views this card can show. A genre drill-down used to be a dead
 *  end with only a Close button, so returning to either top-level view meant
 *  leaving the card first; the picker keeps all three one click apart. */
type View = "bands" | "mix" | "genre";

function ViewSelect({
  view,
  genre,
  onChange,
}: {
  view: View;
  genre: string | null;
  onChange: (next: View) => void;
}) {
  return (
    <select
      value={view}
      onChange={(e) => onChange(e.target.value as View)}
      aria-label="Revenue view"
      className="max-w-full cursor-pointer rounded border border-hairline bg-surface px-1.5 py-0.5 text-sm font-medium text-ink2 hover:text-ink"
    >
      <option value="bands">All games — revenue bands</option>
      <option value="mix">Genre mix by estimated revenue</option>
      {/* Only offered while a genre is open: it is the view you are in, and
          an option that selects nothing would be worse than no option. */}
      {genre ? <option value="genre">{genre} — revenue bands</option> : null}
    </select>
  );
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
  // Collapsed by default. It is the method behind the chart, worth reading
  // once and worth finding again — but it runs to several paragraphs, and
  // open by default it pushed the chart it explains off the screen.
  //
  // <details> rather than useState: the disclosure triangle, keyboard
  // handling and open/closed semantics come from the element, and this needs
  // none of the control that a state hook would buy.
  return (
    <details className="group space-y-2 text-xs leading-relaxed text-muted">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-medium text-ink2 hover:text-ink">
        <ChevronRight
          size={13}
          aria-hidden
          className="transition-transform group-open:rotate-90"
        />
        How this is calculated — {heading}
      </summary>
      <div className="space-y-2 pt-1">
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
    </details>
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
/** Revenue bands as a pie — for one genre, or for the whole estimable
 *  catalogue when `genre` is null. One component for both, mirroring the
 *  single endpoint that serves them. */
function GenreTierView({
  genre,
  palette,
  onClose,
  selector,
  floors,
  onEditBands,
}: {
  genre: string | null;
  palette: string[];
  onClose: () => void;
  selector: React.ReactNode;
  floors: number[];
  onEditBands: () => void;
}) {
  // Which bands are hidden, by label. Labels rather than indices: editing the
  // band set renames and renumbers everything, and an index would then hide
  // whichever band happened to inherit the position.
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  // Reads the tokens rather than taking two of them as props: the tooltip
  // needs a foreground colour as well, and threading a third through would
  // just move the problem.
  const tokens = useChartTokens();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["genre-tier-breakdown", genre ?? "__all__", floors.join(",")],
    queryFn: () => fetchGenreBreakdown(genre, floors),
  });

  const title = selector;
  // Nothing to close out of on the all-games view — the picker is the way
  // back, and a Close that returned somewhere arbitrary would be a guess.
  const closeButton = genre ? (
    <button
      onClick={onClose}
      className="shrink-0 text-xs text-muted hover:text-ink2"
      aria-label={`Close ${genre} breakdown`}
    >
      Close
    </button>
  ) : null;

  if (isLoading || !data) {
    return (
      <ChartCard title={title} action={closeButton}>
        {isError ? (
          <p className="pt-8 text-center text-sm text-muted">
            Could not load the breakdown for {genre ?? "all games"}.
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
        {fmtInt(data.total_games)} released · {fmtInt(data.estimated_games)}{" "}
        estimated
      </span>
      {closeButton}
    </div>
  );

  if (data.total_games === 0) {
    return (
      <ChartCard title={title} action={counter}>
        <p className="pt-8 text-center text-sm text-muted">
          None of the {fmtInt(data.genre_total)} {genre ?? "catalogue"} games can be estimated
          yet — they have fewer than {data.method.min_reviews} reviews, no
          price, or both.
        </p>
      </ChartCard>
    );
  }

  const populated = data.bands.filter((b) => b.game_count > 0);
  const slices = populated.filter((b) => !hidden.has(b.label));
  const toggle = (label: string) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      // Refuse to hide the last visible band — an empty pie is not a view of
      // anything, and the way back would be a legend with nothing in it.
      else if (slices.length > 1) next.add(label);
      return next;
    });

  return (
    <ChartCard
      title={title}
      action={counter}
      footer={
        <>
          <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {populated.map((band) => {
              const off = hidden.has(band.label);
              return (
                <button
                  key={band.label}
                  onClick={() => toggle(band.label)}
                  aria-pressed={!off}
                  title={
                    off
                      ? `Show ${band.label}`
                      : `Hide ${band.label} — ${fmtInt(band.game_count)} games`
                  }
                  className={`flex items-center gap-1.5 ${
                    off ? "text-muted line-through opacity-60" : "text-ink2"
                  } hover:text-ink`}
                >
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{
                      background: off
                        ? tokens.muted
                        : palette[data.bands.indexOf(band) % palette.length],
                    }}
                  />
                  {band.label}
                </button>
              );
            })}
            <button
              onClick={onEditBands}
              className="ml-auto flex items-center gap-1 text-muted hover:text-ink"
            >
              <SlidersHorizontal size={12} aria-hidden /> Edit bands
            </button>
          </div>
          {hidden.size > 0 ? (
            <p className="mb-2 text-xs text-muted">
              {/* The wedges re-fill the circle when a band is hidden, so the
                  visual is relative to what is shown while every number
                  quoted stays relative to the whole. Saying so is cheaper
                  than a chart that silently changes what 100% means. */}
              {hidden.size} band{hidden.size > 1 ? "s" : ""} hidden — wedges are
              drawn across the bands shown, while the percentages below and in
              the tooltip stay out of all {fmtInt(data.total_games)} released
              games.
            </p>
          ) : null}
        <Explanation heading={data.genre} method={data.method}>
          <p>
            Slices are <span className="text-ink2">exclusive bands</span>, not
            thresholds: each game sits in exactly one, so they sum to 100% of
            the {fmtInt(data.total_games)} released{" "}
            {genre ? `${genre} ` : ""}games.
          </p>
          <p>
            <span className="text-ink2">
              {fmtInt(data.unestimated_in_bottom)} of them are in the bottom
              band without a computed figure.
            </span>{" "}
            Nothing is estimated below {data.method.min_reviews} reviews, but a
            paid game with fewer than that has sold a few hundred copies at the
            outside, so under $10K is where it belongs. Counting only the{" "}
            {fmtInt(data.estimated_games)} games that do carry a figure would
            drop the smallest games in the catalogue and flatter the shape of
            the whole distribution.
          </p>
          {data.free_not_estimated > 0 ? (
            <p>
              {fmtInt(data.free_not_estimated)} free-to-play{" "}
              {genre ? `${genre} ` : ""}games are left out entirely rather than
              counted as zero. They earn through items this project does not
              observe, so placing them in any band — including the bottom one —
              would be a claim about them rather than a gap in the data.
            </p>
          ) : null}
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
        </>
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
            stroke={tokens.surface}
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
            {...tooltipStyles(tokens)}
            // Wider than the shared default: this tooltip carries a sentence,
            // not a number.
            contentStyle={{ ...tooltipStyles(tokens).contentStyle, maxWidth: 320 }}
          />
          {/* Same legend component as the all-genres pie, so the two views
              read as one card rather than two designs. It replaces the tier
              buttons here: with every band on screen there is nothing left
              for a threshold selector to select. */}
          {/* Recharts' own legend only lists what it was given, so a hidden
              band would disappear along with the control that unhides it. */}
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
  // Which top-level view to show once no genre is open. Held here rather than
  // in the parent because the parent owns only the genre, which is what the
  // Top-genres bars set.
  // Bands first: it is the shape of the market — 86% of releases under $10K —
  // where the genre mix answers the narrower question of who is in the top
  // slice, and only makes sense once the reader knows how small that slice is.
  const [topLevel, setTopLevel] = useState<"bands" | "mix">("bands");
  // Read once on mount, not during render: localStorage does not exist on the
  // server, and reading it while rendering would make the markup differ.
  const [floors, setFloors] = useState<number[]>(DEFAULT_FLOORS);
  const [editing, setEditing] = useState(false);
  useEffect(() => setFloors(loadFloors()), []);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["genre-revenue-distribution", tier.min],
    queryFn: () => fetchDistribution(tier.min),
    // Keeps the previous pie on screen while the next tier loads, so
    // clicking through the buttons does not flash an empty card.
    placeholderData: (previous) => previous,
    enabled: !genre && topLevel === "mix",
  });

  const palette = sliceColors(tokens);
  const view: View = genre ? "genre" : topLevel;

  const selector = (
    <ViewSelect
      view={view}
      genre={genre}
      onChange={(next) => {
        // Leaving a genre means clearing it in the parent as well, or the
        // drill-down would render straight over whichever view was picked.
        if (next !== "genre") {
          setTopLevel(next);
          if (genre) onClose?.();
        }
      }}
    />
  );
  const title = selector;

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
  if (genre || topLevel === "bands") {
    return (
      <>
        <GenreTierView
          genre={genre}
          palette={palette}
          onClose={onClose ?? (() => undefined)}
          selector={selector}
          floors={floors}
          onEditBands={() => setEditing(true)}
        />
        {editing ? (
          <RevenueBandEditor
            floors={floors}
            onApply={setFloors}
            onClose={() => setEditing(false)}
          />
        ) : null}
      </>
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
            {...tooltipStyles(tokens)}
            contentStyle={{
              ...tooltipStyles(tokens).contentStyle,
              maxWidth: 320,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
        </PieChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
