# Phase G.2.2 Report — OPERATIONAL_TRUTH.md
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization`

---

## 1. Verifications Run

All 21 claims verified against the live system. Full output captured per claim:

| # | Claim | Command | Actual result | Matches claim? |
|---|---|---|---|---|
| 1 | crog-ai.com → 127.0.0.1:3005 | `sudo grep -A2 "crog-ai.com" /etc/cloudflared/config.yml` | `service: http://127.0.0.1:3005` | ✓ YES |
| 2 | Port 3005 CWD = apps/command-center | `sudo readlink /proc/$PID/cwd` | `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center` | ✓ YES |
| 3 | Port 3005 is orphaned SSH session | `sudo systemctl status $PID` | `session-4310.scope — Transient: yes` | ✓ YES |
| 4 | infra/gateway/config.yml claims port 3001 | `grep -A1 "crog-ai.com" infra/gateway/config.yml` | `service: http://127.0.0.1:3001` | ✓ YES (stale confirmed) |
| 5 | fortress-dashboard.service runs from apps/storefront | `systemctl cat fortress-dashboard.service` | `WorkingDirectory=.../apps/storefront` | ✓ YES |
| 6 | cabin-rentals-of-georgia.com NOT served from this box | `curl -sI https://cabin-rentals-of-georgia.com/ \| grep server` | `server: cloudflare` — CDN, not this box | ✓ YES |
| 7 | FastAPI on port 8000 (NOT 8100) | `sudo ss -tlnp \| grep :8000` | Python pid listening on 0.0.0.0:8000 | ✓ YES; 8100 has NOTHING |
| 8 | Backend does NOT autoreload | `systemctl show fortress-backend --property=Restart` | `Restart=always` — restarts on crash, NOT on code change | ✓ YES (no autoreload) |
| 9 | BFF defaults to 8000; run-fortress-dashboard.sh defaults to 8100 | `grep DEFAULT_BACKEND_BASE_URL backend-url.ts` | `"http://127.0.0.1:8000"` — correct; dashboard script `FGP_BACKEND_URL:-http://127.0.0.1:8100` — wrong | ✓ YES (bug confirmed) |
| 10 | FGP:8100 hardcoded in log strings | `grep -rn "FGP:8100" apps/command-center/src/app/api/` | 6 occurrences in 4 files | ✓ YES (misleading) |
| 11 | POSTGRES_API_URI → fortress_shadow | `grep ^POSTGRES_API_URI .env` | `postgresql+asyncpg://fortress_api:...@127.0.0.1:5432/fortress_shadow` | ✓ YES |
| 12 | DATABASE_URL → fortress_guest (rejected) | `grep DATABASE_URL .env` | `postgresql://fgp_app:...@localhost:5432/fortress_guest` | ✓ YES (legacy, ignored) |
| 13 | fortress_shadow_test exists | `psql fortress_shadow_test -c "SELECT current_database();"` | `fortress_shadow_test` | ✓ YES |
| 14 | .env at fortress-guest-platform/.env (NOT backend/.env) | `ls .env backend/.env` | `.env` exists; `backend/.env` does NOT | ✓ YES |
| 15 | Git root = ~/Fortress-Prime | `git rev-parse --show-toplevel` | `/home/admin/Fortress-Prime` | ✓ YES |
| 16 | db_helpers.py exists with get_test_dsn() | `head -20 backend/tests/db_helpers.py` | Function present, raises if unset | ✓ YES |
| 17 | conftest.py monkey-patches AsyncSessionLocal | `grep -n "monkey\|AsyncSessionLocal" conftest.py` | Patches `_db_module.AsyncSessionLocal` in `pytest_configure` | ✓ YES (fragile, documented) |
| 18 | /api/admin/ has payouts and prime — catch-all bypassed | `ls apps/command-center/src/app/api/admin/` | `payouts/ prime/` | ✓ YES |
| 19 | Branch = feature/owner-statements-and-stabilization | `git branch --show-current` | `feature/owner-statements-and-stabilization` | ✓ YES |
| 20 | Multiple stale next-server processes | `ps aux \| grep next-server` | 6 processes (4 stale) | ✓ YES |
| 21 | fortress-console is Python tool, NOT Next.js | `systemctl cat fortress-console.service` | `ExecStart=/usr/local/bin/run-fortress-console.sh` (runs master_console.py) | ✓ YES |

**All 21 claims verified. Zero contradictions with the stated claims.**

---

## 2. Unexpected Findings (not in the original 21 claims)

These were discovered during verification and added to OPERATIONAL_TRUTH.md:

### 2a. Cloudflare tunnel has more entries than expected

