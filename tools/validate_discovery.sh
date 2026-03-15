#!/usr/bin/env bash
set -euo pipefail

CASE_SLUG="fish-trap-suv2026000013"
DECK_URL="http://127.0.0.1:8100/api/internal/deck-key"
PACKS_URL="http://127.0.0.1:8100/api/legal/cases/${CASE_SLUG}/discovery/packs"

echo "[1/4] Minting Deck Key..."
DECK_RESPONSE="$(curl -sS --fail "${DECK_URL}")"
TOKEN="$(printf '%s' "${DECK_RESPONSE}" | jq -r '.access_token // empty')"
if [[ -z "${TOKEN}" ]]; then
  echo "ERROR: Could not parse access token."
  echo "Raw response: ${DECK_RESPONSE}"
  exit 1
fi

echo "[2/4] Finding most recent pack..."
PACKS_RESPONSE="$(curl -sS --fail "${PACKS_URL}" -H "Authorization: Bearer ${TOKEN}")"
PACK_ID="$(printf '%s' "${PACKS_RESPONSE}" | jq -r '.packs[0].id // empty')"
if [[ -z "${PACK_ID}" ]]; then
  echo "ERROR: No discovery packs found."
  echo "Raw response: ${PACKS_RESPONSE}"
  exit 1
fi

VALIDATE_URL="http://127.0.0.1:8100/api/legal/cases/${CASE_SLUG}/discovery/packs/${PACK_ID}/validate"
DETAIL_URL="http://127.0.0.1:8100/api/legal/cases/${CASE_SLUG}/discovery/packs/${PACK_ID}"

echo "[3/4] Validating and scoring pack ${PACK_ID}..."
curl -sS --fail -X POST "${VALIDATE_URL}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" | jq

echo "[4/4] Reading scored pack..."
DETAIL_RESPONSE="$(curl -sS --fail "${DETAIL_URL}" -H "Authorization: Bearer ${TOKEN}")"
echo
echo "=== SCORED DISCOVERY PACK ==="
printf '%s\n' "${DETAIL_RESPONSE}" | jq -r '
  "Pack ID: \(.pack.id)",
  "Case: \(.pack.case_slug)",
  "Target: \(.pack.target_entity)",
  "Status: \(.pack.status)",
  "Created: \(.pack.created_at)",
  "",
  (.items[] | "---- [#\(.sequence_number)] [\(.category)] L=\(.lethality_score // "n/a") P=\(.proportionality_score // "n/a") ----\nQ: \(.content)\nNotes: \(.correction_notes // "n/a")\nRationale: \(.rationale_from_graph)\n")
'

