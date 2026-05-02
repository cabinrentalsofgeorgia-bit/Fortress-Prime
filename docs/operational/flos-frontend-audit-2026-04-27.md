# FLOS Frontend Audit — Command Center ↔ FLOS Pipeline

**Audited:** 2026-04-27 (Mon, evening)
**Scope:** Read-only investigation of the crog-ai.com command center relative to today's FLOS Phase 0a / Phase 1-1 through 1-5 work.
**Auditor:** Claude Code (auto mode, no code/service mutations).

---

## 1. Current State (Phase A–D Findings)

### 1.1 Frontend topology

- **Command center repo:** `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/`
- **Framework:** Next.js 16.1.6 + React 19.2.3 (App Router, `output: "standalone"`)
- **Dev script:** `next dev -p 3000 -H 0.0.0.0`
- **Build script:** `next build && node ../../scripts/sync-next-standalone-assets.mjs`
- **Production hosting:** **self-hosted** Next.js standalone build on spark-2 — *not* Vercel.

### 1.2 Process map (live, observed via `ss -tlnp` + `/proc/<pid>/cwd`)

| Port  | Process                               | Role                                          |
|-------|---------------------------------------|-----------------------------------------------|
| :3000 | `next-server (v16.1.6)` PID 1757777 (cwd: `apps/storefront`)            | storefront (dev or run, port-shared with cmdcenter dev) |
| :3005 | `next-server (v16.1.6)` PID 1877484 (cwd: `apps/command-center/.next/standalone/...`) | **command-center prod** (serves crog-ai.com)  |
| :8000 | `python run.py` PID 1654804           | `fortress-backend.service` (FastAPI)          |
| :9800 | `master_console.py` PID 2096598       | command-center custom python service (api.crog-ai.com / fortress.crog-ai.com upstream) |

> **Note:** the `package.json` dev script at `-p 3000` does not reflect production. Production command-center is built via `next build`, output goes to `.next/standalone/`, and is started on `:3005` by some external mechanism (process manager or shell script — not visible in systemd unit list under `command-center` name).

### 1.3 Cloudflare Tunnel ingress (`/etc/cloudflared/config.yml`)

```yaml
tunnel: aa7222a3-c1c9-4ee3-97c8-fb46b41a654e
ingress:
  - hostname: crog-ai.com                       → http://127.0.0.1:3005    # command-center
  - hostname: www.crog-ai.com                    → http://127.0.0.1:3005
  - hostname: console.crog-ai.com                → http://127.0.0.1:3005
  - hostname: fortress.crog-ai.com               → http://127.0.0.1:9800    # master_console.py
  - hostname: api.crog-ai.com                    → http://127.0.0.1:9800
  - hostname: cabin-rentals-of-georgia.com       → http://127.0.0.1:8100    # storefront prod
  - hostname: www.cabin-rentals-of-georgia.com   → http://127.0.0.1:8100
  - hostname: api.cabin-rentals-of-georgia.com   → http://127.0.0.1:8000    # FastAPI
  - hostname: ssh.crog-ai.com                    → ssh://localhost:22
  - hostname: grafana.crog-ai.com                → http://127.0.0.1:3000
  - hostname: staging.cabin-rentals-of-georgia.com → http://127.0.0.1:8000
  - service: http_status:404
```

`cloudflared.service`: active running. Tunnel routes are stable.

> **Doc conflict:** `crog-ai-backend/README.md` says *"Vercel (React frontend at crog-ai.com)"* — this contradicts current reality. crog-ai.com is served by self-hosted Next.js 16 (App Router) on spark-2 via Cloudflare Tunnel. The system-map.md / crog-vrs.md description (Next.js + Cloudflare Tunnel) is accurate; the crog-ai-backend README is stale.

### 1.4 API client configuration (Phase A.4)

