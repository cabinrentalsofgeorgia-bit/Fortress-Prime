#!/usr/bin/env bash
# Local smoke: Next.js Command Center + FastAPI must both answer.
# Run on Captain after deploy: ./verify-command-center-wiring.sh
set -euo pipefail

NEXT_URL="${NEXT_URL:-http://127.0.0.1:3001}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8100}"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TAG="[command-center-wiring ${STAMP}]"

log() { echo "${TAG} $*"; }
die() { echo "${TAG} FATAL: $*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || die "curl not found"

log "Next.js GET ${NEXT_URL}/login (expect Command Center HTML)"
BODY="$(curl -fsS --max-time 15 "${NEXT_URL}/login")" || die "Next.js not reachable at ${NEXT_URL}/login — is fortress-frontend active on PORT=3001?"
echo "${BODY}" | grep -qi "Command Center" || die "Response is not the staff login page (missing 'Command Center'). Check APP_MODE=command_center / NEXT_PUBLIC_SITE_TYPE=sovereign_glass."

log "FastAPI GET ${BACKEND_URL}/health"
curl -fsS --max-time 10 "${BACKEND_URL}/health" >/dev/null || die "FastAPI not reachable at ${BACKEND_URL}/health — set FGP_BACKEND_URL on Next to this URL, or start fortress-backend."

log "Command Center wiring OK (Next + backend both up locally)"
echo "${TAG} If https://crog-ai.com still shows JSON or /docs, fix Cloudflare ingress: crog-ai.com → http://127.0.0.1:3001 (not :8100). See fortress-guest-platform/infra/gateway/config.yml"
