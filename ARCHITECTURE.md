# Steam 2026 Indie Intelligence Platform — Architecture Plan

> Phase 1 deliverable. This document defines the full architecture, folder
> structure, database schema, API specification and implementation roadmap
> before any feature code is written.

---

## 1. Overview

A production-ready platform that automatically **discovers, collects,
classifies and analyses every Steam indie game released during 2026**.

Core principles:

1. **Steam is the primary source.** No manually curated game lists.
2. **Never fabricate data.** Every business metric (wishlist, revenue, budget)
   carries a provenance status: `confirmed` | `estimated` | `unknown`, plus a
   source name/URL.
3. **Steam AppID is the primary key** across the whole system.
4. **Incremental phases**, each committed before the next one starts.

```
┌─────────────────────────────────────────────────────────────────┐
│                  Data Sources — Valve first-party                │
│  Steam App List API · Steam Store API · Steam Store Pages       │
│  Steam Search · Steam News · Steam Events                       │
│  Steam Top-Wishlists chart · Steam community hubs (followers)   │
├─────────────────────────────────────────────────────────────────┤
│  Labelled non-Valve exceptions (badged as such in the UI):      │
│  SteamCharts — concurrent players, a measurement not a model    │
│  YouTube / Twitch — community clips; content, not demand data   │
└───────────────┬─────────────────────────────────────────────────┘
                │  aiohttp (+ Playwright only when unavoidable)
┌───────────────▼───────────────┐
│   scraper/  (AsyncIO)         │  discovery → store data →
│   resume · retry · rate-limit │  classification → market data →
│   progress bar · logging      │  business data
└───────────────┬───────────────┘
                │  SQLAlchemy (async)
┌───────────────▼───────────────┐
│   PostgreSQL (normalized)     │  games · developers · publishers
│   Alembic migrations          │  genres · tags · steam_stats
│                               │  follower_snapshots · wishlist_rank_*
└───────────────┬───────────────┘  wishlist · marketing · festivals
                                   media · sync_states
                │
┌───────────────▼───────────────┐      ┌──────────────────────────┐
│   backend/  FastAPI REST API  │◄─────┤ exports/ CSV·XLSX·JSON·MD │
│   search·filter·sort·paginate │      └──────────────────────────┘
└───────────────┬───────────────┘
                │  React Query
┌───────────────▼───────────────┐
│   frontend/  Next.js + TS     │  Dashboard · Table · Filters
│   Tailwind · shadcn/ui        │  Game detail pages · Charts
│   TanStack Table · Recharts   │  http://localhost:4000
└───────────────────────────────┘
```

---

## 2. Tech Stack

| Layer      | Technology                                                        |
|------------|-------------------------------------------------------------------|
| Backend    | Python 3.13, FastAPI, SQLAlchemy 2 (async), Alembic, asyncpg      |
| Scraping   | AsyncIO, aiohttp, BeautifulSoup4, Playwright (last resort only)   |
| Data/Export| Pandas, OpenPyXL                                                  |
| Database   | PostgreSQL 16                                                     |
| Frontend   | Next.js, React, TypeScript, TailwindCSS, shadcn/ui, TanStack Table, React Query, Recharts |
| Deployment | Docker Compose                                                    |

---

## 3. Folder Structure

```
game_marketing/
├── docker-compose.yml         # db + backend (+ frontend in Phase 6)
├── .env.example               # environment template
├── ARCHITECTURE.md            # this document
├── README.md
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py             # async migration environment
│   │   └── versions/          # schema migrations
│   └── app/
│       ├── main.py            # FastAPI entrypoint
│       ├── core/
│       │   ├── config.py      # pydantic-settings configuration
│       │   └── logging.py     # structured logging setup
│       ├── db/
│       │   ├── base.py        # DeclarativeBase + naming conventions
│       │   └── session.py     # async engine / session factory
│       ├── models/            # SQLAlchemy ORM models (Phase 1)
│       ├── schemas/           # Pydantic schemas        (Phase 5)
│       ├── api/               # REST routers            (Phase 5)
│       └── services/          # export service etc.     (Phase 8)
│
├── scraper/                   # Phase 2–4: discovery + collectors
│   ├── discovery/             # Steam app list → 2026 indie filter
│   ├── collectors/            # store data, market data, business data
│   ├── classifiers/           # dimension / camera / graphics / engine
│   └── common/                # rate limiter, retry, resume, progress
│
├── workers/                   # scheduled jobs (refresh stats, re-sync)
├── database/
│   └── init/                  # PostgreSQL init scripts (extensions)
├── frontend/                  # Phase 6–7: Next.js dashboard
├── exports/                   # generated CSV / Excel / JSON / Markdown
├── logs/                      # scraper + app logs
└── media/                     # optionally cached images
```

