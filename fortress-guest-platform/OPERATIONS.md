# FORTRESS PRIME: OPERATIONS & RECOVERY RUNBOOK

## 1. INCIDENT RESPONSE: Queue Split-Brain Topology
**Symptom:** Jobs executing twice, database locks, or unexpected worker node collisions.
**Root Cause:** Legacy workers such as `nas_worker.py` booting concurrently with the primary DGX ARQ worker and competing for the same Redis-backed queue topology.
**Resolution:**
- Legacy `fortress-worker.service` has been permanently purged from the DGX cluster.
- Do NOT rebuild or re-enable standalone polling workers.
- Ensure ONLY `fortress-arq-worker.service` owns `backend.core.worker.WorkerSettings`.
- Verify queue ownership:
  `python - <<'PY'`
  `import asyncio`
  `from backend.core.queue import create_arq_pool`
  `async def main():`
  `    pool = await create_arq_pool()`
  `    try:`
  `        print("fortress:arq", await pool.zcard("fortress:arq"))`
  `        print("arq:queue", await pool.zcard("arq:queue"))`
  `    finally:`
  `        await pool.aclose()`
  `asyncio.run(main())`
  `PY`
- Verify active worker processes:
  `python - <<'PY'`
  `import psutil`
  `for proc in psutil.process_iter(["pid", "ppid", "cmdline"]):`
  `    cmd = " ".join(proc.info.get("cmdline") or [])`
  `    if "nas_worker.py" in cmd or "backend.core.worker.WorkerSettings" in cmd:`
  `        print(proc.info["pid"], proc.info["ppid"], cmd)`
  `PY`
- **Verification:** Run `systemctl status fortress-worker.service` and confirm it returns `not-found`.

## 2. INCIDENT RESPONSE: Stale Ledger & Synthetic Residue
**Symptom:** UI displays stuck jobs in `processing` or `queued` state, or the Hunter queue captures synthetic/internal test traffic.
**Root Cause:** Failed test suites, abrupt worker termination, or insufficient filtering of internal identities before queue insertion.
**Resolution (The One-Command Repair):**
- The ARQ worker watchdog now reconciles Redis result records back into `async_job_runs` before classifying jobs as stale.
- Archive and prune old failed or cancelled ledger rows:
  `python backend/scripts/archive_async_job_history.py --older-than-minutes 60 --apply`
  - **UI (manager/super-admin):** Command Center → Admin Operations Glass → *Async job ledger — archive & prune* (same backend: `POST /api/system/ops/async-jobs/archive-prune`; dry-run first).
- If synthetic Hunter rows remain, remove matching `session_fp` artifacts from:
  - `hunter_queue`
  - `recovery_parity_comparisons`
  - `async_job_runs`
- Do not delete live queued storefront candidates until their payloads are inspected for real guest contact data.

## 3. STANDARD PROCEDURE: Worker Restart Verification
When deploying backend async updates or syncing backend dependencies:
1. `touch backend/core/worker.py`
2. `sudo systemctl restart fortress-arq-worker.service`
3. `sudo systemctl restart fortress-backend.service`
4. Monitor the worker:
   `journalctl -u fortress-arq-worker.service -f`
5. **MANDATORY:** You must observe the worker startup markers:
   - `arq_worker_startup`
   - `arq_worker_registry_validated`
6. If fresh `async_job_watchdog_stale_jobs_detected` alerts appear immediately for already-finished jobs, the worker is blind or split-brained and must be investigated before proceeding.

## 4. HUNTER SERVICE: Candidate Validation
- The Hunter service is hardened to drop `@example.com`, `@crog-ai.com`, and identities containing `smoke`, `shadow`, `manual`, `test`, `dedicated`, `synthetic`, `sample`, or `demo`.
- Contactless candidates with no email and no phone are also rejected.
- To verify active live candidates without triggering outreach, query Postgres directly:
  `python - <<'PY'`
  `import asyncio`
  `from sqlalchemy import text`
  `from backend.core.database import get_session_factory, close_db`
  `async def main():`
  `    Session = get_session_factory()`
  `    async with Session() as session:`
  `        rows = await session.execute(text("""`
  `            select session_fp, guest_email, guest_phone, score, status, payload`
  `            from hunter_queue`
  `            where status = 'queued'`
  `            order by score desc, updated_at desc`
  `            limit 10`
  `        """))`
  `        for row in rows.fetchall():`
  `            print(row)`
  `    await close_db()`
  `asyncio.run(main())`
  `PY`
- Reject anything containing:
  - `@example.com`
  - internal `@crog-ai.com`
  - obvious smoke/test markers
  - placeholder phone numbers

## CANONICAL SERVICE STATES
- `fortress-backend.service`: active
- `fortress-arq-worker.service`: active
- `fortress-worker.service`: not found

## NON-NEGOTIABLES
- Do not rebuild `fortress-worker.service`.
- Do not run `nas_worker.py` in parallel with the official worker.
- Do not allow `arq:queue` to accumulate live jobs.
- Keep feature flags in `fortress-guest-platform/.env`.
- Keep cryptographic material in `.env.security`.
