# Spark-1 Current State Capture — 2026-04-29

**Captured:** 2026-04-28 23:30 EDT (early hours of 2026-04-29)
**Captured by:** Claude Code (Opus 4.7, 1M ctx) at operator's direction
**Operator:** Gary Knight
**Source brief:** `/home/admin/flos-phase-a1-postgres-spark1-brief.md` (last edited 2026-04-28 22:49)
**Reason for capture:** Phase A1 brief assumed clean-host install. Spark-1 is not clean — application migration from spark-2 is in progress. Capture state, defer A/B/C decision to morning session.
**Read-only:** No DB / config / service changes were made during capture.

---

## Executive summary

Spark-1 is in the **middle of a spark-2 → spark-1 application migration**. As of this capture:

- **Postgres 16.13** (Ubuntu repo, NOT PGDG) is installed and running. Service started 2026-04-28 11:16 EDT, ~12 hours ago. Cluster `16/main` on `/var/lib/postgresql/16/main`.
- **Three identical schema-only Postgres databases** exist (`fortress_db`, `fortress_prod`, `fortress_shadow_test`) — full Fortress-Prime schema (13 schemas, 291 tables each), zero application data.
- **Two roles** (`fortress_admin`, `fortress_api`) — match canonical contract.
- **`/etc/fortress/admin.env`** holds three Postgres passwords (admin, api, **app**) — `admin:admin 600`, **NOT root-owned** as the Phase A1 brief specifies.
- **Application code copied to `/home/admin/Fortress-Prime.new/`** (symlinked as `Fortress-Prime`) — last touched today.
- **No service** on spark-1 currently consumes this Postgres via systemd `EnvironmentFile=`. No client connections. The DB is provisioned but idle.
- **Inference plane on spark-1 untouched and running:** `fortress-nim-sovereign` container (NIM Llama-3.1-8B), `fortress-ray-worker.service`, `ollama.service`, `fortress-brain.service` (Streamlit on `0.0.0.0:8501`).
- **Postgres bound:** `127.0.0.1:5432`, `192.168.0.104:5432` (LAN). **NOT** on Tailscale `100.127.241.36`.
- **pg_hba.conf** has only one host fortress rule: `host fortress_prod fortress_admin 192.168.0.100/32` (spark-2 LAN, admin only). No `fortress_api` rules. No spark-5 rules. No Tailscale rules.

**The Phase A1 brief and the actual state diverge in shape, not just degree.** Brief assumes "install + configure on clean host." Reality is "application migration in flight, Postgres provisioned by a different bootstrap, Phase A1 must layer onto migration, not replace it."

---

## A. Database inventory

### A.1 DB list and sizes
| DB | Owner | Size | Notes |
|---|---|---|---|
| `fortress_db` | fortress_admin | 36 MB | Schema-only |
| `fortress_prod` | fortress_admin | 36 MB | Schema-only |
| `fortress_shadow_test` | fortress_admin | 36 MB | Schema-only — **NOT in Phase A1 brief** |
| `fortress_shadow` | — | — | **Does not exist.** Operator's capture spec asked for it; not present. |
| `postgres` | postgres | 7.5 MB | Default admin DB |
| `template0` / `template1` | postgres | ~7.5 MB each | Default templates |

All three fortress DBs are **structurally identical**: 13 schemas, 291 tables, same `alembic_version` pair. Restored from the same dump source.

### A.2 Schemas (identical across all three fortress DBs)

```
core             (1 table)   — deliberation_logs
crog_acquisition (6 tables)  — properties, parcels, owners, acquisition_pipeline, intel_events, owner_contacts
division_a       (7 tables)  — chart_of_accounts, journal_entries, transactions, GL, predictions, etc.
division_b       (9 tables)  — same shape + escrow, trust_ledger, vendor_payouts
engineering      (11 tables) — projects, drawings, RFIs, permits, inspections, change_orders, etc.
finance          (2 tables)  — classification_rules, vendor_classifications
hedge_fund       (4 tables)  — active_strategies, watchlist, market_signals, extraction_log
intelligence     (4 tables)  — entities, golden_reasoning, relationships, titan_traces
iot_schema       (2 tables)  — device_events, digital_twins
legal            (38 tables) — case_*, dispatcher_*, mail_ingester_*, sanctions_*, vault_documents, event_log, etc.
legal_cmd        (7 tables)  — attorneys, attorney_scoring, deliberation_events, documents, matters, meetings, timeline
public           (199 tables, owner=pg_database_owner) — full Fortress-Prime + CROG-AI surface
verses_schema    (1 table)   — products
```

