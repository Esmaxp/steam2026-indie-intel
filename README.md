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

   Day to day, `./scripts/start-all.sh` restarts the stack and waits until it
   is actually serving before returning (`--build` to rebuild, `--logs` to
   follow, `--stop` to shut down).

   Alembic migrations apply automatically when the backend container starts.
   First build takes a few minutes (Next.js production build).

   Expected outcome:
   - `GET http://localhost:9100/health` returns 200 with
     `{"status":"ok","database":"ok"}`
   - http://localhost:4000 loads the dashboard (empty until step 3)

3. **Load data — pick ONE of the three options below.**

   **(a) Fast option — restore the pre-exported catalog** (seconds; skips
   discovery/collection entirely; the dump ships with the repo — ~13 MB,
   snapshot details in `database/seed/full_export.meta.txt`):

   ```bash
   docker compose run --rm db_restore
   docker compose run --rm backend alembic upgrade head   # in case migrations landed after the export
   ```

   Expected outcome: the dashboard shows ~14,000+ games immediately, with
   follower counts and Top-Wishlists ranks already populated. The snapshot
   date is in `database/seed/full_export.meta.txt` — prices, reviews,
   followers and ranks are only as fresh as that date. Run
   `docker compose run --rm refresher` afterward for current stats,
   `followers` / `rank_sweep` for current demand signals, or `pipeline` to
   re-discover games released since the snapshot. Safe to re-run (the
   restore drops and recreates the dumped objects).

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
- [ ] `curl http://localhost:9100/health` → `{"status":"ok","database":"ok"}`
- [ ] http://localhost:9100/docs renders the API docs
- [ ] http://localhost:4000 loads; after step 3 the games table lists ≥ 25 games
- [ ] `curl "http://localhost:9100/api/v1/games?page_size=1"` returns JSON with
      `"total"` ≥ 25

## Services

`docker compose up` starts only the first three. Everything under the
**scrape** profile is on-demand: it does **not** auto-start and only runs via
`docker compose run --rm <name>`.

| Service | Purpose | Port | Auto-start? | Run with |
|---|---|---|---|---|
| db | PostgreSQL 16 storage | 9432 | yes | `docker compose up` |
| backend | FastAPI REST API + migrations | 9100 | yes | `docker compose up` |
| frontend | Next.js dashboard | 4000 | yes | `docker compose up` |
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
| followers | Community-hub follower counts (daily) | – | no (profile: scrape) | `docker compose run --rm followers` |
| rank_sweep | Valve Top-Wishlists ordinal sweep (daily) | – | no (profile: scrape) | `docker compose run --rm rank_sweep` |
| disclosures | Developer-disclosed wishlist counts from Steam news | – | no (profile: scrape) | `docker compose run --rm disclosures` |
| tests | Unit tests (pure functions, no DB) | – | no (profile: scrape) | `docker compose run --rm tests` |

Community-video flow (all optional, needs `YOUTUBE_API_KEY` / `TWITCH_*` keys
for actual videos): `websites` → `scanner` → review at
http://localhost:4000/admin/submissions →
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

