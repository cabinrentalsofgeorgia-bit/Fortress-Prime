# Fortress Prime — Full-Stack Authentication & Telemetry Audit

**Scope:** Monorepo `apps/command-center` + `apps/storefront`, FastAPI on DGX, Zone B staff host `crog-ai.com` / `www.crog-ai.com` via Cloudflare Tunnel.  
**Principles:** No mock data in production paths; fixes are native (bcrypt, RS256 JWT, HttpOnly cookie), not auth bypass.

This document records **as-run findings** against the current codebase and a **hardening backlog** you can execute after any incident.

---

## PHASE 1 — Cryptographic identity & database integrity

### Canonical tools (no bypass)

| Purpose | Location |
|--------|----------|
| Password hashing (bcrypt) | `backend/core/security.py` — `hash_password`, `verify_password` |
| Native hash reset | `backend/scripts/reset_staff_password.py` — uses `hash_password` (not passlib; codebase is **bcrypt** directly) |
| Read-only audit | `backend/scripts/audit_staff_user.py` — prints role, `is_active`, bcrypt prefix |

**Commander reset (break-glass):**

```bash
cd fortress-guest-platform
python backend/scripts/audit_staff_user.py --email 'ops@example.com'
FGP_STAFF_PASSWORD_RESET='new-secret' python backend/scripts/reset_staff_password.py --email 'ops@example.com'
```

### Schema / Zone B access

- Table: `staff_users` (`StaffUser` in `backend/models/staff.py`).
- Roles: `super_admin`, `manager`, `reviewer` — all satisfy `RoleChecker([...])` on protected telemetry routes.
- FastAPI `get_current_user` loads `StaffUser` by JWT `sub` (UUID) and rejects inactive users.

### Finding

- **Passlib:** Not used; audit language should say **bcrypt** to match implementation.
- **Password mismatch:** Resolved operationally with `reset_staff_password.py`; `audit_staff_user.py` proves bcrypt prefix before login tests.

---

## PHASE 2 — Backend API contract (FastAPI)

### Login

- **Route:** `POST /api/auth/login` — `backend/api/auth.py`
- **Behavior:** Email normalized with `.lower()`; `verify_password` vs `password_hash`; mints **RS256** JWT via `create_access_token` with claims: `sub` (user id), `role`, `email`, `exp`, `iat`; header `kid`.

### JWT validation

- **Dependency:** `get_current_user` — Bearer only; decodes RS256, checks `kid` if configured, loads user by UUID `sub`.
- **Note:** There are no separate OAuth-style **scopes** in the JWT; authorization is **role** on the user row + `RoleChecker`.

### Telemetry (correct paths — not `/api/system/telemetry`)

The audit prompt referenced `/api/system/telemetry`; the **actual** protected surfaces used by the Command Center dashboard include:

| Client hook | Next BFF path | Upstream FastAPI |
|-------------|---------------|------------------|
| `useParityDashboard` | `/api/telemetry/parity-dashboard` | `GET /api/telemetry/parity-dashboard` |
| `useSovereignPulse` | `/api/telemetry/sovereign-pulse` | (router under `/api/telemetry`) |
| `useFunnelHQ` | `/api/telemetry/funnel-hq` | (router under `/api/telemetry`) |
| `useSystemHealth` | `/api/system-health` | `GET /api/system/health` (see BFF) |

**Protected example:** `GET /api/telemetry/dashboard` and `GET /api/telemetry/parity-dashboard` use `Depends(RoleChecker([SUPER_ADMIN, MANAGER, REVIEWER]))` — valid Bearer → 200 (or 5xx if data layer fails); missing/invalid token → **401**.

### Streamline status

- **Route:** `GET /api/integrations/streamline/status` — `backend/api/integrations.py`
- **Finding:** **No `Depends(get_current_user)`** — callable without staff JWT. Acceptable only if every path to `:8100` is already zero-trust (LAN + tunnel); **hardening:** require `RoleChecker` for any integration that leaks operational detail.

---

## PHASE 3 — BFF (Next.js Command Center)

### Login

- **File:** `apps/command-center/src/app/api/auth/login/route.ts`
- **Direct FGP path:** `POST` to `buildBackendUrl("/api/auth/login")` (i.e. `FGP_BACKEND_URL`).
- **Cookie:** On success, sets **`fortress_session`** = `access_token`, **HttpOnly**, **Secure** when `x-forwarded-proto: https` or HTTPS URL, **SameSite=Lax**, `path=/`, `maxAge=86400`.

