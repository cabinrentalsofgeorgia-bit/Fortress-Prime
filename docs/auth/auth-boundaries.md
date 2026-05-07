# Fortress Legal Auth Boundaries

Status: read-only discovery snapshot on 2026-05-07.

## Authentication Model

Repository evidence shows the command-center auth model uses:

- Next.js BFF route handlers under `apps/command-center/src/app/api`.
- `fortress_session` as the staff session cookie.
- Bearer-token bridging where route handlers synthesize or forward authorization to backend services.
- Backend auth routes under `/api/auth/*`.
- Role/capability helpers such as `canManageLegalOps` for frontend gating, with backend routes expected to enforce authorization server-side.

## Host Boundary

Command Center staff host detection includes:

- `crog-ai.com`
- `www.crog-ai.com`

`apps/command-center/next.config.ts` uses `staffHostsForServerActions()` for server action allowed origins.

## BFF Boundary

The command-center BFF is the boundary between browser session state and backend auth:

- Browser authenticates through `/api/auth/login`, `/api/auth/sso`, `/api/auth/me`, and `/api/auth/logout`.
- The catch-all `/api/[...path]` route proxies backend requests.
- Cookie and authorization bridging must never log raw cookies, tokens, or passwords.

## Auth State File

Known authenticated checker state:

- `.auth/crog-ai-gary.json`

Rules:

- Do not print it.
- Do not copy it.
- Do not commit it.
- Do not weaken `.auth` ignores.
- Do not change auth behavior while doing topology or docs work.

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
