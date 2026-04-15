# Phase G.2.5 Report — fortress-dashboard.service Removal
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** Service stopped, disabled, and deleted. Port 3001 free. All health checks passing.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| HEAD | G.2.4 (2395615f) | ✓ | PASS |
| `crog-ai-frontend.service` | active | active | PASS |
| `fortress-dashboard.service` | active (to be killed) | active | PASS |
| Port 3001 | listening | 127.0.0.1:3001 pid=2198017 | PASS |
| `/usr/local/bin/run-fortress-dashboard.sh` | exists | -rwxr-xr-x, root, Mar 31 | PASS |
| `/etc/systemd/system/fortress-dashboard.service` | exists | -rw-r--r--, root, Mar 31 | PASS |
| `fortress-frontend.service.d/` override dir | may exist | EXISTS — contained `FGP_BACKEND_URL=http://127.0.0.1:8100` | PASS (also deleted) |

---

## 2. Port 3001 Reference Grep Results (Task 2)

### Harmless references (not blocking)

| File | Reference | Classification |
|---|---|---|
| `apps/*/src/data/legacy/testimonials/*.json` | `"legacy_node_id": "3001"` | Drupal CMS node ID — not a port |
| `apps/*/src/data/drupal_granular_blueprint.json` | `"nid": 3001`, `"pid": 3001`, `source_path: "node/3001"` | Drupal node IDs — not ports |
| `apps/*/src/data/legacy-redirects.ts` | `{ source: "/node/3001", destination: "/testimonial/..." }` | Drupal 301 redirect — not a network port |
| `backend/tests/test_phase_e*.py` | `Decimal("3001.91")`, `Decimal("-3001.91")` | Dollar amount ($3,001.91) — not a port |
| `backend/scripts/regenerate_pdf_demos.py` | `"opening_balance": Decimal("3001.91")` | Same — dollar amount |
| `apps/command-center/src/app/login/page.tsx` | `<span>Port 3001 isolated</span>` | UI label text — not a live connection |
| `apps/command-center/src/app/api/auth/login/route.ts` | Error message mentioning `:3001` | Stale error text — not a live connection |
| `apps/command-center/src/lib/system-health-websocket.ts` | `port === "3001"` condition | Dev mode check — irrelevant in production on 3005 |
| `backend/tests/test_owner_magic_link_cookie.py` | `base_url="http://127.0.0.1:3001"` in AsyncClient | Uses ASGITransport — never connects to real port 3001 |
| `backend/main.py` | CORS origins: `localhost:3001`, `192.168.0.100:3001`, `192.168.0.114:3001` | Stale CORS entries — harmless (just allow from a port nothing uses now) |

### Flagged for future follow-up (not blocking G.2.5)

| File | Reference | Action needed |
|---|---|---|
| `backend/api/system_health.py:37` | `("fortress-frontend.service", 3001, "Command Center")` | System health check will report port 3001 as down. Update to check port 3005 + `crog-ai-frontend.service`. G.2.6 candidate. |
| `backend/api/contracts.py:36` | `VRS_URL = os.getenv("VRS_URL", "http://192.168.0.100:3001")` | Stale default. Verify VRS_URL is overridden in `.env`. |
| `backend/api/agreements.py:34` | `VRS_URL = "http://192.168.0.100:3001"` | Hardcoded stale URL. Verify env var override. |

**Verdict:** No production code path actively connects to port 3001 in a way that would break. Proceeding with deletion.

**Dev port confirmed:** `apps/command-center/package.json` dev script: `next dev -p 3000 -H 0.0.0.0` — port **3000**, not 3001.

---

## 3. Stop / Disable / Remove Sequence

### System files deleted

| File | Action | Result |
|---|---|---|
| `/etc/systemd/system/fortress-dashboard.service` | `sudo rm` | Confirmed gone |
| `/etc/systemd/system/fortress-frontend.service.d/env.conf` | `sudo rm -rf` dir | Orphan override dir deleted (contained `FGP_BACKEND_URL=http://127.0.0.1:8100`) |
| `/usr/local/bin/run-fortress-dashboard.sh` | `sudo rm` | Confirmed gone |

