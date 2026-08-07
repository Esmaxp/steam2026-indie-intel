"use client";

import { Download } from "lucide-react";
import { API_BASE } from "@/lib/api";
import { useFilterParams } from "@/hooks/use-filter-params";

const FORMATS = [
  { key: "csv", label: "CSV" },
  { key: "xlsx", label: "Excel" },
  { key: "json", label: "JSON" },
  { key: "md", label: "Markdown" },
] as const;

/** Downloads the CURRENT filtered/sorted view — same query the table uses. */
export function ExportButtons() {
  const { searchParams } = useFilterParams();

  function exportUrl(format: string): string {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("page");
    params.delete("page_size");
    params.set("format", format);
    return `${API_BASE}/api/v1/export?${params.toString()}`;
  }

  return (
    <div className="flex items-center gap-1.5">
      <span className="mr-1 inline-flex items-center gap-1 text-xs text-muted">
        <Download size={13} aria-hidden /> Export filtered:
      </span>
      {FORMATS.map((format) => (
        <a
          key={format.key}
          href={exportUrl(format.key)}
          download
          className="inline-flex h-8 items-center rounded-md border border-hairline bg-surface px-2.5 text-xs text-ink transition-colors hover:bg-grid/40"
        >
          {format.label}
        </a>
      ))}
    </div>
  );
}