### A.3 Row counts (key tables)

| DB | `legal.event_log` | `legal.cases` | `public.email_archive` |
|---|---|---|---|
| fortress_db | 0 | 0 | 0 |
| fortress_prod | 0 | 0 | 0 |
| fortress_shadow_test | 0 | 0 | 0 |

**Only one table > 100 rows in any DB:** `public.spatial_ref_sys` = 8500 rows — that's PostGIS reference data, populated by the `postgresql-16-postgis-3` install. **No application data** has been loaded into any DB yet.

### A.4 alembic_version (identical across all three DBs)

```
q2b3c4d5e6f7
r3c4d5e6f7g8
```

**Two rows = divergent migration heads.** This is exactly the Issue #204 trap the Phase A1 brief warns about. Whatever schema dump was used had a multi-head alembic state baked in. Future `alembic upgrade head` will fail or branch.

### A.5 Full table list of fortress_db (representative — same in all three DBs)

291 rows total. See `/home/admin/.claude/projects/-home-admin/2ce642cf-93e1-4238-93ee-92149b4275fe/tool-results/byfpwn9cf.txt` for the complete listing if needed (preserved tool-results file). Key clusters:

- **legal.\*** (38): case_actions, case_evidence, case_graph_edges_v2/nodes_v2, case_posture, case_precedents, case_slug_aliases, case_statements, case_statements_v2, case_watchdog, cases, chronology_events, correspondence, deadlines, deposition_kill_sheets_v2, discovery_draft_items_v2/packs_v2, dispatcher_dead_letter, dispatcher_event_attempts, dispatcher_pause, dispatcher_routes, distillation_memory, entities, event_log, expense_intake, filings, ingest_runs, legal_exemplars, mail_ingester_metrics/pause/state, priority_sender_rules, privilege_log, sanctions_alerts_v2, sanctions_tripwire_runs_v2, timeline_events, uploads, vault_documents
- **legal_cmd.\*** (7): attorney_scoring, attorneys, deliberation_events, documents, matters, meetings, timeline
- **public.\*** (199): full CROG-AI hospitality surface (reservations, guest_*, property_*, ruebarue_*, etc.) PLUS Fortress-Prime cross-cutting (alembic_version, agent_*, ai_*, intelligence_ledger, legal_clients/docket/intel/matters, etc.)

---

## B. Role inventory

```
   Role name    |                         Attributes                         
----------------+------------------------------------------------------------
 fortress_admin | Create role, Create DB                                     
 fortress_api   | (login only — no CREATEDB, no superuser, no replication)   
 postgres       | Superuser, Create role, Create DB, Replication, Bypass RLS 
```

**Three roles total.** Matches canonical contract: `fortress_admin` + `fortress_api`. **No `fortress_readonly`. No `fortress_app`** — even though `admin.env` has `POSTGRES_FORTRESS_APP_PASSWORD`. The "app" key is orphaned.

### B.1 CONNECT privilege matrix

| DB | postgres | fortress_admin | fortress_api |
|---|---|---|---|
| fortress_db | t | t | t |
| fortress_prod | t | t | t |
| fortress_shadow_test | t | t | t |

CONNECT is granted everywhere (default for all roles unless revoked). But **no Phase 0a-8 grants** have been applied — `fortress_api` cannot INSERT to `legal.event_log` and cannot UPDATE `legal.event_log_id_seq` (verified earlier in this session, not re-checked here).

---

## C. Active connections

