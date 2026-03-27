#!/usr/bin/env bash
# Sovereign end-to-end auth + BFF + Hunter smoke for Fortress Prime.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ROOT="${ROOT_DIR}/fortress-guest-platform"
BACKEND_BASE="${FGP_BACKEND_URL:-http://127.0.0.1:8100}"
APP_BASE="${FORTRESS_SMOKE_APP_URL:-https://crog-ai.com}"
EMAIL="${FORTRESS_SMOKE_EMAIL:?set FORTRESS_SMOKE_EMAIL}"
PASSWORD="${FORTRESS_SMOKE_PASSWORD:?set FORTRESS_SMOKE_PASSWORD}"
COOKIE_JAR="$(mktemp)"
SMOKE_EXECUTE_FP=""
SMOKE_DISMISS_FP=""

cleanup() {
  rm -f "${COOKIE_JAR}"
  if [[ -z "${SMOKE_EXECUTE_FP}" && -z "${SMOKE_DISMISS_FP}" ]]; then
    return 0
  fi
  (
    cd "${APP_ROOT}"
    FORTRESS_SMOKE_EXECUTE_FP="${SMOKE_EXECUTE_FP}" \
    FORTRESS_SMOKE_DISMISS_FP="${SMOKE_DISMISS_FP}" \
    python3 - <<'PY'
import asyncio
import os
from sqlalchemy import delete
from backend.core.database import get_session_factory, close_db
from backend.models.hunter import HunterQueueEntry
from backend.models.recovery_parity_comparison import RecoveryParityComparison

EXECUTE_FP = (os.environ.get("FORTRESS_SMOKE_EXECUTE_FP") or "").strip()
DISMISS_FP = (os.environ.get("FORTRESS_SMOKE_DISMISS_FP") or "").strip()
TARGETS = [fp for fp in (EXECUTE_FP, DISMISS_FP) if fp]

async def main() -> None:
    if not TARGETS:
        return
    Session = get_session_factory()
    async with Session() as session:
        await session.execute(
            delete(RecoveryParityComparison).where(RecoveryParityComparison.session_fp.in_(TARGETS))
        )
        await session.execute(delete(HunterQueueEntry).where(HunterQueueEntry.session_fp.in_(TARGETS)))
        await session.commit()
    await close_db()

asyncio.run(main())
PY
  ) >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[1] POST ${BACKEND_BASE}/api/auth/login"
LOGIN_JSON="$(curl -sS -X POST "${BACKEND_BASE}/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}")"
TOKEN="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('access_token',''))" "${LOGIN_JSON}")"
EXPIRES="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('expires_in',''))" "${LOGIN_JSON}")"
if [[ -z "${TOKEN}" ]]; then
  echo "FAIL: no access_token in response: ${LOGIN_JSON}" >&2
  exit 1
fi
echo "    OK token prefix=${TOKEN:0:12}… expires_in=${EXPIRES}"

echo "[2] GET ${BACKEND_BASE}/api/auth/me"
ME_CODE="$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${TOKEN}" "${BACKEND_BASE}/api/auth/me")"
[[ "${ME_CODE}" == "200" ]] || { echo "FAIL: /api/auth/me -> ${ME_CODE}" >&2; exit 1; }
echo "    OK ${ME_CODE}"

echo "[3] GET ${BACKEND_BASE}/api/integrations/streamline/status auth contracts"
ST_NA="$(curl -sS -o /dev/null -w '%{http_code}' "${BACKEND_BASE}/api/integrations/streamline/status")"
[[ "${ST_NA}" == "401" ]] || { echo "FAIL: expected 401 unauthenticated, got ${ST_NA}" >&2; exit 1; }
ST_OK="$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${TOKEN}" "${BACKEND_BASE}/api/integrations/streamline/status")"
[[ "${ST_OK}" == "200" ]] || { echo "FAIL: streamline/status with auth -> ${ST_OK}" >&2; exit 1; }
echo "    OK unauth=${ST_NA} auth=${ST_OK}"

echo "[4] POST ${APP_BASE}/api/auth/login (BFF cookie bridge)"
BFF_LOGIN_CODE="$(curl -sS -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" -o /tmp/fortress-bff-login.json -w '%{http_code}' \
  -X POST "${APP_BASE}/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}")"
[[ "${BFF_LOGIN_CODE}" == "200" ]] || { echo "FAIL: BFF login -> ${BFF_LOGIN_CODE}" >&2; cat /tmp/fortress-bff-login.json >&2; exit 1; }
grep -q 'fortress_session' "${COOKIE_JAR}" || { echo "FAIL: fortress_session cookie not set by BFF login" >&2; exit 1; }
echo "    OK ${BFF_LOGIN_CODE}"

echo "[5] GET ${APP_BASE}/api/auth/me and dashboard hydration routes"
BFF_ME="$(curl -sS -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" -o /dev/null -w '%{http_code}' "${APP_BASE}/api/auth/me")"
[[ "${BFF_ME}" == "200" ]] || { echo "FAIL: BFF auth/me -> ${BFF_ME}" >&2; exit 1; }
BFF_DASH="$(curl -sS -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" -o /dev/null -w '%{http_code}' "${APP_BASE}/api/analytics/dashboard")"
[[ "${BFF_DASH}" == "200" ]] || { echo "FAIL: BFF analytics/dashboard -> ${BFF_DASH}" >&2; exit 1; }
echo "    OK auth/me=${BFF_ME} dashboard=${BFF_DASH}"

echo "[6] Seed synthetic Hunter queue rows"
SEED_JSON="$(
  cd "${APP_ROOT}" && python3 - <<'PY' | tail -n 1