---

## 4. Database Schema (PostgreSQL, normalized)

### Provenance policy

Every value that Steam does **not** expose (wishlist, revenue, budget,
developer/publisher country) is stored with:

- `status` — enum `data_status`: `confirmed` / `estimated` / `unknown`
- `source_name` + `source_url` — where the value came from
- `recorded_at` — when it was observed

If no public source exists, the value stays `NULL` with status `unknown`.
**Values are never invented.**

### Enum types

| Enum                 | Values                                                                 |
|----------------------|------------------------------------------------------------------------|
| `data_status`        | confirmed, estimated, unknown                                          |
| `dimension`          | 2d, 2.5d, 3d, unknown                                                  |
| `camera`             | top_down, isometric, first_person, third_person, side_scroller, unknown|
| `graphics_style`     | pixel_art, hd_pixel_art, voxel, stylized, low_poly, realistic, anime, hand_painted, ps1_style, ps2_style, unknown |
| `game_engine`        | unity, unreal, godot, gamemaker, custom, unknown                       |
| `controller_support` | full, partial, none, unknown                                           |
| `steam_deck_support` | verified, playable, unsupported, unknown                               |
| `media_type`         | header, capsule, screenshot, movie                                     |
| `sync_stage`         | discovery, store_data, classification, market_data, business_data      |
| `sync_status`        | pending, in_progress, done, failed, skipped                            |

### Tables

**games** — one row per Steam app (PK = `appid`, no surrogate key)
- `appid` BIGINT PK, `name`, `short_description`
- `steam_store_url`, `steamdb_url`
- `release_date` DATE, `release_date_raw` TEXT (Steam strings like "Q1 2026"),
  `is_released`, `coming_soon`, `early_access` BOOL
- `page_creation_date` DATE + `page_creation_source`
- `demo_available` BOOL, `demo_appid`, `demo_release_date`
- `is_free`, `currency`, `launch_price_cents`, `current_price_cents`,
  `launch_discount_pct`
- `controller_support`, `steam_deck_support` (enums)
- `supported_languages` JSONB
- `header_image_url`, `capsule_image_url`
- classification: `dimension`, `camera`, `graphics_style`, `engine`
  (all default `unknown`; classifier only upgrades when confident)
- `is_indie` BOOL (discovery filter result), `first_seen_at`, `last_synced_at`

**developers / publishers**
- `id` PK, `name` UNIQUE, `country` (+ `country_status` data_status),
  `website`, `notes`
- m2m junctions: `game_developers`, `game_publishers`

**genres** — `id` PK, `steam_genre_id` UNIQUE, `name`; junction `game_genres`

**tags** — `id` PK, `name` UNIQUE; junction `game_tags` (+ `rank`, `votes`)

**steam_stats** — append-only time-series snapshots
- `id` PK, `appid` FK, `captured_at`
- `positive_reviews`, `negative_reviews`, `total_reviews`, `positive_pct`,
  `review_score`, `review_score_desc`
- `peak_ccu`, `avg_ccu` (NULL when not publicly available)
- `followers` — vestigial; superseded by `follower_snapshots` and dropped in
  a later migration. Its only writer was the retired Gamalytic path.
- `source_name`, `source_url`

