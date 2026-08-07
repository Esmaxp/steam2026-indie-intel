import type { Config } from "tailwindcss";

/** Design tokens live in globals.css as CSS variables (light + dark);
 *  Tailwind color names just point at them. */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        page: "var(--page)",
        surface: "var(--surface)",
        ink: "var(--ink)",
        ink2: "var(--ink-2)",
        muted: "var(--muted)",
        grid: "var(--grid)",
        hairline: "var(--hairline)",
        accent: "var(--accent)",
        "status-good": "var(--status-good)",
        "status-warn": "var(--status-warn)",
        "status-critical": "var(--status-critical)",
        "good-text": "var(--good-text)",
      },
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
