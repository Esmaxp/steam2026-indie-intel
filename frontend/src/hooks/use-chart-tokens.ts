"use client";

import { useEffect, useState } from "react";

/** SVG presentation attributes can't resolve CSS var(); read the computed
 *  token values and re-read when the color scheme flips. */
const FALLBACK = {
  series1: "#2a78d6",
  series2: "#eb6834",
  grid: "#e1e0d9",
  muted: "#898781",
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
