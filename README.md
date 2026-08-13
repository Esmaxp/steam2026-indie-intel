# Steam 2026 Indie Intelligence Platform

Automatically discovers, collects, classifies and analyses every Steam indie
game released during 2026. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full
plan, database schema and roadmap.

This README is written so a human **or an autonomous agent** can set the whole
site up from a fresh clone with zero outside help. Follow the numbered steps
in order; each states its expected outcome.

## Prerequisites

- Docker with Docker Compose v2 (`docker compose version` works). That is
  **all** the default path needs — no local Python or Node required.

## Getting started (fresh clone → working dashboard)

1. **Configure the environment** (no real API keys needed — defaults boot
   everything; key-dependent features degrade gracefully):

   ```bash
   cp .env.example .env
   ```

2. **Build and start the core stack** (db + backend + frontend):

   ```bash
   docker compose up --build -d
   ```

   Alembic migrations apply automatically when the backend container starts.
   First build takes a few minutes (Next.js production build).

   Expected outcome:
   - `GET http://localhost:8000/health` returns 200 with
     `{"status":"ok","database":"ok"}`
   - http://localhost:3000 loads the dashboard (empty until step 3)

3. **Load data — pick ONE of the three options below.**

   **(a) Fast option — restore the pre-exported catalog** (seconds; skips
   discovery/collection entirely; the dump ships with the repo — ~13 MB,
   snapshot details in `database/seed/full_export.meta.txt`):

   ```bash
   docker compose run --rm db_restore
   docker compose run --rm backend alembic upgrade head   # in case migrations landed after the export
   ```

   Expected outcome: the dashboard shows ~14,000+ games immediately. The
   snapshot date is in `database/seed/full_export.meta.txt` — prices,
   reviews and wishlist/revenue estimates are only as fresh as that date.
   Run `docker compose run --rm refresher` afterward for current stats, or
   `pipeline` to re-discover games released since the snapshot. Safe to
   re-run (the restore drops and recreates the dumped objects).

   **(b) Quick sample — run the real pipeline on ~50 games** (~10 minutes;
   use this if you specifically want to test the collection pipeline
   itself):

   ```bash
   docker compose run --rm seed
   ```

   Expected outcome: the command exits 0 and the dashboard shows dozens of
   games with names, tags, prices and images. Safe to re-run or interrupt —
   progress is checkpointed per game.

   **(c) Full fresh collection** — process the entire discovery queue and
   collect market data from scratch (takes hours, rate-limited on purpose):

   ```bash
   docker compose run --rm pipeline
   ```

### Verify your setup

- [ ] `docker compose ps` shows `db`, `backend`, `frontend` running (healthy)
- [ ] `curl http://localhost:8000/health` → `{"status":"ok","database":"ok"}`
- [ ] http://localhost:8000/docs renders the API docs
- [ ] http://localhost:3000 loads; after step 3 the games table lists ≥ 25 games
- [ ] `curl "http://localhost:8000/api/v1/games?page_size=1"` returns JSON with
      `"total"` ≥ 25

## Services

`docker compose up` starts only the first three. Everything under the
**scrape** profile is on-demand: it does **not** auto-start and only runs via
`docker compose run --rm <name>`.

| Service | Purpose | Port | Auto-start? | Run with |
|---|---|---|---|---|
| db | PostgreSQL 16 storage | 5432 | yes | `docker compose up` |
| backend | FastAPI REST API + migrations | 8000 | yes | `docker compose up` |
| frontend | Next.js dashboard | 3000 | yes | `docker compose up` |
| db_restore | Restore the committed full-catalog snapshot | – | no (profile: scrape) | `docker compose run --rm db_restore` |
| seed | Quick-start data seed (~50 games) | – | no (profile: scrape) | `docker compose run --rm seed` |
| discovery | Find 2026 indie games on Steam | – | no (profile: scrape) | `docker compose run --rm discovery` |
| collector | Full store data per queued game | – | no (profile: scrape) | `docker compose run --rm collector` |
| market | Market/estimate collector (Phase 4) | – | no (profile: scrape) | `docker compose run --rm market` |
| pipeline | discovery → collector → market chain | – | no (profile: scrape) | `docker compose run --rm pipeline` |
| refresher | Daily stats snapshot refresh | – | no (profile: scrape) | `docker compose run --rm refresher` |
| websites | Backfill `games.website` from Steam | – | no (profile: scrape) | `docker compose run --rm websites` |
| scanner | Detect social channels on game websites | – | no (profile: scrape) | `docker compose run --rm scanner` |
| video_prefetch | Warm per-game video cache | – | no (profile: scrape) | `docker compose run --rm video_prefetch` |
| reclassify | Replay the rule-based classifier over collected games (free, offline) | – | no (profile: scrape) | `docker compose run --rm reclassify` |
| dimension_local | Fill unresolved 2D/3D from catalog similarity (offline TF-IDF, free) | – | no (profile: scrape) | `docker compose run --rm dimension_local` |
| dimension_vision | Classify 2D/3D from a screenshot (needs `ANTHROPIC_API_KEY`) | – | no (profile: scrape) | `docker compose run --rm dimension_vision` |
| dimension_similarity | Estimate 2D/3D from metadata when no tag, rule or screenshot settles it (needs `ANTHROPIC_API_KEY`) | – | no (profile: scrape) | `docker compose run --rm dimension_similarity` |

