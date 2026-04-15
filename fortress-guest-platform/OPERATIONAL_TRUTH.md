# OPERATIONAL_TRUTH.md

> **Read this first.** Source of truth for the verified state of the Fortress Prime production
> deployment as of 2026-04-15. Where reality conflicts with other docs, scripts, or configs in
> the repo, **this doc wins**. Every claim has a verification command — re-run any of them
> before trusting.
>
> **When you discover something new that's true and not here, add it (with verification command).
> When you fix a known operational gap, remove the gap and update the relevant section.**

---

## Why this doc exists: 2026-04-15 hour of pain

~60 minutes of G.2.1 deployment debugging traced to:

1. `crog-ai.com` was served by an orphaned next-server on **port 3005** (SSH session, NOT systemd) — now fixed by `crog-ai-frontend.service` (G.2.3)  
2. `infra/gateway/config.yml` in the repo claimed port 3001 — it is now a documented copy of `/etc/cloudflared/config.yml` (G.2.4)  
3. `fortress-dashboard.service` was misnamed; ran the **storefront** on port 3001 with wrong FGP_BACKEND_URL (8100) — **deleted in G.2.5**; its misconfiguration won't bite future sessions  
4. BFF proxy log strings hardcode `"FGP:8100"` even though FastAPI actually runs on **8000**  
5. After any backend code change, `sudo systemctl restart fortress-backend` is **mandatory** — no autoreload  
6. Two next-server proxy route files (`/api/[...path]` catch-all and `/api/vrs/[...path]`) can compete for the same path when a named sibling directory exists under `/api/admin/`

---

## Production deployment topology

### Cloudflare tunnel (actual running config)

**Authoritative file:** `/etc/cloudflared/config.yml` (live, read via sudo)  
**Repo documentation copy:** `infra/gateway/config.yml` (reconciled in G.2.4 — see note below)

```bash
# Verify:
sudo grep -A2 "crog-ai.com\|cabin-rentals\|grafana" /etc/cloudflared/config.yml

# Verify repo copy matches production:
sudo diff /etc/cloudflared/config.yml \
          <(grep -v '^#' infra/gateway/config.yml | sed '/^[[:space:]]*$/d')
# Expected: one blank-line difference only (whitespace, not content)
```

| Hostname | Routes to | Notes |
|---|---|---|
| `crog-ai.com` | `http://127.0.0.1:3005` | Next.js command center (`crog-ai-frontend.service`) |
| `www.crog-ai.com` | `http://127.0.0.1:3005` | Same |
| `console.crog-ai.com` | `http://127.0.0.1:3005` | Same |
| `fortress.crog-ai.com` | `http://127.0.0.1:9800` | Python master_console (fortress-console.service) |
| `api.crog-ai.com` | `http://127.0.0.1:9800` | Same |
| `cabin-rentals-of-georgia.com` | `http://127.0.0.1:8100` | **DEAD TUNNEL ENTRY** — nothing on 8100; domain serves via Cloudflare CDN from a different origin. Tunnel entry is stale. |
| `www.cabin-rentals-of-georgia.com` | `http://127.0.0.1:8100` | Same dead entry |
| `api.cabin-rentals-of-georgia.com` | `http://127.0.0.1:8000` | FastAPI directly |
| `staging.cabin-rentals-of-georgia.com` | `http://127.0.0.1:8000` | FastAPI directly (dev/staging) |
| `grafana.crog-ai.com` | `http://127.0.0.1:3000` | Grafana |
| `ssh.crog-ai.com` | `ssh://localhost:22` | SSH tunnel |

**`infra/gateway/config.yml` note (G.2.4):** The in-repo file was rewritten on 2026-04-15 to mirror `/etc/cloudflared/config.yml`. It is a documentation copy only — cloudflared does not read it. Drift between the two is expected as the production config changes; use the diff command above to check.

---

### Port map (verified live 2026-04-15)

```bash
# Verify:
sudo ss -tlnp | grep -E ":3001|:3005|:8000|:8100|:9800"
```

