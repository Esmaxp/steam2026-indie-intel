# Steam 2026 Indie Intelligence Platform

Automatically discovers, collects, classifies and analyses every Steam indie
game released during 2026. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full
plan, database schema and roadmap.

## Data honesty

Steam does **not** expose wishlist, revenue or budget numbers. Every such
value is stored with a provenance status — **Confirmed / Estimated /
Unknown / Conflicting** — plus a source link and fetch date. Data is never
fabricated.

Estimate sources: SteamSpy (owner ranges, free API), Gamalytic (requires
`GAMALYTIC_API_KEY`), VG Insights public pages (currently behind an
authenticated SPA → honestly Unknown), and human-verified disclosures via
`python -m scraper.collectors.disclosed_numbers_source`. Multiple estimates
are cross-validated by median; sources disagreeing by more than 50% are
marked **Conflicting** with every source shown. Budgets are either Confirmed
disclosures or explicitly labeled heuristics (team-cost and revenue-ratio
methods, formulas and inputs stored for audit — see ARCHITECTURE.md §9).

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

- PostgreSQL → `localhost:5432`
- Backend API → http://localhost:8000 (docs at `/docs`, health at `/health`)
- Frontend dashboard → http://localhost:3000 (arrives in Phase 6)

Migrations run automatically when the backend container starts.

## Local development (without Docker)

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -e .
# point DATABASE_URL at a running PostgreSQL, then:
alembic upgrade head
uvicorn app.main:app --reload
```

## Project phases

1. ✅ Architecture & database
2. ✅ Steam discovery service — `docker compose run --rm discovery` (see `scraper/README.md`)
3. ✅ Steam data collector — `docker compose run --rm collector`
4. ✅ Public market intelligence collector — `docker compose run --rm market`
   (or run the whole chain: `docker compose run --rm pipeline`)
5. ✅ REST API — http://localhost:8000/docs (`/api/v1/games`, dashboard, filters)
6. ✅ Frontend dashboard — http://localhost:3000 (`cd frontend && npm run dev` locally)
7. ✅ Charts & analytics — dashboard analytics grid + per-game stats history
8. ✅ Export system — CSV / Excel / JSON / Markdown of the current filtered view
   (buttons above the table, or `GET /api/v1/export?format=csv&...`); copies land in `exports/`