- **Client (`src/lib/api.ts`)**: reads `NEXT_PUBLIC_API_URL` (empty by default for staff hosts). On staff hosts (`crog-ai.com`), all API traffic uses **same-origin BFF** (`/api/*`) backed by `fortress_session` cookie. `console.warn` fires if `NEXT_PUBLIC_API_URL` is set on a staff host (sovereign glass model violation).
- **Server-side client (`src/lib/server/fortress-backend.ts`)**: marked `import "server-only"`, requires `FORTRESS_BACKEND_BASE_URL` (must be `https://`) and `FORTRESS_INTERNAL_API_TOKEN` env vars; sends `Authorization: Bearer <token>` + `X-Fortress-Ingress: command_center` + `X-Fortress-Tunnel-Signature: <token>`.
- **BFF catch-all (`src/app/api/[...path]/route.ts`)**: routes by prefix:
  - `/api/vrs/`, `/api/service-health`, `/api/cluster-telemetry`, `/api/bridge/`, `/api/email-intake/`, `/api/login`, `/api/logout`, `/api/verify`, `/api/signup`, `/api/profile`, `/api/users` → `COMMAND_CENTER_URL` (default `http://127.0.0.1:9800`, the python `master_console.py`).
  - Everything else → `getBackendBaseUrl()` (FastAPI at `:8000` via `FORTRESS_BACKEND_BASE_URL`).
  - Signs internal-FGP requests with `INTERNAL_API_TOKEN || SWARM_API_KEY` for non-public paths.

### 1.5 `.env.local` keys (redacted)

```
API_PORT=<redacted>
NEXT_PUBLIC_APP_URL=<redacted>
NEXT_PUBLIC_SITE_TYPE=<redacted>
DATABASE_URL=<redacted>
POSTGRES_ADMIN_URI=<redacted>
POSTGRES_API_URI=<redacted>
DATABASE_POOL_SIZE=<redacted>
DATABASE_MAX_OVERFLOW=<redacted>
JWT_SECRET_KEY=<redacted>
JWT_ALGORITHM=<redacted>
JWT_EXPIRATION_HOURS=<redacted>
JWT_KEY_ID=<redacted>
JWT_ACCEPT_LEGACY_HS256=<redacted>
JWT_LEGACY_HS256_SECRETS=<redacted>
```

> **Anomaly worth flagging:** `command-center/package.json` lists `"pg": "^8.20.0"` as a runtime dep, and `.env.local` has `DATABASE_URL` / `POSTGRES_ADMIN_URI`. Per `CLAUDE.md` ("the frontend must never import `pg`, `asyncpg`, `psycopg2`"), this is either a violation or a server-side-only utility import. Did not deep-trace usage — **investigation deferred.**

### 1.6 Auth flow (Phase A.5)

- **Login**: client → `POST /api/auth/login` (proxied via BFF to FastAPI `/api/auth/login`). Returns `{ access_token, token_type, user }`. Token persisted in `localStorage` as `fgp_token`.
- **StaffUser shape**: `{ id, email, first_name, last_name, role: "super_admin" | "manager" | "reviewer", is_active?, notification_phone?, notification_email? }`.
- **Per-request auth**: `api.ts` reads token from `localStorage`; BFF extracts via `Authorization: Bearer` → `fortress_session` cookie → `x-fgp-token` (3-tier fallback).
- **Cookie**: `fortress_session` (set by BFF after login, used for cookie-based session continuity).
- **Server-only static bearer**: separate from JWT — used by `fortress-backend.ts` server functions and BFF signing path (`INTERNAL_API_TOKEN || SWARM_API_KEY`).

### 1.7 FastAPI service state (Phase D.1, D.2)

| Field                | Value                                                                |
|----------------------|----------------------------------------------------------------------|
| Service              | `fortress-backend.service`                                            |
| State                | active (running)                                                      |
| Started              | **Sun 2026-04-26 21:07:11 EDT** (≈22 h before this audit)             |
| Main PID             | 1654804                                                               |
| Memory               | 353 MB                                                                |
| Working tree HEAD when started | unknown directly; main branch HEAD = `b458d8867` — no FLOS code |

**Critical: running service has 0 FLOS endpoints.** Probed `http://127.0.0.1:8000/openapi.json`:

```
FLOS endpoints registered: 0
Total /api/internal/legal/* endpoints: 80
All routes count: 586
Service version reported: Fortress Guest Platform 1.0.0
```

The 80 `/api/internal/legal/*` endpoints registered are the **legacy** legal surface (cases, deadlines, correspondence, council, deposition, sanctions, discovery, etc.). **Not one** of: `dispatcher_*`, `mail/health`, `event_log`, `case_posture`, `legal_mail_ingester`, `legal_dispatcher_health`.

