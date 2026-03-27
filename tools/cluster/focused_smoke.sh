#!/usr/bin/env bash
set -euo pipefail

# Focused smoke test for Fortress Prime "NIM convergence" flow.
# Requires backend running (default: http://127.0.0.1:8110).

BASE_URL="${BASE_URL:-http://127.0.0.1:8110}"
CHECK_IN="${CHECK_IN:-2026-04-10}"
CHECK_OUT="${CHECK_OUT:-2026-04-13}"
GUESTS="${GUESTS:-2}"
FGP_ROOT="${FGP_ROOT:-$(cd "$(dirname "$0")/../../fortress-guest-platform" && pwd)}"

TOKEN="$(python3 - <<'PY'
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from jose import jwt

private_key = open('/tmp/hitl-keys/private.pem').read()
payload = {
    'sub': str(uuid4()),
    'role': 'admin',
    'email': 'smoke@fortress.local',
    'iat': datetime.now(timezone.utc),
    'exp': datetime.now(timezone.utc) + timedelta(hours=1),
}
print(jwt.encode(payload, private_key, algorithm='RS256', headers={'kid': 'fgp-rs256-v1'}))
PY
)"

echo "== Tool Discovery =="
curl -sS -H "Authorization: Bearer ${TOKEN}" \
  "${BASE_URL}/api/v1/properties/availability?check_in=${CHECK_IN}&check_out=${CHECK_OUT}&guests=${GUESTS}" \
  > /tmp/focused_smoke_availability.json
python3 - <<'PY'
import json
obj = json.load(open('/tmp/focused_smoke_availability.json'))
required = {"check_in", "check_out", "guests", "results"}
missing = sorted(required - set(obj.keys()))
if missing:
    raise SystemExit(f"availability schema missing keys: {missing}")
print("availability keys:", sorted(obj.keys()))
print("availability results:", len(obj.get("results", [])))
PY

echo
echo "== Redaction Check =="
PYTHONPATH="${FGP_ROOT}" python3 - <<'PY'
from backend.services.privacy_router import sanitize_for_cloud
payload = {
    "guest_name": "John Doe",
    "note": "Guest John Doe requested late check-in",
}
decision = sanitize_for_cloud(payload)
if decision.redacted_payload.get("guest_name") != "GUEST_ALPHA":
    raise SystemExit("guest_name was not aliased to GUEST_ALPHA")
if "GUEST_ALPHA" not in decision.redacted_payload.get("note", ""):
    raise SystemExit("name alias missing from note redaction")
print("redaction status:", decision.redaction_status)
print("redacted payload:", decision.redacted_payload)
PY

echo
echo "== Chain Of Custody =="
SOURCE_PATH="/smoke-test-$(date +%s)"
curl -sS -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"source_path\":\"${SOURCE_PATH}\",\"destination_path\":\"/smoke-test-new\",\"is_permanent\":true,\"reason\":\"smoke-test\"}" \
  "${BASE_URL}/api/v1/seo/redirects" \
  > /tmp/focused_smoke_redirect.json

curl -sS -H "Authorization: Bearer ${TOKEN}" \
  "${BASE_URL}/api/openshell/audit/log?limit=100" \
  > /tmp/focused_smoke_audit.json

python3 - <<'PY'
import json
redirect = json.load(open('/tmp/focused_smoke_redirect.json'))
rows = json.load(open('/tmp/focused_smoke_audit.json'))
source = redirect["source_path"]
row = next((x for x in rows if x.get("action") == "seo.redirect.write" and x.get("metadata_json", {}).get("source_path") == source), None)
if not row:
    raise SystemExit("missing seo.redirect.write audit row for smoke redirect")
print("redirect id:", redirect["id"])
print("audit entry_hash:", row["entry_hash"])
print("audit signature:", row["signature"])
print("audit prev_hash:", row.get("prev_hash"))
PY

echo
echo "Focused smoke test PASS"
