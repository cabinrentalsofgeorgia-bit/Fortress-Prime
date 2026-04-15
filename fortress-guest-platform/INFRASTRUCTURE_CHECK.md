# Infrastructure Check — Fortress Prime Backend
**Date:** 2026-04-14  
**Purpose:** Read-only fact-finding before scheduling a monthly owner statement email job.  
**Scope:** spark-node-2, the only node running the FastAPI backend.  
**Method:** Live shell commands and file reads. No files were modified.

---

## Section 1 — Operating System

The backend host is **spark-node-2**, running **Ubuntu 24.04.4 LTS (Noble Numbat)** on an
ARM64 (aarch64) processor — this is the NVIDIA DGX Spark hardware as expected. The kernel
is Linux 6.17.0-1014-nvidia, which is Ubuntu's NVIDIA-patched kernel for the DGX platform.

```
Linux spark-node-2 6.17.0-1014-nvidia #14-Ubuntu SMP PREEMPT_DYNAMIC
aarch64 GNU/Linux
Ubuntu 24.04.4 LTS (Noble Numbat)
```

The machine has been running without a reboot for at least five days based on service
uptime. It is the host where all backend processes, the database, and the NAS mount live.

---

## Section 2 — Cron: Status and Existing Jobs

### Is system cron running?

**Yes.** The standard Ubuntu `cron` daemon is installed, enabled at boot, and has been
running continuously since April 8. It is a single-process setup on PID 3633:

```
● cron.service - Regular background program processing daemon
   Active: active (running) since Wed 2026-04-08 09:00:54 EDT; 5 days ago
   Main PID: 3633 (cron)
```

### What jobs are already scheduled?

The `admin` user's crontab is extensive. Here is a plain-English summary of what is
already running on this machine:

| Time | Job | What it does |
|------|-----|--------------|
| Every 5 min, always | `email_bridge` | Compliance email archiver — runs very frequently |
| Every 10 min, 8am–10pm | `gmail_watcher` | Scans guest email inbox, drafts AI replies |
| Every 2 hrs | `kyc_watchdog` | Monitors legal case email |
| Every 2 hrs | `ingest_market_imap` | Pulls market intelligence emails |
| Daily 01:00 | `night_shift.sh` | GPU photo indexing |
| Daily 02:00 | `backup_db.sh` | Postgres backup to NAS |
| Daily 02:00 | `classification_janitor.py` | AI self-healing classifier |
| Daily 03:00 | `lockdown_cluster.sh` | Security sweep |
| Daily 03:00 | `rsync` ChromaDB backup | Vector DB backup to NAS |
| Daily 04:00 | `backup_code.sh` | Codebase backup |
| Daily 04:00 | `update_intelligence.sh` | Intelligence update |
| Daily 05:00 | `streamline_property_sync.py` | Streamline property data |
| Daily 05:15 | `groundskeeper_shadow.py` | Operations data |
| Daily 05:30 | `quant_revenue.py` | 30-day rate card generation |
| Daily 05:45 | `universal_intelligence_hunter.py` | Ingests feeds for 9 AI personas |
| Daily 06:00 | `market_watcher` + `watchtower_briefing` | Market briefing emails to Gary |
| Daily 06:15 | `ops_heartbeat.sh` | Operations status |
| Daily 06:30 | `nvidia_sentinel.py` | GPU/driver monitoring |
| Daily 09:00 | `reactivation_hunter` (two entries) | Sales outreach — **note: duplicate entry** |
| @reboot | `revenue_consumer_daemon.py` | Boots an event consumer daemon |
| Sunday 03:00 | `data_hygiene.py` | Weekly database purge |
| Sunday 03:30 | `vector_gc.py` | Vector database garbage collection |
| Sunday 04:00 | Inline `VACUUM ANALYZE` | Database maintenance |
| 1st of month 00:00 | `find ... -delete` | Log file rotation |

The root crontab is empty (or the current user does not have permission to read it).

There is **no existing monthly owner statement job** in this crontab.

The `/etc/cron.d/` directory contains only system-level entries (sysstat, anacron,
e2scrub). Nothing related to the Fortress application.

There is a **duplicate cron entry** for the reactivation hunter (09:00 daily appears
twice with slightly different commands). This is harmless but worth cleaning up.

---

## Section 3 — How the FastAPI Backend Is Running

The FastAPI backend is **not** running in Docker, not in a tmux session, and not started
manually. It is running as a **systemd service** (`fortress-backend.service`), managed
by the operating system. This means it starts automatically on boot and restarts itself
if it crashes.

The launcher chain:

1. **`fortress-backend.service`** calls `/usr/local/bin/run-fortress-backend.sh`
2. That shell script loads three environment files (`.env`, `.env.dgx`, `.env.security`)
3. It then runs `python run.py` inside the project's virtual environment

The ARQ background job worker runs as a **separate** systemd service
(`fortress-arq-worker.service`) that loads the same environment files and runs:

```
python -m arq backend.core.worker.WorkerSettings
```

