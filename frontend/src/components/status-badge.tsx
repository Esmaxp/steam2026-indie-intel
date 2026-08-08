import { AlertTriangle, CheckCircle2, CircleHelp, TrendingUp } from "lucide-react";
import type { DataStatus } from "@/lib/types";

/** Provenance badge: icon + label, color never carries meaning alone. */
export function StatusBadge({ status }: { status: DataStatus }) {
  if (status === "conflicting") {
    return (
      <span
        className="inline-flex items-center gap-1 text-xs font-medium text-ink2"
        title="Independent estimate sources disagree by more than 50% — check each source on the game page"
      >
        <AlertTriangle size={13} aria-hidden className="text-[#ec835a]" />
        Conflicting
      </span>
    );
  }
  if (status === "confirmed") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-good-text">
        <CheckCircle2 size={13} aria-hidden />
        Confirmed
      </span>
    );
  }
  if (status === "estimated") {
    return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-ink2">
        <TrendingUp size={13} aria-hidden className="text-status-warn" />
        Estimated
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted">
      <CircleHelp size={13} aria-hidden />
      Unknown
    </span>
  );
}
