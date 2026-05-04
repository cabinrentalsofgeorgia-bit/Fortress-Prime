# MarketClub Hedge Fund Signals Production Runbook

**Status:** release hardening only; no new product mechanics
**Scope:** Hedge Fund Signals cockpit, dry-run gate, guarded execution, rollback, audit, monitoring, alerts, and Signal Health Dashboard
**Primary audience:** supervised operator and release owner

## Release Rule

Do not expand product behavior until this runbook, the audit playbook, incident response checklist, rollback drill checklist, hosted database migration verification, RLS/policy verification, and staging smoke test are complete.

This phase is not allowed to add:

- automatic rollback
- automatic trade or signal changes
- acceptance/execution shortcuts
- ticker/date rollback paths
- new production write mechanics
- RLS bypasses or broad grants

## Production Surfaces

Backend:

- service: `crog-ai-backend.service`
- port: `127.0.0.1:8026`
- required env: `DATABASE_URL`
- optional env: `CROG_AI_CORS_ORIGINS`
- app health: `GET /healthz`

Database:

- schema: `hedge_fund`
- Alembic version table: `hedge_fund.alembic_version_crog_ai`
- app role: `crog_ai_app`
- production baseline parameter set: `dochia_v0_estimated`
- candidate parameter set: `dochia_v0_2_range_daily`

Cockpit:

- Command Center path: `/financial/hedge-fund`
- read-only awareness layer: `GET /api/financial/signals/health-dashboard`
- audit endpoints under `GET /api/financial/signals/promotion/{id}/...`

## Pre-Release Lock

The release owner must record:

- branch, PR number, merge commit, and deploy target
- staging backend URL and staging cockpit URL
- database name and host
- operator token owner for execution/rollback drills
- last backup timestamp or hosted provider restore point
- exact Alembic head before migration
- exact Alembic head after migration

Hard stop if the target database is not `fortress_db` or the staging/production database cannot be distinguished.

## Environment And Config Verification

Run on the target host before deploying:

```bash
systemctl status crog-ai-backend.service --no-pager
systemctl cat crog-ai-backend.service
journalctl -u crog-ai-backend.service -n 80 --no-pager
```

Verify:

- service runs as `admin`
- working directory is `/home/admin/Fortress-Prime/crog-ai-backend`
- `NoNewPrivileges=true`
- backend binds `127.0.0.1:8026`
- no operator token, database password, or raw `DATABASE_URL` is printed in logs
- `DATABASE_URL` points to `fortress_db`, not `fortress_prod`
- frontend `NEXT_PUBLIC_API_URL` points to the intended backend for staging
- Cloudflare/tunnel route points at the intended frontend/backend pair

Backend checks:

```bash
cd /home/admin/Fortress-Prime/crog-ai-backend
.venv/bin/python - <<'PY'
from app.database import database_url
url = database_url()
print(url.split('@')[-1])
assert 'fortress_db' in url
assert 'fortress_prod' not in url
PY
curl -fsS http://127.0.0.1:8026/healthz
```

## Hosted DB Migration Verification

Before running migrations:

```bash
cd /home/admin/Fortress-Prime/crog-ai-backend
.venv/bin/alembic current
.venv/bin/alembic history --verbose | head -80
```

Apply only after confirming the restore point:

```bash
.venv/bin/alembic upgrade head
.venv/bin/alembic current
```

Then run the read-only verification SQL:

```bash
psql "$DATABASE_URL" \
  -v ON_ERROR_STOP=1 \
  -f deploy/sql/marketclub_release_hardening_verification.sql
```

Required outcomes:

- `hedge_fund.alembic_version_crog_ai` is at the expected head
- all audit, monitoring, alert, acknowledgement, and signal health objects exist
- `crog_ai_app` has SELECT/EXECUTE only where expected
- no unexpected `SECURITY DEFINER` functions are present
- rollback and execution audit tables can be joined by audited IDs
- no duplicate executions exist for the same acceptance/idempotency pair

## RLS And Policy Verification

Run the RLS section in `deploy/sql/marketclub_release_hardening_verification.sql`.

Hard stop if:

- any promoted write/audit table has RLS unexpectedly disabled
- `crog_ai_app` has INSERT/UPDATE/DELETE on tables outside the intentional function path
- `PUBLIC` has privileges on Hedge Fund signal tables, views, or functions
- a new `SECURITY DEFINER` function appears without a narrow, documented operator check
- rollback can be reasoned about by ticker/date instead of audited `market_signal_id`

## Staging Smoke Test

Use `MARKETCLUB-SIGNALS-STAGING-SMOKE-TEST.md`.

Minimum pass:

- backend health works
- cockpit loads `/financial/hedge-fund`
- Promotion Gate, Shadow Review, Dry-Run Verification Gate, Lifecycle Timeline, Reconciliation, Post-Execution Monitoring, Post-Execution Alerts, and Signal Health Dashboard render
- acceptance button remains disabled unless verification is PASS
- execution/rollback controls are not triggered during smoke
- health dashboard alerts are non-blocking warnings only

## Release Decision

Release may proceed only when:

- local and CI tests passed
- hosted migration verification passed
- RLS/policy verification passed
- staging smoke test passed
- incident response and rollback drill checklists are reviewed
- operator audit playbook is current

Record the sign-off in the release notes with:

- release owner
- timestamp
- PR/commit
- staging evidence links
- migration version
- smoke test result
- known warnings

## Post-Release Watch

For the first trading session after deploy, watch:

- `GET /api/financial/signals/health-dashboard`
- `GET /api/financial/signals/promotion/{id}/reconciliation`
- `GET /api/financial/signals/promotion/{id}/alerts`
- backend logs for 5xx/errors
- database lock or permission errors

Escalate using `MARKETCLUB-SIGNALS-INCIDENT-RESPONSE-CHECKLIST.md` if any audit invariant changes from `HEALTHY/WARNING` to `ERROR`, any mutation endpoint fails after operator submission, or the cockpit cannot trace decision -> execution -> outcome -> rollback.
