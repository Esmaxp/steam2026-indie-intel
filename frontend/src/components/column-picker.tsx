"use client";

import type { Table } from "@tanstack/react-table";
import { Check, Columns3 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { GameListItem } from "@/lib/types";
import { Button } from "@/components/ui/button";

/** Show/hide menu for the games table columns.
 *
 * Reads and mutates TanStack's own `columnVisibility` state, so the table
 * stays the single source of truth — this component holds no column state.
 */
export function ColumnPicker({
  table,
  onReset,
}: {
  table: Table<GameListItem>;
  onReset: () => void;
}) {
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  // "expand" is the chevron affordance, not data — never offer to hide it.
  const toggleable = table
    .getAllLeafColumns()
    .filter((column) => column.id !== "expand");
  const visibleCount = toggleable.filter((column) => column.getIsVisible()).length;

  return (
    <div ref={boxRef} className="relative">
      <Button
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="true"
        aria-expanded={open}
        className="h-8 px-2.5 text-xs"
      >
        <Columns3 size={13} aria-hidden />
        Columns
        <span className="text-muted">
          {visibleCount}/{toggleable.length}
        </span>
      </Button>

      {open ? (
        <div
          role="menu"
          className="absolute left-0 z-30 mt-1 max-h-[22rem] w-56 overflow-y-auto rounded-md border border-hairline bg-surface p-1 shadow-md"
        >
          {toggleable.map((column) => {
            const visible = column.getIsVisible();
            // Keep at least one data column on screen — an empty table is a dead end.
            const locked = visible && visibleCount === 1;
            return (
              <button
                key={column.id}
                role="menuitemcheckbox"
                aria-checked={visible}
                disabled={locked}
                onClick={() => column.toggleVisibility()}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm text-ink transition-colors hover:bg-grid/40 disabled:cursor-not-allowed disabled:opacity-40"
              >
                <span
                  aria-hidden
                  className={`flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                    visible ? "border-accent bg-accent text-white" : "border-hairline"
                  }`}
                >
                  {visible ? <Check size={11} strokeWidth={3} /> : null}
                </span>
                {String(column.columnDef.header)}
              </button>
            );
          })}

          <div className="mt-1 border-t border-hairline pt-1">
            <button
              onClick={onReset}
              className="w-full rounded px-2 py-1.5 text-left text-xs text-accent transition-colors hover:bg-grid/40"
            >
              Reset to defaults
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
