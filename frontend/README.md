# frontend/

Next.js (App Router) + TypeScript + TailwindCSS + TanStack Table + React Query
dashboard for the Steam 2026 Indie Intelligence Platform.

- `/` — dashboard cards (totals, honest averages with sample sizes) +
  filterable/sortable games table. Filter state lives in the URL, so views are
  shareable. Sorting is server-side via the API.
- `/games/[appid]` — game detail: images, companies, classification,
  business data with Confirmed / Estimated / Unknown provenance badges and
  source links, review stats, timeline, media, business-data history.

Missing values always render as an em dash — never a fake zero. Charts arrive
in Phase 7; export buttons in Phase 8.

## Community Clips (/community)

Social video gallery + header account links.

- **Accounts:** fill URLs in `src/config/social.ts` — empty entries are
  hidden; nothing is invented. Icons get tooltips and open in new tabs.
- **YouTube / Twitch (auto):** set `YOUTUBE_API_KEY`, `YOUTUBE_CHANNEL_ID`,
  `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TWITCH_USER_LOGIN` in the
  root `.env` (server-side only — calls run in a Next.js route handler,
  results cached 1 hour; on error the UI shows a "visit the channel"
  fallback link instead of an empty grid).
- **TikTok / Instagram / X (manual):** these platforms have no usable
  public listing APIs (restricted, review-gated or paid), so add entries by
  hand to `src/data/videos.json`:
  ```json
  { "platform": "tiktok", "url": "https://...", "title": "Launch clip",
    "thumbnail": "https://... (optional)", "published_at": "2026-08-01" }
  ```

## Run locally

```bash
npm install
npm run dev        # http://localhost:3000 (API expected at localhost:8000)
```

Set `NEXT_PUBLIC_API_URL` to point at a different backend.

## Docker

Built and served by `docker compose up` (standalone output, port 3000).