**follower_snapshots** — append-only, MEASURED community-hub member counts
- `id` PK, `appid` FK, `captured_at`, `followers` NOT NULL
- `source_name`, `source_url`
- Separate from `steam_stats` on purpose: `latest_stats_sq()` is
  `DISTINCT ON (appid) ORDER BY captured_at DESC`, so a follower-only row on
  the daily follower cadence would become "the latest stats row" and blank
  reviews/CCU for that game. The two run on different cadences (followers:
  daily, upcoming games; reviews/CCU: market queue, released games) and
  cannot share a DISTINCT-ON table.

**wishlist_rank_sweeps** — one row per Top-Wishlists sweep run
- `id` PK, `started_at`, `finished_at`, `cc` (region is part of the
  observation), `total_count`, `rows_ingested`, `status`, `source_url`, `notes`
- `status` CHECK in (complete, partial, failed). The header exists so a
  truncated sweep cannot pass as a complete one: consumers read rank only
  from `complete` sweeps, otherwise an aborted run reads as "everything below
  rank N left the chart" and fabricates enormous deltas.

**wishlist_rank_entries** — a game's ordinal position in one sweep
- `id` PK, `sweep_id` FK CASCADE, `appid`, `rank`, `name`
- UNIQUE (sweep_id, appid); INDEX (appid, sweep_id)
- `appid` deliberately has **no FK** to `games` — the chart is a global
  ~5.2k-row list across all of Steam while this catalogue is indie-only, so
  an FK would discard most rows and prevent backfilling rank history for a
  game discovered later. Consumers INNER JOIN to `games`.
- A rank is an ORDER, not a count. Valve blends total wishlists with recent
  velocity, so no wishlist count may be derived from it.

**wishlist_records** — append-only, provenance-tracked
- `id` PK, `appid` FK, `status` data_status, `wishlist_count` (nullable),
  `comparator` ('=' | '>='), `disclosed_on` (the announcement's own date, as
  distinct from `recorded_at` = ingestion time),
  `source_name`, `source_url`, `recorded_at`, `notes`
- Only ever `confirmed` (a developer stated the figure publicly) or
  `unknown`. No wishlist estimate is computed for any game.
- `comparator` is load-bearing: ~93% of harvested disclosures are round-number
  lower bounds ("over 100,000"), and recording those as exact would overstate
  what was said. Partial UNIQUE (appid, source_url, wishlist_count) WHERE
  source_url IS NOT NULL makes the harvester re-runnable.

**revenue_records** — append-only, provenance-tracked
- `id` PK, `appid` FK, `status` data_status
- `gross_revenue_usd`, `net_revenue_usd`, `estimated_sales`,
  `estimated_owners_min`, `estimated_owners_max` (all nullable)
- `source_name`, `source_url`, `recorded_at`, `notes`

**marketing_info** — one row per game
- `id` PK, `appid` FK UNIQUE
- `budget_estimate_usd` (nullable) + `budget_status` data_status
- `marketing_notes`, `developer_interview_url`, `publisher_interview_url`,
  `kickstarter_url`, `source_name`, `source_url`

**festivals** — `id` PK, `name`, `is_next_fest` BOOL, `start_date`, `end_date`
- junction `game_festivals` (+ `source_url`, `notes`)

**media_assets** — `id` PK, `appid` FK, `media_type` enum, `url`,
`thumbnail_url`, `position`, `local_path`

**sync_states** — scraper resume support (Phase 2+)
- `appid` + `stage` composite PK, `status` sync_status, `attempts`,
  `last_attempt_at`, `last_error`

Indexes: `games.name` (trigram via `pg_trgm` for fast ILIKE search),
`games.release_date`, `games.engine`, `games.dimension`, FK columns on all
child tables, `steam_stats (appid, captured_at DESC)`,
`follower_snapshots (appid, captured_at)`, `wishlist_rank_entries (appid, sweep_id)`.

**Sort order caveat:** the `data_status` enum cannot be ordered on directly.
`conflicting` was appended with `ALTER TYPE ADD VALUE` (migration 0003), so
PostgreSQL sorts it *after* `unknown` rather than ahead of it — a stale
`unknown` row would beat a fresh `conflicting` one. `games_query.status_priority()`
supplies the intended order as a CASE expression; use it, never the raw column.

---

## 5. API Specification (implemented in Phase 5)

