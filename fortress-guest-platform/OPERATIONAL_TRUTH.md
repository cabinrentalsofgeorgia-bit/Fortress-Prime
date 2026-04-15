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

1. `crog-ai.com` is served by an orphaned next-server on **port 3005** (SSH session, NOT systemd)  
2. `infra/gateway/config.yml` in the repo claims port 3001 — that is the *intended* config, not the running one  
3. `fortress-dashboard.service` is misnamed; it runs the **storefront** (apps/storefront) on port 3001, not the command center  
4. BFF proxy log strings hardcode `"FGP:8100"` even though FastAPI actually runs on **8000**  
5. After any backend code change, `sudo systemctl restart fortress-backend` is **mandatory** — no autoreload  
6. Two next-server proxy route files (`/api/[...path]` catch-all and `/api/vrs/[...path]`) can compete for the same path when a named sibling directory exists under `/api/admin/`

---

## Production deployment topology

### Cloudflare tunnel (actual running config)

**File:** `/etc/cloudflared/config.yml` (read-only via sudo; this is the live config, NOT `infra/gateway/config.yml`)

```
Verify: sudo grep -A2 "crog-ai.com\|cabin-rentals\|grafana" /etc/cloudflared/config.yml
```

| Hostname | Routes to | Notes |
|---|---|---|
| `crog-ai.com` | `http://127.0.0.1:3005` | Next.js command center (orphaned process) |
| `www.crog-ai.com` | `http://127.0.0.1:3005` | Same |
| `console.crog-ai.com` | `http://127.0.0.1:3005` | Same |
| `fortress.crog-ai.com` | `http://127.0.0.1:9800` | Python master_console (fortress-console.service) |
| `api.crog-ai.com` | `http://127.0.0.1:9800` | Same |
| `cabin-rentals-of-georgia.com` | `http://127.0.0.1:8100` | **DEAD ENTRY** — nothing runs on 8100; domain is served by Cloudflare CDN from a separate origin (legacy Drupal) |
| `staging.cabin-rentals-of-georgia.com` | `http://127.0.0.1:8000` | FastAPI directly (dev/staging) |
| `grafana.crog-ai.com` | `http://127.0.0.1:3000` | Grafana |
| `ssh.crog-ai.com` | `ssh://localhost:22` | SSH tunnel |

**⚠️ STALE DOC WARNING:** `infra/gateway/config.yml` (repo file) claims `crog-ai.com → port 3001`. This is the intended future state, NOT the live state. The live config is `/etc/cloudflared/config.yml`.

---

### Port map (verified live 2026-04-15)

```bash
# Verify:
sudo ss -tlnp | grep -E ":3001|:3005|:8000|:8100|:9800"
```

| Port | Process | Service | App |
|---|---|---|---|
| 3001 | `next-server (v16.1.6)` pid 2198017 | `fortress-dashboard.service` (systemd ✓) | **apps/storefront** |
| 3005 | `next-server (v16.1.6)` pid 2323282 | **None — orphaned SSH session** ⚠️ | **apps/command-center** |
| 8000 | `python` (uvicorn) | `fortress-backend.service` (systemd ✓) | FastAPI backend |
| 8100 | **NOTHING** | — | Dead port referenced in many stale configs |
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

### fortress-dashboard.service (port 3001 — storefront)

```bash
# Verify:
sudo systemctl cat fortress-dashboard.service | grep -E "Description|WorkingDirectory|ExecStart"
# Description=Fortress Guest Platform Dashboard
# WorkingDirectory=.../apps/storefront
```

Despite the name "Dashboard", this service runs the **public storefront** (`apps/storefront`) on port 3001, NOT the admin command center. The `run-fortress-dashboard.sh` script has `APP_DIR="${ROOT_DIR}/fortress-guest-platform/apps/storefront"`.

**⚠️ FGP_BACKEND_URL default bug:** `run-fortress-dashboard.sh` defaults `FGP_BACKEND_URL` to `http://127.0.0.1:8100` — which has nothing listening. If this script's env is ever used by the storefront BFF, it will fail. The correct default is port 8000.

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

As of 2026-04-15, **6 next-server processes** are running:
- 1 from Apr 11 (v16.1.6, not listening on any port — zombie)
- 3 from Apr 13 (v14.2.35 — old major version, not listening)
- 1 started 11:45 today by systemd (fortress-dashboard → storefront, port 3001)
- 1 started 12:05 today by SSH session (command-center, port 3005)

**Periodic cleanup needed.** Kill any process not bound to a tracked port:
```bash
# Find PIDs listening on ports you care about:
sudo ss -tlnp | grep -E ":3001|:3005" | grep -oE 'pid=[0-9]+' | cut -d= -f2

# Kill everything else (check each PID before killing):
ps aux | grep next-server | grep -v grep | awk '{print $2}'
```

---

## Known operational gaps

| Gap | Severity | Recommended Phase |
|---|---|---|
| **infra/gateway/config.yml is stale** — claims port 3001, live is 3005 | MEDIUM | G.2.4: update or delete |
| **run-fortress-dashboard.sh has wrong FGP_BACKEND_URL default (8100 → should be 8000)** | MEDIUM | G.2.5 |
| **cabin-rentals-of-georgia.com Cloudflare tunnel entry routes to dead port 8100** | LOW (not serving from this box anyway) | G.2.4 |
| **BFF proxy log strings hardcode "FGP:8100"** (actual port is 8000) | LOW | Fix when touching proxy files |
| **G.1.8 monkey-patch is fragile** — services with pre-cached AsyncSessionLocal bypass test isolation | MEDIUM | G.2.6 |
| **~5 stale next-server processes accumulating** | LOW | Manual cleanup |
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
```bash
sudo systemctl restart fortress-dashboard
sudo systemctl status fortress-dashboard | head -5
```

---

## How to use this doc

- **Every Claude Code session reads this as Task 0** before any infrastructure-touching work.
- Verify each claim against the live system before acting on it.
- When you discover a new truth, **ADD it** with a verification command.
- When you fix a known gap, **DELETE** the gap entry and update the relevant section.
- When a previously-stated truth has changed, **UPDATE** the section and add a dated note.