```
 datname  | usename  | application_name | client_addr | state  |         query_start         
----------+----------+------------------+-------------+--------+-----------------------------
 postgres | postgres | psql             |             | active | 2026-04-28 23:30:20.5474-04
```

**One row, and it's the diagnostic query itself.** Zero application traffic. **Nothing is using this DB right now.**

---

## D. Secrets file

```
-rw------- 1 admin admin 250 Apr 28 10:39 /etc/fortress/admin.env
```

**Keys (values not dumped):**
```
POSTGRES_FORTRESS_ADMIN_PASSWORD
POSTGRES_FORTRESS_APP_PASSWORD
POSTGRES_FORTRESS_API_PASSWORD
```

**`/etc/fortress/` directory state:**
```
drwx------   2 admin admin   4096 Apr 28 10:39 .
drwxr-xr-x 190 root  root   12288 Apr 28 10:52 ..
-rw-------   1 admin admin    250 Apr 28 10:39 admin.env
-rw-------   1 root  root      83 Apr 19 13:04 nim.env  (NGC_API_KEY only)
```

**Brief expectation vs reality:**
- Brief wants: `/etc/fortress/spark-1-postgres.env`, root-owned, mode 600
- Reality: `/etc/fortress/admin.env`, `admin:admin`, mode 600
- Different filename, different ownership. Brief's path does not exist.

**No other Postgres-credential `.env` files anywhere on the system** (verified via `find / -name "*fortress*.env"`).

---

## E. systemd consumers of admin.env / fortress_db / fortress_prod / fortress_app

```
$ sudo grep -rl "admin.env\|fortress_db\|fortress_prod\|fortress_app" /etc/systemd/system/
(no matches)
```

**Zero systemd units reference any of these.** Confirmed by exhaustive grep.

### E.1 All `EnvironmentFile=` references in systemd

```
fortress-nim-sovereign.service  → /etc/fortress/nim.env       (NGC_API_KEY only — unrelated to Postgres)
k3s-agent.service               → /etc/default/k3s-agent etc. (k3s, unrelated)
dgx-dashboard.service           → /opt/nvidia/dgx-dashboard-service/ports.env
nvidia-cdi-refresh.service      → /etc/nvidia-container-toolkit/nvidia-cdi-refresh.env
snap.mesa-2404.component-monitor.service → /etc/environment
```

**No fortress-app / fortress-api / fortress-brain / fortress-ray-worker service references admin.env.** The Streamlit Brain on 0.0.0.0:8501 is running, but its unit file does not load `admin.env` — meaning either: (a) it does not currently use Postgres, (b) it loads a `.env` from working directory at runtime, or (c) it's wired some other way. **Not investigated further per scope.**

### E.2 Active fortress / inference services

```
fortress-brain.service           loaded active running   Fortress Prime Brain (Streamlit)  → 0.0.0.0:8501
fortress-nim-sovereign.service   loaded active running   NIM Llama-3.1-8B (DGX-Spark)       → container only
fortress-ray-worker.service      loaded active running   Ray worker
ollama.service                   loaded active running   Ollama (currently only nomic-embed-text resident)
```

**All four must remain running per Phase A1 brief Section 3.**

---

## F. Cron and timers

### F.1 User crontabs
- `crontab -l` (admin user): **no crontab**
- `sudo crontab -l` (root): **no crontab**

### F.2 /etc/cron.\*/
Only stock Ubuntu jobs (anacron, e2scrub_all, sysstat, apport, apt-compat, dpkg, logrotate, man-db, quota). **No fortress / postgres / backup cron.**

### F.3 systemd timers (notable)
```
anacron.timer             — every ~hour, ran 23 min ago
sysstat-collect.timer     — every 10 min, ran 23 sec ago
dpkg-db-backup.timer      — daily, next 00:00
logrotate.timer           — daily, next 00:00
fwupd-refresh.timer       — daily-ish
apt-daily.timer           — next 02:14
ua-timer.timer            — next 04:46
motd-news.timer           — next 05:50
apt-daily-upgrade.timer   — next 06:53
update-notifier-download.timer — next 10:07
systemd-tmpfiles-clean.timer   — next 10:17
e2scrub_all.timer         — Sunday weekly
fstrim.timer              — Monday weekly
```

