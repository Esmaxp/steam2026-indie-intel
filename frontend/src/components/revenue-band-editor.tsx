"use client";

/** Editing the revenue bands the pie is cut into.
 *
 *  The default six are a reasonable guess at what matters, not a fact about
 *  the market — "under $10K" is one bucket holding 86% of releases, which is
 *  the right resolution for some questions and useless for others. Anyone
 *  asking "how many clear a year of rent" wants their own edges.
 *
 *  A band set is edited and sent as its FLOORS. Bands as labelled intervals
 *  can be malformed in ways floors cannot — overlapping, gapped, unordered —
 *  so the shape that reaches the server is the one that cannot express those
 *  mistakes, and the labels are derived there.
 */

import { Plus, RotateCcw, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { fmtInt } from "@/lib/format";

export const DEFAULT_FLOORS = [0, 10_000, 50_000, 100_000, 500_000, 1_000_000];
/** Mirrors MAX_BANDS in backend/app/api/v1/dashboard.py. */
export const MAX_BANDS = 10;
const STORAGE_KEY = "steam2026.revenue-bands.floors.v1";

export function loadFloors(): number[] {
  if (typeof window === "undefined") return DEFAULT_FLOORS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_FLOORS;
    const parsed = JSON.parse(raw);
    // Validated on the way out as well as in: a stored set from an older
    // build, or one hand-edited in devtools, would otherwise 422 every
    // request with no way for the user to see why.
    return validate(parsed) === null ? parsed : DEFAULT_FLOORS;
  } catch {
    return DEFAULT_FLOORS;
  }
}

function saveFloors(floors: number[]) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(floors));
  } catch {
    // Private browsing. The bands still apply for this session.
  }
}

/** The same rules the server enforces, checked here so the message arrives
 *  while the user is still looking at the field that caused it. */
export function validate(floors: unknown): string | null {
  if (!Array.isArray(floors) || floors.some((f) => typeof f !== "number" || !isFinite(f))) {
    return "Every edge must be a number.";
  }
  if (floors.length < 2) return "Two edges at least — one band cannot be a pie.";
  if (floors.length > MAX_BANDS) return `At most ${MAX_BANDS} bands.`;
  if (floors[0] !== 0) return "The first edge must be 0, or games below it vanish.";
  for (let i = 1; i < floors.length; i += 1) {
    if (floors[i] <= floors[i - 1]) return "Edges must ascend and not repeat.";
  }
  return null;
}

export function RevenueBandEditor({
  floors,
  onApply,
  onClose,
}: {
  floors: number[];
  onApply: (next: number[]) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<number[]>(floors);
  const error = validate(draft);

  // Escape closes, because a dialog that traps you is worse than no dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const setEdge = (index: number, value: number) =>
    setDraft((prev) => prev.map((f, i) => (i === index ? value : f)));

  const addEdge = () =>
    setDraft((prev) => {
      // Doubling the top edge is the shape these sets already have — each
      // band wider than the last — so the new row is usually close to right.
      const last = prev[prev.length - 1] || 1000;
      return [...prev, last * 2];
    });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      // A click on the backdrop is the other way out. Stopped from inside the
      // card so a click on the form does not dismiss it.
      onClick={onClose}
      role="presentation"
    >
      <Card
        className="w-full max-w-md p-5"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Edit revenue bands"
      >
        <div className="mb-1 flex items-start justify-between gap-2">
          <h3 className="text-sm font-medium text-ink">Revenue bands</h3>
          <button onClick={onClose} aria-label="Close" className="text-muted hover:text-ink">
            <X size={15} />
          </button>
        </div>
        <p className="mb-3 text-xs text-muted">
          Each row is the lower edge of a band, in net USD. The first is always
          0; the last opens the top band.
        </p>

        <div className="flex flex-col gap-1.5">
          {draft.map((floor, index) => (
            <div key={index} className="flex items-center gap-2">
              <span className="w-6 shrink-0 text-right text-xs text-muted">
                {index + 1}
              </span>
              <span className="text-xs text-muted">$</span>
              <input
                type="number"
                min={0}
                step={1000}
                value={floor}
                disabled={index === 0}
                onChange={(e) => setEdge(index, Number(e.target.value))}
                className="w-40 rounded border border-hairline bg-surface px-2 py-1 text-sm tabular-nums text-ink disabled:text-muted"
                aria-label={`Band ${index + 1} lower edge`}
              />
              <span className="grow text-xs text-muted">
                {index === draft.length - 1
                  ? "and above"
                  : `up to $${fmtInt(draft[index + 1])}`}
              </span>
              <button
                onClick={() => setDraft((prev) => prev.filter((_, i) => i !== index))}
                // The 0 edge is not removable: without it the games below the
                // new first edge would simply not appear anywhere.
                disabled={index === 0 || draft.length <= 2}
                aria-label={`Remove band ${index + 1}`}
                className="text-muted hover:text-status-critical disabled:opacity-30 disabled:hover:text-muted"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            onClick={addEdge}
            disabled={draft.length >= MAX_BANDS}
            className="h-7 gap-1.5 px-2 text-xs"
          >
            <Plus size={12} aria-hidden /> Add band
          </Button>
          <Button
            onClick={() => setDraft(DEFAULT_FLOORS)}
            className="h-7 gap-1.5 px-2 text-xs"
          >
            <RotateCcw size={12} aria-hidden /> Reset
          </Button>
          <span className="grow" />
          <Button
            onClick={() => {
              saveFloors(draft);
              onApply(draft);
              onClose();
            }}
            disabled={error !== null}
            className="h-7 px-3 text-xs"
          >
            Apply
          </Button>
        </div>
        {error ? <p className="mt-2 text-xs text-status-critical">{error}</p> : null}
      </Card>
    </div>
  );
}
