#!/usr/bin/env bash
# Read-only soak verification for legal event-driven cutover.
# Usage: soak_check.sh <checkpoint-label>   e.g. soak_check.sh +1h

set -euo pipefail

CHECKPOINT="${1:-unspecified}"
LOG_FILE="/var/log/fortress-soak.log"
ALERT_FLAG="/var/lib/fortress/soak_alert.flag"
ENV_FILE="/home/admin/Fortress-Prime/fortress-guest-platform/.env"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "$(dirname "$ALERT_FLAG")"
touch "$LOG_FILE" 2>/dev/null || true

if [[ ! -r "$ENV_FILE" ]]; then
  echo "[$TS] [$CHECKPOINT] FATAL: cannot read $ENV_FILE" | tee -a "$LOG_FILE" | logger -t fortress-soak
  exit 1
fi
# Read POSTGRES_ADMIN_URI from .env at runtime (not cached). The .env's
# broken-out FORTRESS_DB_* keys are stale (they point to miner_bot which
# fails authentication); the URI is the canonical admin credential.
ADMIN_URI=""
while IFS='=' read -r key val; do
  [[ "$key" == "POSTGRES_ADMIN_URI" ]] && ADMIN_URI="$val"
done < <(grep -E '^POSTGRES_ADMIN_URI=' "$ENV_FILE")

if [[ -z "$ADMIN_URI" ]]; then
  echo "[$TS] [$CHECKPOINT] FATAL: POSTGRES_ADMIN_URI not found in $ENV_FILE" | tee -a "$LOG_FILE" | logger -t fortress-soak
  exit 1
fi

URI_REST="${ADMIN_URI#*://}"
USERPASS="${URI_REST%%@*}"
HOSTPATH="${URI_REST#*@}"
HOSTPORT="${HOSTPATH%%/*}"
DB_USER="${USERPASS%%:*}"
DB_PASS="${USERPASS#*:}"
DB_HOST="${HOSTPORT%%:*}"
if [[ "$HOSTPORT" == *:* ]]; then
  DB_PORT="${HOSTPORT##*:}"
else
  DB_PORT=5432
fi

if [[ -z "$DB_USER" || -z "$DB_PASS" || -z "$DB_HOST" ]]; then
  echo "[$TS] [$CHECKPOINT] FATAL: failed to parse POSTGRES_ADMIN_URI (user/pass/host empty)" | tee -a "$LOG_FILE" | logger -t fortress-soak
  exit 1
fi

run_counts() {
  local db="$1"
  PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$db" \
    -t -A -F '|' --no-psqlrc -v ON_ERROR_STOP=1 -c "
    SELECT
      (SELECT COUNT(*) FROM legal.event_log),
      (SELECT COUNT(*) FROM legal.event_log WHERE processed_at IS NOT NULL),
      (SELECT COUNT(*) FROM legal.event_log WHERE processed_at IS NULL),
      (SELECT COUNT(*) FROM legal.case_posture),
      (SELECT COUNT(*) FROM legal.dispatcher_event_attempts),
      (SELECT COUNT(*) FROM legal.dispatcher_dead_letter)
  "
}

count_marker() {
  journalctl -u fortress-arq-worker --since '1 hour ago' --no-pager 2>/dev/null \
    | grep -c "$1" || true
}

WORKER_STATE="$(systemctl is-active fortress-arq-worker 2>&1 || true)"
WORKER_SINCE="$(systemctl show fortress-arq-worker -p ActiveEnterTimestamp --value 2>/dev/null || echo unknown)"

if ! DB_LINE="$(run_counts fortress_db 2>/dev/null)"; then
  DB_LINE='ERROR|ERROR|ERROR|ERROR|ERROR|ERROR'
fi
IFS='|' read -r EVT_TOTAL EVT_PROC EVT_PEND POSTURES ATTEMPTS DEAD_LETTERS <<< "$DB_LINE"

