#!/usr/bin/env bash
# Run the follower sweep to completion, in resumable batches.
#
# A full catalogue sweep is ~5 hours at the polite 4s interval, which is
# longer than most shells or agent sessions live. Each batch commits as it
# goes and select_stale() skips anything already fresh, so this loop can be
# killed and restarted at any point without losing or repeating work.
#
# Usage:
#   bash scripts/sweep-followers.sh              # run in the foreground
#   nohup bash scripts/sweep-followers.sh > logs/follower-sweep.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."
BATCH="${BATCH:-400}"

while :; do
  out="$(docker compose run --rm followers \
        python -m workers.refresh_followers --limit "$BATCH" 2>&1)"
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
