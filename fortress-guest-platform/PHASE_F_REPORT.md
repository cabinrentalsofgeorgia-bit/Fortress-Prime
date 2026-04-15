# Phase F Report — Owner Statement Cron and Send Pipeline
**Date:** 2026-04-14  
**Test count before:** 762  **Test count after:** 790 passing (+28 Phase F tests, same 3 pre-existing failures)

---

## 1. ARQ Cron Registration

Both jobs are registered in `WorkerSettings.cron_jobs` in `backend/core/worker.py`.
ARQ 0.27 evaluated the schedule against timezone `America/New_York`.

| Job | Day | Hour (ET) | Minute | Next fire (from 2026-04-14 17:46 EDT) |
|---|---|---|---|---|
| `generate_monthly_statements_job` | 12 | 06:00 | 00 | **2026-05-12 06:00 EDT** |
| `send_approved_statements_job` | 15 | 09:30 | 30 | **2026-04-15 09:30 EDT** |

Both use `run_at_startup=False`. Both are also registered in `WorkerSettings.functions`
(ARQ requires this for cron jobs to execute, in addition to the `cron_jobs` list).

---

## 2. generate_monthly_statements_job

**File:** `backend/tasks/statement_jobs.py`

**Signature:**
```python
async def generate_monthly_statements_job(ctx: dict[str, Any]) -> None
```

**What it does:**
1. Computes the previous calendar month's dates via `compute_previous_month(date.today())`:
   - `first_of_this_month - 1 day` = last day of previous month = `period_end`
   - `period_end.replace(day=1)` = first day of previous month = `period_start`
2. Calls `generate_monthly_statements(db, period_start, period_end, dry_run=False)`
3. Tallies outcomes: created, updated, skipped_locked, skipped_not_renting, skipped_not_enrolled, error
4. Calls `_send_alert_email_summary()` with the results
5. Returns None — no exceptions propagate

**Previous-month computation (edge cases):**

| Today | period_start | period_end |
|---|---|---|
| May 12 | April 1 | April 30 |
| January 15 | December 1 (prev year) | December 31 (prev year) |
| March 12 | February 1 | February 28 (or 29 leap) |
| February 1 | January 1 | January 31 |

**Exception handling:** The entire function body is wrapped in `try/except`. If an
unexpected exception occurs, `summary.fatal_error` is populated, the alert email is sent
with a FAILED subject, and the function returns cleanly — the ARQ worker loop is
never disrupted.

**Parallel mode:** This job runs unconditionally regardless of `CROG_STATEMENTS_PARALLEL_MODE`.
The flag only suppresses email sends, not statement generation.

---

## 3. send_approved_statements_job

**File:** `backend/tasks/statement_jobs.py`

**Signature:**
```python
async def send_approved_statements_job(ctx: dict[str, Any]) -> None
```

**Parallel mode gate (first thing the function checks):**
```python
if settings.crog_statements_parallel_mode:
    logger.info("parallel_mode_active_skipping_sends")
    _send_alert_email_summary(summary, run_ts)   # alert says PARALLEL MODE
    return
```

**Per-statement loop (when parallel_mode=False):**
1. Query for all `OwnerBalancePeriod` rows with `status='approved'` and `emailed_at IS NULL`
2. For each period:
   a. Load OPA → get `owner_email`, `owner_name`
   b. Load Property → get `prop_name`
   c. Render PDF via `render_owner_statement_pdf(db, period.id)`
   d. Build filename: `owner_statement_{last}_{prop_short}_{YYYY-MM}.pdf`
   e. Call `send_email(to=owner_email, subject="Your statement for {Month YYYY}...", attachments=[PDF])`
   f. On SMTP success: call `mark_statement_emailed(db, period.id)` → status transitions to `emailed`
   g. On SMTP failure: log error, record in summary, **continue to next statement**

**Failure isolation:** One owner's send failure does not block the rest. The job
completes all statements and summarizes failures in the alert email.

**Exception handling:** Same `try/except` wrapper as the generation job.

---

## 4. Manual Test Endpoint

**Endpoint:** `POST /api/admin/payouts/statements/{period_id}/send-test`  
**Auth:** `require_manager_or_admin`

**Request body:**
```json
{
  "override_email": "admin@crog.com",
  "note": "optional verification note"
}
```

**Example curl:**
```bash
curl -X POST http://localhost:8100/api/admin/payouts/statements/10907/send-test \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"override_email": "gary@crog.com", "note": "Checking the Knight Feb 2026 statement"}'
```

**Response (success):**
```json
{
  "success": true,
  "sent_to": "gary@crog.com",
  "statement_status_unchanged": true,
  "pdf_size_bytes": 4737,
  "message": "Test statement for February 2026 sent to gary@crog.com. The real owner (Knight Mitchell Gary) was NOT notified. Statement status remains 'pending_approval'."
}
```

**Error responses:**
- `404` — period_id not found
- `400` — override_email fails pattern validation (`^[^@\s]+@[^@\s]+\.[^@\s]+$`)
- `500` — SMTP not configured, or SMTP send failed

**Key behaviors:**
- Does NOT call `mark_statement_emailed` — statement stays in its current status
- Works regardless of `CROG_STATEMENTS_PARALLEL_MODE`
- Subject line: `[TEST] Your statement for {Month YYYY} — Cabin Rentals of Georgia`
- Email body: `*** THIS IS A TEST SEND ***` warning + real owner name/email disclosure

