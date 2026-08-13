#!/usr/bin/env bash
# Harvest developer-disclosed wishlist counts to completion, in batches.
#
# Unlike the follower sweep, this worker has no staleness filter — it walks
# the catalogue in appid order — so the loop advances an explicit
# --start-appid instead of relying on the query to skip finished work.
# Ingestion is idempotent (partial unique index on appid+source_url+count),
# so an overlapping or repeated batch cannot duplicate a disclosure.
#
# The loop registers a sweep_jobs row and passes its id to every batch, so the
# run shows up in /admin/sweeps with progress and an ETA, and the Pause/Stop
# buttons there control it — the same controls an API-launched sweep gets.
#
# Usage:
#   bash scripts/sweep-disclosures.sh                 # dry run, CSV to logs/
#   bash scripts/sweep-disclosures.sh --write         # insert CONFIRMED rows
#   nohup bash scripts/sweep-disclosures.sh --write > logs/disclosure-sweep.log 2>&1 &
#
# Resume after an interruption by passing the last appid it reported:
#   START=1234567 bash scripts/sweep-disclosures.sh --write
#
# Stopping it: press Stop in /admin/sweeps and the loop exits after the current
# batch. To kill it outright, kill the loop AND the container.
#   kill <loop-pid>; docker ps --filter name=disclosures-run -q | xargs -r docker stop
set -uo pipefail
cd "$(dirname "$0")/.."
BATCH="${BATCH:-400}"
START="${START:-0}"

JOB="$(docker compose run --rm disclosures \
      python -m scraper.common.job_control create disclosures "$START" \
      2>/dev/null | tr -d '[:space:]')"
if [ -z "${JOB//[0-9]/}" ] && [ -n "$JOB" ]; then
  echo "registered sweep job $JOB — controllable from /admin/sweeps"
else
  echo "could not register a sweep job; running uncontrolled"
  JOB=""
fi

finish() {
  [ -n "$JOB" ] && docker compose run --rm disclosures \
    python -m scraper.common.job_control finish "$JOB" "$1" >/dev/null 2>&1
}
trap 'finish interrupted; exit 130' INT TERM

while :; do
  out="$(docker compose run --rm disclosures \
        python -m workers.harvest_disclosures \
        --limit "$BATCH" --start-appid "$START" \
        ${JOB:+--job-id "$JOB"} "$@" 2>&1)"
  echo "$out" | grep -E 'appid [0-9]+:|Summary|Scanning' || echo "$out" | tail -2

  # A stop from the UI makes the worker return early, which otherwise looks
  # like a short final batch and would be reported as completion.
  if [ -n "$JOB" ]; then
    flags="$(docker compose run --rm disclosures \
            python -m scraper.common.job_control flags "$JOB" 2>/dev/null | tr -d '\r')"
    if [ "${flags##* }" = "1" ]; then
      echo "stop requested from the admin UI — exiting after this batch"
      finish cancelled
      exit 0
    fi
  fi

  if ! echo "$out" | grep -q "Summary"; then
    echo "batch did not finish cleanly; retrying in 30s"
    sleep 30
    continue
  fi

  scanned="$(echo "$out" | sed -n "s/.*'scanned': \([0-9]*\).*/\1/p" | tail -1)"
  if [ "${scanned:-0}" -lt "$BATCH" ]; then
    echo "harvest complete: last batch returned $scanned (< $BATCH)"
    finish done
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
    finish failed
    break
  fi
  START="$next"
  echo "--- next batch from appid $START ---"
done
