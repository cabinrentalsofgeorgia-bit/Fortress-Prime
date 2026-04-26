# Shared: Auth and Secrets

Last updated: 2026-04-26

## Technical overview

Three trust boundaries:

1. **Public ingress** — Cloudflare Tunnels in front of FastAPI. UFW denies all public inbound; tunnels are the only path. Public storefront uses unauthenticated routes; private APIs require host-header check + JWT.
2. **Staff / AI agent ingress (command-center)** — JWT RS256 auth between Next.js command-center and FastAPI. Tokens issued by the auth service (`backend/api/auth/*`), signed by `JWT_RSA_PRIVATE_KEY`. Header check `Host: crog-ai.com` enforces the internal-route boundary; mismatched `Host` returns HTTP 403 (the "Ingress Boundary Violation" error you've seen during smoke tests).
3. **Machine-to-machine ingress (Swarm / NIM-brain / Ollama callers)** — `X-Swarm-Token` constant-time validation per `backend/core/security_swarm.py::verify_swarm_token`.

## Secret storage

- **`pass(1)` (gpg-agent backed)** for IMAP, integration credentials, sovereign keys. Pass tree under `fortress/`:
  - `fortress/mailboxes/<alias>` for IMAP
  - other slugs for Stripe, Twilio, Channex, Streamline, Plaid, etc.
- **systemd `EnvironmentFile=`** drop-ins load secrets at service start via `fortress-load-secrets` bash loader (`deploy/secrets/install.sh` per session 2026-04-22 work)
- **Local `.env`** at `/home/admin/Fortress-Prime/fortress-guest-platform/.env` for development + script-time fallback. Loaded by `python-dotenv` in scripts that need it (e.g. PR D and PR I scripts call `_ensure_env_loaded()`).

## JWT key material

- `JWT_RSA_PRIVATE_KEY` / `JWT_RSA_PUBLIC_KEY` env vars (PEM-formatted)
- RS256 algorithm
- Public key embedded in command-center build for client-side verification
- `AUDIT_LOG_SIGNING_KEY` separately for openshell audit logs

## Cloudflare Tunnels

- Storefront tunnel: routes `cabin-rentals-of-georgia.com` → FastAPI
- Command-center tunnel: routes `crog-ai.com` → FastAPI (different host header)
- Tunnel config in `~/.cloudflared/` (operator host)
- Captain mailbox watcher uses `CAPTAIN_CLOUDFLARED_RUNBOOK.md` for connectivity

## Consumers

- Every FastAPI route that requires authentication (most routes under `/api/internal/*`)
- Every M2M caller (Swarm grading, NIM brain ingestion, etc.) using `X-Swarm-Token`
- Captain IMAP poller (uses `pass show` for credentials)
- All systemd services pulling secrets via `EnvironmentFile`

## Contract / API surface

- `Authorization: Bearer <jwt>` for staff routes
- `Host: crog-ai.com` required for `/api/internal/*` (without it → HTTP 403)
- `X-Swarm-Token` required for M2M routes (without it → HTTP 401/403 fail-closed)
- `audit_log_signing_key` signs each row in `openshell_audit_logs` (immutable trail)

## Where to read the code

- `backend/api/auth/*` — JWT issuance, verification, refresh
- `backend/core/security_swarm.py` — `verify_swarm_token` constant-time check
- `backend/middleware/ingress_boundary.py` (or equivalent) — host-header check
- `deploy/secrets/install.sh` — secrets loader
- `secrets.manifest` — declared secret registry
- `~/.cloudflared/config.yml` — tunnel routes (operator host, not in repo)
- CONSTITUTION.md Article I.III — security/networking constraints

## Operator-managed PAT

The GitHub Personal Access Token used by Claude Code on `spark-node-2` is documented as a known limitation in Issue #221 — currently create-only for issues + PRs; no `issues:write` or `pull-requests:write` scope. Several manual cleanup tasks accumulate per session (close duplicates, edit PR bodies). Upgrade path documented in #221.

## Cross-references

- CONSTITUTION.md Article I.III
- Issue #221 — PAT scope upgrade
- [`captain-email-intake.md`](captain-email-intake.md) — IMAP credential flow
- [`infrastructure.md`](infrastructure.md) — Cloudflare Tunnel topology

Last updated: 2026-04-26