The tunnel routes:
- `fortress.crog-ai.com` and `api.crog-ai.com` → port 9800 (Python master_console)
- `cabin-rentals-of-georgia.com` → port 8100 (DEAD — nothing on 8100, domain served from legacy CDN)
- `staging.cabin-rentals-of-georgia.com` → port 8000 (FastAPI directly, not Next.js BFF)
- `grafana.crog-ai.com` → port 3000 (Grafana)

The dead tunnel entry for `cabin-rentals-of-georgia.com` → 8100 is interesting: the domain IS live (Cloudflare CDN returns 200), but it's NOT served from this box. The Cloudflare tunnel entry is either a stale remnant or routes through a different Cloudflare service.

### 2b. The catch-all BFF routes SOME paths to port 9800

The catch-all `apps/command-center/src/app/api/[...path]/route.ts` has dual-backend routing:
- "CC paths" → `COMMAND_CENTER_URL || http://127.0.0.1:9800` (Python master_console tool)
- Everything else → `FGP_BACKEND_URL || http://127.0.0.1:8000` (FastAPI)

The `"isCC ? 'CC:9800' : 'FGP:8100'"` log string in the catch-all itself contains two different wrong ports: the CC label says 9800 (correct for that path) but the FGP label says 8100 (wrong; should be 8000).

### 2c. Old Apr 11 next-server is alive but not listening

PID 1135123 (from Apr 11) is still in the process table, from apps/command-center (based on CWD), but is not listening on any port. This is a zombie/orphan consuming memory.

### 2d. Port 3001 IS systemd-managed (fortress-dashboard.service, started today)

The `fortress-dashboard.service` started today at 11:45 EDT and IS the process on port 3001. It's correctly systemd-managed. The naming is just confusing (serves storefront, not dashboard/command-center).

---

## 3. Cross-reference: Which Sessions Produced Which Lessons

| Lesson | Discovered in | Phase |
|---|---|---|
| fortress_shadow is runtime DB (not fortress_guest) | Full system discovery | G.0.5 |
| crog-ai.com served on port 3001 (now corrected to 3005) | System orientation | G.0.5 |
| alembic-reconciliation docs were stale | Doc reconciliation | G.0.6 |
| G.1 cleanup was on wrong DB (fortress_guest not fortress_shadow) | System orientation | G.0.5 |
| 19,720 test rows in fortress_shadow (real runtime DB) | Cleanup execution | G.1.6 |
| db_helpers.py and TEST_DATABASE_URL isolation | Test isolation | G.1.7 |
| G.1.8 monkey-patch fragility | Test isolation | G.1.8 |
| New BFF proxy needed for /api/admin/payouts/* | G.2.1 debugging | G.2.1 |
| Port is 3005 not 3001; fortress-dashboard is storefront not command-center | G.2.1 deployment | G.2.1 |
| run-fortress-dashboard.sh has wrong FGP_BACKEND_URL default (8100) | G.2.2 verification | G.2.2 |
| Cloudflare tunnel has dead entry for cabin-rentals-of-georgia.com → 8100 | G.2.2 verification | G.2.2 |
| Catch-all BFF dual-backend (9800 for CC paths, 8000 for FGP paths) | G.2.2 verification | G.2.2 |

---

## 4. Confidence Rating per Section

| Section | Confidence | Basis |
|---|---|---|
| Cloudflare tunnel topology | **VERY HIGH** | `sudo cat /etc/cloudflared/config.yml` verbatim |
| Port map | **CERTAIN** | `sudo ss -tlnp` live output |
| crog-ai.com process management | **CERTAIN** | `systemctl status $PID` shows transient session scope |
| Stale infra/gateway/config.yml | **CERTAIN** | Diff between two files confirmed |
| FastAPI port 8000 | **CERTAIN** | `sudo ss -tlnp | grep :8000` |
| Backend no-autoreload | **CERTAIN** | `systemctl show Restart=always` = crashes restart, code does not |
| BFF URL defaults | **CERTAIN** | Source code + script grepped verbatim |
| Database routing | **CERTAIN** | Python source + live `psql` confirmed |
| Test isolation fragility | **HIGH** | Mechanism documented; fragility documented in G.1.8 report |
| Process accumulation | **CERTAIN** | `ps aux` output at time of check; will change over time |
| fortress-console = Python tool | **CERTAIN** | Script read, master_console.py confirmed |

---

## 5. Recommendation: OPERATIONAL_TRUTH.md as Task 0

Every future Claude Code session touching Fortress Prime infrastructure should begin with:

```
Task 0: Read OPERATIONAL_TRUTH.md at the repo root. Verify any claim
that is relevant to this session's work before acting on it.
```

This eliminates the class of debugging hours where the mental model of "what's running where" diverges from reality. The 21 claims in this doc cover every failure mode encountered across G.0 through G.2.2.

The doc is designed to be living: add when you learn, remove when you fix, update when things change.
