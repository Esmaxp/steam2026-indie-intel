"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { fetchFilterOptions } from "@/lib/api";
import { labelFor } from "@/lib/format";
import { useFilterParams } from "@/hooks/use-filter-params";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/button";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function DebouncedInput({
  paramKey,
  placeholder,
  className,
}: {
  paramKey: string;
  placeholder: string;
  className?: string;
}) {
  const { searchParams, setParams } = useFilterParams();
  const urlValue = searchParams.get(paramKey) ?? "";
  const [value, setValue] = useState(urlValue);

  useEffect(() => setValue(urlValue), [urlValue]);
  useEffect(() => {
    const handle = setTimeout(() => {
      if (value !== urlValue) setParams({ [paramKey]: value || null });
    }, 400);
    return () => clearTimeout(handle);
  }, [value, urlValue, paramKey, setParams]);

  return (
    <Input
      value={value}
      onChange={(e) => setValue(e.target.value)}
      placeholder={placeholder}
      className={className}
    />
  );
}

function ParamSelect({
  paramKey,
  label,
  options,
  optionLabels,
}: {
  paramKey: string;
  label: string;
  options: (string | number)[];
  optionLabels?: (v: string | number) => string;
}) {
  const { searchParams, setParams } = useFilterParams();
  return (
    <Select
      value={searchParams.get(paramKey) ?? ""}
      onChange={(e) => setParams({ [paramKey]: e.target.value || null })}
      aria-label={label}
    >
      <option value="">{label}</option>
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {optionLabels ? optionLabels(opt) : labelFor(String(opt))}
        </option>
      ))}
    </Select>
  );
}

const RELEASE_STATUS_OPTIONS = [
  { value: "", label: "All" },
  { value: "released", label: "Released" },
  { value: "upcoming", label: "Upcoming (2026)" },
] as const;

