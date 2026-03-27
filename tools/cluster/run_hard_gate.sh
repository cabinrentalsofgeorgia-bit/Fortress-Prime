#!/usr/bin/env bash
set -euo pipefail

# Sovereign hard-gate runner for self-hosted CI on Spark head node.
# Blocks deployment if focused smoke or fabric threshold checks fail.

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
FGP_DIR="${ROOT_DIR}/fortress-guest-platform"
PORT="${PORT:-8115}"
BASE_URL="${BASE_URL:-http://127.0.0.1:${PORT}}"
NODES="${NODES:-192.168.0.104 192.168.0.100 192.168.0.101 192.168.0.102}"

cd "$FGP_DIR"

if [[ ! -f /tmp/hitl-keys/private.pem || ! -f /tmp/hitl-keys/public.pem ]]; then
  mkdir -p /tmp/hitl-keys
  openssl genrsa -out /tmp/hitl-keys/private.pem 2048 >/dev/null 2>&1
  openssl rsa -in /tmp/hitl-keys/private.pem -pubout -out /tmp/hitl-keys/public.pem >/dev/null 2>&1
fi

JWT_RSA_PRIVATE_KEY="$(base64 -w0 /tmp/hitl-keys/private.pem)"
JWT_RSA_PUBLIC_KEY="$(base64 -w0 /tmp/hitl-keys/public.pem)"
export JWT_RSA_PRIVATE_KEY JWT_RSA_PUBLIC_KEY JWT_KEY_ID=fgp-rs256-v1
export DATABASE_URL="${DATABASE_URL:-postgresql:///fortress_guest}"
export TWILIO_ACCOUNT_SID="${TWILIO_ACCOUNT_SID:-AC00000000000000000000000000000000}"
export TWILIO_AUTH_TOKEN="${TWILIO_AUTH_TOKEN:-twilio_auth_token_placeholder}"
export TWILIO_PHONE_NUMBER="${TWILIO_PHONE_NUMBER:-+15005550006}"

python3 -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT" --log-level warning >/tmp/fortress-hard-gate-backend.log 2>&1 &
BACKEND_PID=$!
trap 'kill $BACKEND_PID >/dev/null 2>&1 || true' EXIT
sleep 3

cd "$ROOT_DIR"
BASE_URL="$BASE_URL" FGP_ROOT="$FGP_DIR" tools/cluster/focused_smoke.sh
python3 -m pytest -q fortress-guest-platform/backend/tests/test_focused_smoke.py
tools/cluster/nvidia_fabric_health_monitor.sh --nodes "$NODES"

echo "SOVEREIGN HARD-GATE PASS"
