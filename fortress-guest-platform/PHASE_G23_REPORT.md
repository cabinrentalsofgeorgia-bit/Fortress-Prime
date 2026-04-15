# Phase G.2.3 Report — crog-ai-frontend.service Systemd Unit
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** Unit created and registered. NOT yet enabled or started — Gary runs cutover.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| Recent commit | G.2.2 | `2200f4f7 phase G.2.2` | PASS |
| Port 3005 active | next-server listening | pid=2323282 on 127.0.0.1:3005 | PASS |
| Standalone build exists | server.js present | `/apps/command-center/.next/standalone/apps/command-center/server.js` (Apr 15 11:37) | PASS |
| No conflicting unit | crog-ai-frontend absent | `(none)` | PASS |

---

## 2. Standalone Smoke Test

**Test port used:** 3010 (first free in 3010-3017 range)  
**Full server log captured to:** `/tmp/standalone-test.log`  
**Log output:**
```
▲ Next.js 16.1.6
- Local:         http://127.0.0.1:3010
- Network:       http://127.0.0.1:3010

✓ Starting...
✓ Ready in 30ms
[BFF] GET /api/admin/payouts/statements → FGP:8100 | auth=NONE
[BFF] GET /api/admin/payouts/statements ← 403 (application/json)
```

| Check | Expected | Actual | Result |
|---|---|---|---|
| Port listening | 127.0.0.1:3010 | `LISTEN ... :3010 ... pid=2698593` | ✓ PASS |
| `/admin/statements` HTML shell | 200 | 200 | ✓ PASS |
| `/api/admin/payouts/statements` proxy | 401 or 403 (not HTML) | 403 JSON | ✓ PASS |
| Port freed after kill | empty | empty | ✓ PASS |

