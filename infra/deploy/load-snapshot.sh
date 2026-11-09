#!/usr/bin/env bash
# Load the 98-document snapshot corpus into the echr-deploy compose database.
#
#   infra/deploy/load-snapshot.sh            # ingest: build it from data/snapshot inside the image
#   infra/deploy/load-snapshot.sh dump       # restore a pg_dump of a dev database (fast, no models)
#
# Never touches the echr-lookup compose project's data: dump mode only READS the source DB.
# Env: SRC_CONTAINER (default echr-lookup-db-1), SRC_DB (default echr_m3), SRC_USER (default echr).
set -euo pipefail

cd "$(dirname "$0")/../.."
MODE="${1:-ingest}"
COMPOSE=(docker compose -f infra/deploy/compose.yml -p echr-deploy)
[ -n "${IMAGE_TARGET:-}" ] && [ "$IMAGE_TARGET" = runtime-slim ] && \
  COMPOSE=(docker compose -f infra/deploy/compose.yml -f infra/deploy/compose.slim.yml -p echr-deploy)

"${COMPOSE[@]}" up -d --wait db
start=$(date +%s)

case "$MODE" in
  ingest)
    # --reset empties the app tables and re-applies infra/migrations, then embeds every chunk.
    "${COMPOSE[@]}" run --rm --no-deps api python -m rag.ingest --source snapshot --reset
    ;;
  dump)
    SRC_CONTAINER="${SRC_CONTAINER:-echr-lookup-db-1}"
    SRC_DB="${SRC_DB:-echr_m3}"
    SRC_USER="${SRC_USER:-echr}"
    # Extensions already exist in the target (infra/init); the dump recreates only the tables.
    docker exec "$SRC_CONTAINER" pg_dump -U "$SRC_USER" -d "$SRC_DB" \
      --clean --if-exists --no-owner --no-acl --exclude-extension='*' --exclude-schema=paradedb \
      | "${COMPOSE[@]}" exec -T db psql -U echr -d echr -v ON_ERROR_STOP=1 -q -o /dev/null
    ;;
  *)
    echo "usage: $0 [ingest|dump]" >&2
    exit 2
    ;;
esac

# Apply infra/migrations (e.g. M1's tool_log table) that the source database may not have.
"${COMPOSE[@]}" run --rm --no-deps api python -c \
  "from rag.index import connect, migrate; migrate(connect())"

echo "loaded in $(( $(date +%s) - start )) s ($MODE)"
"${COMPOSE[@]}" exec -T db psql -U echr -d echr -Atc \
  "SELECT 'documents=' || (SELECT count(*) FROM documents) || ' paragraphs=' || (SELECT count(*) FROM paragraphs) || ' chunks=' || (SELECT count(*) FROM chunks)"
