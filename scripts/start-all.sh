#!/usr/bin/env bash
# Restart the local stack: db + backend + frontend.
#
# Stops whatever this project already has running, brings it back up, and
# waits until the backend reports healthy and the frontend answers — so when
# the script returns, the URLs it prints actually work.
#
# WHY IT DOES NOT KILL BY PORT:
# The obvious implementation — find the PID on port 4000 and kill it — is
# actively dangerous here. On macOS with Colima (and Docker Desktop, and any
# VM-backed runtime) the process listening on a published port is the
# runtime's own forwarder, not the app:
#
#     ssh  51812  ssh: /Users/volkan/.colima/_lima/colima/ssh.sock [mux]
#
# Killing that takes down Docker itself, and on a shared machine the listener
# might belong to somebody else's app entirely — these ports were chosen in
# the first place to stop colliding with other local projects. So this script
# stops containers through `docker compose`, kills stray host processes ONLY
# when it can prove they belong to this repo, and merely warns about anything
# else holding a port.
#
# Usage:
#   ./scripts/start-all.sh            restart the stack and wait for health
#   ./scripts/start-all.sh --build    rebuild images first (after code changes)
#   ./scripts/start-all.sh --logs     restart, then follow backend+frontend logs
#   ./scripts/start-all.sh --stop     stop the stack and exit
#   ./scripts/start-all.sh --help
set -euo pipefail
cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd -P)"

SERVICES=(db backend frontend)
BACKEND_PORT="${BACKEND_PORT:-9100}"
FRONTEND_PORT="${FRONTEND_PORT:-4000}"
POSTGRES_PORT="${POSTGRES_PORT:-9432}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"

DO_BUILD=0
DO_LOGS=0
DO_STOP=0

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
warn() { printf '\033[33m!\033[0m %s\n' "$1"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$1"; }
die()  { printf '\033[31m✗\033[0m %s\n' "$1" >&2; exit 1; }

# Print the header comment block, stopping at the first line of actual code.
usage() {
  awk 'NR>1 && /^#/ { sub(/^# ?/, ""); print; next } NR>1 { exit }' "$0"
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --build) DO_BUILD=1 ;;
    --logs)  DO_LOGS=1 ;;
    --stop)  DO_STOP=1 ;;
    -h|--help) usage ;;
    *) die "unknown option: $1  (try --help)" ;;
  esac
  shift
done

command -v docker >/dev/null 2>&1 || die "docker not found on PATH"
docker compose version >/dev/null 2>&1 || die "docker compose v2 is required"
docker info >/dev/null 2>&1 || die "the Docker daemon is not reachable — start it first (e.g. colima start)"

# --- stray host processes from the non-Docker dev path ----------------------
# Only ever kills a process whose working directory is inside THIS repo, so a
# uvicorn/next belonging to another checkout (or another project entirely) is
# left alone.
process_cwd() {
  # `|| true`: lsof exits non-zero when it finds nothing, and under set -e a
  # failing command substitution would abort the whole script.
  lsof -a -d cwd -p "$1" -Fn 2>/dev/null | sed -n 's/^n//p' | head -1 || true
}

kill_repo_dev_servers() {
  local killed=0 pid cwd
  for pid in $(pgrep -f 'uvicorn app.main:app' 2>/dev/null || true) \
             $(pgrep -f 'next dev|next-server|next start' 2>/dev/null || true); do
    cwd="$(process_cwd "$pid")"
    case "$cwd" in
      "$REPO_ROOT"|"$REPO_ROOT"/*)
        warn "stopping local dev server from this repo (pid $pid)"
        kill "$pid" 2>/dev/null || true
        killed=1
        ;;
    esac
  done
  [ "$killed" -eq 1 ] && sleep 1
  return 0
}

# Report — never kill — anything else sitting on a port we are about to bind.
report_foreign_listeners() {
  local port owner
  for port in "$BACKEND_PORT" "$FRONTEND_PORT" "$POSTGRES_PORT"; do
    owner="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1" (pid "$2")"}' || true)"
    if [ -n "$owner" ]; then
      case "$owner" in
        ssh*|com.docke*|docker*|vpnkit*)
          : ;;  # the container runtime's own forwarder — expected
        *)
          warn "port $port is held by $owner — not this project, and NOT killed."
          warn "  If that is a leftover of yours, stop it yourself, or change the"
          warn "  host-side port in docker-compose.yml."
          ;;
      esac
    fi
  done
}

stop_stack() {
  bold "Stopping ${SERVICES[*]}…"
  docker compose stop "${SERVICES[@]}" >/dev/null 2>&1 || true
  # Remove the containers too, so a rebuilt image is actually picked up.
  docker compose rm -fs "${SERVICES[@]}" >/dev/null 2>&1 || true
  kill_repo_dev_servers
  ok "stopped"
}

wait_for_backend() {
  local waited=0
  printf 'Waiting for backend'
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    if curl -fsS "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
      printf '\n'; return 0
    fi
    # Fail fast on a container that died rather than waiting out the timeout.
    if [ -z "$(docker compose ps -q backend)" ]; then
      printf '\n'; return 1
    fi
    printf '.'; sleep 2; waited=$((waited + 2))
  done
  printf '\n'; return 1
}

wait_for_frontend() {
  local waited=0
  printf 'Waiting for frontend'
  while [ "$waited" -lt "$HEALTH_TIMEOUT" ]; do
    if curl -fsS -o /dev/null "http://localhost:${FRONTEND_PORT}" 2>/dev/null; then
      printf '\n'; return 0
    fi
    printf '.'; sleep 2; waited=$((waited + 2))
  done
  printf '\n'; return 1
}

if [ "$DO_STOP" -eq 1 ]; then
  stop_stack
  exit 0
fi

stop_stack
report_foreign_listeners

bold "Starting ${SERVICES[*]}…"
if [ "$DO_BUILD" -eq 1 ]; then
  docker compose up -d --build "${SERVICES[@]}"
else
  docker compose up -d "${SERVICES[@]}"
fi

if wait_for_backend; then
  ok "backend  http://localhost:${BACKEND_PORT}  $(curl -fsS "http://localhost:${BACKEND_PORT}/health")"
else
  docker compose logs --tail 30 backend || true
  die "backend did not become healthy within ${HEALTH_TIMEOUT}s (logs above)"
fi

if wait_for_frontend; then
  ok "frontend http://localhost:${FRONTEND_PORT}"
else
  docker compose logs --tail 30 frontend || true
  die "frontend did not answer within ${HEALTH_TIMEOUT}s (logs above)"
fi

ok "postgres localhost:${POSTGRES_PORT}"

games="$(curl -fsS "http://localhost:${BACKEND_PORT}/api/v1/games?page_size=1" 2>/dev/null \
  | sed -n 's/.*"total":\([0-9]*\).*/\1/p' | head -1 || true)"
if [ "${games:-0}" -eq 0 ] 2>/dev/null; then
  warn "the catalogue is empty — run:  docker compose run --rm db_restore"
else
  ok "catalogue: ${games} games"
fi

if [ "$DO_LOGS" -eq 1 ]; then
  bold "Following logs (Ctrl-C to stop; the stack keeps running)…"
  docker compose logs -f backend frontend
fi