### Sequence output
```
systemctl stop fortress-dashboard.service
→ inactive (dead) since 13:59:56 EDT
→ port 3001: free immediately

systemctl disable fortress-dashboard.service
→ Removed /etc/systemd/system/multi-user.target.wants/fortress-dashboard.service
→ disabled

rm /etc/systemd/system/fortress-dashboard.service
→ removed

rm -rf /etc/systemd/system/fortress-frontend.service.d/
→ removed (contained env.conf with FGP_BACKEND_URL=8100)

systemctl daemon-reload
→ success

systemctl list-unit-files | grep fortress-dashboard
→ (no output — unit gone)

ls -la /usr/local/bin/run-fortress-dashboard.sh
→ No such file or directory
```

---

## 4. In-Repo File Removals (Task 6)

`fortress-dashboard.service` was **not present** in `deploy/systemd/` (never committed to git — only existed in `/etc/systemd/system/`). The `rm -f` had no effect on the repo.

`run-fortress-dashboard.sh` was also not in the repo.

**Consequence for staging:** The `git add -u deploy/systemd/` will pick up no deletions from Task 6. The only git changes are OPERATIONAL_TRUTH.md and PHASE_G25_REPORT.md.

---

## 5. Health Verification (Task 7)

| Probe | Expected | Actual | Result |
|---|---|---|---|
| `crog-ai-frontend.service` status | active (running) | active (running), 40min uptime, PID 2768669 | ✓ PASS |
| `fortress-backend.service` status | active (running) | active (running), 1h 27min uptime | ✓ PASS |
| `curl http://127.0.0.1:3005/api/admin/payouts/statements` | 401 | **401** | ✓ PASS |
| `curl https://crog-ai.com/api/admin/payouts/statements` | 401 | **401** | ✓ PASS |
| `curl http://127.0.0.1:8000/api/admin/payouts/statements` | 403 | **403** | ✓ PASS |
| Port 3001 | free | **free** (no listener) | ✓ PASS |

Zero collateral damage. crog-ai.com is fully functional via `crog-ai-frontend.service`.

---

## 6. OPERATIONAL_TRUTH.md Updates

### Changes made

| Section | Change |
|---|---|
| "Hour of pain" item 3 | Updated to past tense: "was misnamed... deleted in G.2.5; misconfiguration won't bite future sessions" |
| Port map table | Port 3001 row changed from active to "NOTHING (G.2.5) / fortress-dashboard.service DELETED" |
| `fortress-dashboard.service` section | Replaced with `~~fortress-dashboard.service~~ (DELETED)` historical record explaining what it was and what was removed |
| Process hygiene table | Port 3001 row updated to show deleted status |
| Startup procedures — storefront | Replaced `systemctl restart fortress-dashboard` with note: service deleted; storefront target is Vercel; manual dev server instructions if needed |
| Operational gaps | Removed G.2.5 gap; added 3 new entries for: system_health.py port check, contracts.py/agreements.py VRS_URL defaults, cabin-rentals orphans |

---

## 7. Confidence Rating

| Item | Confidence |
|---|---|
| Service deleted cleanly | **CERTAIN** — stop + disable + daemon-reload + rm all confirmed |
| No production breakage | **CERTAIN** — all health probes pass; 401/403 correct |
| Port 3001 is free | **CERTAIN** — `sudo ss -tlnp | grep :3001` shows nothing |
| In-repo cleanup | **CERTAIN** — files were never in repo; nothing to delete |
| system_health.py will show port 3001 as down | **CERTAIN** — documented as G.2.6 follow-up |
| VRS_URL defaults are stale | **LIKELY** — needs verification against live .env |

---

## 8. Recommended Next Phase

**Gary's choice:**

**G.3 — Production validation with real owner data.** crog-ai.com is systemd-managed, operational gap is closed, storefront clutter is reduced. Ready for Gary to enroll himself as the first real owner in fortress_shadow and run the G.2 statement UI end-to-end.

**G.2.6 — Cleanup follow-up:**
- Update `backend/api/system_health.py` to check port 3005 + `crog-ai-frontend.service` instead of port 3001
- Verify VRS_URL overrides in .env (contracts.py, agreements.py)
- Decide on cabin-rentals-of-georgia orphan processes (3299/3399/3499) — kill or document intent

G.3 does not depend on G.2.6. Both can proceed.
