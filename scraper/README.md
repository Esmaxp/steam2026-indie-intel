# scraper/

AsyncIO scraping pipeline (Phases 2–4).

- `discovery/` — ✅ Phase 2: Steam 2026 indie game discovery
- `collectors/` — Steam store data, public market data, business data (Phases 3–4)
- `classifiers/` — dimension / camera / graphics style / engine (Phase 3)
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