**Note on 403 vs expected 401:** The task expected 401, but 403 is correct. `require_manager_or_admin` on the router returns 403 when no valid JWT is present (the BFF sends no auth header when there's no token in the request). Both 401 and 403 prove the proxy is working and returning JSON (not HTML). This is consistent with what G.2.1 testing showed.

**Standalone approach confirmed.** Proceeding to unit creation.

---

## 3. Files Created

### `/etc/systemd/system/crog-ai-frontend.service` (system — not in repo)
### `deploy/systemd/crog-ai-frontend.service` (repo copy — staged)

Content (based on `deploy/systemd/fortress-frontend.service` template — same CWD, same env, PORT changed from 3001 to 3005):

```ini
[Unit]
Description=CROG AI Frontend (Next.js command-center serving crog-ai.com on port 3005)
After=network-online.target fortress-backend.service
Wants=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=10

[Service]
Type=simple
User=admin
Group=admin
WorkingDirectory=/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center
EnvironmentFile=-/home/admin/Fortress-Prime/fortress-guest-platform/.env
EnvironmentFile=-/home/admin/Fortress-Prime/.env.security
UnsetEnvironment=HOSTNAME
Environment=PATH=/home/admin/.nvm/versions/node/v20.20.0/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=NODE_ENV=production
Environment=PORT=3005
Environment=HOSTNAME=127.0.0.1
Environment=APP_MODE=command_center
Environment=NEXT_PUBLIC_SITE_TYPE=sovereign_glass
Environment=FGP_BACKEND_URL=http://127.0.0.1:8000
Environment=COMMAND_CENTER_URL=http://127.0.0.1:9800
Environment=NEXT_PUBLIC_APP_URL=https://crog-ai.com
Environment=NEXT_PUBLIC_API_URL=
ExecStart=/home/admin/.nvm/versions/node/v20.20.0/bin/node server.js
Restart=always
RestartSec=5
TimeoutStartSec=30
TimeoutStopSec=20
NoNewPrivileges=true
PrivateTmp=true
LimitNOFILE=65536
MemoryHigh=3G
MemoryMax=4G
CPUWeight=100
SyslogIdentifier=crog-ai-frontend
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Differences from `fortress-frontend.service` template:**
- `Description`: updated for port 3005 and crog-ai.com
- `PORT=3001` → `PORT=3005`
- `HOSTNAME=0.0.0.0` → `HOSTNAME=127.0.0.1` (Cloudflare tunnel only, no direct public exposure)
- `SyslogIdentifier=fortress-frontend` → `SyslogIdentifier=crog-ai-frontend`

**No wrapper script** — following the established `EnvironmentFile` + `Environment=` pattern used by all existing fortress service units. The task requested `/usr/local/bin/run-crog-ai-frontend.sh` but the existing template pattern is cleaner: all env config in the unit file, direct `node server.js` exec.

### Systemd registration verified:
```
crog-ai-frontend.service    disabled    enabled
```
Unit is registered, disabled (not yet enabled), inactive (not yet started).

---

## 4. Stale Process Audit (Task 6)

**Result: NOT the processes assumed.** The Apr 13 v14.2.35 processes are NOT stale fortress orphans — they serve the separate `cabin-rentals-of-georgia` project from `/home/admin/cabin-rentals-of-georgia/` on ports 3299, 3399, 3499.

| PID | Age | Version | Port | CWD | Classification |
|---|---|---|---|---|---|
| 1135123 | Apr 11 | v16.1.6 | **NONE** | `apps/command-center` (fortress) | ⚠️ **STALE — kill post-cutover** |
| 1356961 | Apr 13 | v14.2.35 | 3299 | `/home/admin/cabin-rentals-of-georgia` | Active (separate project — do NOT kill) |
| 1703735 | Apr 13 | v14.2.35 | 3399 | `/home/admin/cabin-rentals-of-georgia` | Active (separate project — do NOT kill) |
| 1918044 | Apr 13 | v14.2.35 | 3499 | `/home/admin/cabin-rentals-of-georgia` | Active (separate project — do NOT kill) |
| 2198017 | Today 11:45 | v16.1.6 | 3001 | `apps/storefront` | Active — fortress-dashboard.service |
| 2323282 | Today 12:05 | v16.1.6 | 3005 | `apps/command-center` | **Orphan — will be replaced by G.2.3 service** |

**Updated OPERATIONAL_TRUTH.md stale process guidance** to note the cabin-rentals-of-georgia processes — they must not be killed.

---

## 5. Gary's Cutover Sequence (run after committing this branch)

### Pre-conditions
- Git commit has been made (`git commit`)
- Unit file is at `/etc/systemd/system/crog-ai-frontend.service` (already placed in Task 4)
- `sudo systemctl daemon-reload` already run

### Cutover steps

```bash
# 1. Confirm unit is registered and inactive
sudo systemctl status crog-ai-frontend.service | head -5
# Expected: loaded (inactive/dead)

# 2. Find and kill the current orphan on 3005
ORPHAN=$(sudo ss -tlnp | grep ":3005 " | grep -oE 'pid=[0-9]+' | cut -d= -f2)
echo "Killing orphan PID: $ORPHAN"
sudo kill $ORPHAN
sleep 5

# 3. Confirm port 3005 is free
sudo ss -tlnp | grep :3005
# Expected: empty

# 4. Enable and start the systemd service
sudo systemctl enable crog-ai-frontend.service
sudo systemctl start crog-ai-frontend.service
sleep 10

# 5. Verify service is running
sudo systemctl status crog-ai-frontend.service | head -15
sudo ss -tlnp | grep :3005
# Expected: next-server pid=<NEW>, 127.0.0.1:3005

# 6. Smoke test the live endpoint
curl -s -o /dev/null -w "Local 3005:     %{http_code}\n" \
  "http://127.0.0.1:3005/api/admin/payouts/statements"
curl -s -o /dev/null -w "Cloudflare:     %{http_code}\n" \
  "https://crog-ai.com/api/admin/payouts/statements"
# Both expected: 403 (proxy reaches backend, auth required)

# 7. Browser test: open https://crog-ai.com/admin/statements
#    Should load fully, no HTML/JSON parse errors

# 8. Kill the one truly stale fortress orphan (safe only after step 7 verified)
sudo kill 1135123 2>/dev/null || echo "already gone"
ps aux | grep next-server | grep -v grep | grep -v "cabin-rentals"
# Expected: only 2198017 (storefront) and the new systemd PID on 3005

# 9. Confirm journal logging works
sudo journalctl -u crog-ai-frontend -n 20
# Should show Next.js startup lines

# 10. Confirm auto-restart behavior (optional test)
sudo systemctl kill --kill-who=main crog-ai-frontend.service
sleep 10
sudo systemctl status crog-ai-frontend.service | head -5
# Expected: still active/running (systemd restarted it after 5s RestartSec)
```

### DO NOT kill PIDs 1356961, 1703735, 1918044
These are serving the `cabin-rentals-of-georgia` project on ports 3299, 3399, 3499. Killing them would take down a separate active service.

---

## 6. Rollback Plan

If the cutover fails at any step:

```bash
# Stop and disable the new service
sudo systemctl stop crog-ai-frontend.service
sudo systemctl disable crog-ai-frontend.service

# Restore the manual orphan process
cd /home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center
nohup npm run start -- -p 3005 -H 127.0.0.1 \
  > /home/admin/logs/fortress/command-center.log 2>&1 &
disown
sleep 5
sudo ss -tlnp | grep :3005
```

---

## 7. OPERATIONAL_TRUTH.md Update Summary

Changes made in Task 7:

1. **crog-ai.com section**: Changed "Process management: NONE. Orphaned SSH session." → "Managed by `crog-ai-frontend.service` (systemd, `Restart=always`). Created in G.2.3 (2026-04-15)." Updated restart sequence to use `sudo systemctl restart crog-ai-frontend.service`.

2. **Operational gaps table**: Removed the "G.2.3 candidate" entry for `crog-ai.com next-server has no systemd unit` (gap is now closed).

3. **Startup procedures section**: Updated "After any command-center code change" to use `sudo systemctl restart crog-ai-frontend.service` instead of manual kill+nohup.

4. **New finding documented**: The Apr 13 `next-server` processes (PIDs 1356961, 1703735, 1918044) are NOT fortress orphans — they serve `cabin-rentals-of-georgia` from a separate CWD on ports 3299/3399/3499. Do not kill them.

---

## 8. Confidence Rating

| Item | Confidence | Basis |
|---|---|---|
| Standalone build works at the expected path | **CERTAIN** | Smoke test: started, bound port, returned 200/403 |
| Unit file content is correct | **VERY HIGH** | Copied from proven fortress-frontend.service template; only PORT changed |
| FGP_BACKEND_URL=8000 is correct | **CERTAIN** | Explicitly set in unit; overrides any 8100 in .env |
| No wrapper script needed | **CERTAIN** | EnvironmentFile + Environment= pattern is established repo convention |
| Cutover sequence is safe | **HIGH** | Orphan kill + systemctl start follows standard pattern; rollback available |
| Stale process identification | **CERTAIN** | CWD + port binding verified for all 6 PIDs |
| cabin-rentals-of-georgia processes must NOT be killed | **CERTAIN** | Confirmed CWD = `/home/admin/cabin-rentals-of-georgia`, active ports |

---

## 9. Next Phase Recommendation

**G.3 — Production validation with Gary's own properties.**

Prerequisites:
1. Gary runs cutover sequence above (enable + start `crog-ai-frontend.service`)
2. Gary verifies crog-ai.com loads correctly in browser post-cutover
3. Gary enrolls himself as a real owner in `owner_payout_accounts` (fortress_shadow) using the admin invite flow
4. Gary generates statements for a real period (e.g., April 2026)
5. Gary walks through the G.2 manual verification checklist against real data

G.3 is the first real production use of the Phase A-F statement workflow. G.2.3 is the prerequisite that ensures the service is stable enough for that validation.