### Gateway / SSO

- Optional Path 1: Command Center gateway → SSO exchange; Path 2 always tries direct FGP with normalized email.

### CSRF / `allowedOrigins`

- **File:** `apps/command-center/next.config.ts` — `experimental.serverActions.allowedOrigins` includes `staffHostsForServerActions()` from `src/lib/domain-boundaries.ts` → **`crog-ai.com`**, **`www.crog-ai.com`**, plus `NEXT_PUBLIC_STAFF_HOSTS` extras.
- **Login form** uses `fetch("/api/auth/login")` (same-origin), not Server Actions — origin allowlist primarily affects Server Actions elsewhere.

### Session bridge for `/api/auth/me`

- **File:** `apps/command-center/src/app/api/auth/me/route.ts`
- If browser has **only** `fortress_session` (no `Authorization`), BFF forwards `Authorization: Bearer <cookie>` to FastAPI and merges `access_token` into JSON so the client can refill `fgp_token` in `fetchMe`.

---

## PHASE 4 — Hydration, proxy, hooks

### `proxy.ts` (Next 16)

- **File:** `apps/command-center/src/proxy.ts` — currently **no-op** (`NextResponse.next()`). Session enforcement is **not** at the edge file; it lives in **`AuthGuard`** + **`CommandCenterRoot`** + client **`api`** layer.

### `auth-guard.tsx`

- Calls `bootstrapSession()` → `fetchMe()` → `GET /api/auth/me` with `credentials: "include"` so **HttpOnly cookie** participates.
- On failure: clears token + `fgp_user`, redirects to `/login` — **no infinite loop** if `/login` is public.

### `api.ts`

- Sends **`Authorization: Bearer`** from `localStorage` `fgp_token` when present.
- **`credentials: "include"`** so `fortress_session` is sent on same-origin `/api/*` calls.
- BFF catch-all **`[...path]/route.ts`** resolves token: **Bearer first**, else **`fortress_session`**, else `x-fgp-token`.

### Dashboard hydration bug (fixed)

- `command/page.tsx` used `healthData ? Object.values(healthData.nodes) : []` — when `nodes` was **null**, `Object.values(null)` threw. **Fix:** `healthData?.nodes ? Object.values(healthData.nodes) : []`.

---

## Hardening backlog (post-audit)

| Item | Status |
|------|--------|
| 1. Integration auth (`/api/integrations/*` staff RBAC) | **Done** — all Streamline / owner / housekeeping / feedback / guest / reservation routes require `RoleChecker`. |
| 2. Cookie ↔ JWT TTL | **Done** — `LoginResponse.expires_in` from `jwt_expiration_hours`; BFF `fortress_session` `maxAge` follows; `POST /api/auth/logout` already clears cookie. |
| 3. Login rate limit | **Done** — in-process sliding window on `POST /api/auth/login` (per client IP). |
| 4. Operational smoke | **Script:** `scripts/fortress_auth_pipeline_smoke.sh` (needs `FORTRESS_SMOKE_EMAIL` / `FORTRESS_SMOKE_PASSWORD`). Plus `./scripts/verify_captain_cloudflared.sh`. |
| 5. Standalone static sync | **Done** in `npm run build` for Command Center. |
| 6. Secrets hygiene | Operational discipline (rotate break-glass passwords). |
| 7. JWT key rotation | Document in ops; `kid` mismatch rejected in `decode_token`. |
| 8. `SystemHealthResponse.nodes` | **Done** — optional / nullable in TS; dashboard guards `Object.values`. |
| 9. Staff glass ↔ BFF | **Done** — `NEXT_PUBLIC_API_URL` empty in `fortress-frontend.service`; client warns if set on staff host. |

---

## Quick reference — prove the pipeline

```bash
# Phase 1
cd fortress-guest-platform && python backend/scripts/audit_staff_user.py --email 'cabin.rentals.of.georgia@gmail.com'

# Phase 2 (after login token in TOKEN)
curl -sS -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8100/api/auth/me
curl -sS -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8100/api/telemetry/parity-dashboard

# Tunnel / static
cd /home/admin/Fortress-Prime && ./scripts/verify_captain_cloudflared.sh
```

---

*This audit was reconciled to the repository state at authoring time; re-run scripts and curls after migrations or ingress changes.*
