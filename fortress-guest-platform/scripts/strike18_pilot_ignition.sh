#!/usr/bin/env bash
# STRIKE 18 — Pilot Ignition (Concierge recovery SMS cohort arming)
#
# Arms Strike 17 env gates for a bounded pilot: property slugs + loyalty tiers.
# "10% cohort" here means an explicit allowlist you tune (not random sampling).
#
# Prerequisites (operator must verify):
#   - CONCIERGE_RECOVERY_SMS_ENABLED=true
#   - Twilio credentials set
#   - AGENTIC_SYSTEM_ACTIVE=true (unless CONCIERGE_STRIKE_REQUIRE_AGENTIC_SYSTEM_ACTIVE=false)
#
# Default env file: fortress-guest-platform/backend/.env (override with FORTRESS_BACKEND_ENV).
#
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_ROOT="$(cd -- "${SCRIPT_DIR}/../backend" && pwd)"
ENV_FILE="${FORTRESS_BACKEND_ENV:-${BACKEND_ROOT}/.env}"

# --- Safe cohort (edit before run) ---
TARGET_SLUGS="${STRIKE18_TARGET_SLUGS:-luxury-creekside-cabin,mountain-view-lodge}"
TARGET_TIERS="${STRIKE18_TARGET_TIERS:-PLATINUM,GOLD}"

upsert_env() {
  local key="$1"
  local val="$2"
  local file="$3"
  if [[ ! -f "$file" ]]; then
    printf '%s=%s\n' "$key" "$val" >"$file"
    echo "Created ${file} with ${key}"
    return
  fi
  if grep -qE "^[[:space:]]*${key}=" "$file"; then
    sed -i "s|^[[:space:]]*${key}=.*|${key}=${val}|" "$file"
  else
    printf '\n%s=%s\n' "$key" "$val" >>"$file"
  fi
}

echo "--- INITIATING STRIKE 18: PILOT IGNITION ---"
echo "Env file: ${ENV_FILE}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "WARNING: ${ENV_FILE} missing; creating minimal entries." >&2
fi

if [[ -f "$ENV_FILE" ]]; then
  cp -a "${ENV_FILE}" "${ENV_FILE}.strike18.bak.$(date +%Y%m%d%H%M%S)"
  echo "Backup written alongside ${ENV_FILE}"
fi

upsert_env "CONCIERGE_STRIKE_ENABLED" "true" "$ENV_FILE"
upsert_env "CONCIERGE_STRIKE_ALLOWED_PROPERTY_SLUGS" "${TARGET_SLUGS}" "$ENV_FILE"
upsert_env "CONCIERGE_STRIKE_ALLOWED_LOYALTY_TIERS" "${TARGET_TIERS}" "$ENV_FILE"

echo ""
echo "Updated keys:"
echo "  CONCIERGE_STRIKE_ENABLED=true"
echo "  CONCIERGE_STRIKE_ALLOWED_PROPERTY_SLUGS=${TARGET_SLUGS}"
echo "  CONCIERGE_STRIKE_ALLOWED_LOYALTY_TIERS=${TARGET_TIERS}"
echo ""
echo "Verify also set:"
echo "  CONCIERGE_RECOVERY_SMS_ENABLED=true"
echo "  AGENTIC_SYSTEM_ACTIVE=true   (if CONCIERGE_STRIKE_REQUIRE_AGENTIC_SYSTEM_ACTIVE=true)"
echo "  TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER"
echo ""

if [[ "${STRIKE18_RESTART_WORKER:-1}" == "1" ]]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl cat fortress-worker.service &>/dev/null; then
    echo "RESTARTING fortress-worker.service ..."
    sudo systemctl restart fortress-worker.service
    echo "Worker restart issued."
  else
    echo "SKIP: fortress-worker.service not found; restart your FastAPI/arq worker manually so env reloads."
  fi
else
  echo "SKIP worker restart (STRIKE18_RESTART_WORKER=0)."
fi

echo ""
echo "STATUS: STRIKE 18 ARMED for slugs [${TARGET_SLUGS}] and tiers [${TARGET_TIERS}]."
