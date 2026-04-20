# Fortress Prime Operations Runbook

## CREDENTIAL ROTATION NOTICE 2026-04-20

The following credentials were previously hardcoded in source and were scrubbed in PR #98.
**Both must be rotated before running any script that uses them.**

- **`analyst_writer` postgres role password** — used by `src/fleet_commander.py`.
  Set new password via `sudo -u postgres psql -c "ALTER ROLE analyst_writer PASSWORD '...';"`,
  then update `ANALYST_WRITER_PASSWORD` in `.env` and vault.

- **Fortress staff login password** (`cabin.rentals.of.georgia@gmail.com`) — used by
  `seed_master_admin.py`, `smoke_test_seo.py`, and E2E Playwright helpers.
  Rotate via the staff login UI or `backend/scripts/reset_staff_password.py`,
  then update `FORTRESS_SMOKE_PASSWORD` and `ADMIN_SEED_PASSWORD` in `.env` and vault.

All three env vars are now required at runtime — scripts fail fast with a clear error if unset.

This runbook captures the verified recovery steps for the Fortress Prime async runtime after the auth and Hunter incident.

## Canonical Worker Topology

- `fortress-arq-worker.service` is the only allowed ARQ owner for `backend.core.worker.WorkerSettings`.
- `fortress-backend.service` serves the FastAPI authority.
- `fortress-worker.service` and `nas_worker.py` are deprecated legacy paths and must remain disabled.

## Queue Split-Brain Check

Use this when jobs appear queued in `async_job_runs` but do not drain.

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
python - <<'PY'
import asyncio
from backend.core.queue import create_arq_pool

async def main():
    pool = await create_arq_pool()
    try:
        print("fortress:arq", await pool.zcard("fortress:arq"))
        print("arq:queue", await pool.zcard("arq:queue"))
    finally:
        await pool.aclose()

asyncio.run(main())
PY
```

Expected steady state:

- `fortress:arq` carries live work for the official worker.
- `arq:queue` must stay empty.

If `arq:queue` is non-zero, look for an unauthorized worker:

```bash
python - <<'PY'
import psutil
for proc in psutil.process_iter(["pid", "ppid", "cmdline"]):
    cmd = " ".join(proc.info.get("cmdline") or [])
    if "nas_worker.py" in cmd or "backend.core.worker.WorkerSettings" in cmd:
        print(proc.info["pid"], proc.info["ppid"], cmd)
PY
```

## Service Health Checks

```bash
systemctl is-active fortress-backend.service fortress-arq-worker.service fortress-worker.service
```

Expected:

- `fortress-backend.service` = `active`
- `fortress-arq-worker.service` = `active`
- `fortress-worker.service` = `inactive` or `not-found`

## Smoke Verification

Run the full auth, BFF, and Hunter smoke suite:

```bash
cd /home/admin/Fortress-Prime
FORTRESS_SMOKE_EMAIL='cabin.rentals.of.georgia@gmail.com' \
FORTRESS_SMOKE_PASSWORD='<your-password-here>' \
./scripts/fortress_auth_pipeline_smoke.sh
```

Pass condition:

- backend login works
- BFF cookie bridge works
- dashboard hydration works
- Hunter dismiss returns `204`
- Hunter execute reaches `sent`

## Ledger Reconciliation

The ARQ worker watchdog now reconciles finished Redis result records back into `async_job_runs` before classifying jobs as stale.

If the ledger still contains old failed or cancelled rows that are no longer operator-relevant, archive and prune them:

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
python backend/scripts/archive_async_job_history.py --older-than-minutes 60 --apply
```

Archive output lands under:

- `fortress-guest-platform/backend/artifacts/async-job-archives/`

## Hunter Cleanup

If synthetic Hunter rows were created during diagnostics, remove them from:

- `hunter_queue`
- `recovery_parity_comparisons`
- `async_job_runs`

Do not delete live queued Hunter candidates. Confirm the target `session_fp` values first.

## Restart Sequence

Use this after worker code or queue-repair changes:

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
touch backend/core/worker.py
sudo systemctl restart fortress-arq-worker.service
sudo systemctl restart fortress-backend.service
```

Then verify:

```bash
systemctl is-active fortress-arq-worker.service fortress-backend.service
sudo journalctl -u fortress-arq-worker.service -n 40 --no-pager
```

## Non-Negotiables

- Do not re-enable `fortress-worker.service`.
- Do not launch `nas_worker.py` unless explicitly doing isolated legacy forensics.
- Do not allow any process to consume `arq:queue`.
- Keep feature flags in `fortress-guest-platform/.env`.
- Keep cryptographic material in `.env.security` only.
