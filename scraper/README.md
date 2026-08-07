# scraper/

AsyncIO scraping pipeline (Phases 2–4).

- `discovery/` — Steam App List → filter to 2026 indie games (Phase 2)
- `collectors/` — Steam store data, public market data, business data (Phases 3–4)
- `classifiers/` — dimension / camera / graphics style / engine (Phase 3)
- `common/` — rate limiter, retry with backoff, resume via `sync_states`, tqdm progress

Rules: respect rate limits, retry failures, resume where stopped, log to
`logs/`, never fabricate data, AppID-keyed deduplication.