---

## 5. Alert Email

**Function:** `_send_alert_email_summary(summary: JobSummary, run_timestamp: datetime)`

### Normal generation run (subject example):
```
[Crog-VRS] generate_monthly_statements for April 2026 (2026-04-01 to 2026-04-30) — 9 created, 0 errors
```

### Parallel mode send run (subject example):
```
[Crog-VRS] PARALLEL MODE send_approved_statements for April 2026 (2026-04-01 to 2026-04-30) — 0 sent, 0 failed
```

### Failed run (subject example):
```
[Crog-VRS] FAILED generate_monthly_statements — see details
```

### Body structure (plain text):
```
Crog-VRS Owner Statement Job Run
=================================
Job:        generate_monthly_statements
Period:     April 2026 (2026-04-01 to 2026-04-30)
Run time:   2026-04-12 11:00:23 UTC
*** PARALLEL MODE ACTIVE ***   [if applicable]
FATAL ERROR: [error message]   [if applicable]

Results
-------
Created/drafted:   9
Updated drafts:    0
Skipped (locked):  1
Skipped (no rent): 0
Skipped (no enrl): 4
Errors:            0
Emails sent:       0
Emails failed:     0

Per-owner outcomes
------------------
  Knight Mitchell Gary    Cherokee Sunrise...   created
  Dutil David             Above the Timberl...  created
  Patrick M Rooke         Cohutta Sunset        created
  ... (up to 50 shown)

Review the statement queue at:
  GET /api/admin/payouts/statements?status=pending_approval
  GET /api/admin/payouts/statements?status=approved
```

**When alert email cannot be sent:**
- `OWNER_STATEMENT_ALERT_EMAIL` unset → logs `ERROR owner_statement_alert_email_not_configured` and returns cleanly
- SMTP not configured → logs `WARNING smtp_not_configured_skipping_alert` and returns cleanly
- Neither failure stops the cron job from completing

---

## 6. Required Env Vars

| Variable | Default | Purpose |
|---|---|---|
| `CROG_STATEMENTS_PARALLEL_MODE` | `true` | Gates real email sends. `true` = generation only, no owner emails. |
| `OWNER_STATEMENT_ALERT_EMAIL` | `""` | Receives run-summary after every cron fire. Leave empty to disable. |

Both are defined in `backend/core/config.py` and documented in `.env.example`.

---

## 7. Test Count Delta

| Phase | Passing | Notes |
|---|---|---|
| Phase E.6 baseline | 762 | |
| Phase F | **790** | +28 Phase F tests |

3 pre-existing failures unchanged.

---

## 8. Confidence: HIGH

All 28 Phase F tests pass. ARQ loaded both cron jobs successfully and reported correct
next-fire times. The worker import was verified at runtime. The send-test endpoint correctly:
rejects bad emails, returns 404 for missing periods, does not transition statement status,
includes `[TEST]` in subject, and returns 500 on SMTP failure.

---

## 9. Critical Operator Instructions

### Before the next 12th of any month

1. Set `OWNER_STATEMENT_ALERT_EMAIL` in the production `.env` file:
   ```
   OWNER_STATEMENT_ALERT_EMAIL=gary@cabin-rentals-of-georgia.com
   ```

2. Restart the ARQ worker so it picks up the new env var:
   ```bash
   systemctl restart fortress-arq-worker.service
   ```

3. Verify the cron is registered after restart:
   ```bash
   systemctl status fortress-arq-worker.service
   # Look for log lines like:
   #   cron job registered: generate_monthly_statements_job day=12 hour=6 minute=0
   ```
   Or check the ARQ logs directly:
   ```bash
   journalctl -u fortress-arq-worker.service --since "1 hour ago"
   ```

### Enabling real owner emails (Phase G cutover)

**DO NOT** set `CROG_STATEMENTS_PARALLEL_MODE=false` until:
1. Phase G parallel validation has completed
2. The product owner has reviewed the validation report and approved the cutover
3. The decision is recorded in NOTES.md with the date

To enable real sends after Phase G approval:
```bash
# In production .env:
CROG_STATEMENTS_PARALLEL_MODE=false
systemctl restart fortress-arq-worker.service
```

**Test the pipeline first** using the manual test endpoint:
```bash
curl -X POST /api/admin/payouts/statements/{period_id}/send-test \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"override_email": "your@email.com", "note": "Phase G validation complete"}'
```

---

## 10. NOTES.md Additions

Added to NOTES.md:
- "DO NOT set CROG_STATEMENTS_PARALLEL_MODE=false until Phase G completes"
- "OWNER_STATEMENT_ALERT_EMAIL must be set before the next 12th"

---

## STOP — Product Owner Review Required

Phase F is complete. Before Phase G:

1. Set `OWNER_STATEMENT_ALERT_EMAIL` in the production `.env`
2. Restart `fortress-arq-worker.service`
3. Confirm the next-fire time for the generation cron (May 12, 2026 at 06:00 ET)
4. Optionally: test the manual send endpoint against a known `period_id` to verify the PDF email pipeline end-to-end
5. Do NOT set `CROG_STATEMENTS_PARALLEL_MODE=false` — that happens only after Phase G