if ! PROD_LINE="$(run_counts fortress_prod 2>/dev/null)"; then
  PROD_LINE='ERROR|ERROR|ERROR|ERROR|ERROR|ERROR'
fi
IFS='|' read -r P_EVT P_EVT_PROC P_EVT_PEND P_POSTURES P_ATTEMPTS P_DEAD_LETTERS <<< "$PROD_LINE"

if [[ "$DB_LINE" == ERROR* || "$PROD_LINE" == ERROR* ]]; then
  PARITY="UNKNOWN-DB-ERROR"
elif [[ "$EVT_TOTAL" == "$P_EVT" && "$POSTURES" == "$P_POSTURES" \
     && "$ATTEMPTS" == "$P_ATTEMPTS" && "$DEAD_LETTERS" == "$P_DEAD_LETTERS" ]]; then
  PARITY="HOLDS"
else
  PARITY="DIVERGED"
fi

FAIL_PREFLIGHT="$(count_marker 'preflight_failed')"
FAIL_TASKDIED="$(count_marker 'task_died')"
FAIL_PRIV="$(count_marker 'InsufficientPrivilegeError')"
FAIL_TOTAL=$(( ${FAIL_PREFLIGHT:-0} + ${FAIL_TASKDIED:-0} + ${FAIL_PRIV:-0} ))

if [[ "$WORKER_STATE" != "active" ]]; then
  STATE="BLOCKED"
  STATE_REASON="worker not active ($WORKER_STATE)"
elif [[ "$PARITY" == "DIVERGED" || "$PARITY" == "UNKNOWN-DB-ERROR" ]]; then
  STATE="BLOCKED"
  STATE_REASON="parity check: $PARITY"
elif [[ "$FAIL_TOTAL" -gt 0 ]]; then
  STATE="DEGRADED"
  STATE_REASON="failure markers in last hour: preflight=$FAIL_PREFLIGHT task_died=$FAIL_TASKDIED priv=$FAIL_PRIV"
elif [[ "$EVT_PROC" -gt 0 && "$ATTEMPTS" -gt 0 && "$POSTURES" -gt 0 ]]; then
  STATE="COMPLETE"
  STATE_REASON="end-to-end flow observed"
elif [[ "$EVT_TOTAL" == "0" && "$ATTEMPTS" == "0" && "$POSTURES" == "0" ]]; then
  STATE="AWAITING-FIRST-EVENT"
  STATE_REASON="no producer/consumer activity yet"
else
  STATE="PARTIAL"
  STATE_REASON="some activity but missing one of: processed events, attempts, postures"
fi

{
  echo "================================================================"
  echo "[$TS] [$CHECKPOINT] fortress soak check"
  echo "----------------------------------------------------------------"
  echo "Worker:        $WORKER_STATE  since=$WORKER_SINCE"
  echo "fortress_db:   events=$EVT_TOTAL processed=$EVT_PROC pending=$EVT_PEND postures=$POSTURES attempts=$ATTEMPTS dead_letters=$DEAD_LETTERS"
  echo "fortress_prod: events=$P_EVT processed=$P_EVT_PROC pending=$P_EVT_PEND postures=$P_POSTURES attempts=$P_ATTEMPTS dead_letters=$P_DEAD_LETTERS"
  echo "Parity:        $PARITY"
  echo "Failures(1h):  preflight_failed=$FAIL_PREFLIGHT  task_died=$FAIL_TASKDIED  InsufficientPrivilegeError=$FAIL_PRIV"
  echo "STATE:         $STATE — $STATE_REASON"
} | tee -a "$LOG_FILE" | logger -t fortress-soak

if [[ "$STATE" == "DEGRADED" || "$STATE" == "BLOCKED" ]]; then
  printf "[%s] [%s] %s — %s\n" "$TS" "$CHECKPOINT" "$STATE" "$STATE_REASON" >> "$ALERT_FLAG"
fi