| Port | Process | Service | App |
|---|---|---|---|
| 3001 | **NOTHING** (G.2.5) | fortress-dashboard.service **DELETED** | Was storefront — misleading, removed |
| 3005 | `next-server (v16.1.6)` | `crog-ai-frontend.service` (systemd ✓, G.2.3) | **apps/command-center** |
| 3299/3399/3499 | `next-server (v14.2.35)` × 3 | **Orphaned SSH session** (session-2592.scope) ⚠️ | `/home/admin/cabin-rentals-of-georgia` — **do NOT kill** |
| 8000 | `python` (uvicorn) | `fortress-backend.service` (systemd ✓) | FastAPI backend |
| 8100 | **NOTHING** | — | Dead port in tunnel config |
| 9800 | `python3` | `fortress-console.service` (systemd ✓) | master_console.py (internal tool) |

---

### crog-ai.com — command center (port 3005)

**Process management: `crog-ai-frontend.service` (systemd, `Restart=always`).** Created in G.2.3 (2026-04-15). Cutover from orphaned SSH session to systemd performed by Gary after G.2.3 commit. Unit file: `/etc/systemd/system/crog-ai-frontend.service`. Repo copy: `deploy/systemd/crog-ai-frontend.service`.

```bash
# Verify port and service:
sudo ss -tlnp | grep :3005
sudo systemctl status crog-ai-frontend.service | head -10

# Verify CWD:
PID=$(sudo ss -tlnp | grep ":3005 " | grep -oE 'pid=[0-9]+' | cut -d= -f2)
sudo readlink /proc/$PID/cwd
# → /home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center
```

**Restart sequence (after code change):**
```bash
# 1. Build new artifact
cd /home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center
npm run build

# 2. Restart via systemd
sudo systemctl restart crog-ai-frontend.service
sleep 8
sudo systemctl status crog-ai-frontend.service | head -5
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3005/api/admin/payouts/statements
# Expected: 403 (proxy live, backend auth required)
```

---

### ~~fortress-dashboard.service~~ (DELETED — Phase G.2.5)

This service was stopped, disabled, and its unit file and launch script permanently deleted in G.2.5 (2026-04-15). Its misconfiguration won't bite future sessions.

