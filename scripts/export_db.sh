#!/usr/bin/env bash
# One-shot database snapshot for the fast-clone restore path.
#
# Run this MANUALLY, locally, whenever the catalog has grown enough to be
# worth refreshing (e.g. weekly) — never from CI or a schedule. The stack
# must be up (docker compose up -d).
#
# The dump deliberately INCLUDES alembic_version: the restored database is
# then self-consistent at the export's schema revision, and the documented
# follow-up step `docker compose run --rm backend alembic upgrade head`
# applies anything that landed after the export. (Excluding it would leave
# head bookkeeping pointing at old-schema tables — silently broken.)
#
# Usage:  bash scripts/export_db.sh
set -euo pipefail
cd "$(dirname "$0")/.."

POSTGRES_USER="${POSTGRES_USER:-steam}"
POSTGRES_DB="${POSTGRES_DB:-steam2026}"
OUT_DIR="database/seed"
DUMP="$OUT_DIR/full_export.dump"
META="$OUT_DIR/full_export.meta.txt"

mkdir -p "$OUT_DIR"

echo "Dumping $POSTGRES_DB (custom format, compressed)..."
docker compose exec -T db pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB" > "$DUMP"

GAMES=$(docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c "SELECT count(*) FROM games;")
REVISION=$(docker compose exec -T backend alembic current 2>/dev/null | tail -1 | tr -d '\r')
SIZE=$(du -h "$DUMP" | cut -f1)

cat > "$META" <<EOF
exported_at: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
games_rows: $GAMES
alembic_revision: $REVISION
dump_size: $SIZE
restore: docker compose run --rm db_restore
then:    docker compose run --rm backend alembic upgrade head
note: prices, reviews, followers and wishlist ranks are only as fresh as
      exported_at. Run 'docker compose run --rm refresher' for current
      stats, 'followers' and 'rank_sweep' for current demand signals, or
      'pipeline' to re-discover games released since this snapshot.
EOF

echo "Wrote $DUMP ($SIZE, $GAMES games, revision: $REVISION)"
cat "$META"