This is the worker that executes all background tasks (data sync, payouts, AI jobs, etc.).

A third relevant service is `fortress-sync-worker.service`, which runs a continuous
Streamline PMS polling loop (`python -m backend.sync`).

**The backend runs only on spark-node-2.** There is no evidence of the FastAPI application
running on other Spark nodes. (Other services like Ollama and Open WebUI run on other
nodes, but the FastAPI app is single-node.)

**Nine other Fortress systemd services** are also running on this machine: the command
center Next.js app, the Channex channel egress worker, the automation event consumer, the
file watcher, the Ray distributed compute head, the inference bridge, the telemetry
agent, the LiteLLM gateway, and a legal inference mode (currently stopped/failed).

There is **also a systemd timer system** in use — see Section 5.

---

## Section 4 — Network Connectivity

**PostgreSQL database:** ✅ Reachable.  
The database runs on `127.0.0.1:5432` (on the same machine). Connection was confirmed
with `pg_isready` and a live `SELECT version()` query that returned PostgreSQL 16.13.
No network hop is needed.

**Streamline VRS API:** ✅ Reachable.  
The API URL points to `web.streamlinevrs.com` over port 443 (HTTPS). A TCP connection
test confirmed the host is reachable. The code uses `STREAMLINE_API_KEY` for
authentication (key name only; value not shown here).

**Email (SMTP):** ✅ Reachable.  
The configured mail server is `mail.cabin-rentals-of-georgia.com` on port 587 (standard
SMTP submission port). A TCP connection test confirmed the server is accepting connections.
This is the outgoing mail server for the business domain — it is plain SMTP, not a
third-party email service API like SendGrid or Mailgun.

---

## Section 5 — Every Scheduled Job in the Entire Project

The project uses **three different scheduling mechanisms**, all of which are active:

### Mechanism 1: System cron (admin user's crontab)
Already documented fully in Section 2. Approximately 25 jobs defined. The cron daemon
runs all of them. None are related to owner statements.

### Mechanism 2: Systemd timers (the "right" way on Ubuntu)
There are three application timers registered with systemd:

| Timer | Schedule | What it triggers |
|-------|----------|-----------------|
| `fortress-deadline-sweeper.timer` | Daily at 06:00 | A one-shot Python script that sweeps legal/contract deadlines |
| `crog-hunter-worker.timer` | Daily at 09:00 ET | The reactivation hunter (sales outreach) |
| `fortress-nightly-finetune.timer` | Daily at 02:00 | LLM fine-tuning job (currently in failed state) |

All three use `OnCalendar` with `Persistent=true`, which means if the machine was off
at the scheduled time, the job will run once when it comes back up. The deadline sweeper
and hunter timer use `TimeZone=America/New_York`.

### Mechanism 3: ARQ worker's internal polling loops
The ARQ worker (the background job system) runs several **internal async loops** that
fire on their own schedule. These do not appear in crontab or systemd timers — they are
loops inside the Python process itself:

| Loop | Schedule | What it does |
|------|----------|-------------|
| Payout sweep loop | Once daily at 6am ET | Checks if owner payouts are due and fires transfers |
| Hermes daily auditor | Once daily at midnight | Reconciles the trust ledger |
| Streamline sync | Every ~5 minutes | Polls Streamline for reservation/availability changes |
| Parity observer | Configurable interval | SEO/pricing parity checks |
| Research scout | Configurable interval | Acquisition intelligence |

**The ARQ system itself also natively supports cron jobs** via `cron_jobs` in
`WorkerSettings`. This feature exists in the installed version of ARQ (0.27.0) but is
**not currently used** — the `WorkerSettings` class defines only `functions` (on-demand
jobs) with no `cron_jobs` list. The payout sweep and hermes loops are hand-rolled
`asyncio.sleep()` loops instead of using ARQ's built-in cron feature.

### Searching for other scheduler libraries
- **APScheduler:** Not found in the codebase.
- **Celery:** Not found.
- **Dramatiq / RQ:** Not found.
- **Python `schedule` library:** Not found.
- **BackgroundScheduler:** Not found.

---

## Section 6 — Email Provider

The email provider is **plain SMTP** using the business's own mail server at
`mail.cabin-rentals-of-georgia.com` on port 587.

