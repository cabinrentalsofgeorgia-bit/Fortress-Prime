#!/usr/bin/env bash
set -euo pipefail

CASE_SLUG="${1:-fish-trap-suv2026000013}"
DEPONENT_ENTITY="${2:-J. David Stuart}"
BASE_URL="http://127.0.0.1:8100"
DECK_URL="${BASE_URL}/api/internal/deck-key"
POST_URL="${BASE_URL}/api/legal/cases/${CASE_SLUG}/deposition/kill-sheet"
LIST_URL="${BASE_URL}/api/legal/cases/${CASE_SLUG}/deposition/kill-sheets"

echo "[1/3] Minting Deck Key..."
DECK_RESPONSE="$(curl -sS --fail "${DECK_URL}")"
TOKEN="$(printf '%s' "${DECK_RESPONSE}" | jq -r '.access_token // empty')"
if [[ -z "${TOKEN}" ]]; then
  echo "ERROR: Could not parse access token."
  echo "Raw response: ${DECK_RESPONSE}"
  exit 1
fi

echo "[2/3] Generating deposition kill-sheet for ${DEPONENT_ENTITY}..."
POST_RESPONSE="$(curl -sS --fail -X POST "${POST_URL}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg deponent "${DEPONENT_ENTITY}" '{deponent_entity:$deponent}')")"
printf '%s\n' "${POST_RESPONSE}" | jq

echo "[3/3] Reading kill-sheet history..."
LIST_RESPONSE="$(curl -sS --fail "${LIST_URL}" -H "Authorization: Bearer ${TOKEN}")"
printf '%s\n' "${LIST_RESPONSE}" | jq -r '
  "Case: \(.case_slug)",
  "Total Kill-Sheets: \(.total)",
  "",
  (.kill_sheets[0] | "Deponent: \(.deponent_entity)\nStatus: \(.status)\nCreated: \(.created_at)\n\nSummary:\n\(.summary)\n"),
  "High Risk Topics:",
  (.kill_sheets[0].high_risk_topics[]? | " - \(.)"),
  "",
  "Document Sequence:",
  (.kill_sheets[0].document_sequence[]? | " - \(.doc_name): \(.tactical_purpose)"),
  "",
  "Suggested Questions:",
  (.kill_sheets[0].suggested_questions[]? | " - \(.)")
'
