#!/usr/bin/env bash
set -uo pipefail

# Read-only staging preflight for MarketClub Hedge Fund Signals.
# This script intentionally performs no lifecycle writes. The only write attempt
# is the required negative permission test, wrapped in a transaction that rolls
# back and must be denied before any row can be inserted.

failures=0

STAGING_API_URL="${STAGING_API_URL:-https://staging-api.crog-ai.com}"
STAGING_API_HOST="${STAGING_API_HOST:-staging-api.crog-ai.com}"

section() {
  printf '\n== %s ==\n' "$1"
}

pass() {
  printf 'PASS: %s\n' "$1"
}

fail() {
  printf 'FAIL: %s\n' "$1"
  failures=$((failures + 1))
}

info() {
  printf 'INFO: %s\n' "$1"
}

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    fail "$name is required"
  else
    pass "$name is set"
  fi
}

json_get() {
  local file="$1"
  local key="$2"
  python3 - "$file" "$key" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)
value = data
for part in sys.argv[2].split("."):
    value = value.get(part, "") if isinstance(value, dict) else ""
print(value)
PY
}

parse_url_field() {
  local value="$1"
  local field="$2"
  python3 - "$value" "$field" <<'PY'
from urllib.parse import urlparse
import sys

raw = sys.argv[1].strip()
field = sys.argv[2]
normalized = (
    raw.replace("postgresql+psycopg", "postgresql")
       .replace("postgresql+asyncpg", "postgresql")
)
parsed = urlparse(normalized)
if field == "host":
    print(parsed.hostname or "")
elif field == "port":
    print(parsed.port or "")
elif field == "database":
    print(parsed.path.lstrip("/"))
elif field == "scheme":
    print(parsed.scheme)
else:
    raise SystemExit(f"unknown field: {field}")
PY
}

run_psql() {
  local sql="$1"
  psql -X -v ON_ERROR_STOP=1 -At "$DATABASE_URL" -c "$sql"
}

run_operator_psql() {
  local sql="$1"
  local url="${OPERATOR_DATABASE_URL:-${DATABASE_URL:-}}"
  psql -X -v ON_ERROR_STOP=1 -At "$url" -c "$sql"
}

section "Inputs"
require_env EXPECTED_COMMIT_SHA
require_env STAGING_DB_PROJECT_ID
require_env OPERATOR_TEST_USER
require_env OPERATOR_AUTH_HEADER
require_env DATABASE_URL
info "staging_api_url=$STAGING_API_URL"
info "staging_api_host=$STAGING_API_HOST"
info "expected_commit_sha=${EXPECTED_COMMIT_SHA:-}"
info "staging_db_project_id=${STAGING_DB_PROJECT_ID:-}"
info "operator_test_user=${OPERATOR_TEST_USER:-}"

section "DNS"
dig_output="$(dig "$STAGING_API_HOST" A 2>&1 || true)"
printf '%s\n' "$dig_output"
if printf '%s\n' "$dig_output" | grep -q "status: NOERROR" \
  && printf '%s\n' "$dig_output" | grep -qE "IN[[:space:]]+A[[:space:]]+[0-9]"; then
  pass "dig resolves $STAGING_API_HOST"
else
  fail "dig did not resolve $STAGING_API_HOST"
fi

nslookup_output="$(nslookup "$STAGING_API_HOST" 2>&1 || true)"
printf '%s\n' "$nslookup_output"
if printf '%s\n' "$nslookup_output" | grep -q "Address:"; then
  pass "nslookup resolves $STAGING_API_HOST"
else
  fail "nslookup did not resolve $STAGING_API_HOST"
fi

section "API Health"
health_body="$(mktemp)"
health_headers="$(mktemp)"
health_status="$(curl -sS -D "$health_headers" -o "$health_body" -w "%{http_code}" "${STAGING_API_URL%/}/healthz" 2>&1 || true)"
cat "$health_headers"
cat "$health_body"
printf '\n'
if [ "$health_status" = "200" ]; then
  pass "/healthz returned HTTP 200"
else
  fail "/healthz returned ${health_status:-curl_failed}, expected 200"
fi

health_status_value="$(json_get "$health_body" status 2>/dev/null || true)"
health_env_value="$(json_get "$health_body" env 2>/dev/null || true)"
health_service_value="$(json_get "$health_body" service 2>/dev/null || true)"
if [ "$health_status_value" = "ok" ] && [ "$health_env_value" = "staging" ] && [ "$health_service_value" = "crog-ai-backend" ]; then
  pass "/healthz exposes required staging service identity"
else
  fail "/healthz missing required identity; status=$health_status_value env=$health_env_value service=$health_service_value"
fi

section "Version"
version_body="$(mktemp)"
version_status="$(curl -sS -o "$version_body" -w "%{http_code}" "${STAGING_API_URL%/}/version" 2>&1 || true)"
cat "$version_body"
printf '\n'
version_commit="$(json_get "$version_body" commit 2>/dev/null || true)"
version_branch="$(json_get "$version_body" branch 2>/dev/null || true)"
version_build_time="$(json_get "$version_body" build_time 2>/dev/null || true)"
if [ "$version_status" = "200" ] \
  && [ "$version_commit" = "${EXPECTED_COMMIT_SHA:-}" ] \
  && [ "$version_branch" = "main" ] \
  && [ -n "$version_build_time" ]; then
  pass "/version exposes expected commit, branch, and build_time"
else
  fail "/version invalid; status=$version_status commit=$version_commit branch=$version_branch build_time=$version_build_time"
fi

