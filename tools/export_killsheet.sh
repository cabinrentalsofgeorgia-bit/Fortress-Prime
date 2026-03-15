#!/usr/bin/env bash
set -euo pipefail

CASE_SLUG="${1:-fish-trap-suv2026000013}"
OUT_FILE="/home/admin/Fortress-Prime/J_David_Stuart_Kill_Sheet.md"
BASE_URL="http://127.0.0.1:8100"
DECK_URL="${BASE_URL}/api/internal/deck-key"
LIST_URL="${BASE_URL}/api/legal/cases/${CASE_SLUG}/deposition/kill-sheets"

echo "[1/3] Minting Deck Key..."
DECK_RESPONSE="$(curl -sS --fail "${DECK_URL}")"
TOKEN="$(printf '%s' "${DECK_RESPONSE}" | jq -r '.access_token // empty')"
if [[ -z "${TOKEN}" ]]; then
  echo "ERROR: Could not parse access token."
  echo "Raw response: ${DECK_RESPONSE}"
  exit 1
fi

echo "[2/3] Resolving latest kill-sheet ID..."
LIST_RESPONSE="$(curl -sS --fail "${LIST_URL}" -H "Authorization: Bearer ${TOKEN}")"
SHEET_ID="$(printf '%s' "${LIST_RESPONSE}" | jq -r '.kill_sheets[0].id // empty')"
if [[ -z "${SHEET_ID}" ]]; then
  echo "ERROR: No kill-sheets found for case ${CASE_SLUG}."
  exit 1
fi

EXPORT_URL="${BASE_URL}/api/legal/cases/${CASE_SLUG}/deposition/kill-sheets/${SHEET_ID}/export"
echo "[3/3] Downloading markdown export..."
curl -sS --fail "${EXPORT_URL}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: text/markdown" > "${OUT_FILE}"

echo "SUCCESS: Deposition tactical brief exported to ${OUT_FILE}"
