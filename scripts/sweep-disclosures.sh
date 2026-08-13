#!/usr/bin/env bash
# Harvest developer-disclosed wishlist counts to completion, in batches.
#
# Unlike the follower sweep, this worker has no staleness filter — it walks
# the catalogue in appid order — so the loop advances an explicit
# --start-appid instead of relying on the query to skip finished work.
# Ingestion is idempotent (partial unique index on appid+source_url+count),
# so an overlapping or repeated batch cannot duplicate a disclosure.
#
# Usage:
#   bash scripts/sweep-disclosures.sh                 # dry run, CSV to logs/
#   bash scripts/sweep-disclosures.sh --write         # insert CONFIRMED rows
#   nohup bash scripts/sweep-disclosures.sh --write > logs/disclosure-sweep.log 2>&1 &
#
# Resume after an interruption by passing the last appid it reported:
#   START=1234567 bash scripts/sweep-disclosures.sh --write
#
# Stopping it: kill the loop AND the container.
#   kill <loop-pid>; docker ps --filter name=disclosures-run -q | xargs -r docker stop
set -uo pipefail
cd "$(dirname "$0")/.."
BATCH="${BATCH:-400}"
START="${START:-0}"

while :; do
  out="$(docker compose run --rm disclosures \
        python -m workers.harvest_disclosures \
        --limit "$BATCH" --start-appid "$START" "$@" 2>&1)"
  echo "$out" | grep -E 'appid [0-9]+:|Summary|Scanning' || echo "$out" | tail -2

  if ! echo "$out" | grep -q "Summary"; then
    echo "batch did not finish cleanly; retrying in 30s"
    sleep 30
    continue
  fi

  scanned="$(echo "$out" | sed -n "s/.*'scanned': \([0-9]*\).*/\1/p" | tail -1)"
  if [ "${scanned:-0}" -lt "$BATCH" ]; then
    echo "harvest complete: last batch returned $scanned (< $BATCH)"
    break
  fi

  # Advance past the highest appid this batch covered. Queried rather than
  # parsed from the log, because a batch logs only the games that HAD a
  # disclosure — most produce no appid lines at all.
  next="$(docker compose exec -T db psql -U steam -d steam2026 -tAc \
    "SELECT COALESCE(MAX(appid),0)+1 FROM (
       SELECT appid FROM games WHERE appid >= $START ORDER BY appid LIMIT $BATCH
     ) t" | tr -d '[:space:]')"
  if [ -z "$next" ] || [ "$next" -le "$START" ]; then
    echo "could not advance past appid $START — stopping rather than looping forever"
    break
  fi
  START="$next"
  echo "--- next batch from appid $START ---"
done
