# Fortress Legal Auth Boundaries

Status: auth/database certification snapshot on 2026-05-07.

## Authentication Model

Repository evidence shows the command-center auth model uses:

- Next.js BFF route handlers under `apps/command-center/src/app/api`.
- `fortress_session` as the staff session cookie.
- `fgp_owner_token` as the owner-scoped cookie for owner portal paths.
- `fgp_token` in browser localStorage as the client-side bearer token cache.
- Bearer-token bridging where route handlers synthesize or forward authorization to backend services.
- Backend auth routes under `/api/auth/*`.
- Role/capability helpers such as `canManageLegalOps` for frontend gating, with backend routes expected to enforce authorization server-side.
- FastAPI staff JWTs are RS256 tokens with a configured key id.
- Staff passwords are bcrypt-hashed in the sovereign `staff_users` table.

Session cookie names observed:

- `fortress_session`
- `fgp_owner_token`

Client token cache observed:

- `fgp_token`
- `fgp_user`

## Host Boundary

Command Center staff host detection includes:

- `crog-ai.com`
- `www.crog-ai.com`

`apps/command-center/next.config.ts` uses `staffHostsForServerActions()` for server action allowed origins.

## BFF Boundary

The command-center BFF is the boundary between browser session state and backend auth:

- Browser authenticates through `/api/auth/login`, `/api/auth/sso`, `/api/auth/me`, and `/api/auth/logout`.
- The catch-all `/api/[...path]` route proxies backend requests.
- `/api/auth/login` can attempt gateway-to-SSO exchange and falls back to direct FGP login.
- `/api/auth/me` bridges the HttpOnly `fortress_session` cookie into a backend `Authorization: Bearer` probe when localStorage is empty.
- `/api/auth/logout` clears both `fortress_session` and `fgp_owner_token`.
- The generic BFF proxy extracts bearer auth, `fortress_session`, `fgp_owner_token`, or `x-fgp-token`, then forwards auth to the selected upstream.
- Command Center upstream paths that require cookie auth receive synthesized `fortress_session` cookie state from the bearer token.
- FGP backend upstream paths receive `Authorization: Bearer`.
- Internal FGP requests can be signed with `X-Fortress-Ingress` and `X-Fortress-Tunnel-Signature` when configured.
- Cookie and authorization bridging must never log raw cookies, tokens, or passwords.

Known upstream classes:

- Command Center console upstream: default `http://127.0.0.1:9800`.
- CROG-AI backend upstream: default `http://127.0.0.1:8026`.
- FGP backend upstream: default `http://127.0.0.1:8000`, or configured via `FGP_BACKEND_URL` / `FORTRESS_BACKEND_BASE_URL`.

The staff command-center browser should use same-origin `/api/*` BFF calls. Direct `NEXT_PUBLIC_API_URL` use on staff hosts is warned against in source because it bypasses the sovereign glass BFF model.

## Backend Auth Boundary

Backend auth is implemented in the FastAPI backend:

- Staff login endpoint: `/api/auth/login`.
- Staff profile endpoint: `/api/auth/me`.
- Staff registration and user administration require admin-level dependencies.
- Token verification uses RS256 JWT validation and `kid` checking.
- Staff user resolution reads `staff_users` from the configured sovereign Postgres runtime.
- Inactive staff users are rejected.
- Role guards include admin, manager/admin, operator/reviewer/manager/admin, and route-specific `RoleChecker` dependencies.

Staff roles observed in source:

- `super_admin`
- `admin`
- `manager`
- `reviewer`
- `operator`
- `staff`
- `maintenance`

Frontend legal mutation controls use `canManageLegalOps`, currently manager/admin/super-admin gated. Treat frontend role gates as UI hardening only; backend authorization must remain authoritative.

## Auth State File

Known authenticated checker state:

- `.auth/crog-ai-gary.json`

Rules:

- Do not print it.
- Do not copy it.
- Do not commit it.
- Do not weaken `.auth` ignores.
- Do not change auth behavior while doing topology or docs work.

## Risk Areas

- BFF proxy logs currently include redacted token prefixes for some paths. Do not expand these logs, and prefer boolean auth-present logging for future hardening.
- Source contains multiple auth bridges: cookie, localStorage bearer token, owner token, gateway SSO exchange, and internal ingress token. Changes must be made narrowly and tested against all paths.
- Some public path allowlists include broad non-legal surfaces. Do not alter public auth boundaries during Fortress Legal-only stabilization.
- Frontend role gates are not sufficient authorization; backend route dependencies must be verified before any new legal mutation path is enabled.
- `.auth` checker state exists outside repo scope and must remain uninspected unless an operator authorizes a separate authenticated smoke phase.

## Required Redaction

All logs and docs must redact:

- cookies,
- access tokens,
- auth headers,
- passwords,
- Supabase keys,
- database URLs,
- private keys,
- service-role keys.

## Future Agent Rule

If an auth route, cookie name, role mapping, SSO path, host boundary, or checker auth-state location changes, update this file in the same PR.
