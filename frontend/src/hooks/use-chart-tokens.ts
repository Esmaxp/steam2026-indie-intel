"use client";

import { useEffect, useState } from "react";

/** SVG presentation attributes can't resolve CSS var(); read the computed
 *  token values and re-read when the color scheme flips. */
const FALLBACK = {
  series1: "#2a78d6",
  series2: "#eb6834",
  grid: "#e1e0d9",
  muted: "#898781",
  ink: "#0b0b0b",
  ink2: "#52514e",
  surface: "#fcfcfb",
  statusGood: "#0ca30c",
  statusWarn: "#fab219",
  statusCritical: "#d03b3b",
};

export function useChartTokens() {
  const [tokens, setTokens] = useState(FALLBACK);

  useEffect(() => {
    const read = () => {
      const styles = getComputedStyle(document.documentElement);
      const get = (name: string, fallback: string) =>
        styles.getPropertyValue(name).trim() || fallback;
      setTokens({
        series1: get("--series-1", FALLBACK.series1),
        series2: get("--series-2", FALLBACK.series2),
        grid: get("--grid", FALLBACK.grid),
        muted: get("--muted", FALLBACK.muted),
        ink: get("--ink", FALLBACK.ink),
        ink2: get("--ink-2", FALLBACK.ink2),
        surface: get("--surface", FALLBACK.surface),
        statusGood: get("--status-good", FALLBACK.statusGood),
        statusWarn: get("--status-warn", FALLBACK.statusWarn),
        statusCritical: get("--status-critical", FALLBACK.statusCritical),
      });
    };
    read();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", read);
    return () => mq.removeEventListener("change", read);
  }, []);

  return tokens;
}


/** Styling for a Recharts <Tooltip>, spread as `{...tooltipStyles(tokens)}`.
 *
 *  Recharts defaults its tooltip text to a dark colour and colours each item
 *  by its series. Setting only `background` therefore produces near-black text
 *  on the near-black `--surface` in dark mode — the panel is legible, the words
 *  inside it are not. All three surfaces need the foreground stated: the
 *  wrapper, the label, and the items, whose inline per-series colour is
 *  otherwise applied before any inherited value.
 *
 *  Items lose their series tint as a result. The chart and its legend already
 *  carry that mapping, and a tooltip whose text cannot be read carries nothing.
 */
export function tooltipStyles(tokens: ReturnType<typeof useChartTokens>) {
  return {
    contentStyle: {
      background: tokens.surface,
      border: `1px solid ${tokens.grid}`,
      borderRadius: 6,
      fontSize: 12,
      color: tokens.ink,
    },
    labelStyle: { color: tokens.ink },
    itemStyle: { color: tokens.ink },
  } as const;
}