**What it was:** Ran `apps/storefront` (Next.js v16) on port 3001 via `run-fortress-dashboard.sh`. The name "Dashboard" implied it served the admin command center (it didn't). Its `FGP_BACKEND_URL` defaulted to port 8100 (nothing there). No Cloudflare tunnel routed to port 3001. Served no production domain.

**Port 3001 is now free.** If something tries to connect to port 3001, it will be refused.

**Note:** `backend/api/system_health.py` still checks port 3001 as "Command Center" — this will report it as down. Update that file to check port 3005 + `crog-ai-frontend.service` in a future pass.

**Also deleted:**
- `/etc/systemd/system/fortress-dashboard.service`
- `/etc/systemd/system/fortress-frontend.service.d/env.conf` (orphan override dir — contained `FGP_BACKEND_URL=http://127.0.0.1:8100`)
- `/usr/local/bin/run-fortress-dashboard.sh`

---

### cabin-rentals-of-georgia.com — separate project (ports 3299/3399/3499)

**⚠️ DO NOT KILL** these processes. They serve a separate project and are not fortress orphans.

```bash
# Identify these processes (they run from /home/admin/cabin-rentals-of-georgia):
ps aux | grep "next-server" | grep -v grep
# Re-verify CWDs:
for p in $(ps aux | grep "next-server v14" | grep -v grep | awk '{print $2}'); do
  echo "PID $p: $(sudo readlink /proc/$p/cwd 2>/dev/null)"
done
# Expected CWD: /home/admin/cabin-rentals-of-georgia (NOT fortress-guest-platform)
```

**Verified 2026-04-15 (G.2.3/G.2.4):**
- PIDs 1356961, 1703735, 1918044 (rotate over time)
- Next.js **v14.2.35** (the fortress apps use v16.1.6 — version difference is one identification signal)
- CWD: `/home/admin/cabin-rentals-of-georgia` (separate repo)
- Ports: 3299, 3399, 3499 (not tunnel-routed — these are local dev/staging, not production)
- **Process management: None — orphaned SSH session (session-2592.scope)**
- Tunnel routes: `cabin-rentals-of-georgia.com` → 8100 (dead/stale tunnel entry, unrelated to these ports)

**How to identify them after process churn:** Any `next-server v14.x` process whose CWD is `/home/admin/cabin-rentals-of-georgia`. Never kill a process without confirming its CWD is not the cabin-rentals-of-georgia directory.

---

### fortress-console.service (port 9800 — Python tool)

```bash
# Verify:
sudo systemctl cat fortress-console.service | grep -E "Description|ExecStart"
# Description=Fortress Command Center (crog-ai.com — port 9800)   ← misleading name
# ExecStart=/usr/local/bin/run-fortress-console.sh
```

Despite the description saying "Fortress Command Center (crog-ai.com)", this service runs `master_console.py` — an internal Python operations tool. The Next.js command center serving crog-ai.com is the orphaned process on port 3005. These are two completely separate things.

---

## Backend (FastAPI)

### Service facts

```bash
# Port:
sudo ss -tlnp | grep :8000
# → python pid=XXXXX

# Service:
sudo systemctl status fortress-backend | head -5

# Restart after ANY code change:
sudo systemctl restart fortress-backend
sudo systemctl status fortress-backend | head -5
```

- **Port: 8000** (NOT 8100 — 8100 has nothing listening)
- **Service:** `fortress-backend.service` (systemd-managed, `Restart=always`)
- **No autoreload.** `run.py` (via uvicorn) does NOT hot-reload on code change.
- **Mandatory after any `.py` change:** `sudo systemctl restart fortress-backend`

### BFF URL routing (catch-all `/api/[...path]/route.ts`)

The catch-all BFF routes requests to **two** different backends:

```bash
# Verify:
grep -n "COMMAND_CENTER\|getBackendBaseUrl\|isCC\|9800\|8000" \
  apps/command-center/src/app/api/\[...path\]/route.ts | head -10
```

| Path type | Routes to | Port |
|---|---|---|
| "CC paths" (COMMAND_CENTER_PREFIXES) | `COMMAND_CENTER_URL` env or `127.0.0.1:9800` | 9800 (Python tool) |
| Everything else | `FGP_BACKEND_URL` env or `127.0.0.1:8000` | **8000** (FastAPI) |

**⚠️ Misleading log strings:** All BFF proxy files print `"FGP:8100"` in their console logs:
```bash
grep -rn "FGP:8100" apps/command-center/src/app/api/ | grep -v node_modules
```
These strings are hardcoded and wrong. The actual URL used is port 8000. Do not trust the port number in BFF console output.

---

## Databases

### Which DB the FastAPI runtime uses

```bash
# Verify:
grep "^POSTGRES_API_URI" .env
# → postgresql+asyncpg://fortress_api:fortress@127.0.0.1:5432/fortress_shadow

grep "ALLOWED_POSTGRES_DATABASES" backend/core/config.py
# → frozenset({"fortress_prod", "fortress_shadow", "fortress_db", "fortress_shadow_test"})
```

**FastAPI runtime DB: `fortress_shadow`** (via `POSTGRES_API_URI` → `settings.database_url`)

`fortress_guest` is rejected by the settings validator even though `.env` has `DATABASE_URL` pointing at it. The `DATABASE_URL` env var is a legacy artefact and is silently ignored by the application.

### DB summary

| Database | User | Role | Alembic head | Contents |
|---|---|---|---|---|
| `fortress_shadow` | `fortress_api` | **Production runtime** | `e6a1b2c3d4f5` | All operational data; 0 rows in statement tables (cleaned G.1.6) |
| `fortress_shadow_test` | `fortress_api` | **Test isolation** | `e6a1b2c3d4f5` | Schema clone; test fixture data from G.1.7 (185 OPA, 439 OBP, 39 OC) |
| `fortress_guest` | `fgp_app` | Legacy/secondary | `c4a8f1e2b9d0` | 2,665 historical reservations; NOT written by FastAPI runtime |

```bash
# Verify fortress_shadow_test exists:
psql "postgresql://fortress_admin:fortress@127.0.0.1:5432/fortress_shadow_test" \
  -c "SELECT current_database();"
```

### .env file location

```bash
# Verify:
ls -la .env backend/.env 2>&1
# .env → /home/admin/Fortress-Prime/fortress-guest-platform/.env (EXISTS, 7.3KB)
# backend/.env → DOES NOT EXIST
```

**`.env` is at `fortress-guest-platform/.env`**, NOT at `backend/.env`. Some scripts and phase reports incorrectly reference `backend/.env`.

### Git root

```bash
git -C ~/Fortress-Prime rev-parse --show-toplevel
# → /home/admin/Fortress-Prime
```

The git repository root is `/home/admin/Fortress-Prime`, one level **above** `fortress-guest-platform/`. All `git add` paths in scripts must use `fortress-guest-platform/...` relative to the repo root.

---

## Tests

### Test DB isolation

```bash
# Verify db_helpers.py exists (G.1.7):
ls backend/tests/db_helpers.py

# Verify TEST_DATABASE_URL is in .env:
grep TEST_DATABASE_URL .env
```

- Test files use `from backend.tests.db_helpers import get_test_dsn` for direct DB connections
- `conftest.py` (`pytest_configure`) monkey-patches `backend.core.database.AsyncSessionLocal` when `TEST_DATABASE_URL` is set, redirecting all DI-based route handlers to `fortress_shadow_test`
- **Fragile:** Services that cache `AsyncSessionLocal` before `pytest_configure` runs will still use `fortress_shadow`. Known limitation from G.1.8.
- `fortress_shadow` target tables stayed at 0 rows during the G.1.8 verification run ✓

```bash
# Before running any test suite, confirm TEST_DATABASE_URL is set:
echo "TEST_DATABASE_URL=${TEST_DATABASE_URL:-NOT SET}"
# If NOT SET, export it:
export TEST_DATABASE_URL=postgresql://fortress_api:fortress@127.0.0.1:5432/fortress_shadow_test
```

---

## Frontend / BFF proxy routing

### Active proxy route files

```bash
# Verify:
ls apps/command-center/src/app/api/admin/
# → payouts/  prime/

ls apps/command-center/src/app/api/
# → admin/  auth/  intelligence/  legal/  login/  [...path]/  system/  system-health/  telemetry/  vrs/
```

### Route precedence rule

When a named subdirectory exists under `/api/admin/` (e.g., `prime/`), Next.js App Router no longer falls through to the catch-all `[...path]` for other paths under `/api/admin/`. Each distinct path prefix under a named subdirectory **requires its own explicit proxy route** unless the catch-all itself is at `/api/admin/[...path]/`.

| Path | Proxy file that handles it |
|---|---|
| `/api/admin/payouts/*` | `src/app/api/admin/payouts/[...path]/route.ts` (G.2.1) |
| `/api/admin/prime/*` | `src/app/api/admin/prime/stream/route.ts` (specific SSE) |
| `/api/vrs/*` | `src/app/api/vrs/[...path]/route.ts` |
| Everything else | `src/app/api/[...path]/route.ts` catch-all |

**If you add a new `/api/admin/X/*` backend path and see HTML responses:** create `src/app/api/admin/X/[...path]/route.ts` by copying the payouts proxy and changing the path string.

### Current branch

```bash
git -C ~/Fortress-Prime branch --show-current
# → feature/owner-statements-and-stabilization
```

---

## Process hygiene (accumulating stale processes)

```bash
# Check for stale next-server processes:
ps aux | grep next-server | grep -v grep
```

As of 2026-04-15, **6 next-server processes** are running (updated in G.2.3/G.2.4):

| PID | Age | Version | Port | Owner | Action |
|---|---|---|---|---|---|
| 1135123 | Apr 11 | v16.1.6 | None | fortress (apps/command-center) | Kill — zombie, serves nothing |
| 1356961 | Apr 13 | v14.2.35 | 3299 | cabin-rentals-of-georgia project | **Do NOT kill** |
| 1703735 | Apr 13 | v14.2.35 | 3399 | cabin-rentals-of-georgia project | **Do NOT kill** |
| 1918044 | Apr 13 | v14.2.35 | 3499 | cabin-rentals-of-georgia project | **Do NOT kill** |
| 2198017 | Today | v16.1.6 | 3001 | ~~fortress-dashboard.service~~ (DELETED G.2.5) | Gone — port 3001 now free |
| 2768669 | Today | v16.1.6 | 3005 | crog-ai-frontend.service (systemd, G.2.3) | Leave |

PIDs rotate over time. To identify safe-to-kill processes:
```bash
# Find fortress next-servers not bound to a tracked port:
for PID in $(ps aux | grep "next-server v16" | grep -v grep | awk '{print $2}'); do
  PORT=$(sudo ss -tlnp 2>/dev/null | grep "pid=$PID")
  if [ -z "$PORT" ]; then
    CWD=$(sudo readlink /proc/$PID/cwd 2>/dev/null)
    echo "STALE: PID $PID, CWD=$CWD — safe to kill IF CWD is fortress"
  fi
done
# Never kill a process whose CWD is /home/admin/cabin-rentals-of-georgia
```

---

## Known operational gaps

| Gap | Severity | Recommended Phase |
|---|---|---|
| **`backend/api/system_health.py` checks port 3001 as "Command Center"** — will show as down after G.2.5 deletion; should be updated to check port 3005 + `crog-ai-frontend.service` | LOW | G.2.6 |
| **`backend/api/contracts.py` and `agreements.py` default `VRS_URL` to 192.168.0.100:3001** — stale defaults; check if overridden by env var in production | LOW | verify in .env |
| **Storefront (cabin-rentals-of-georgia) orphans on 3299/3399/3499** — Next.js v14.2.35 from `/home/admin/cabin-rentals-of-georgia`, orphaned SSH session, not tunnel-reachable | LOW | G.2.6 candidate: kill after confirming no consumer |
| **cabin-rentals-of-georgia.com tunnel routes to dead port 8100** | LOW | Stale tunnel entry; domain served from other origin. Leave as-is until known safe to change. |
| **BFF proxy log strings hardcode "FGP:8100"** (actual port is 8000) | LOW | Fix when touching proxy files |
| **G.1.8 monkey-patch is fragile** — services with pre-cached AsyncSessionLocal bypass test isolation | MEDIUM | G.2.6 |
| **cabin-rentals-of-georgia next-servers on 3299/3399/3499 are orphaned** (no systemd) | LOW | Not fortress scope — separate project decision |
| **crog-ai-frontend.service binds to 0.0.0.0:3005 instead of 127.0.0.1** (unit has HOSTNAME=127.0.0.1 but Next.js ignores it when HOSTNAME env is set via UnsetEnvironment first) | LOW | Functional via Cloudflare tunnel; fix HOSTNAME binding in a future pass |
| **Bucket C: ~90 untracked/modified files on fix/storefront-quote-light-mode** | MEDIUM | Separate reconciliation phase |
| **fortress_shadow has 0 real OPAs** — G.2 UI shows empty state until G.3 owner enrollment | BLOCKER for G.3 | G.3 |

---

## Startup / restart procedures

### After any FastAPI (`backend/`) code change
```bash
sudo systemctl restart fortress-backend
sudo systemctl status fortress-backend | head -5
# Wait for "Active: active (running)"
```

### After any command-center (`apps/command-center/`) code change
```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center
npm run build
sudo systemctl restart crog-ai-frontend.service
sleep 8
sudo systemctl status crog-ai-frontend.service | head -5
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3005/api/admin/payouts/statements
# Expected: 403
```

### After any storefront (`apps/storefront/`) code change

**fortress-dashboard.service was deleted in G.2.5.** The storefront's production target is Vercel, not this box. If a local storefront dev server is needed, start manually:
```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform/apps/storefront
FGP_BACKEND_URL=http://127.0.0.1:8000 \
  nohup node .next/standalone/apps/storefront/server.js \
  --port <PORT> --hostname 127.0.0.1 > /tmp/storefront.log 2>&1 &
```

---

## Known operational facts

### fortress_shadow reservation test fixtures (cleaned G.3.5)

fortress_shadow.reservations contained **43 test fixtures** with prefixes `E5-`, `E6-`, `B6OWN-`, `B6REG-`, `E2E-` and far-future `check_in_dates` (2056–2099 range). These were Hermes parity test data that caused false discrepancies on the parity dashboard, resetting the "100 consecutive $0.00 deltas" gate. Also cleaned: 7 orphan rows in `parity_audits` and 7 in `financial_approvals` referencing those fixtures.

**Cleaned in G.3.5 on 2026-04-15.** Cleanup scripts: `backend/scripts/g35_cleanup_commit.sql` (Gary runs once).

**Rule going forward:** Future test data MUST NOT be inserted directly into fortress_shadow. Use fortress_shadow_test (G.1.7) for all test fixtures.

```bash
# Verify clean post-execution:
psql "$PSQL" -c "
  SELECT COUNT(*) AS far_future_test_fixtures FROM reservations
  WHERE check_in_date >= '2027-01-01';
  -- Expected: 0"
```

### Property UUID divergence between fortress_guest and fortress_shadow

The property UUIDs for Gary Knight's properties differ between the two databases. This is critical for any future cross-DB operations.

| Property | fortress_guest UUID | fortress_shadow UUID |
|---|---|---|
| Fallen Timber Lodge | `1781fd69-a7e3-4df6-9216-c6152c9c19b6` | `93b2253d-7ae4-4d6f-8be2-125d33799c88` |
| Cherokee Sunrise on Noontootla Creek | `099f273a-6d2b-4eeb-9474-80fd89c18071` | `50a9066d-fc2e-44c4-a716-25adb8fbad3e` |
| Serendipity on Noontootla Creek | `bdef1b0d-8c7c-4126-a9d9-249b3d6b2621` | `63bf8847-9990-4a36-9943-b6c160ce1ec4` |

Any future fortress_guest → fortress_shadow backfill must apply this mapping via a CASE expression on `property_id`. See `backend/scripts/g4_backfill_commit.sql` for the pattern.

The `g4_backfill_commit.sql` script also handles: `phone_number` → `phone` column rename in guests, TIMESTAMP → TIMESTAMPTZ cast, and denormalized `guest_email`/`guest_name` columns populated via JOIN.

### G.4 reservation backfill (staged, not yet executed)

Backfill of Gary Knight's (sl_owner_id 146514) Q1 2026 reservations from fortress_guest → fortress_shadow scripted in G.4 (2026-04-15). Dry-run verified: 16 reservations + 16 linked guests, 0 conflicts. Gary runs `psql "$PSQL" -f backend/scripts/g4_backfill_commit.sql` to execute.

Post-backfill: fortress_shadow.reservations → 73 rows (57 real + 16 backfilled). Gary then re-runs March 2026 statement generation in `/admin/statements` UI to get non-zero totals for manual comparison with Streamline.

For future larger backfills (all 14 active properties, longer history): repeat the pattern from `g4_backfill_commit.sql` with expanded property UUID mappings and date range.

---

## Statement classification policy

**Streamline is the source of truth for what's commissionable vs pass-through.** CROG's job is parity, not opinion. When CROG and Streamline disagree on classification, Streamline wins. `_COMMISSIONABLE_PATTERNS` in `backend/services/statement_computation.py` reflects observed Streamline behavior and must be updated to match whenever a parity discrepancy is found.

**Verification command:**
```bash
grep -A 10 "_COMMISSIONABLE_PATTERNS" \
  backend/services/statement_computation.py
```

### Currently commissionable (verified against Streamline 2026-04-15)
- **Base rent** — from `nightly_rate` column (stores TOTAL booking rent, not per-night rate; G.5 Fix 1)
- **Additional person fees** — `required_fees` entries whose name contains "additional person"
- **Additional party fees** — `required_fees` entries whose name contains "additional party"
- **Extra guest fees** — `required_fees` entries whose name contains "extra guest"
- **Extra person fees** — `required_fees` entries whose name contains "extra person"

### Currently pass-through (excluded from commission base)
- Cleaning fees, ADW (accidental damage waiver), processing fees
- Lodging tax, DOT tax, state/county taxes
- **Pet fees** (removed from commissionable in G.5.1 — Streamline treats them as pass-through at Fallen Timber Lodge; removal confirmed March 2026 parity)
- Pet cleaning fees
- Security deposits
- Anything not matching the commissionable list above (safe default)

### History
- G.5 (2026-04-15): Fixed `nightly_rate × nights` multiplication bug; added required_fees parsing
- G.5.1 (2026-04-15): Removed "pet" from commissionable after Streamline parity check showed Pet Fee is pass-through. Confirmed exact parity: CROG = Streamline = $6,209 for Gary Knight's March 2026 Fallen Timber Lodge statement.

---

## How to use this doc

- **Every Claude Code session reads this as Task 0** before any infrastructure-touching work.
- Verify each claim against the live system before acting on it.
- When you discover a new truth, **ADD it** with a verification command.
- When you fix a known gap, **DELETE** the gap entry and update the relevant section.
- When a previously-stated truth has changed, **UPDATE** the section and add a dated note.