import asyncio
import hashlib
import json
import time
from backend.core.database import get_session_factory, close_db
from backend.models.hunter import HunterQueueEntry

def session_fp(label: str) -> str:
    seed = f"{label}:{time.time_ns()}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()

async def main() -> None:
    execute_fp = session_fp("fortress-smoke-execute")
    dismiss_fp = session_fp("fortress-smoke-dismiss")
    Session = get_session_factory()
    async with Session() as session:
        session.add_all(
            [
                HunterQueueEntry(
                    session_fp=execute_fp,
                    campaign="reactivation",
                    guest_email="smoke-execute@crog-ai.com",
                    payload={
                        "property_slug": "smoke-test-cabin",
                        "prey_class": "target_alpha",
                        "drop_off_point": "quote_open",
                        "drop_off_point_label": "Quote Open",
                        "guest_display_name": "Smoke Execute",
                    },
                    score=91,
                    status="queued",
                ),
                HunterQueueEntry(
                    session_fp=dismiss_fp,
                    campaign="reactivation",
                    guest_email="smoke-dismiss@crog-ai.com",
                    payload={
                        "property_slug": "smoke-test-cabin",
                        "prey_class": "target_bravo",
                        "drop_off_point": "checkout_step",
                        "drop_off_point_label": "Checkout Step",
                        "guest_display_name": "Smoke Dismiss",
                    },
                    score=77,
                    status="queued",
                ),
            ]
        )
        await session.commit()
    await close_db()
    print(json.dumps({"execute_fp": execute_fp, "dismiss_fp": dismiss_fp}))

asyncio.run(main())
PY
)"
SMOKE_EXECUTE_FP="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['execute_fp'])" "${SEED_JSON}")"
SMOKE_DISMISS_FP="$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['dismiss_fp'])" "${SEED_JSON}")"
echo "    OK execute=${SMOKE_EXECUTE_FP:0:12}… dismiss=${SMOKE_DISMISS_FP:0:12}…"

echo "[7] GET ${APP_BASE}/api/hunter/queue?status_filter=pending_review"
QUEUE_JSON="$(curl -sS -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" "${APP_BASE}/api/hunter/queue?status_filter=pending_review&limit=200")"
python3 - "${QUEUE_JSON}" "${SMOKE_EXECUTE_FP}" "${SMOKE_DISMISS_FP}" <<'PY'
import json
import sys
rows = json.loads(sys.argv[1])
fps = {row.get("session_fp") for row in rows}
missing = [fp for fp in sys.argv[2:] if fp not in fps]
if missing:
    raise SystemExit(f"missing synthetic hunter rows from queue: {missing}")
print("    OK queue rows visible through BFF")
PY

echo "[8] DELETE ${APP_BASE}/api/hunter/queue/{dismiss_fp}"
DISMISS_CODE="$(curl -sS -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" -o /dev/null -w '%{http_code}' \
  -X DELETE "${APP_BASE}/api/hunter/queue/${SMOKE_DISMISS_FP}")"
[[ "${DISMISS_CODE}" == "204" ]] || { echo "FAIL: hunter dismiss -> ${DISMISS_CODE}" >&2; exit 1; }
echo "    OK ${DISMISS_CODE}"

echo "[9] POST ${APP_BASE}/api/hunter/execute"
EXECUTE_JSON="$(curl -sS -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" \
  -X POST "${APP_BASE}/api/hunter/execute" \
  -H 'Content-Type: application/json' \
  -d "{\"session_fp\":\"${SMOKE_EXECUTE_FP}\"}")"
EXECUTE_JOB_ID="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('job_id',''))" "${EXECUTE_JSON}")"
if [[ -z "${EXECUTE_JOB_ID}" ]]; then
  echo "FAIL: hunter execute did not return job_id: ${EXECUTE_JSON}" >&2
  exit 1
fi
echo "    OK job_id=${EXECUTE_JOB_ID}"

echo "[10] Poll async_job_runs + hunter_queue until execute is sent"
(
  cd "${APP_ROOT}"
  FORTRESS_SMOKE_EXECUTE_FP="${SMOKE_EXECUTE_FP}" \
  FORTRESS_SMOKE_EXECUTE_JOB_ID="${EXECUTE_JOB_ID}" \
  python3 - <<'PY'
import asyncio
import os
from sqlalchemy import select
from backend.core.database import get_session_factory, close_db
from backend.models.async_job import AsyncJobRun
from backend.models.hunter import HunterQueueEntry

EXECUTE_FP = os.environ["FORTRESS_SMOKE_EXECUTE_FP"]
JOB_ID = os.environ["FORTRESS_SMOKE_EXECUTE_JOB_ID"]

async def main() -> None:
    Session = get_session_factory()
    async with Session() as session:
        for _ in range(30):
            job = await session.get(AsyncJobRun, JOB_ID)
            queue = await session.execute(
                select(HunterQueueEntry).where(HunterQueueEntry.session_fp == EXECUTE_FP).limit(1)
            )
            entry = queue.scalar_one_or_none()
            if job and job.status == "failed":
                raise SystemExit(f"execute job failed: {job.error_text}")
            if job and job.status == "succeeded" and entry and entry.status == "sent":
                print("    OK execute job succeeded and hunter row marked sent")
                break
            await session.rollback()
            await asyncio.sleep(1)
        else:
            raise SystemExit("timed out waiting for hunter execute success")
    await close_db()

asyncio.run(main())
PY
)

echo "fortress_auth_pipeline_smoke: PASS"
