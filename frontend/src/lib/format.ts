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

export function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  return `${value.toFixed(0)}%`;
}

export function fmtDate(iso: string | null | undefined, raw?: string | null): string {
  if (!iso) return raw || DASH;
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function fmtCompact(value: number | null | undefined): string {
  if (value === null || value === undefined) return DASH;
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
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