Base URL: `/api/v1`

| Method | Path                    | Description                                        |
|--------|-------------------------|----------------------------------------------------|
| GET    | `/health`               | liveness + DB connectivity                         |
| GET    | `/games`                | list; search, filters, sort, pagination            |
| GET    | `/games/{appid}`        | full game detail (all relations, latest stats)     |
| GET    | `/games/{appid}/stats`  | stats time-series                                  |
| GET    | `/dashboard/summary`    | dashboard cards (totals, averages)                 |
| GET    | `/dashboard/charts`     | aggregations for Recharts (Phase 7)                |
| GET    | `/filters/options`      | distinct developers/publishers/genres/tags/engines |
| GET    | `/export`               | CSV / Excel / JSON / Markdown of filtered set      |

`GET /games` query parameters:
`q` (name search), `developer`, `publisher`, `genre`, `tag`, `engine`,
`dimension`, `graphics_style`, `camera`, `demo_available`, `next_fest`,
`release_month`, `min_reviews`, `min_positive_pct`, `min_peak_ccu`,
`wishlist_status`, `revenue_status`, `min_wishlist`, `min_revenue`,
`sort` (column, `-` prefix = desc), `page`, `page_size`.

Responses always expose provenance:
`{"wishlist": {"value": 12500, "status": "estimated", "source": "..."}}`.

---

## 6. Scraper Design (Phase 2–4)

- **AsyncIO pipeline** with per-domain token-bucket rate limiter
  (Steam Store API ≈ 1 req/1.5 s, conservative).
- **Resume support** via `sync_states` table — restart continues where it
  stopped, never re-fetches finished stages.
- **Retry** with exponential backoff + jitter on 429/5xx/network errors.
- **Progress bar** (tqdm) + structured file logging to `logs/`.
- **Deduplication** — AppID primary key; discovery upserts.
- Playwright used **only** where plain HTTP fails (e.g. JS-rendered pages).

Discovery filter (Phase 2): app list → appdetails → keep
`type == "game"`, release year 2026 (or coming_soon with 2026 date),
`genres` contains Indie (id 23) or tags contain "Indie".

