# Phase G.2.4 Report — Gateway Config Reconciliation and Storefront Topology
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization`

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| HEAD | G.2.3 (98987ecc) | `98987ecc phase G.2.3` | PASS |
| `crog-ai-frontend.service` | active | **active** (Gary ran cutover; PID 2768669) | PASS ✓ |
| Port 3005 | listening | 0.0.0.0:3005 (see note §8) | PASS |
| `infra/gateway/config.yml` | exists | exists | PASS |
| `/etc/cloudflared/config.yml` | readable | readable | PASS |

**Note:** Gary ran the G.2.3 cutover between sessions. The `crog-ai-frontend.service` is now active with PID 2768669 (systemd-managed). The orphaned PID 2323282 from G.2.3 is gone.

---

## 2. Storefront Port Verification (Task 2)

### a. PIDs still running
```
PID 1356961  PPID 1  user admin  elapsed 2-08:26:23  next-server (v14.2.35)
PID 1703735  PPID 1703734  user admin  elapsed 2-07:30:46  next-server (v14.2.35)
PID 1918044  PPID 1  user admin  elapsed 2-06:56:31  next-server (v14.2.35)
```
All three are still running, ~2.5 days elapsed.

### b. Port bindings
```
PID 1356961 → *:3299
PID 1703735 → *:3399
PID 1918044 → *:3499
```
All three bind to all interfaces (`*`, not 127.0.0.1), on ports 3299, 3399, 3499.

### c. CWDs
```
PID 1356961: /home/admin/cabin-rentals-of-georgia
PID 1703735: /home/admin/cabin-rentals-of-georgia
PID 1918044: /home/admin/cabin-rentals-of-georgia
```
All three run from `/home/admin/cabin-rentals-of-georgia` — a **separate repository**, not fortress-guest-platform.

### d. Systemd ownership
All three: `session-2592.scope — Transient: yes`  
**Not systemd-managed.** Same orphaned SSH session (2592) as the pre-G.2.3 crog-ai-frontend was. This session has been alive for at least 2.5 days.

### e. Cloudflare tunnel relationship
The Cloudflare tunnel for `cabin-rentals-of-georgia.com` routes to **port 8100** (nothing listening). These processes on 3299/3399/3499 are NOT reachable via the tunnel — they're local dev/staging instances.

**Verdict:** G.2.3 claim confirmed entirely. These are:
- A separate project (`cabin-rentals-of-georgia`)
- Orphaned SSH session processes
- Local dev/staging, not publicly reachable via the tunnel
- **Must NOT be killed** by fortress maintenance operations

---

## 3. infra/gateway/config.yml Rewrite

### Old content (stale)
```yaml
# Staff UI (Next.js Command Center) must use port 3001. Do NOT point crog-ai.com at :8100
tunnel: ${CLOUDFLARE_TUNNEL_ID}
credentials-file: /etc/cloudflared/${CLOUDFLARE_TUNNEL_ID}.json

ingress:
  - hostname: www.crog-ai.com
    service: http://127.0.0.1:3001     ← WRONG (live is 3005)
  - hostname: crog-ai.com
    service: http://127.0.0.1:3001     ← WRONG (live is 3005)
  - hostname: staging.cabin-rentals-of-georgia.com
    service: http://127.0.0.1:3000     ← missing from live config
  - hostname: api.cabin-rentals-of-georgia.com
    service: http://127.0.0.1:8100
  - service: http_status:404
```
**4 ingress rules, 2 wrong ports, placeholder tunnel ID.**

### New content (reconciled with production)
```yaml
# Documentation copy of /etc/cloudflared/config.yml
# Not loaded by cloudflared — authoritative is /etc/cloudflared/config.yml
# Last reconciled: 2026-04-15 (Phase G.2.4)

tunnel: aa7222a3-c1c9-4ee3-97c8-fb46b41a654e
credentials-file: /etc/cloudflared/aa7222a3-c1c9-4ee3-97c8-fb46b41a654e.json
protocol: http2

