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
        <ParamToggle paramKey="next_fest" label="Next Fest" />
        <ParamToggle paramKey="released" label="Released" />
        <ParamToggle paramKey="early_access" label="Early Access" />
        <ParamSelect
          paramKey="indie_confidence"
          label="Indie confidence"
          options={["high", "medium", "low"]}
          optionLabels={(v) =>
            v === "high" ? "High confidence" : v === "medium" ? "Medium" : "Low (flagged)"
          }
        />
        <HideFlaggedToggle />
        <ParamSelect
          paramKey="wishlist_status"
          label="Wishlist status"
          options={options?.data_statuses ?? []}
        />
        <ParamSelect
          paramKey="revenue_status"
          label="Revenue status"
          options={options?.data_statuses ?? []}
        />
        <DebouncedInput paramKey="min_reviews" placeholder="Min reviews" className="w-28" />
        <DebouncedInput paramKey="min_positive_pct" placeholder="Min +%" className="w-24" />
        <DebouncedInput paramKey="min_peak_ccu" placeholder="Min CCU" className="w-24" />
        <DebouncedInput paramKey="min_wishlist" placeholder="Min wishlist" className="w-28" />
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
