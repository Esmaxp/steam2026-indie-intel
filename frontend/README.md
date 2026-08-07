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

## Run locally

```bash
npm install
npm run dev        # http://localhost:3000 (API expected at localhost:8000)
```

Set `NEXT_PUBLIC_API_URL` to point at a different backend.

## Docker

Built and served by `docker compose up` (standalone output, port 3000).