Classification (Phase 3): rule-based signals — Steam tags (e.g. "Pixel
Graphics", "3D", "Isometric"), store description keywords, engine detection
via SteamDB tech page / demo depots / known engine artifacts. Anything
uncertain stays `unknown`.

---

## 7. Roadmap

| Phase | Deliverable                              | Status |
|-------|------------------------------------------|--------|
| 1     | Architecture, folder structure, database schema, Docker Compose, FastAPI skeleton | ✅ this commit |
| 2     | Steam discovery service (2026 indie games) | ✅ |
| 3     | Steam data collector + classification      | ✅ |
| 4     | Public market & business intelligence collector | ✅ |
| 5     | REST API (search/filter/sort/paginate/export endpoints) | ✅ (export arrives with Phase 8) |
| 6     | Frontend dashboard (Next.js)               | ✅ |
| 7     | Charts and analytics                       | ✅ |
| 8     | Export system (CSV/Excel/JSON/Markdown)    | ✅ |
| 9     | Community videos (per-game YouTube/Twitch galleries) | ✅ |
| 10    | First-party demand signals — followers, Top-Wishlists rank, developer disclosures; third-party estimate vendors retired | ✅ |

Phase 10 adds four on-demand services: `followers`, `rank_sweep`,
`disclosures` and `tests`. All are keyless except the video ones.

Each phase is committed before the next one starts.

---

## 8. Running (Phase 1 state)

```bash
docker compose up --build
# → PostgreSQL on :9432, migrations applied automatically,
#   FastAPI on http://localhost:9100  (GET /health, GET /docs)
```

Frontend joins Docker Compose in Phase 6 and will serve
`http://localhost:4000`.

---

## 9. Revenue & Budget Methodology (Phases 9–16)

### Indie filter (multi-signal)

The Steam "Indie" genre is the mandatory base filter. On top of it:
`games.indie_confidence` = **high** (self-published: developer == publisher,
suffix-insensitive), **medium** (third-party or Devolver-scale boutique
label), **low** (publisher matches the known AAA/AA list → also
`is_indie=false`; flagged, never deleted). Companies shipping 5+ titles in
any 30-day window get `low_quality_signal=true` on all their games
(mass-publishing / asset-flip pattern) — surfaced as a filter, not removed.

### Demand signals: measured, not modelled

Steam publishes no wishlist counts, and no third-party estimate of one has
ever been validated in public against a real Steamworks number. The project
therefore reports what Valve does publish, and refuses to derive the rest:

| Signal | Source | Status |
|---|---|---|
| Followers | community hub member count | measured, exact |
| Followers Δ14d | our own snapshots, differenced | measured |
| Wishlist rank | Steam Top-Wishlists chart | measured ordinal |
| Wishlist count | developer's own announcement | `confirmed`, else `unknown` |

**No wishlist number or range is ever derived.** A followers×k figure with a
constant k is a monotone transform of a column already on screen — zero added
information — and with a genre-varying k it reorders games on a coefficient
whose within-genre dispersion is unpublished. The observed wishlist/follower
ratio spans roughly 7.5×–30× and does not tighten with scale.

Disclosures are harvested from official Steam news
(`workers/harvest_disclosures.py`) and written only at `confirmed`, with the
announcement URL and its own date. Because that is the highest trust tier, the
harvester defaults to a dry run and requires `--write`.

### Revenue: estimated first-party, as a band, with its arithmetic attached

The third-party estimate vendors (Gamalytic, SteamSpy, VG Insights) were
retired and their rows deleted in migration 0013 — of 8,380 rows, 0 carried
revenue, 0 carried sales, and 99.8% were the 0–20,000 owners bucket.

What replaced them (migration 0017) is a first-party estimator:
`app/services/revenue_estimate.py` (pure, no DB) turns measured signals into
copies-sold bands, `workers/estimate_revenue.py` writes one
`revenue_estimates` row per signal, and the merge below rebuilds the
`revenue_records` summary from those rows.

- **reviews** — tiered multiplier (20/27/36/49/48× by review count), the
  level-setting signal. Gated at 10 reviews.
- **ccu** — all-time peak concurrents × 25/50/100. These factors were
  *fitted against the review estimator* on the 1,826 games where both fire,
  so agreement between the two is not independent confirmation. Listed in
  `revenue_merge.CROSS_CHECK_SOURCES`: it widens the band and shows up in
  `estimate_spread`, but never moves the summary value — concurrency runs
  high for multiplayer and low for short games at identical sales.
- **followers** — hub followers × 1.2/2.0/3.0, via wishlists. The only
  signal that works before launch.

Copies become money in one place (`to_revenue`): list price × 0.65 average
selling price, then × 0.70 Valve × 0.95 refunds × 0.90 regional/VAT. Free
games get copies but never revenue — their money is in items we do not
observe.

`workers/calibrate_revenue.py` compares the result against developer-
disclosed copies (harvested by `sales_disclosures.py`, promoted by a human)
and proposes a single global scalar — never a per-tier refit, which ten
data points cannot support.

`revenue_estimates` / `revenue_records` and `revenue_merge.merge_estimates()`
also still carry human-verified developer figures from
`disclosed_numbers_source.py`:
1. A Confirmed disclosure wins outright.
2. One estimate → passed through as `estimated`.
3. 2+ estimates → **median**; `estimate_spread = (max−min)/median`;
   spread > 0.5 → status **conflicting**, all sources listed and linked.

### Budget: two labeled heuristics, never fact

- **Confirmed** only from public disclosures entered via
  `disclosed_numbers_source.py` (source URL mandatory).
- **Method A (team_cost)** = team_size × dev_months × regional monthly cost
  (`budget_cost_tables.py`, cited). Missing any input → no calculation.
- **Method B (revenue_ratio)** = gross revenue × [0.20 .. 0.40], citing
  public GameDiscoverCo break-even analyses; skipped when revenue is
  conflicting/unknown.
Both methods store formula + exact inputs in `budget_estimates` (auditable);
the game page shows a "How was the budget estimated?" panel.
