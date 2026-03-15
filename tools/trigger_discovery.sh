#!/usr/bin/env bash
set -euo pipefail

DECK_URL="http://127.0.0.1:8100/api/internal/deck-key"
DISCOVERY_URL="http://127.0.0.1:8100/api/legal/cases/fish-trap-suv2026000013/discovery/draft-pack"
REQUEST_BODY='{"target_entity":"Generali","max_items":10}'

echo "[1/2] Minting Deck Key..."
DECK_RESPONSE="$(curl -sS --fail "${DECK_URL}")"
TOKEN="$(printf '%s' "${DECK_RESPONSE}" | sed -n 's/.*"access_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
if [[ -z "${TOKEN}" ]]; then
  echo "ERROR: Could not parse access token."
  echo "Raw response: ${DECK_RESPONSE}"
  exit 1
fi

echo "[2/2] Triggering discovery draft generation..."
curl -sS --fail -X POST "${DISCOVERY_URL}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${REQUEST_BODY}"
echo
echo "Discovery strike complete."