This is not a third-party transactional email service (not SendGrid, Mailgun, Postmark,
AWS SES, Resend, or similar). The configured environment variables are:
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM_NAME`,
`EMAIL_FROM_ADDRESS`.

The email service code (`backend/services/email_service.py`) uses Python's built-in
`smtplib` to connect directly to this server. The code will skip sending silently if
`SMTP_HOST` or `SMTP_USER` is not set, returning `False` instead of raising an error.

The code has been verified working in practice — it successfully sends booking alert
emails when reservations are confirmed. The test suite shows expected failures when
the email address does not exist (deliverability problem at destination, not a
configuration problem at the sending end).

---

## Section 7 — Streamline API: What We Can Already Call (Owner-Relevant)

The Streamline integration file (`backend/integrations/streamline_vrs.py`) already
knows how to call the following Streamline API methods, all of which are relevant to
owner statements and reconciliation:

### Methods already implemented:

**`GetOwnerList` → `fetch_owners()`**
Returns the directory of all property owners: owner ID, name, email. This is how we
get the Streamline owner ID that all other owner-specific calls require.

**`GetUnitOwnerBalance` → `fetch_unit_owner_balance(unit_id)`**
Returns the current outstanding balance owed to the owner for a specific property unit.
This is called during the nightly full sync (Phase 7) and stores the result on the
property record.

**`GetMonthEndStatement` → `fetch_owner_statement(owner_id, unit_id, start_date, end_date, include_pdf)`**
This is the most important one for the statement job. It calls Streamline's
`GetMonthEndStatement` endpoint with a date range and an owner ID. It can optionally
return a PDF of the statement. The method is already fully implemented with date
defaulting logic (it defaults to the previous month if no dates are supplied).

**`GetReservations` (return_full:true) → `fetch_reservations(start_date, end_date)`**
Returns reservations with full guest details, payment folio, owner charges, and
housekeeping schedule. This is the source of truth for what revenue was generated in a
given period.

### Notably not implemented:
The code comments mention `GetOwnerStatements` as a deprecated alternative and
recommends using `GetMonthEndStatement` instead. There is no separate "owner ledger by
date range" call, but `GetMonthEndStatement` with a date range covers that use case.

The full sync in `run_full_sync()` already calls `fetch_owners()` and
`fetch_unit_owner_balance()` as Phase 7 of the nightly sync. It does not currently
call `fetch_owner_statement()` on a schedule — that is what the new monthly job would do.

---

## Recommendations

### Is spark-node-2 the right host for a monthly cron job?

**Yes, it is the only option**, and it is appropriate. The database, the Streamline
connection, and the SMTP server are all reachable from this machine. The backend process
is managed by systemd and restarts automatically. The NAS is mounted. This is the
canonical backend host.

The one thing to note: the machine is already running roughly 25 cron entries plus
9+ systemd services. It is not at risk of running out of resources for a lightweight
monthly job, but the crontab is getting crowded and disorganized.

### Is system cron the right tool, or should we use something already in place?

**System cron is the wrong tool for this job.** The better option — the one already
established on this machine — is a **systemd timer**.

Here is why:

1. **Two other application jobs already use systemd timers** (`fortress-deadline-sweeper`
   and `crog-hunter-worker`). The pattern is established.

2. **Systemd timers have `Persistent=true`**, which means if the machine is off or
   rebooting on the 1st of the month at 08:00, the job will still run once when the
   machine comes back up. A cron job would silently miss that window.

3. **Systemd gives you `journalctl -u fortress-owner-statements` for logs**, status
   checks with `systemctl status`, and failure alerts. A cron job writes to a log
   file only if you configure it.

4. There is also a **third option worth considering**: ARQ's built-in `cron_jobs`
   feature. ARQ 0.27.0 supports it natively, and the ARQ worker is already running
   24/7 on this machine. Adding the monthly statement job as an ARQ cron entry in
   `WorkerSettings.cron_jobs` would mean it is tracked in the same system as all
   other background jobs, benefits from ARQ's retry logic, and does not require a
   separate service or timer file. The existing payout sweep loop (which currently
   uses a hand-rolled `asyncio.sleep` loop) is evidence that the team was unaware of
   this feature — there is an opportunity to consolidate.

**Recommended approach:** Use an ARQ `cron_jobs` entry, not a systemd timer and not
system cron. It fits the architecture already in place.

### What would you need before scheduling this safely?

1. **Confirmation of the target time and timezone.** The payout sweep and hunter timer
   both use `America/New_York` (Eastern Time). Should the statement job also run at
   08:00 ET on the 1st of each month? Or a different time? The comment in the code
   says "1st of month at 08:00 ET" but this was never actually wired.

2. **Decision on the data source.** The current `send_monthly_statement()` function
   builds the statement from the local Postgres database (the `reservations` table).
   The Streamline integration has `fetch_owner_statement()` which can pull the
   authoritative statement directly from Streamline, including a PDF. Which one should
   the job use? Using Streamline's own statement data would be more accurate for
   reconciliation; using local Postgres is simpler and faster. This decision affects
   what the job does.

3. **A test run against a real enrolled owner.** The statement email code has never
   been sent to a real owner (the test suite only checks the "skip gracefully when no
   owner is enrolled" case). Before automating it monthly, it should be sent manually
   once to a test email address to confirm the HTML renders correctly, the numbers
   are right, and the email arrives.

4. **Confirmation that `owner_payout_accounts` has real rows.** The statement job
   iterates over enrolled owners. If no owners have accepted their invitations yet,
   the job would run but send nothing. This is not harmful but should be understood
   by the person scheduling it.

5. **A way to monitor failures.** If the SMTP server is down on the 1st of the month,
   the job silently returns `False`. There is currently no alerting. At minimum, the
   job should write a summary to a log that can be checked, and ideally it should
   send a failure notification to an admin address.