section "Operator Read-Only Auth"
operator_probe="$(mktemp)"
operator_status="$(curl -sS -H "${OPERATOR_AUTH_HEADER:-Authorization: Bearer missing}" -o "$operator_probe" -w "%{http_code}" "${STAGING_API_URL%/}/api/financial/signals/latest?limit=1" 2>&1 || true)"
cat "$operator_probe"
printf '\n'
if [ "$operator_status" = "200" ]; then
  pass "operator user can call read-only staging endpoint"
else
  fail "operator read-only endpoint returned $operator_status"
fi

section "Database Identity"
if [ -z "${DATABASE_URL:-}" ]; then
  fail "DATABASE_URL missing; skipped DB identity"
else
  db_scheme="$(parse_url_field "$DATABASE_URL" scheme)"
  db_host="$(parse_url_field "$DATABASE_URL" host)"
  db_port="$(parse_url_field "$DATABASE_URL" port)"
  db_name="$(parse_url_field "$DATABASE_URL" database)"
  info "database_scheme=$db_scheme"
  info "database_host=${db_host:-<empty>}"
  info "database_port=${db_port:-<empty>}"
  info "database_name=${db_name:-<empty>}"
  case "$db_host" in
    ""|"localhost"|"127.0.0.1"|"::1")
      fail "DATABASE_URL points to local host, not hosted staging"
      ;;
    *)
      pass "DATABASE_URL host is hosted/non-local"
      ;;
  esac

  if command -v psql >/dev/null 2>&1; then
    db_identity="$(run_psql "SELECT current_database() || '|' || current_user || '|' || now();" 2>&1 || true)"
    printf '%s\n' "$db_identity"
    if [ -n "$db_identity" ] && ! printf '%s' "$db_identity" | grep -qiE "error|could not|failed"; then
      pass "DB connectivity works"
    else
      fail "DB connectivity failed"
    fi
  else
    fail "psql is required for DB checks"
  fi
fi

section "Migration Table"
if [ -n "${DATABASE_URL:-}" ] && command -v psql >/dev/null 2>&1; then
  migration_output="$(run_psql "SELECT 1 FROM supabase_migrations.schema_migrations LIMIT 1;" 2>&1 || true)"
  printf '%s\n' "$migration_output"
  if [ "$migration_output" = "1" ]; then
    pass "supabase_migrations.schema_migrations exists"
  else
    fail "supabase_migrations.schema_migrations check failed"
  fi
else
  fail "skipped migration table check"
fi

section "Required Functions"
if [ -n "${DATABASE_URL:-}" ] && command -v psql >/dev/null 2>&1; then
  functions_output="$(run_psql "
SELECT proname
FROM pg_proc
WHERE proname IN (
  'verify_promotion_dry_run',
  'execute_guarded_signal_promotion',
  'rollback_guarded_signal_promotion'
)
ORDER BY proname;" 2>&1 || true)"
  printf '%s\n' "$functions_output"
  for fn in execute_guarded_signal_promotion rollback_guarded_signal_promotion verify_promotion_dry_run; do
    if printf '%s\n' "$functions_output" | grep -qx "$fn"; then
      pass "function exists: $fn"
    else
      fail "function missing: $fn"
    fi
  done
else
  fail "skipped required function check"
fi

section "Required Views"
if [ -n "${DATABASE_URL:-}" ] && command -v psql >/dev/null 2>&1; then
  views_output="$(run_psql "
SELECT viewname
FROM pg_views
WHERE schemaname = 'hedge_fund'
  AND viewname IN (
    'v_signal_promotion_rollback_drill',
    'v_signal_promotion_reconciliation'
  )
ORDER BY viewname;" 2>&1 || true)"
  printf '%s\n' "$views_output"
  for view in v_signal_promotion_reconciliation v_signal_promotion_rollback_drill; do
    if printf '%s\n' "$views_output" | grep -qx "$view"; then
      pass "view exists: $view"
    else
      fail "view missing: $view"
    fi
  done
else
  fail "skipped required view check"
fi

section "RLS"
if [ -n "${DATABASE_URL:-}" ] && command -v psql >/dev/null 2>&1; then
  rls_output="$(run_psql "
SELECT relname || '|' || relrowsecurity::TEXT
FROM pg_class
WHERE relname IN (
  'market_signals',
  'signal_promotion_execution_rows',
  'signal_promotion_rollback_audits'
)
ORDER BY relname;" 2>&1 || true)"
  printf '%s\n' "$rls_output"
  for table_name in market_signals signal_promotion_execution_rows signal_promotion_rollback_audits; do
    if printf '%s\n' "$rls_output" | grep -qx "$table_name|true"; then
      pass "RLS enabled: $table_name"
    else
      fail "RLS missing/disabled: $table_name"
    fi
  done
else
  fail "skipped RLS check"
fi

section "Negative Direct Write"
if [ -n "${DATABASE_URL:-}" ] && command -v psql >/dev/null 2>&1; then
  negative_output="$(run_operator_psql "BEGIN; INSERT INTO hedge_fund.market_signals DEFAULT VALUES; ROLLBACK;" 2>&1 || true)"
  printf '%s\n' "$negative_output"
  if printf '%s\n' "$negative_output" | grep -qiE "permission denied|row-level security|not authorized|insufficient privilege"; then
    pass "direct market_signals insert is denied"
  else
    fail "direct market_signals insert was not denied by permission/RLS"
  fi
else
  fail "skipped negative direct write test"
fi

section "Final"
if [ "$failures" -eq 0 ]; then
  pass "staging preflight passed; release evidence runbook may proceed"
  exit 0
fi

fail "staging preflight failed with $failures blocker(s); do not run lifecycle writes"
exit 1