### 1.8 Git state — why FLOS isn't in the running service

| Branch                          | HEAD       | Has `legal_dispatcher_health.py` / `legal_mail_health.py`? |
|---------------------------------|------------|------------------------------------------------------------|
| `main`                          | `b458d8867` | **No** — last main commit is `fix(infra): per-host NIM cache isolation` |
| `feat/flos-phase-1-4-cli-health` (current checkout) | `36b200409` (this audit) → `842b3d18e` (Phase 1-4E) | **Yes** — both files exist, registered in `main.py:105-106 / 538-547` |

Today's FLOS Phase 1-3 / 1-4 / 1-5 / 1-6 work has **not been merged to main**. Working tree is on the feat branch, but the running service was started yesterday from a different working tree state and has cached its imports. **Restarting the service from current working tree (feat branch) would register the FLOS endpoints.** Restarting from main (post-checkout `git checkout main`) would not.

---

## 2. FLOS UI Coverage (Phase B–C cross-reference)

### 2.1 Existing legal UI in command-center

```
src/app/(dashboard)/legal/page.tsx                                            # cases list
src/app/(dashboard)/legal/email-intake/page.tsx                               # email intake (legacy, pre-FLOS)
src/app/(dashboard)/legal/council/page.tsx                                    # council deliberation
src/app/(dashboard)/legal/cases/[slug]/page.tsx                               # case detail
src/app/(dashboard)/legal/cases/[slug]/war-room/page.tsx                      # war-room view
src/app/(dashboard)/legal/cases/[slug]/deposition/[targetId]/print/page.tsx   # deposition print
src/app/api/legal/council/stream/route.ts                                     # SSE (BFF)
src/app/api/legal/council/[jobId]/stream/route.ts                             # SSE (BFF)
```

### 2.2 Endpoint consumption — `legal-hooks.ts`

22 distinct `/api/internal/legal/*` calls discovered, all hitting **legacy** surfaces:
- `/api/internal/legal/cases` (list)
- `/api/internal/legal/cases/{slug}` (detail)
- `/api/internal/legal/cases/{slug}/deadlines`
- `/api/internal/legal/cases/{slug}/correspondence`
- `/api/internal/legal/cases/{slug}/timeline`
- `/api/internal/legal/cases/{slug}/graph/snapshot`, `/graph/refresh`
- `/api/internal/legal/cases/{slug}/discovery/packs`, `/discovery/draft-pack`
- `/api/internal/legal/cases/{slug}/sanctions/sweep`, `/sanctions/alerts`, `/sanctions/drafts`
- `/api/internal/legal/cases/{slug}/deposition/kill-sheet`, `/deposition/kill-sheets`, `/deposition/kill-sheets/{sheetId}/export`
- `/api/internal/legal/cases/{slug}/extract`
- `/api/internal/legal/correspondence/{corrId}/status`, `/download`, `/content`
- `/api/internal/legal/deadlines/{deadlineId}`

### 2.3 FLOS surfaces with **zero** UI consumption

`grep -rnE '/api/internal/legal/(dispatcher|mail)/' src/` → **0 hits.**

| FLOS Surface                                | API endpoint (when registered)                              | UI consumer |
|---------------------------------------------|-------------------------------------------------------------|-------------|
| `legal.event_log`                           | (would be `/api/internal/legal/event-log` or similar)       | none         |
| `legal.case_posture`                        | `/api/internal/legal/posture/{slug}` (per Phase 1-4D CLI)   | none         |
| `legal.dispatcher_routes`                   | not yet exposed                                              | none         |
| `legal.dispatcher_event_attempts`           | not yet exposed                                              | none         |
| `legal.dispatcher_dead_letter`              | `/api/internal/legal/dispatcher/dead-letters` (per 1-4D)    | none         |
| `legal.dispatcher_pause`                    | `/api/internal/legal/dispatcher/pause` / `/resume` (1-4B)   | none         |
| `legal_mail_ingester` health                | `legal_mail_health.py` GET handler at line 334              | none         |
| `legal_dispatcher` health                   | `legal_dispatcher_health.py` GET handler at line 321        | none         |