**No fortress / postgres / backup timers.** Phase A1 brief's nightly backup timer (`spark1-pg-backup.timer`) is not configured.

---

## G. Existing Postgres config

### G.1 postgresql.conf (non-default values)

The file appears to have been edited beyond defaults — note the override section at the bottom:

```
# (defaults from PGDG/Ubuntu — abbreviated)
data_directory       = '/var/lib/postgresql/16/main'
hba_file             = '/etc/postgresql/16/main/pg_hba.conf'
port                 = 5432
max_connections      = 100      ← default
shared_buffers       = 128MB    ← default
ssl                  = on (snakeoil cert)
log_line_prefix      = '%m [%p] %q%u@%d '
log_timezone         = 'America/New_York'
timezone             = 'America/New_York'

# Custom overrides (later in file, last value wins):
shared_buffers           = 8GB
work_mem                 = 32MB
maintenance_work_mem     = 1GB
effective_cache_size     = 24GB
max_connections          = 200
wal_level                = replica
random_page_cost         = 1.1
shared_preload_libraries = 'pg_stat_statements'
listen_addresses         = 'localhost,192.168.0.104'
```

**Important:** The override block is tuned for a heavyweight workload (8 GB shared_buffers, 24 GB effective_cache_size, 200 max_connections, pg_stat_statements preloaded). **The Phase A1 brief's perf block (1 GB / 4 GB / 256 MB / 32 MB / 50 connections) would be a downgrade** if appended naively — and because `postgresql.conf` uses last-value-wins semantics, appending the brief's block would silently cap shared_buffers at 1 GB and cut max_connections in half.

### G.2 pg_hba.conf (effective rules only)

```
local   all             postgres                                peer
local   all             all                                     peer
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256
local   replication     all                                     peer
host    replication     all             127.0.0.1/32            scram-sha-256
host    replication     all             ::1/128                 scram-sha-256
host    fortress_prod   fortress_admin  192.168.0.100/32        scram-sha-256
```

**Only ONE non-default rule: `host fortress_prod fortress_admin 192.168.0.100/32`.**
- Spark-2's LAN IP (192.168.0.100), admin role, prod DB only.
- **No fortress_api access from anywhere except localhost.**
- **No spark-5 access.**
- **No Tailscale-IP access.**

### G.3 Config file timestamps
```
postgresql.conf   Apr 28 11:13   (edited after install — added override block)
pg_hba.conf       Apr 28 11:13   (edited — added the one fortress_prod rule)
```

Both edited 3 minutes before service start (11:16). So the bootstrap script wrote these too.

---

## H. Active TCP listeners (full)

| Local Address | Process | Notes |
|---|---|---|
| `127.0.0.1:5432` | postgres pid 1315161 | ✓ Postgres loopback |
| `192.168.0.104:5432` | postgres pid 1315161 | ✓ Postgres LAN |
| `127.0.0.1:6379` + `[::1]:6379` | redis-server pid 1291591 | Redis from same bootstrap |
| `0.0.0.0:8501` + `[::]:8501` | streamlit pid 1294025 | **fortress-brain (Streamlit) — publicly bound** |
| `0.0.0.0:22` | sshd | SSH |
| `0.0.0.0:8000` + `[::]:8000` | docker-proxy | container port |
| `*:11434` | ollama pid 1332187 | Ollama API (all interfaces) |
| `127.0.0.1:42493` | ollama pid 1398400 | Ollama runner (model serving) |
| `192.168.0.104:36973` | ray::RuntimeEnv | Ray |
| `127.0.0.1:52365`, `192.168.0.104:52365`, `[::ffff:192.168.0.104]:36457`, `0.0.0.0:39549` | ray::DashboardA | Ray dashboard agent |
| `*:38261`, `*:37693` | raylet | Ray |
| `100.127.241.36:49746` + `[fd7a:115c:a1e0::fd39:f124]:45856` | tailscaled | Tailscale |
| `127.0.0.1:20241` | cloudflared | Cloudflare tunnel |
| `127.0.0.1:11000` | dashboard-service | DGX dashboard |
| `127.0.0.1:631` + `[::1]:631` | cupsd | Print spooler (local) |
| `127.0.0.53%lo:53` + `127.0.0.54:53` | systemd-resolve | DNS |
| `*:5201` | iperf3 | iperf server (likely from earlier benchmarking) |
| `*:7946` | dockerd | Docker swarm gossip |