Demand-signal flow (no keys at all — every source is Valve's own): run
`followers` and `rank_sweep` daily to build the time series that make
Followers Δ14d and Rank Δ7d meaningful, and `disclosures` occasionally to
pick up new developer announcements.

All three can also be triggered from the dashboard at **Data sweeps** in the
header (http://localhost:4000/admin/sweeps): tick any combination, optionally
narrow which games are scanned by release date, and watch live progress. One
sweep runs at a time **per collector**, so concurrent runs cannot multiply the
request rate against Steam. Different collectors can run together — followers
talks to steamcommunity.com, disclosures to api.steampowered.com and rank to
store.steampowered.com, so they do not compete.

Each run shows when it started, how long it has been going, and how much is
left. The ETA is labelled **measured** when it comes from observed throughput
and **assumed rate** when it is arithmetic on the configured request interval —
a full-catalogue follower sweep is ~18h at 4s per game, disclosures ~8h at
1.5s. **Pause** holds position between games and keeps everything collected;
**Continue** resumes it; **Stop** ends the run. Every collector is resumable,
so none of the three loses work.

A run that finished, failed, was stopped, or died with the backend gets
**Continue** and **Delete** buttons. Continue starts a new job with the same
settings from where the old one stopped. Delete removes the record so it
cannot be re-run — it takes two clicks, and it removes only the record:
follower snapshots, disclosures and chart entries are keyed by game and are
untouched. A live run is refused rather than deleted; stop it first. The original row is kept as the record of what
happened rather than being revived. Followers and rank work out where to
resume from the database; disclosures cannot — it writes rows only for the
~5% of games that announced a figure, so "already scanned" leaves no trace for
the other 95% — and its walk position is carried across explicitly.

The same controls reach the long CLI sweeps, which are the practical way to run
a full catalogue pass because they survive a backend restart:

```bash
nohup bash scripts/sweep-followers.sh --include-released > logs/follower-sweep.log 2>&1 &
nohup bash scripts/sweep-disclosures.sh --write > logs/disclosure-sweep.log 2>&1 &
```

Each script registers a `sweep_jobs` row and passes its id to every batch, so
it appears in the admin UI alongside API-launched runs and honours the same
buttons. A run whose heartbeat has gone quiet is flagged there: a CLI sweep is
a separate process the backend cannot otherwise observe, so a killed shell loop
would look "running" forever.

> **The /admin routes are unauthenticated.** Admin auth is not implemented
> yet, so anyone who can reach the API can approve submissions and start
> hours-long sweeps. Keep port 9100 bound to localhost until it is.

## Market intelligence API (for the Game Market Analyzer agent)

`/api/v1/market/*` is a read surface built for an LLM agent that turns this
catalogue into game concepts. The per-game endpoints under `/api/v1/games`
already expose everything; these return the *aggregate that answers the
question* instead of 23,078 rows.

Start at **`GET /api/v1/market/manifest`** — it returns the tool's own
capabilities, a glossary for every metric, the success-band definitions, live
coverage counts, and the rules below as data. An agent that reads only the
other endpoints will eventually infer a wishlist number from followers or read
a top-decile share as a success rate, and neither mistake is visible in a JSON
payload.

| Endpoint | Answers |
|---|---|
| `GET /market/manifest` | What this tool can and cannot tell you. Call first. |
| `GET /market/coverage` | Which signals exist right now, and how densely. |
| `GET /market/trending` | Breakouts by measured movement — or current demand leaders when nothing has moved yet. Check `basis`. |
| `GET /market/genres` | Supply, outcome and demand per Steam genre. |
| `GET /market/tags` | The same per tag — 429 of them, the vocabulary that actually describes a game. |
| `GET /market/design-attributes?axis=` | How a design or commercial choice performed: `dimension`, `camera`, `graphics_style`, `engine`, `price_band`, `early_access`, `demo_available`. |
| `GET /market/landscape?tag=&genre=` | The competitive field for a concept: size, outcomes, direct competitors, adjacent tags. Filters are ANDed. |

Three properties are deliberate, and they exist because the consumer is an
agent optimising for a confident answer:

- **Every response states its own coverage.** A momentum signal needs two
  observations separated by time. When that does not exist yet, an empty
  trending list would read as a flat market — so `coverage.notes` says
  outright that the time series is too young, and `basis` says whether a
  ranking came from movement or from current standing.
- **An unknown genre or tag is a 422, not an empty result.** Guessing
  `Deckbuilder` (the real tag is `Deckbuilding`) would otherwise return a
  field of zero games and read as an untapped niche rather than a typo — with
  874 titles actually in it. The error carries near-miss suggestions.
- **Outcome is a position, never a sale.** `top_decile_share` is the share of
  a slice's *rankable* games in the top decile of their release-month cohort,
  reported next to `outcome_sample` so a tag with twelve rankable games cannot
  masquerade as a trend. Nothing here multiplies reviews into revenue.

The [data-honesty rules](#data-honesty) apply in full: no wishlist figure is
estimated, and no revenue figure exists to report. Those two constraints ship
inside the manifest so the agent carries them into its own output.

## Data honesty

Steam does **not** expose wishlist, revenue or budget numbers. Every such
value is stored with a provenance status — **Confirmed / Estimated /
Unknown / Conflicting** — plus a source link and fetch date. Data is never
fabricated.

**The wishlist column shows a developer-confirmed disclosure, or it shows
Unknown. There is no derived wishlist number or range for anyone else** — not
from followers, not from rank, not bought from a vendor. No third-party
wishlist estimate has ever been validated in public against a real Steamworks
figure, so no accuracy could be stated for one.

What is shown instead is measured and first-party:

| Column | What it is |
|---|---|
| **Followers** | Steam community-hub members — a count Valve publishes. Exact. |
| **Followers Δ14d** | Change across our own snapshots. Blank, never `0`, until two exist. |
| **Wishlist rank** | Position on Valve's Top-Wishlists chart. An *order*, not a count — it blends total wishlists with recent velocity. "Not ranked" is the common case: the chart holds ~5.2k games across all of Steam. |
| **Wishlist** | A figure the developer stated publicly, with the announcement date and a link. `≥` when they gave a lower bound ("over 100,000"), which most do. |

Disclosures are harvested from official Steam news
(`docker compose run --rm disclosures`), and entered by hand via
`python -m scraper.collectors.disclosed_numbers_source`. Both write only at
**Confirmed**, so the harvester defaults to a dry-run CSV for review and needs
`--write` to insert.

Revenue has no first-party source and reports **Unknown** for every game. The
third-party estimate vendors were retired: across 8,380 collected rows, none
carried a revenue or sales figure. **SteamCharts** is kept for concurrent
players and labelled third-party in the UI — it publishes an observed
measurement rather than a model output.

### Genre success breakdown (measured ranking)

Steam publishes no sales figures either — so rather than estimate them, the
analytics section ranks what Valve does publish. Click a bar in "Top genres"
and the pie shows where that genre's games sit among their peers by review
count: top 1%, top 10%, top 25%, upper half, lower half.

Two things make it a measurement rather than a guess. The measure is Steam's
own review count, and each game is ranked inside its **release-month cohort**,
so an August release competes with August releases (median reviews run 13 for
January's cohort down to 6 for August's — comparing across them would bury new
games for no reason). Because it is a ranking, no sales multiplier is involved
and there is nothing to disagree with. The bands live in
`backend/app/services/success_bands.py`; the response also carries each band's
baseline share, which is what makes "this genre over-indexes" a real claim
rather than an impression.

Games that cannot be ranked — unreleased, or released with no reviews yet —
are reported in their own counters and left out of the pie.

```bash
curl "http://localhost:9100/api/v1/dashboard/genre-success?genre=RPG"
curl "http://localhost:9100/api/v1/dashboard/genre-success?genre=Casual"
```

## Troubleshooting

- **Port already in use** (9432/9100/4000): stop the conflicting process, or
  change `POSTGRES_PORT` in `.env` (database) / edit the `ports:` mapping in
  `docker-compose.yml` (backend/frontend), then `docker compose up -d`.
  Only ever change the **left** (host) side of a `ports:` mapping — the right
  side is the container-internal port the process actually listens on.
  Moving the backend also means updating `NEXT_PUBLIC_API_URL` (compose build
  arg) and the CORS origin in `backend/app/main.py`.
- **Backend unhealthy / migrations pending**: `docker compose logs backend` —
  the container runs `alembic upgrade head` on start; a failure there is
  almost always the db not being ready yet (compose waits on its healthcheck,
  so simply retry `docker compose up -d`) or a stale volume from an older
  schema (`docker compose down -v` wipes it, then `up --build`).
- **Dashboard is empty**: that's a fresh database, not a bug. Run
  `docker compose run --rm seed` (step 3) and refresh after ~10 minutes.
- **"not configured" / missing videos**: the YouTube/Twitch keys are empty.
  This is the documented graceful state — add `YOUTUBE_API_KEY` or
  `TWITCH_*` to `.env` and `docker compose up -d backend frontend`.
- **Wishlist column reads "Unknown" / rank reads "Not ranked"**: both are
  correct, not a misconfiguration. There is no API key that fills them. Run
  `docker compose run --rm disclosures` to harvest developer announcements,
  and `docker compose run --rm rank_sweep` to populate ranks; most games will
  legitimately stay Unknown and unranked.
- **Followers Δ14d is blank**: it needs two snapshots at least 14 days apart.
  Run `docker compose run --rm followers` daily; there is no way to backfill.

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
export DATABASE_URL=postgresql+asyncpg://steam:steam@localhost:9432/steam2026  # PowerShell: $env:DATABASE_URL="..."
alembic upgrade head
uvicorn app.main:app --reload --port 9100
```

Frontend:

```bash
cd frontend
npm install
# Linux/macOS:
NEXT_PUBLIC_API_URL=http://localhost:9100 npm run dev
# Windows (PowerShell):
$env:NEXT_PUBLIC_API_URL="http://localhost:9100"; npm run dev
```

## Tests

```bash
docker compose run --rm tests                                  # whole suite
docker compose run --rm tests python -m pytest tests/test_search_parse.py -v
```

No database and no network: every test is a pure-function test over saved
real payloads in `tests/fixtures/`. That is the point — these parsers fail
**silently**. A Steam markup change makes them return zero rows or `None`
rather than raising, and the result would be a shipped column quietly going
blank or, worse, filling with wrong values. The fixtures pin the shapes that
were observed live.

Locally without Docker: `pip install -e "./backend[dev]" && pytest` from the
repo root.

## Project phases

1. ✅ Architecture & database
2. ✅ Steam discovery service — `docker compose run --rm discovery` (see `scraper/README.md`)
3. ✅ Steam data collector — `docker compose run --rm collector`
4. ✅ Public market intelligence collector — `docker compose run --rm market`
   (or run the whole chain: `docker compose run --rm pipeline`)
5. ✅ REST API — http://localhost:9100/docs (`/api/v1/games`, dashboard, filters)
6. ✅ Frontend dashboard — http://localhost:4000 (`cd frontend && npm run dev` locally)
7. ✅ Charts & analytics — dashboard analytics grid + per-game stats history
8. ✅ Export system — CSV / Excel / JSON / Markdown of the current filtered view
   (buttons above the table, or `GET /api/v1/export?format=csv&...`); copies land in `exports/`
9. ✅ Community videos — lazy per-game YouTube/Twitch galleries with view
   counts, developer channel submissions + admin review (`/admin/submissions`),
   website/channel discovery workers (`websites`, `scanner`, `video_prefetch`)
10. ✅ First-party demand signals — community-hub followers + 14-day delta,
    Valve Top-Wishlists rank, and developer-disclosed wishlist counts
    harvested from Steam news (`followers`, `rank_sweep`, `disclosures`).
    Third-party estimate vendors retired: the wishlist column shows a
    confirmed disclosure or Unknown, never a derived figure.
