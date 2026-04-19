#!/usr/bin/env bash
# ci-schema-dump.sh — generate a CI-compatible schema snapshot from fortress_shadow.
#
# Produces:
#   fortress-guest-platform/ci/schema.sql       — schema-only pg_dump, CI-adapted
#   fortress-guest-platform/ci/schema.meta.json — alembic heads, git tree hash, timestamp
#
# Usage:
#   bash scripts/ci-schema-dump.sh [DB_NAME]
#   DB_NAME defaults to fortress_shadow
#
# The dump is CI-adapted:
#   - CREATE EXTENSION postgis / vector are removed (not in postgres:16 container)
#   - geometry column type replaced with text (parcels.geom)
#   - vector(N) column type replaced with text (property_knowledge_chunks.embedding)
#   - SET ROLE TO fortress_admin prepended so objects are owned by fortress_admin
#
# On production databases these tables already have the correct types; the
# type substitution only affects fresh CI DBs where no data is present.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CI_DIR="$REPO_ROOT/fortress-guest-platform/ci"
DB="${1:-fortress_shadow}"

echo "[ci-schema-dump] source DB: $DB"
echo "[ci-schema-dump] output dir: $CI_DIR"

# --- alembic heads ---
ALEMBIC_HEADS=$(cd "$REPO_ROOT/fortress-guest-platform" && \
  PYTHONPATH="$PWD" .uv-venv/bin/alembic -c backend/alembic.ini heads 2>/dev/null \
  | grep "(head)" | awk '{print $1}' | sort | tr '\n' ',' | sed 's/,$//')
echo "[ci-schema-dump] alembic heads: $ALEMBIC_HEADS"

# --- git state ---
COMMIT=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
TREE_HASH=$(git -C "$REPO_ROOT" rev-parse HEAD:fortress-guest-platform/backend/alembic/versions 2>/dev/null || echo "unknown")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# --- generate raw dump ---
echo "[ci-schema-dump] running pg_dump ..."
RAW=$(pg_dump \
  --schema-only \
  --no-owner \
  --no-privileges \
  --no-tablespaces \
  --no-comments \
  "$DB" 2>/dev/null)

# --- CI-adapt the dump ---
# 1. Remove postgis and vector CREATE EXTENSION (not available in postgres:16 container)
# 2. Replace geometry column type with text (parcels.geom — not used by E2E tests)
# 3. Replace vector(N) with text (property_knowledge_chunks.embedding — not used by E2E tests)
ADAPTED=$(echo "$RAW" \
  | grep -v "CREATE EXTENSION IF NOT EXISTS postgis" \
  | grep -v "CREATE EXTENSION IF NOT EXISTS vector" \
  | grep -v "^COMMENT ON EXTENSION postgis" \
  | grep -v "^COMMENT ON EXTENSION vector" \
  | sed 's/ geometry\b/ text/g' \
  | sed 's/ geometry(/ text --(geometry(/g' \
  | sed 's/ public\.geometry([^)]*) / text /g' \
  | sed 's/ public\.geometry([^)]*),/ text,/g' \
  | sed "s/ vector([0-9]*) / text /g" \
  | sed "s/ vector([0-9]*)$/ text/g" \
  | sed "s/ public\.vector([0-9]*) / text /g" \
  | sed "s/ public\.vector([0-9]*)$/ text/g" \
  | grep -v "USING gist")

# --- write schema.sql ---
{
  echo "-- CI schema snapshot for fortress-guest-platform"
  echo "-- Generated: $TIMESTAMP"
  echo "-- Source:    $DB"
  echo "-- Commit:    $COMMIT"
  echo "-- Alembic:   $ALEMBIC_HEADS"
  echo "-- NOTE: geometry/vector types replaced with text for CI compatibility."
  echo "--       postgis/vector extensions omitted (postgres:16 has pgcrypto/uuid-ossp)."
  echo ""
  echo "SET statement_timeout = 0;"
  echo "SET lock_timeout = 0;"
  echo "SET client_encoding = 'UTF8';"
  echo "SET standard_conforming_strings = on;"
  echo ""
  echo "-- Ensure all objects are created as fortress_admin (matches CI role provisioning)"
  echo "SET ROLE TO fortress_admin;"
  echo ""
  echo "$ADAPTED"
} > "$CI_DIR/schema.sql"

# --- write schema.meta.json ---
python3 - <<PYEOF > "$CI_DIR/schema.meta.json"
import json
heads = [h for h in "$ALEMBIC_HEADS".split(",") if h]
print(json.dumps({
    "alembic_revisions": heads,
    "alembic_versions_tree": "$TREE_HASH",
    "generated_at": "$TIMESTAMP",
    "source_db": "$DB",
    "source_commit": "$COMMIT",
}, indent=2))
PYEOF

SCHEMA_LINES=$(wc -l < "$CI_DIR/schema.sql")
SCHEMA_SIZE=$(du -sh "$CI_DIR/schema.sql" | cut -f1)
echo "[ci-schema-dump] schema.sql: $SCHEMA_LINES lines, $SCHEMA_SIZE"
echo "[ci-schema-dump] Done. Commit fortress-guest-platform/ci/ to activate."