**Postgres NOT bound on Tailscale (`100.127.241.36`).** Streamlit Brain IS publicly bound on `0.0.0.0:8501` — worth noting from a network-sovereignty perspective even though out of Phase A1 scope.

---

## I. apt history — install timeline

All by user `admin (uid 1000)` on 2026-04-28:

```
Start-Date: 2026-04-28  08:02:32   (17 sec total)
Command:    apt-get install -y postgresql-16 postgresql-contrib-16 redis-server
            build-essential libpq-dev python3-venv python3-dev ocrmypdf
Installed:  postgresql-16 (16.13-0ubuntu0.24.04.1), postgresql-client-16,
            postgresql-common, redis-server (5:7.0.15-1ubuntu0.24.04.4),
            libpq-dev, libpq5, ocrmypdf (15.2.0+dfsg1-1), pikepdf, lxml,
            and ~30 transitive deps (PDF/OCR toolchain + Python deps)
Upgraded:   libssl3t64 + openssl
End-Date:   2026-04-28  08:02:49

Start-Date: 2026-04-28  10:52:25   (6 sec total)
Command:    apt-get install -y postgresql-16-postgis-3
Installed:  postgresql-16-postgis-3 (3.4.2+dfsg-1ubuntu3) + GDAL/GEOS/PROJ stack
End-Date:   2026-04-28  10:52:31

Start-Date: 2026-04-28  10:52:47   (instant)
Command:    apt-get install -y postgresql-16-pgvector
Installed:  postgresql-16-pgvector (0.6.0-1)
End-Date:   2026-04-28  10:52:47
```

**Interpretation:** This is a **CROG-AI / Fortress-Prime application bootstrap**, not a Phase A1 Postgres-only install. The 08:02 batch installed Postgres alongside Redis, the OCR toolchain, and Python build tools. The 10:52 batch added PostGIS + pgvector — extensions Fortress-Prime depends on but the Phase A1 brief does not require.

---

## J. Recent file activity

### J.1 /etc/fortress/
```
-rw------- 1 root root  83 Apr 19 13:04 /etc/fortress/nim.env
-rw------- 1 admin admin 250 Apr 28 10:39 /etc/fortress/admin.env
```
admin.env was created at 10:39, between the two install batches.

### J.2 /home/admin/ — recently modified files (last 7 days, top-level)

The application migration is **visible in the file tree:**
```
/home/admin/Fortress-Prime  →  /home/admin/Fortress-Prime.new  (symlink, created Apr 28 08:42)
/home/admin/Fortress-Prime.new/   (directory, mtime Apr 28 08:41)
  app.py
  CLAUDE.md
  CODEBASE_OVERVIEW.md
  PROJECT_MANIFEST.md
  Makefile
  Dockerfile.pulse-agent
  Dockerfile.refinery-agent
  docker-compose.local.yml
  document_miner.py
  email_miner_maildir.py
  miner_work.py
  titan_brain.py
  fortress_atlas.yaml
  packages.txt
  add_safety_valve.sql
  inspect_zillow.sql
  verify_cleanup.sql
  ingest_now.sh
  debug_body.py
  ...
```

Plus:
```
/home/admin/Fortress-Prime.legacy/   (older copy, last touched Mar 10)
/home/admin/flos-phase-a1-postgres-spark1-brief.md   (Apr 28 22:49 — tonight)
/home/admin/.bashrc                                   (Apr 28 08:26)
/home/admin/.bash_history                             (Apr 28 22:49)
/home/admin/hostfile                                  (Apr 25)
```

**This is unambiguously a live application migration.** `Fortress-Prime.new/` is the spark-2 application code copied over for spark-1 to run.

