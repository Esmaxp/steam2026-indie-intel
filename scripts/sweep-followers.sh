#!/usr/bin/env bash
# Run the follower sweep to completion, in resumable batches.
#
# A full-catalogue sweep is many hours at the polite 4s interval — longer than
# most shells or agent sessions live. Each batch commits as it goes and
# select_stale() skips anything already fresh, so this loop can be killed and
# restarted at any point without losing or repeating work.
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
# Stopping it: kill the loop AND the container, or the container keeps going.
#   kill <loop-pid>; docker ps --filter name=followers-run -q | xargs -r docker stop
set -uo pipefail
cd "$(dirname "$0")/.."
BATCH="${BATCH:-400}"

while :; do
  out="$(docker compose run --rm followers \
        python -m workers.refresh_followers --limit "$BATCH" "$@" 2>&1)"
  echo "$out" | grep -E 'scanned|Summary|Nothing stale' || echo "$out" | tail -2
  if echo "$out" | grep -q "Nothing stale to refresh"; then
    echo "sweep complete: nothing stale left"
    break
  fi
  if ! echo "$out" | grep -q "Summary"; then
    echo "batch did not finish cleanly; retrying in 30s"
    sleep 30
  fi
done
