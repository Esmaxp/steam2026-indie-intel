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
│                        Data Sources                             │
│  Steam App List API · Steam Store API · Steam Store Pages       │
│  Steam Search · Steam News · Steam Events                       │
│  SteamDB · Steam Charts · VG Insights · Gamalytic ·             │
│  GameDiscoverCo · Kickstarter · Press / Dev blogs (public only) │
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
│   Alembic migrations          │  genres · tags · stats · revenue
│                               │  wishlist · marketing · festivals
└───────────────┬───────────────┘  media · sync_states
                │
┌───────────────▼───────────────┐      ┌──────────────────────────┐
│   backend/  FastAPI REST API  │◄─────┤ exports/ CSV·XLSX·JSON·MD │
│   search·filter·sort·paginate │      └──────────────────────────┘
└───────────────┬───────────────┘
                │  React Query
┌───────────────▼───────────────┐
│   frontend/  Next.js + TS     │  Dashboard · Table · Filters
│   Tailwind · shadcn/ui        │  Game detail pages · Charts
│   TanStack Table · Recharts   │  http://localhost:3000
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
- `peak_ccu`, `avg_ccu`, `followers` (NULL when not publicly available)
- `source_name`, `source_url`

**wishlist_records** — append-only, provenance-tracked
- `id` PK, `appid` FK, `status` data_status, `wishlist_count` (nullable),
  `source_name`, `source_url`, `recorded_at`, `notes`

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
child tables, `steam_stats (appid, captured_at DESC)`.

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
| 4     | Public market & business intelligence collector | pending |
| 5     | REST API (search/filter/sort/paginate/export endpoints) | pending |
| 6     | Frontend dashboard (Next.js)               | pending |
| 7     | Charts and analytics                       | pending |
| 8     | Export system (CSV/Excel/JSON/Markdown)    | pending |

Each phase is committed before the next one starts.

---

## 8. Running (Phase 1 state)

```bash
docker compose up --build
# → PostgreSQL on :5432, migrations applied automatically,
#   FastAPI on http://localhost:8000  (GET /health, GET /docs)
```

Frontend joins Docker Compose in Phase 6 and will serve
`http://localhost:3000`.