Community-video flow (all optional, needs `YOUTUBE_API_KEY` / `TWITCH_*` keys
for actual videos): `websites` → `scanner` → review at
http://localhost:3000/admin/submissions (token = `ADMIN_TOKEN` from `.env`) →
`video_prefetch`.

Passing flags to an on-demand service requires the full command form, because
compose replaces the service's `command:` with whatever follows the service
name:

```bash
docker compose run --rm collector python -m scraper.collectors.run --limit 500
docker compose run --rm discovery python -m scraper.discovery.run --mode search --include-untagged
```

Visual classification (dimension / camera / graphics style) runs as a ladder,
cheapest first:

1. **`tag`** — Steam's own 2D/2.5D/3D tag.
2. **`rule_based`** — inference from camera, graphics style and description
   (free, part of the collector).
3. **`similarity`** — `dimension_local`: an offline TF-IDF + cosine-similarity
   vote over the games already settled by steps 1-2. Free, local, no API key
   and no network call. Measured on a 2,000-game holdout: 68% coverage at 89%
   accuracy with the defaults (`--validate N` re-measures it any time).
4. **`vision_ai` / `similarity_ai`** — `dimension_vision` reads a screenshot,
   `dimension_similarity` estimates from metadata. Both cost real API money and
   need `ANTHROPIC_API_KEY`.

Every step only ever fills rows still `unknown`, never overwrites a settled
value, and records itself in `games.dimension_source`. Step 3 additionally skips
games that carry a dimension tag of their own: if such a game is still unknown,
its tags contradicted each other, and text similarity has no business
overruling that.

```bash
docker compose run --rm dimension_local python -m workers.classify_dimension_local --dry-run
docker compose run --rm dimension_local python -m workers.classify_dimension_local --validate 2000
docker compose run --rm dimension_local            # apply
```

Because `store_data` never re-runs for a game once it is DONE, improvements to
the classifier are invisible to already-collected games. The `reclassify`
service replays the current rules over them — free and offline, filling only
fields that are still `unknown` and never overwriting a settled value. Always
measure first:

```bash
docker compose run --rm reclassify python -m workers.reclassify_classification --dry-run
docker compose run --rm reclassify
```

`engine` is the one field left deliberately empty for most games: Steam does not
publish it, so it is only known when a developer names the engine in the store
legal notice or description. It is never inferred by AI — an engine is a hard
fact, not a visual observation, and guessing it would violate the data-honesty
rule below.

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

### Genre success breakdown (estimated)

Steam publishes no sales figures either, so the analytics section's genre
success breakdown — click a bar in "Top genres" — is an explicit heuristic: the
Boxleiter method, `estimated_sales = total_reviews * multiplier`. The API
returns the formula, the multiplier actually used and its source, and the UI
prints them under the pie, the same way every other estimate carries its
inputs. The constant lives in `backend/app/services/boxleiter.py` with its
provenance and credible range (25-60; the "true" value varies by price, genre
and age). Games with no review count are reported separately and excluded from
the pie rather than guessed into a tier.

```bash
curl "http://localhost:8000/api/v1/dashboard/genre-success?genre=Action"
curl "http://localhost:8000/api/v1/dashboard/genre-success?genre=RPG&multiplier=50"
```

## Troubleshooting

- **Port already in use** (5432/8000/3000): stop the conflicting process, or
  change `POSTGRES_PORT` in `.env` (database) / edit the `ports:` mapping in
  `docker-compose.yml` (backend/frontend), then `docker compose up -d`.
- **Backend unhealthy / migrations pending**: `docker compose logs backend` —
  the container runs `alembic upgrade head` on start; a failure there is
  almost always the db not being ready yet (compose waits on its healthcheck,
  so simply retry `docker compose up -d`) or a stale volume from an older
  schema (`docker compose down -v` wipes it, then `up --build`).
- **Dashboard is empty**: that's a fresh database, not a bug. Run
  `docker compose run --rm seed` (step 3) and refresh after ~10 minutes.
- **"not configured" / missing videos or estimates**: optional API keys are
  empty. This is the documented graceful state — add `GAMALYTIC_API_KEY`,
  `YOUTUBE_API_KEY` or `TWITCH_*` to `.env` and
  `docker compose up -d backend frontend` to enable those features.

## Local development (without Docker)

Backend (needs a running PostgreSQL — easiest: `docker compose up -d db`):

```bash
cd backend
# Linux/macOS:
python -m venv .venv && source .venv/bin/activate
# Windows (PowerShell):
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -e .
# .env's DATABASE_URL uses host "db" (Docker); for local dev point it at localhost:
export DATABASE_URL=postgresql+asyncpg://steam:steam@localhost:5432/steam2026  # PowerShell: $env:DATABASE_URL="..."
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
# Linux/macOS:
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
# Windows (PowerShell):
$env:NEXT_PUBLIC_API_URL="http://localhost:8000"; npm run dev
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
9. ✅ Community videos — lazy per-game YouTube/Twitch galleries with view
   counts, developer channel submissions + admin review (`/admin/submissions`),
   website/channel discovery workers (`websites`, `scanner`, `video_prefetch`)
