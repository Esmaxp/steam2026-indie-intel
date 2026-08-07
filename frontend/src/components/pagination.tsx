"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { fmtInt } from "@/lib/format";
import { useFilterParams } from "@/hooks/use-filter-params";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";

export function Pagination({
  page,
  pages,
  total,
}: {
  page: number;
  pages: number;
  total: number;
}) {
  const { searchParams, setParams } = useFilterParams();
  const pageSize = searchParams.get("page_size") ?? "25";

  return (
    <div className="flex flex-wrap items-center gap-3 text-sm text-ink2">
      <span>
        {fmtInt(total)} games · page {page} / {pages}
      </span>
      <div className="ml-auto flex items-center gap-2">
        <Select
          value={pageSize}
          onChange={(e) => setParams({ page_size: e.target.value })}
          aria-label="Rows per page"
        >
          {[25, 50, 100, 200].map((n) => (
            <option key={n} value={n}>
              {n} / page
            </option>
          ))}
        </Select>
        <Button
          disabled={page <= 1}
          onClick={() => setParams({ page: String(page - 1) }, false)}
          aria-label="Previous page"
        >
          <ChevronLeft size={14} aria-hidden /> Prev
        </Button>
        <Button
          disabled={page >= pages}
          onClick={() => setParams({ page: String(page + 1) }, false)}
          aria-label="Next page"
        >
          Next <ChevronRight size={14} aria-hidden />
        </Button>
      </div>
    </div>
  );
}