---

## K. Network state, sessions, uptime

### K.1 Tailscale tailnet (online nodes only)
```
100.127.241.36  spark-1                       linux   self
100.80.122.100  spark-2                       linux   ✓ online
100.96.13.99    spark-5                       linux   ✓ online
100.96.44.85    spark-3-1                     linux   ✓ online
100.125.35.42   spark-4                       linux   ✓ online
100.71.225.76   spark-6                       linux   ✓ online
100.112.199.24  fortress-linux                linux   ✓ online
100.66.180.7    fortresscrog-ai1s-mac-mini    macOS   ✓ online
100.113.162.72  garys-imac-2                  macOS   ✓ active (relay "mia")
100.100.118.91  garys-mac-mini-1              macOS   ✓ online
100.72.106.17   garyscyberpowe                windows ✓ online
100.77.89.127   iphone172                     iOS     ✓ online

Offline:  spark-3, ds1825-1, garys-mac-mini, garys-macbook-pro-1,
          garys-macbook-pro, rivers-edge-nuc
```

### K.2 Active sessions on spark-1
```
admin   seat0          2026-04-16 10:01   (login screen, console)
admin   :1             2026-04-16 10:01   (X session)
admin   pts/1          2026-04-16 11:17   (100.127.241.36 — spark-1 self)
admin   pts/2          2026-04-28 22:50   (100.113.162.72 — garys-imac-2, this session probably)
admin   pts/3          2026-04-23 19:11   (192.168.0.100 — spark-2 LAN, idle 5 days)
admin   pts/4          2026-04-28 22:50   (tmux 1420509.%0)
admin   pts/10         2026-04-25 13:36   (192.168.0.109 — unknown LAN host)
admin   pts/11         2026-04-25 13:36   (192.168.0.104 — spark-1 LAN self)
```

**6 active SSH/login sessions.** Operator has live work in tmux. **Worth flagging:** wipe-style operations (Path B) could disrupt sessions and any in-progress work.

### K.3 Login history (last 10)
Active session originated from `100.113.162.72` (garys-imac-2) at 22:50 EDT. Multiple recent connections from imac-2 and spark-1 LAN IPs throughout 2026-04-28. wtmp goes back to 2026-02-04.

### K.4 Uptime
```
23:30:37 up 12 days, 13:29,  6 users,  load average: 0.21, 0.35, 0.55
```

Spark-1 has been continuously up since 2026-04-16 ~10:00 EDT. The 08:02 install today happened in the middle of that uptime — service add, not boot.

---

## Synthesis for morning session

### What spark-1 is currently running

Spark-1 is the **inference plane** (NIM Llama-3.1-8B in Docker, Ray worker, Ollama, fortress-brain Streamlit on 8501) that is **also being prepared as a data plane host**. At 08:02 today an `admin`-user bootstrap script installed Postgres 16.13 (Ubuntu repo), Redis, the OCR toolchain, and Python build deps; then provisioned three databases (`fortress_db`, `fortress_prod`, `fortress_shadow_test`) with the full Fortress-Prime schema (13 schemas, 291 tables) and the canonical `fortress_admin`/`fortress_api` role pair, with credentials in `/etc/fortress/admin.env`. PostGIS + pgvector were added at 10:52. The Postgres tuning in `postgresql.conf` is heavyweight (8 GB shared_buffers, 24 GB effective_cache_size, 200 max_connections, pg_stat_statements). Spark-2's application code has been copied to `/home/admin/Fortress-Prime.new/` and symlinked. **Nothing is yet wired to the new Postgres** — no systemd unit references `admin.env`, no client connections exist, and `pg_hba.conf` still allows only `fortress_admin` from spark-2's LAN IP into `fortress_prod`. The Phase A1 brief (drafted assuming clean-host install) was last edited at 22:49 tonight; given the divergence between brief and reality, the operator paused before picking A/B/C and asked for state capture.

### Three things to flag for the morning operator review

