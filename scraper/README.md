# scraper/

AsyncIO scraping pipeline (Phases 2–4).

- `discovery/` — ✅ Phase 2: Steam 2026 indie game discovery
- `collectors/` — ✅ Phase 3 store data + ✅ Phase 4 market/business data
- `classifiers/` — ✅ Phase 3: dimension / camera / graphics style / engine

**Fetch everything in one go:** `docker compose run --rm pipeline`
(discovery → store data for the whole queue → market data for the whole
queue; every step is checkpointed, so interrupting and re-running resumes).
- `common/` — rate-limited retrying HTTP client, resume via `sync_states`, logging

## Discovery (Phase 2)

Two automatic modes — no manually curated lists:

**search** (default, fast): Steam Search filtered to the Indie tag.
Pass 1 walks released games sorted by release date (newest first) and stops
once results fall before 2026. Pass 2 walks coming-soon games and keeps those
whose announced date mentions 2026. Undated "Coming soon"/"TBA" entries are
skipped — their year is unknown and data is never guessed; later re-runs pick
them up once Steam shows a date.

**applist** (exhaustive backstop): `ISteamApps/GetAppList/v2` lists every app
on Steam; each candidate is validated via the appdetails API (type=game,
Indie genre id 23, release year 2026). ~1 request / 1.5 s, so the full
catalog takes a long time — progress is checkpointed per app in
`sync_states`, and each run validates `--limit` more apps, resuming
automatically.

Both modes upsert on AppID (no duplicates) and queue every found game for
Phase 3 store-data collection (`sync_states.stage = store_data`).

### Run

```bash
# via Docker Compose (db + backend must be up)
docker compose run --rm discovery                                # search mode
docker compose run --rm discovery python -m scraper.discovery.run --mode applist --limit 1000

# locally (from repo root)
pip install -e ./backend
set DATABASE_URL=postgresql+asyncpg://steam:steam@localhost:5432/steam2026
python -m scraper.discovery.run --mode search
```

Logs land in `logs/discovery.log`; progress bars show live status.

Rules: respect rate limits (search 1 req/s, appdetails 1 req/1.5 s), retry
with exponential backoff on 429/5xx, resume where stopped, never fabricate
data, AppID-keyed deduplication.

## Store data collector (Phase 3)

Processes the `store_data` queue that discovery filled. Per game it fetches:

- **appdetails** — name, description, developers/publishers, release info,
  early access (genre 70), genres, languages, prices, controller support,
  header/capsule images, screenshots, movies, demo appid
- **store page** — user tags with vote counts (parsed from `InitAppTagModal`)
- **Deck compatibility report** — verified / playable / unsupported / unknown
- **demo appdetails** — demo release date (a demo is its own Steam app)

Classification (`classifiers/classify.py`) is rule-based from tags + store
description + legal notice (engine detection: Unreal/Unity/Godot/GameMaker
copyright lines). Anything without a clear signal stays **unknown**.

Honesty notes: Steam page creation date and developer/publisher
country/website are not exposed by Steam → left NULL for Phase 4 public-source
enrichment. Launch price is only recorded when observed within 7 days of
release. Games whose release moved out of 2026 (or lost the Indie genre) are
removed and logged.

Games that pass are queued for Phase 4 (`market_data`).

```bash
docker compose run --rm collector                    # 200 queued games
docker compose run --rm collector python -m scraper.collectors.run --limit 500
docker compose run --rm collector python -m scraper.collectors.run --appid 123456
```

Logs land in `logs/collector.log`. Default `--limit 0` processes the entire
queue (all discovered 2026 indie games).

## Market & business data collector (Phase 4)

Processes the `market_data` queue that the store collector filled. Per game:

- **Steam appreviews API** — positive/negative/total reviews, review score
  (authoritative Steam data)
- **SteamCharts** — all-time peak CCU + last-30-days average CCU (public
  aggregator; games without a chart simply stay NULL)
- **Steam News API** — Steam Next Fest participation, recorded only when an
  official news item mentions it (the news link is stored as the source)
- **Gamalytic public API** — wishlist / copies sold / gross revenue / owners
  **estimates**, stored append-only with `status = estimated` and source URL

Provenance guarantees: Steam does not expose wishlist/revenue — those are
only written when a public estimator provides a number, always flagged
`estimated` with a source; nothing found = no record = Unknown in the UI.
Review stats snapshots accumulate over time in `steam_stats` (append-only),
so re-running the collector builds a history.

```bash
docker compose run --rm market
docker compose run --rm market python -m scraper.collectors.run_market --appid 123456
```

Logs land in `logs/market.log`.