> Surface gap is **complete**. FLOS event-driven pipeline has no UI surface today, even when the API endpoints are eventually registered (post-merge + restart).

---

## 3. Gaps + Recommended Actions (Phase E.2)

### Gap A — Running service lacks FLOS endpoints
- **Cause**: service started from main code; FLOS PRs unmerged.
- **Options**:
  - **A1.** Merge FLOS feat branches to main, restart `fortress-backend.service`.
  - **A2.** Restart service against current feat-branch working tree (uvicorn loads from disk on import). Risk: feat branch is not the canonical deploy target.
  - **A3.** Defer until full FLOS Phase 1-7 / Phase 2 review; soak via worker only (current state).
- **Recommended**: A1 once Phase 1-5 cutover is validated (events flow, parity holds). Don't restart prematurely.

### Gap B — JWT vs static bearer middleware conflict (GH #257)
- **Cause**: global JWT middleware intercepts `/api/internal/*` before the endpoint's `_enforce_internal_auth` static-bearer check runs.
- **Options**:
  - **B1.** Exempt `/api/internal/*` from JWT middleware (one rule).
  - **B2.** Issue service JWTs; drop static-bearer pattern.
- **Recommended**: B1, lower blast radius. Resolves after Gap A so the endpoint becomes hittable at all.

### Gap C — No FLOS UI surface
- **Cause**: today's work is backend-only; UI not yet in scope.
- **Options**:
  - **G1.** Add `/legal/flos` page consuming `dispatcher/health`, `mail/health`, dead-letter list, posture get. ~1-2 days. Requires Gap A + Gap B closed first.
  - **G2.** Defer UI; verify via psql / CLI / soak log only. Current cutover plan.
  - **G3.** Fix Gap B + register a minimal "ops" widget on existing `/legal` dashboard page surfacing dispatcher state.
- **Recommended**: **G2 for soak window** (24 h). After +24h soak completes successfully, evaluate G1 vs G3 based on operator demand.

### Gap D — `crog-ai-backend/README.md` doc drift
- **Cause**: README claims Vercel hosting; reality is self-hosted Next.js.
- **Recommendation**: file a docs ticket or fix in next docs sweep. Low priority.

### Gap E — `pg` package in command-center frontend
- **Cause**: unclear; may be server-side-only utility import.
- **Recommendation**: trace `import` callers via `grep -rn "from 'pg'\|require('pg')" apps/command-center/src/`. If no live reference, remove. If used in server-only files, document the exception.

---

## 4. Division Boundary Compliance (Phase F)

### 4.1 Zone segmentation observed

- `apps/storefront/` (port :8100, cabin-rentals-of-georgia.com) — Zone A (public)
- `apps/command-center/` (port :3005, crog-ai.com) — Zone B (internal staff + AI)
- Cloudflare Tunnel ingress separation enforces hostname → upstream port mapping; no shared listener.
- `command-center/src/lib/domain-boundaries.ts` exports `isStorefrontHost` / `isStaffHost` and `staffHostsForServerActions()` consumed in `next.config.ts` `serverActions.allowedOrigins`. Server actions are explicitly scoped.

### 4.2 Auth segmentation

- **Same StaffUser model** serves both VRS and legal sections (single role enum: `super_admin | manager | reviewer`).
- `src/lib/roles.ts` mirrors backend role checks; legal pages do not appear to require a separate role. **A staff `manager` likely sees both VRS reservations and legal cases** — if this is intended, fine; if legal data should be more restricted, this is a gap.
- No evidence of legal-only role gating in the audited files. **Investigation deferred.**

### 4.3 Recommended verification

If legal data confidentiality requires a stricter gate:
- Add `legal_reviewer` or similar role.
- Wrap `(dashboard)/legal/*` in a role-check layout.tsx.

This is **not a current FLOS blocker** — flagging for awareness only.

---

## 5. Verification Checklist for Operator (Phase E.1)

Operator runs these from a browser at `crog-ai.com`. Each item lists the URL, expected behavior, "broken" symptoms, and which backend service must be running.

### 5.1 Site loads + auth gate works

