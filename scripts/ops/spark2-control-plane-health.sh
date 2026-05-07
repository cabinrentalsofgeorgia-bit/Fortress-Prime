#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
OPS_ROOT="${OPS_ROOT:-/home/admin/ops}"
HARD_FAILURES=0
WARNINGS=0

redact() {
  sed -E 's#([A-Za-z0-9_]*(SECRET|TOKEN|COOKIE|PASSWORD|PASS|KEY|AUTH|DATABASE_URL|DB_URL|SUPABASE)[A-Za-z0-9_]*=)[^[:space:]]+#\1[REDACTED]#Ig'
}

section() {
  printf '\n== %s ==\n' "$1"
}

warn() {
  WARNINGS=$((WARNINGS + 1))
  printf 'WARN: %s\n' "$*"
}

hard_fail() {
  HARD_FAILURES=$((HARD_FAILURES + 1))
  printf 'FAIL: %s\n' "$*"
}

check_file() {
  local path="$1"
  if [[ -f "$path" ]]; then
    printf 'OK file %s\n' "$path"
  else
    hard_fail "missing file $path"
  fi
}

check_service() {
  local unit="$1"
  if ! command -v systemctl >/dev/null 2>&1; then
    warn "systemctl unavailable; cannot inspect $unit"
    return
  fi
  local status
  status="$(systemctl is-active "$unit" 2>/dev/null || true)"
  if [[ "$status" == "active" ]]; then
    printf 'OK service %s active\n' "$unit"
  else
    warn "service $unit status=${status:-unknown}"
  fi
}

check_port() {
  local port="$1"
  if ! command -v ss >/dev/null 2>&1; then
    warn "ss unavailable; cannot inspect port $port"
    return
  fi
  if ss -ltn "sport = :$port" 2>/dev/null | awk 'NR > 1 {found=1} END {exit found ? 0 : 1}'; then
    printf 'OK port %s listening\n' "$port"
  else
    warn "port $port not listening"
  fi
}

check_http_head() {
  local label="$1"
  local url="$2"
  if ! command -v curl >/dev/null 2>&1; then
    warn "curl unavailable; cannot check $label"
    return
  fi
  local code
  code="$(curl -k -sS -o /dev/null -I --max-time 5 -w '%{http_code}' "$url" 2>/dev/null || true)"
  case "$code" in
    200|301|302|307|308|401|403|404)
      printf 'OK http %s %s\n' "$label" "$code"
      ;;
    000|"")
      warn "http $label unavailable"
      ;;
    *)
      warn "http $label unexpected_status=$code"
      ;;
  esac
}

section "Identity"
printf 'script=spark2-control-plane-health\n'
printf 'mode=read-only\n'
printf 'hostname=%s\n' "$(hostname 2>/dev/null || printf unavailable)"
printf 'timestamp_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if find "$REPO_ROOT" -path '*/.auth' -prune -print -quit | grep -q .; then
  printf 'auth_state=present-but-not-read\n'
else
  printf 'auth_state=not-present\n'
fi

section "Host"
uptime | redact || warn "uptime unavailable"
df -h / "$REPO_ROOT" "$OPS_ROOT" 2>/dev/null | redact || warn "disk check unavailable"
free -h 2>/dev/null | redact || warn "memory check unavailable"

section "Git"
if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'branch=%s\n' "$(git -C "$REPO_ROOT" branch --show-current)"
  printf 'commit=%s\n' "$(git -C "$REPO_ROOT" log -1 --oneline)"
  git -C "$REPO_ROOT" status -sb | redact
else
  hard_fail "repo root is not a git worktree: $REPO_ROOT"
fi

section "Control Plane Runbooks"
check_file "$OPS_ROOT/runbooks/spark2-control-plane.md"
check_file "$OPS_ROOT/runbooks/fortress-legal-runbook.md"
check_file "$OPS_ROOT/runbooks/branch-discipline.md"
check_file "$OPS_ROOT/runbooks/production-gates.md"
check_file "$OPS_ROOT/runbooks/autonomous-agent-policy.md"

section "Fortress Legal Operational Docs"
check_file "$REPO_ROOT/docs/production/runtime-lineage.md"
check_file "$REPO_ROOT/docs/deployment/promotion-gates.md"
check_file "$REPO_ROOT/docs/runbooks/cli-agent-operating-rules.md"

section "Services"
check_service "cloudflared.service"
check_service "crog-ai-frontend.service"
check_service "fortress-backend.service"
check_service "fortress-console.service"

section "Ports"
check_port 3005
check_port 9800
check_port 8000
check_port 8026

section "Unauthenticated HTTP"
check_http_head "local-command-center-login" "http://127.0.0.1:3005/login"
check_http_head "local-console-root" "http://127.0.0.1:9800/"
check_http_head "local-backend-health" "http://127.0.0.1:8000/health"
check_http_head "local-staging-api-health" "http://127.0.0.1:8026/health"

section "Final"
printf 'warnings=%s\n' "$WARNINGS"
printf 'hard_failures=%s\n' "$HARD_FAILURES"
if [[ "$HARD_FAILURES" -gt 0 ]]; then
  printf 'SPARK2_CONTROL_PLANE_HEALTH_STATUS=FAIL\n'
  exit 1
fi
printf 'SPARK2_CONTROL_PLANE_HEALTH_STATUS=OK_WITH_%s_WARNINGS\n' "$WARNINGS"