/** 3-way segmented control bound to the release_status query param. */
function ReleaseStatusControl() {
  const { searchParams, setParams } = useFilterParams();
  const current = searchParams.get("release_status") ?? "";
  return (
    <div
      className="inline-flex overflow-hidden rounded-md border border-hairline"
      role="group"
      aria-label="Release status"
    >
      {RELEASE_STATUS_OPTIONS.map((option) => (
        <button
          key={option.value}
          onClick={() => setParams({ release_status: option.value || null })}
          aria-pressed={current === option.value}
          className={`h-9 px-3 text-sm transition-colors ${
            current === option.value
              ? "bg-accent/10 font-medium text-accent"
              : "bg-surface text-ink2 hover:bg-grid/40"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** include_flagged defaults to true server-side; the toggle sets it false. */
function HideFlaggedToggle() {
  const { searchParams, setParams } = useFilterParams();
  const active = searchParams.get("include_flagged") === "false";
  return (
    <Button
      onClick={() => setParams({ include_flagged: active ? null : "false" })}
      className={active ? "border-accent bg-accent/10 text-accent" : ""}
      aria-pressed={active}
      title="Hide games flagged for mass-publishing patterns (5+ releases by the same company within 30 days)"
    >
      Hide flagged
    </Button>
  );
}

/** include_limited defaults to true server-side; the toggle sets it false. */
function HideLimitedToggle() {
  const { searchParams, setParams } = useFilterParams();
  const active = searchParams.get("include_limited") === "false";
  return (
    <Button
      onClick={() => setParams({ include_limited: active ? null : "false" })}
      className={active ? "border-accent bg-accent/10 text-accent" : ""}
      aria-pressed={active}
      title="Hide games whose Steam profile features are still restricted — Valve's own signal that a game has not cleared its sales and engagement bar"
    >
      Hide Steam-limited
    </Button>
  );
}

function ParamToggle({ paramKey, label }: { paramKey: string; label: string }) {
  const { searchParams, setParams } = useFilterParams();
  const active = searchParams.get(paramKey) === "true";
  return (
    <Button
      onClick={() => setParams({ [paramKey]: active ? null : "true" })}
      className={active ? "border-accent bg-accent/10 text-accent" : ""}
      aria-pressed={active}
    >
      {label}
    </Button>
  );
}

export function FiltersBar() {
  const { searchParams, setParams } = useFilterParams();
  const { data: options } = useQuery({
    queryKey: ["filter-options"],
    queryFn: fetchFilterOptions,
  });

  const hasFilters = [...searchParams.keys()].some(
    (key) => !["page", "page_size", "sort"].includes(key),
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <DebouncedInput paramKey="q" placeholder="Search games…" className="w-56" />
        <DebouncedInput paramKey="developer" placeholder="Developer" className="w-40" />
        <DebouncedInput paramKey="publisher" placeholder="Publisher" className="w-40" />
        <ParamSelect paramKey="genre" label="Genre" options={options?.genres ?? []} />
        <ParamSelect paramKey="tag" label="Tag" options={options?.tags ?? []} />
        <ParamSelect paramKey="engine" label="Engine" options={options?.engines ?? []} />
        <ParamSelect
          paramKey="dimension"
          label="2D / 3D"
          options={options?.dimensions ?? []}
        />
        <ParamSelect
          paramKey="graphics_style"
          label="Graphics"
          options={options?.graphics_styles ?? []}
        />
        <ParamSelect
          paramKey="release_month"
          label="Release month"
          options={options?.release_months ?? []}
          optionLabels={(m) => MONTH_NAMES[Number(m) - 1] ?? String(m)}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <ParamToggle paramKey="demo_available" label="Has demo" />
        <ParamToggle paramKey="has_website" label="Has website" />
        <ParamToggle paramKey="has_videos" label="Has videos" />
        <ParamToggle paramKey="next_fest" label="Next Fest" />
        <ReleaseStatusControl />
        <ParamToggle paramKey="early_access" label="Early Access" />
        {/* One question: did somebody actually build this? Reads only
            production evidence — screenshots, localisation, achievements, a
            real description — and nothing about marketing, price or release
            status. That last part matters: the older combined effort score
            put 60% of its weight on commercial decisions, so a game that was
            made and then never marketed scored the same as a bulk upload,
            and free games could barely clear the bar at all.

            It replaces two controls that used to sit here (an effort ×
            traction crossing and a "Developer effort" tier), both built on
            that confounded score. The traction axis is a separate question
            and is not what this filter is for. */}
        <ParamSelect
          paramKey="craft_class"
          label="Craft level"
          options={["serious", "mixed", "hobby", "unknown"]}
          optionLabels={(v) =>
            v === "serious"
              ? "Real effort"
              : v === "mixed"
                ? "Some effort"
                : v === "hobby"
                  ? "Low effort / noise"
                  : "Not yet assessed"
          }
        />
        <HideFlaggedToggle />
        <HideLimitedToggle />
        {/* Now a real partition of the catalogue: `confirmed` = a developer
            disclosed a figure, `unknown` = everything else. */}
        <ParamSelect
          paramKey="wishlist_status"
          label="Wishlist status"
          options={options?.data_statuses ?? []}
        />
        <ParamToggle paramKey="ranked_only" label="On wishlist chart" />
        <DebouncedInput paramKey="min_reviews" placeholder="Min reviews" className="w-28" />
        <DebouncedInput paramKey="min_positive_pct" placeholder="Min +%" className="w-24" />
        <DebouncedInput paramKey="min_peak_ccu" placeholder="Min CCU" className="w-24" />
        <DebouncedInput
          paramKey="min_followers"
          placeholder="Min followers"
          className="w-32"
        />
        <DebouncedInput
          paramKey="max_wishlist_rank"
          placeholder="Rank ≤"
          className="w-24"
        />
        {hasFilters ? (
          <Button
            onClick={() =>
              setParams(
                Object.fromEntries(
                  [...searchParams.keys()]
                    .filter((k) => !["page_size", "sort"].includes(k))
                    .map((k) => [k, null]),
                ),
              )
            }
            className="text-muted"
          >
            Clear filters
          </Button>
        ) : null}
      </div>
    </div>
  );
}
