#!/usr/bin/env bash
set -euo pipefail

CASE_SLUG="${1:-fish-trap-suv2026000013}"
BASE_URL="http://127.0.0.1:8100"
DECK_URL="${BASE_URL}/api/internal/deck-key"
SWEEP_URL="${BASE_URL}/api/legal/cases/${CASE_SLUG}/sanctions/sweep"
ALERTS_URL="${BASE_URL}/api/legal/cases/${CASE_SLUG}/sanctions/alerts"

echo "[1/3] Minting Deck Key..."
DECK_RESPONSE="$(curl -sS --fail "${DECK_URL}")"
TOKEN="$(printf '%s' "${DECK_RESPONSE}" | jq -r '.access_token // empty')"
if [[ -z "${TOKEN}" ]]; then
  echo "ERROR: Could not parse access token."
  echo "Raw response: ${DECK_RESPONSE}"
  exit 1
fi

echo "[2/3] Triggering sanctions sweep for ${CASE_SLUG}..."
curl -sS --fail -X POST "${SWEEP_URL}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" | jq

echo "[3/3] Reading sanctions alerts..."
ALERTS_RESPONSE="$(curl -sS --fail "${ALERTS_URL}" -H "Authorization: Bearer ${TOKEN}")"
printf '%s\n' "${ALERTS_RESPONSE}" | jq -r '
  "Case: \(.case_slug)",
  "Total Alerts: \(.total)",
  "",
  (.alerts[]? | "---- [\(.alert_type)] score=\(.confidence_score) status=\(.status) ----\n\(.contradiction_summary)\n")
'
