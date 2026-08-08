# workers/

Scheduled background jobs.

## refresh_stats

Re-queues released games for market-data collection and runs the collector,
so `steam_stats` accumulates daily snapshots (the time-series charts on game
detail pages need at least two).

```bash
docker compose run --rm refresher                 # default: refresh > 20h old
python -m workers.refresh_stats --min-age-hours 20
```

Schedule it daily, e.g.:

- **Windows Task Scheduler**: run
  `docker compose -f <repo>\docker-compose.yml run --rm refresher` daily at
  a quiet hour.
- **cron**: `0 6 * * * cd /path/to/repo && docker compose run --rm refresher`
