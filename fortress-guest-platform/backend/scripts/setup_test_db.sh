#!/usr/bin/env bash
# Phase G.1.5 — Create and migrate fortress_shadow_test
#
# Idempotent: safe to run multiple times. Second run is a no-op if the DB
# already exists and is at the current alembic head.
#
# What this script does:
#   1. Creates fortress_shadow_test if it does not exist
#   2. Grants SELECT, INSERT, UPDATE, DELETE on all tables to fortress_api
#   3. Grants USAGE on all sequences to fortress_api
#   4. Runs alembic upgrade head against fortress_shadow_test
#
# Prerequisites:
#   - fortress_admin role must exist and have CREATEDB privilege
#   - fortress_api role must exist
#   - POSTGRES_ADMIN_URI must be set (points to fortress_shadow — we derive
#     the test DB URL from it by replacing the database name)
#
# Usage:
#   POSTGRES_ADMIN_URI="postgresql://fortress_admin:PASSWORD@127.0.0.1:5432/fortress_shadow" \
#     bash backend/scripts/setup_test_db.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Resolve base admin URI ────────────────────────────────────────────────────
if [[ -z "${POSTGRES_ADMIN_URI:-}" ]]; then
  ENV_FILE="${REPO_ROOT}/.env"
  if [[ -f "${ENV_FILE}" ]]; then
    POSTGRES_ADMIN_URI="$(grep '^POSTGRES_ADMIN_URI' "${ENV_FILE}" \
      | head -1 | cut -d= -f2- | tr -d '"' \
      | sed 's|postgresql+asyncpg://|postgresql://|')"
  fi
fi

if [[ -z "${POSTGRES_ADMIN_URI:-}" ]]; then
  echo "ERROR: POSTGRES_ADMIN_URI is not set."
  exit 1
fi

# Strip asyncpg driver prefix (pg_dump/psql need plain postgresql://)
ADMIN_URI_PLAIN="${POSTGRES_ADMIN_URI/postgresql+asyncpg:\/\//postgresql:\/\/}"

# Derive the test DB URI by replacing the database name in the URI path
TEST_DB_NAME="fortress_shadow_test"
TEST_URI_PLAIN="${ADMIN_URI_PLAIN%/*}/${TEST_DB_NAME}"

# For alembic we need the asyncpg form
TEST_URI_ASYNCPG="${TEST_URI_PLAIN/postgresql:\/\//postgresql+asyncpg:\/\/}"

echo "=== G.1.5 Test DB Setup ==="
echo "Admin URI:    ${ADMIN_URI_PLAIN//:*@/:***@}"   # mask password
echo "Test DB:      ${TEST_DB_NAME}"
echo ""

# ── Step 1: Create database if it doesn't exist ───────────────────────────────
echo "Step 1: Create ${TEST_DB_NAME} if not exists..."
DB_EXISTS=$(psql "${ADMIN_URI_PLAIN}" -t -A -c \
  "SELECT COUNT(*) FROM pg_database WHERE datname = '${TEST_DB_NAME}';" 2>/dev/null || echo "0")

if [[ "${DB_EXISTS}" -eq 0 ]]; then
  psql "${ADMIN_URI_PLAIN}" -c \
    "CREATE DATABASE ${TEST_DB_NAME} OWNER fortress_admin;"
  echo "  Created ${TEST_DB_NAME}."
else
  echo "  ${TEST_DB_NAME} already exists — skipping CREATE."
fi

# ── Step 2: Grant privileges to fortress_api ─────────────────────────────────
echo "Step 2: Grant privileges to fortress_api on ${TEST_DB_NAME}..."
psql "${TEST_URI_PLAIN}" <<GRANTS
GRANT CONNECT ON DATABASE ${TEST_DB_NAME} TO fortress_api;
GRANT USAGE ON SCHEMA public TO fortress_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fortress_api;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO fortress_api;
GRANTS
echo "  Grants applied."

# ── Step 3: Run alembic upgrade head ─────────────────────────────────────────
echo "Step 3: Run alembic upgrade head against ${TEST_DB_NAME}..."
cd "${REPO_ROOT}"
POSTGRES_ADMIN_URI="${TEST_URI_ASYNCPG}" \
  python3 -m alembic -c backend/alembic.ini upgrade head
echo "  Alembic migration complete."

echo ""
echo "=== Setup complete. ${TEST_DB_NAME} is at alembic head. ==="
echo ""
echo "To use in tests, set:"
echo "  export TEST_DATABASE_URL=\"${TEST_URI_ASYNCPG/fortress_admin/fortress_api}\""
echo "  # (uses fortress_api role for runtime access)"
