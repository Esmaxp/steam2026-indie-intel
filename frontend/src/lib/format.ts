/** Formatting helpers. Missing data renders as an em dash — never a fake zero. */

export const DASH = "—";

export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  return new Intl.NumberFormat("en-US").format(value);
}

export function fmtMoney(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined) return DASH;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

export function fmtPriceCents(
  cents: number | null | undefined,
  currency: string | null,
  isFree: boolean,
): string {
  if (isFree) return "Free";
  if (cents === null || cents === undefined) return DASH;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency ?? "USD",
  }).format(cents / 100);
}

/** Money at a glance: "$1.2M", "$76.4K". For estimates, where the last three
 *  digits are noise and printing them would imply a precision nobody has. */
export function fmtMoneyShort(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  return `${value.toFixed(0)}%`;
}

export function fmtDate(iso: string | null | undefined, raw?: string | null): string {
  if (!iso) return raw || DASH;
  // Date-only values ("2026-08-12") get an explicit local midnight so they do
  // not shift a day in negative UTC offsets. Full timestamps are already an
  // instant and must be parsed as-is — appending to one yields Invalid Date.
  const date = new Date(iso.includes("T") ? iso : `${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return raw || DASH;
  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** Date plus clock time, for events where the hour matters — when a sweep
 *  started, when it last checked in. */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return DASH;
  return date.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** The window an event occupied: "13 Aug, 14:51 → 16:27".
 *  The end drops its date when it falls on the start's day, which is the
 *  common case and halves the width. */
export function fmtDateTimeRange(
  startIso: string | null | undefined,
  endIso: string | null | undefined,
): string {
  const startText = fmtDateTime(startIso);
  if (startText === DASH || !endIso) return startText;
  const start = new Date(startIso as string);
  const end = new Date(endIso);
  if (Number.isNaN(end.getTime())) return startText;
  const sameDay = start.toDateString() === end.toDateString();
  const endText = sameDay
    ? end.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })
    : fmtDateTime(endIso);
  return `${startText} → ${endText}`;
}

/** A span in seconds as coarse human units ("2h 40m", "45s").
 *  Deliberately imprecise above a minute: a multi-hour sweep's ETA is an
 *  estimate, and showing seconds on it would imply otherwise. */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || seconds < 0) return DASH;
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours < 24) return rest ? `${hours}h ${rest}m` : `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

export function fmtCompact(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** Signed delta, with an explicit DASH when the value is unknown.
 *  Critically distinguishes "no measurement yet" (DASH) from "no change" (0):
 *  a follower delta reads DASH until two snapshots exist, never 0. */
export function fmtDelta(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  if (value === 0) return "0";
  return `${value > 0 ? "+" : ""}${new Intl.NumberFormat("en-US").format(value)}`;
}

/** A developer-disclosed wishlist figure. Most disclosures are round-number
 *  lower bounds ("over 100,000"), so the comparator is rendered — dropping it
 *  would present a bound as an exact count. */
export function fmtWishlist(
  value: number | null | undefined,
  comparator?: string,
): string {
  if (value === null || value === undefined) return DASH;
  const prefix = comparator === ">=" ? "≥ " : "";
  return prefix + fmtCompact(value);
}

const LABELS: Record<string, string> = {
  "2d": "2D",
  "2.5d": "2.5D",
  "3d": "3D",
  unknown: "Unknown",
  top_down: "Top-Down",
  isometric: "Isometric",
  first_person: "First-Person",
  third_person: "Third-Person",
  side_scroller: "Side-Scroller",
  pixel_art: "Pixel Art",
  hd_pixel_art: "HD Pixel Art",
  voxel: "Voxel",
  stylized: "Stylized",
  low_poly: "Low Poly",
  realistic: "Realistic",
  anime: "Anime",
  hand_painted: "Hand-Painted",
  ps1_style: "PS1-Style",
  ps2_style: "PS2-Style",
  unity: "Unity",
  unreal: "Unreal Engine",
  godot: "Godot",
  gamemaker: "GameMaker",
  custom: "Custom",
  confirmed: "Confirmed",
  estimated: "Estimated",
  full: "Full",
  partial: "Partial",
  none: "None",
  verified: "Verified",
  playable: "Playable",
  unsupported: "Unsupported",
};

export function labelFor(value: string | null | undefined): string {
  if (!value) return DASH;
  return LABELS[value] ?? value.charAt(0).toUpperCase() + value.slice(1);
}