| Step | URL | Expected | Broken looks like | Required backend |
|------|-----|----------|--------------------|------------------|
| 1 | `https://crog-ai.com/` | Redirects to `/login` if unauthenticated | 502 / 504 / blank | command-center :3005 + cloudflared |
| 2 | `https://crog-ai.com/login` | Login form renders | 401 from BFF before form loads | :3005 + :8000 (FastAPI for `/api/auth/login`) |
| 3 | submit credentials | Redirects to dashboard, sets `fgp_token` localStorage + `fortress_session` cookie | 401 / no redirect | :8000 reachable |

### 5.2 Legal section reachable (legacy surface — should work today)

| Step | URL | Expected | Broken | Required |
|------|-----|----------|--------|----------|
| 4 | `https://crog-ai.com/legal` | Cases list renders (may be empty) | spinner forever / 401 from BFF | :3005 + :8000 |
| 5 | `https://crog-ai.com/legal/email-intake` | Legacy email intake surface | 404 / 500 | :3005 + :8000 |
| 6 | `https://crog-ai.com/legal/council` | Council deliberation surface | 404 | :3005 + :8000 |

### 5.3 FLOS surfaces (will NOT work today — gaps documented)

| Step | URL | Expected behavior **today** | Required to fix |
|------|-----|------------------------------|-----------------|
| 7 | `https://crog-ai.com/legal/flos` | **404 — page does not exist** | Gap C remediation |
| 8 | `curl -H 'Authorization: Bearer <token>' https://api.cabin-rentals-of-georgia.com/api/internal/legal/dispatcher/health` | **404 — endpoint not registered on running service** | Gap A (merge + restart) |
| 9 | After Gap A: same curl | **401 from JWT middleware** | Gap B (exempt or unify) |
| 10 | After Gap A + Gap B: same curl | `200 OK` with health JSON | — |

### 5.4 What works today (the durable backstop)

Until Gaps A, B, C close, FLOS state is observable only via:
- `/var/log/fortress-soak.log` — soak script output
- `psql -d fortress_db -c "SELECT * FROM legal.event_log"` and friends
- `python -m backend.cli.legal_dispatcher status` (Phase 1-4 CLI, runs locally)
- `journalctl -u fortress-arq-worker --follow` for live worker activity

---

## Executive Summary (10-line)

1. **command-center is self-hosted Next.js 16 on spark-2 :3005**, not Vercel — README in `crog-ai-backend/` is stale.
2. **Cloudflare Tunnel routes crog-ai.com → :3005 (Next.js)**, api.crog-ai.com → :9800 (master_console.py), api.cabin-rentals-of-georgia.com → :8000 (FastAPI).
3. **The running fortress-backend (started 22 h ago) has 0 FLOS endpoints registered** — main branch is at `b458d8867` and today's FLOS PRs (Phase 1-3 / 1-4 / 1-5) have not merged to main.
4. **80 legacy `/api/internal/legal/*` endpoints are registered** (cases, deadlines, council, deposition, sanctions, discovery) — the legacy legal UI works.
5. **The command-center has rich legal UI** (`/legal`, `/legal/cases/{slug}`, `/legal/council`, `/legal/email-intake`, war-room, deposition print) consuming 22 legacy endpoints via `legal-hooks.ts`.
6. **Zero UI consumption of FLOS surfaces** — no page references `/api/internal/legal/dispatcher/*` or `/api/internal/legal/mail/*` or any FLOS table.
7. **Auth model**: localStorage `fgp_token` (JWT) + `fortress_session` cookie via BFF; server-side calls use a separate `INTERNAL_API_TOKEN` static bearer.
8. **Gap A** (running service ≠ FLOS code) requires merge + restart; **Gap B** is GH #257 (JWT vs static bearer); **Gap C** is the missing FLOS UI.
9. **Recommended path**: defer UI work (G2) through the 24h Phase 1-6 soak; close Gap A + Gap B once soak validates; revisit Gap C after.
10. **Two new findings worth tracking**: stale Vercel claim in `crog-ai-backend/README.md`, and `pg` runtime dep in command-center (potential CLAUDE.md violation, needs trace).

---

**Audit document path**: `/home/admin/Fortress-Prime/docs/operational/flos-frontend-audit-2026-04-27.md`