ingress:
  - hostname: crog-ai.com              → http://127.0.0.1:3005
  - hostname: www.crog-ai.com          → http://127.0.0.1:3005
  - hostname: console.crog-ai.com      → http://127.0.0.1:3005
  - hostname: fortress.crog-ai.com     → http://127.0.0.1:9800
  - hostname: api.crog-ai.com          → http://127.0.0.1:9800
  - hostname: cabin-rentals-of-georgia.com     → http://127.0.0.1:8100 (dead)
  - hostname: www.cabin-rentals-of-georgia.com → http://127.0.0.1:8100 (dead)
  - hostname: api.cabin-rentals-of-georgia.com → http://127.0.0.1:8000
  - hostname: ssh.crog-ai.com          → ssh://localhost:22
  - hostname: grafana.crog-ai.com      → http://127.0.0.1:3000
  - hostname: staging.cabin-rentals-of-georgia.com → http://127.0.0.1:8000
  - service: http_status:404
```
**12 ingress rules, real tunnel ID, correct ports, documentation header.**

### Diff verification
```
sudo diff /etc/cloudflared/config.yml <(grep -v '^#' infra/gateway/config.yml | sed '/^[[:space:]]*$/d')
→ 4d3
→ <
```
One blank line difference only (line 4 of live config has an extra blank line after `protocol: http2`). Zero content differences. Routes, hostnames, and services are identical.

---

## 4. OPERATIONAL_TRUTH.md Updates

### Sections changed

| Section | Change |
|---|---|
| "Why this doc exists" item 1 | Updated: crog-ai.com orphan now "fixed by crog-ai-frontend.service (G.2.3)" |
| "Why this doc exists" item 2 | Updated: infra/gateway/config.yml "now a documented copy (G.2.4)" |
| Cloudflare tunnel table | Added www.cabin-rentals-of-georgia.com and api.cabin-rentals-of-georgia.com rows; updated crog-ai.com note to reference crog-ai-frontend.service |
| Cloudflare tunnel note | Changed from "STALE DOC WARNING" to documentation-copy status with diff command |
| Port map table | Added 3299/3399/3499 row with "do NOT kill" warning; updated port 3005 to show systemd service |
| **New section** | "cabin-rentals-of-georgia.com — separate project (ports 3299/3399/3499)" with full verification guide |
| Operational gaps table | Removed G.2.4 gaps (gateway config, cabin-rentals tunnel). Added two new lower-priority gaps (cabin-rentals orphaned processes, 0.0.0.0 binding on port 3005) |
| Process hygiene section | Replaced narrative with a table showing safe-to-kill vs do-NOT-kill classifications with a safe identification script |

### Operational gaps closed
- "infra/gateway/config.yml is stale" — CLOSED (rewritten to mirror production)
- "cabin-rentals-of-georgia.com Cloudflare tunnel entry routes to dead port 8100 (as a gap)" — reclassified from actionable gap to "leave as-is until known safe to change" (the production domain is served by Cloudflare CDN, not by this box)

### New operational gaps opened
- `crog-ai-frontend.service` binds to `0.0.0.0:3005` instead of `127.0.0.1:3005` — LOW priority, functional via Cloudflare tunnel
- cabin-rentals-of-georgia next-servers are orphaned (no systemd) — LOW priority, separate project scope

---

## 5. Confidence Rating

| Item | Confidence | Basis |
|---|---|---|
| infra/gateway/config.yml mirrors production | **CERTAIN** | diff shows one blank-line difference, zero content differences |
| Storefront PID claims (G.2.3) confirmed | **CERTAIN** | Live ps + ss + readlink all match |
| cabin-rentals processes are NOT fortress orphans | **CERTAIN** | CWD = `/home/admin/cabin-rentals-of-georgia` confirmed |
| cabin-rentals processes are not tunnel-reachable | **CERTAIN** | Tunnel routes to port 8100 (dead); their ports 3299/3399/3499 not in tunnel |
| OPERATIONAL_TRUTH.md is now accurate | **VERY HIGH** | All claims re-verified against live system during this phase |
| 0.0.0.0 binding on port 3005 | **CERTAIN** — but cause unclear | HOSTNAME env var in unit may conflict with UnsetEnvironment; functional regardless |

---

## 6. Recommended Next Phase

**G.2.5** — Fix `run-fortress-dashboard.sh` `FGP_BACKEND_URL` default (8100 → 8000). Small, targeted, LOW risk.

**Or G.3** — Production validation with Gary's own properties (first real owner enrollment, statement generation, end-to-end G.2 UI walkthrough).

The crog-ai-frontend.service cutover (confirmed active in this session's pre-flight) unblocks both. The remaining operational gaps are all LOW/MEDIUM priority and don't block G.3.