1. **The Phase A1 brief is shape-wrong, not just degree-wrong.** It assumes "Postgres-only install on a clean host." Reality is "application migration with Postgres already provisioned by a broader bootstrap (Postgres + Redis + OCR + PostGIS + pgvector + app code), now waiting to be cut over." The right Phase A1 isn't "install" — it's **harden/configure what's there** (Tailscale binding, full pg_hba, Phase 0a-8 grants, firewall, backup, doc) AND/OR **decide what 'Phase A1' even means in a migration context**. The brief's perf block, if appended, would silently downgrade the existing 8 GB tuning to 1 GB. The brief's secrets path (`spark-1-postgres.env` root-owned) conflicts with the existing `admin.env` (admin-owned) — picking one means rewriting whatever consumes the other.

2. **Two divergent alembic heads (`q2b3c4d5e6f7`, `r3c4d5e6f7g8`) are baked into all three DBs.** This is the Issue #204 trap. Whatever schema dump was used had a multi-head state; any future `alembic upgrade head` from spark-2's Fortress-Prime code will fail or branch. Resolving this requires either re-dumping cleanly from spark-2, or running `alembic merge` on spark-2 first and then re-syncing. It is **not** a "leave for later" item — every migration applied to spark-1 from now on inherits this divergence. The morning brief author should decide whether to fix at the source (spark-2) or accept the divergence and document it.

3. **`fortress_app` role is referenced by `admin.env` but does not exist in the database, and the Streamlit Brain is publicly bound on 0.0.0.0:8501.** The `POSTGRES_FORTRESS_APP_PASSWORD` key in `admin.env` has no corresponding pg_role — either it's stale from an older contract draft, or the bootstrap script intends to create it later, or someone has a different role-naming plan than the canonical 004 contract. Worth resolving before any consumer service is wired up. Separately, `fortress-brain.service` is bound on `0.0.0.0:8501` with no apparent firewall — even though it's out of Phase A1 scope, it's a sovereignty item that may want to land on the same morning's review.

### Decision options surfaced (NOT picked tonight)

The morning session's likely framings, in rough order of operator words from this session:

- **"Phase A1 brief is wrong shape — write a new migration-context brief."** Treat the existing install as the migration baseline. Phase A1 becomes "harden and connect": Tailscale listen, full pg_hba (spark-2 fortress_admin + fortress_api, spark-5 fortress_api read-only), Phase 0a-8 grants, root-owned secrets file (consolidate or migrate from admin.env), iptables, backup, doc. **Does NOT** install or wipe.
- **"Phase A1 brief is right, but additive-not-destructive."** Apply only the parts that don't touch existing state. Skip install, skip role/DB creation. Add Tailscale to listen_addresses (without disturbing the 8 GB perf block), append fortress_api + spark-5 entries to pg_hba, apply Phase 0a-8 grants, configure firewall + backup + doc. Leave admin.env in place.
- **"Application migration is its own phase; Fortress Legal config layered on top."** Treat the spark-2 → spark-1 application migration as a separate (already-in-flight) project. Phase A1's job is just "the Fortress Legal data-plane config that needs to apply once the migration completes." Brief gets re-scoped to the legal-specific overlays (pg_hba spark-5 read-only access for Phase A5 RAG, legal-table grant verification, legal smoke tests, backup of legal data once it lands).
- **"Wipe and redo per original brief"** is technically possible (no active connections, zero data, no consumers) but would also discard the 8 GB perf tuning, the postgis/pgvector extensions, the schema dump, and the bootstrap context — and might surprise whoever ran the 08:02 bootstrap if its purpose extends beyond Phase A1.

### What was NOT done tonight

- No DB / role / config / pg_hba / postgresql.conf change.
- No service start/stop/restart.
- No file in `/etc/fortress/` modified.
- No iptables change.
- No package install or removal.
- Existing tool-results capture file (raw psql output) is preserved at `/home/admin/.claude/projects/-home-admin/2ce642cf-93e1-4238-93ee-92149b4275fe/tool-results/byfpwn9cf.txt` for forensic reference.

---

**End of state capture.** Next session opens this file and decides forward path. No tool action past this point.
