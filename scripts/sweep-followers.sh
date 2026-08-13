#!/usr/bin/env bash
# Run the follower sweep to completion, in resumable batches.
#
# A full-catalogue sweep is many hours at the polite 4s interval — longer than
# most shells or agent sessions live. Each batch commits as it goes and
# select_stale() skips anything already fresh, so this loop can be killed and
# restarted at any point without losing or repeating work.
#
# The loop registers a sweep_jobs row and passes its id to every batch, so the
# run shows up in /admin/sweeps with progress and an ETA, and the Pause/Stop
# buttons there control it — the same controls an API-launched sweep gets.
#
# Any extra arguments are passed straight through to the worker, so:
#
#   bash scripts/sweep-followers.sh                      # upcoming games only
#   bash scripts/sweep-followers.sh --include-released   # whole catalogue
#
# --include-released is what supplies training labels for outcome modelling:
# a released game has a MEASURED outcome (reviews, CCU), so pairing it with a
# follower trajectory is the only way to validate any demand model against
# something observable.
#
#   nohup bash scripts/sweep-followers.sh --include-released \
#     > logs/follower-sweep.log 2>&1 &
#
# Stopping it: press Stop in /admin/sweeps and the loop exits after the current
# batch. To kill it outright, kill the loop AND the container, or the container
# keeps going.
#   kill <loop-pid>; docker ps --filter name=followers-run -q | xargs -r docker stop
set -uo pipefail
cd "$(dirname "$0")/.."
BATCH="${BATCH:-400}"

JOB="$(docker compose run --rm followers \
      python -m scraper.common.job_control create followers 2>/dev/null | tr -d '[:space:]')"
if [ -z "${JOB//[0-9]/}" ] && [ -n "$JOB" ]; then
  echo "registered sweep job $JOB — controllable from /admin/sweeps"
else
  echo "could not register a sweep job; running uncontrolled"
  JOB=""
fi

finish() {
  [ -n "$JOB" ] && docker compose run --rm followers \
    python -m scraper.common.job_control finish "$JOB" "$1" >/dev/null 2>&1
}
# Ctrl-C or a kill should not leave the row claiming to be running.
trap 'finish interrupted; exit 130' INT TERM

while :; do
  out="$(docker compose run --rm followers \
        python -m workers.refresh_followers --limit "$BATCH" \
        ${JOB:+--job-id "$JOB"} "$@" 2>&1)"
  echo "$out" | grep -E 'scanned|Summary|Nothing stale' || echo "$out" | tail -2

  # A stop from the UI makes the worker return early, which otherwise looks
  # like a normal batch and would start another one.
  if [ -n "$JOB" ]; then
    flags="$(docker compose run --rm followers \
            python -m scraper.common.job_control flags "$JOB" 2>/dev/null | tr -d '\r')"
    if [ "${flags##* }" = "1" ]; then
      echo "stop requested from the admin UI — exiting after this batch"
      finish cancelled
      exit 0
    fi
  fi

  if echo "$out" | grep -q "Nothing stale to refresh"; then
    echo "sweep complete: nothing stale left"
    finish done
    break
  fi
  if ! echo "$out" | grep -q "Summary"; then
    echo "batch did not finish cleanly; retrying in 30s"
    sleep 30
  fi
done
