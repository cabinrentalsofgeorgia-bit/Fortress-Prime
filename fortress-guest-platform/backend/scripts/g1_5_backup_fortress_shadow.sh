#!/usr/bin/env bash
# Phase G.1.5 — Pre-cleanup table backup
#
# Captures the full content of the 5 owner-statement tables in fortress_shadow
# BEFORE any cleanup runs. The pg_dump output is --column-inserts format, meaning
# the rows are stored as individual INSERT statements and can be replayed directly
# against any PostgreSQL instance to restore the original data.
#
# Run this BEFORE executing the COMMIT form of the cleanup script (G.1.6).
#
# Usage:
#   POSTGRES_ADMIN_URI="postgresql://fortress_admin:PASSWORD@127.0.0.1:5432/fortress_shadow" \
#     bash backend/scripts/g1_5_backup_fortress_shadow.sh
#
# The POSTGRES_ADMIN_URI env var is read from the shell environment. If not set,
# the script falls back to the value in fortress-guest-platform/.env.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── Resolve connection string ─────────────────────────────────────────────────
# Load .env if POSTGRES_ADMIN_URI is not already set
if [[ -z "${POSTGRES_ADMIN_URI:-}" ]]; then
  ENV_FILE="${REPO_ROOT}/.env"
  if [[ -f "${ENV_FILE}" ]]; then
    # Extract POSTGRES_ADMIN_URI, strip asyncpg driver prefix if present
    POSTGRES_ADMIN_URI="$(grep '^POSTGRES_ADMIN_URI' "${ENV_FILE}" \
      | head -1 \
      | cut -d= -f2- \
      | tr -d '"' \
      | sed 's|postgresql+asyncpg://|postgresql://|')"
  fi
fi

if [[ -z "${POSTGRES_ADMIN_URI:-}" ]]; then
  echo "ERROR: POSTGRES_ADMIN_URI is not set and could not be read from .env"
  exit 1
fi

# Strip asyncpg driver if still present (pg_dump needs plain postgresql://)
PG_URI="${POSTGRES_ADMIN_URI/postgresql+asyncpg:\/\//postgresql:\/\/}"

# ── Output path ───────────────────────────────────────────────────────────────
TS=$(date +%Y%m%d_%H%M%S)
OUT="${SCRIPT_DIR}/g1_5_backup_${TS}.sql"

echo "Backing up 5 owner-statement tables from fortress_shadow..."
echo "Output: ${OUT}"
echo ""

# ── pg_dump: --column-inserts produces plain INSERT statements, not COPY.
# This makes the output portable across Postgres versions and importable
# into fortress_shadow_test for verification without needing superuser.
pg_dump "${PG_URI}" \
  -t owner_payout_accounts \
  -t owner_balance_periods \
  -t owner_charges \
  -t owner_statement_sends \
  -t owner_magic_tokens \
  --data-only \
  --column-inserts \
  -f "${OUT}"

echo ""
echo "Backup complete."
ls -lh "${OUT}"
echo ""
echo "To restore (if needed):"
echo "  psql \"\${POSTGRES_ADMIN_URI}\" -f ${OUT}"
