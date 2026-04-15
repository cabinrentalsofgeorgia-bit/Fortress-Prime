# API Surface Auth Classification

This document classifies the currently mounted Fortress Guest Platform API
surfaces by intended access model after the explicit hardening pass completed on
Mar 30, 2026.

Use this alongside:

- `docs/permission-matrix.md`
- `docs/privileged-surface-checklist.md`

## Purpose

This file exists to answer three questions quickly:

1. Which routes are intentionally public?
2. Which routes are machine-to-machine only?
3. Which routes must always enforce explicit staff-role dependencies?

It is a runtime-oriented complement to the frontend/backend permission matrix.

## Classification Buckets

### 1. Public Guest-Facing

These routes are intentionally reachable without staff JWTs. They still may use
opaque reservation/session tokens, consent gates, or business validation.

- `/health`
- `/api/auth/login`
- `/api/auth/register`
- `/api/auth/owner/request-magic-link`
- `/api/auth/owner/verify-magic-link`
- `/api/auth/owner/logout`
- `/api/guest-portal/*`
- `/api/portal/*`
- `/api/direct-booking/availability`
- `/api/direct-booking/quote`
- `/api/direct-booking/signed-quote`
- `/api/direct-booking/properties`
- `/api/direct-booking/property/*`
- `/api/direct-booking/fleet/*`
- `/api/direct-booking/book`
- `/api/direct-booking/confirm-hold`
- `/api/direct-booking/config`
- `/api/checkout/*`
- `/api/storefront/intent/*`
- `/api/storefront/concierge/*`
- `/api/agreements/public/*`
- `/api/guestbook/*`

Notes:

- `portal.py` and `guest_portal_api.py` are capability-link systems. The
  reservation/confirmation code is the access token.
- `storefront_intent.py` and `storefront_concierge.py` are intentionally public
  but are expected to remain PII-safe and consent-gated.

### 2. Provider-Signed Webhook Ingress

These routes are intentionally public at the middleware layer, but must enforce
provider-specific signature validation in-route.

- `/api/webhooks/stripe`
- `/api/webhooks/stripe-connect`
- `/api/webhooks/stripe-disputes`
- `/api/direct-booking/webhooks/stripe`
- `/api/webhooks/sms/incoming`
- `/api/webhooks/sms/incoming/concierge`
- `/api/webhooks/sms/status`
- `/api/reservations` webhook ingress
- `/api/webhooks/channex`

Notes:

- `stripe_webhooks.py` and `stripe_connect_webhooks.py` validate Stripe
  signatures.
- `webhooks.py` now validates Twilio signatures on the main inbound SMS path,
  concierge SMS path, and SMS status path.
- `webhooks.py` now fails closed when `twilio_auth_token` is missing.
- `webhooks_channex.py` now exists explicitly, validates
  `x-channex-signature`, returns `503` when `CHANNEX_WEBHOOK_SECRET` is not
  configured, and only acknowledges valid signed payloads.

### 3. Machine-to-Machine Token Protected

These routes are expected to be called by internal systems or swarm workers and
should use explicit service-token auth, not staff-role auth.

- `/api/email-bridge/ingest`
- `/api/swarm/financial/*`
- `paperclip_bridge` swarm-tool routes
- `seo_remaps` / `seo` swarm-token routes where applicable
- `rule_engine` emitter routes protected by automation emitter token

Notes:

- `email_bridge.py` now requires `X-Swarm-Token` explicitly.
- `backend/core/security_swarm.py` is the shared helper for `X-Swarm-Token`
  authentication.
- `email_bridge` is allowlisted in `public_api_paths.py` only so the global JWT
  middleware does not block machine callers before route-level swarm auth runs.

### 4. Staff-Role Protected

These routes are expected to enforce explicit backend authorization
dependencies, not rely only on the global JWT middleware.

Representative hardened groups include:

- Admin:
  - `/api/admin/*`
  - `/api/admin/contracts/*`
  - `/api/admin/disputes/*`
- Hunter:
  - `/api/vrs/hunter/*`
  - `/api/hunter/*`
- Owner-internal protection:
  - `/api/owner/*` owner-scoped via `get_current_owner` plus property/subject checks
- Core data and ops:
  - `/api/properties/*`
  - `/api/guests/*`
  - `/api/messages/*`
  - `/api/reservations/*`
  - `/api/work-orders/*`
  - `/api/leads/*`
  - `/api/review-queue/*`
  - `/api/copilot-queue/*`
  - `/api/tenants/*`
  - `/api/templates/*`
  - `/api/utilities/*`
  - `/api/analytics/*`
  - `/api/housekeeping/*`
  - `/api/search/*`
  - `/api/iot/*`
  - `/api/channels/*` operational routes
  - `/api/channel-manager/*`
  - `/api/agent/*`
  - `/api/damage-claims/*`
  - `/api/payments/*`
  - `/api/quotes/*`
  - `/api/agreements/*` non-public routes
- AI / intelligence:
  - `/api/ai/*`
  - `/api/intelligence/*`
  - `/api/intelligence/feed/*`
  - `/api/rules/*`
- Legal:
  - `/api/internal/legal/*` across the hardened legal modules:
    `legal_cases`, `legal_council`, `legal_hold`, `legal_tactical`,
    `legal_graph`, `legal_discovery`, `legal_docgen`, `legal_strategy`,
    `legal_counsel_dispatch`, `legal_sanctions`, `legal_deposition`,
    `legal_agent`, `ediscovery`
- Owner Statements (Phase A-F — added 2026-04-15):
  - `/api/admin/payouts/statements/*` — 9 endpoints — `require_manager_or_admin` (router-level in `admin_statements_workflow.py`)
  - `/api/admin/payouts/charges/*` — 5 endpoints — `require_manager_or_admin` (router-level in `admin_charges.py`)
  - `/api/v1/admin/statements/{owner_id}` — 1 endpoint — **JWT-only, no role check** — known gap, see Residual Ambiguities §5

## Residual Ambiguities / Follow-Ups

### 1. Channex Webhook Is Now Explicit but Still No-Op

File:

- `backend/api/webhooks_channex.py`

Current behavior:

- validates `x-channex-signature` as HMAC-SHA256
- returns `503` if `CHANNEX_WEBHOOK_SECRET` is not configured
- returns `403` if the signature is invalid
- acknowledges valid payloads in observability-only `stub_noop` mode

Recommended follow-up:

- implement the downstream Channex event contract behind the signed ingress
  instead of leaving it in explicit no-op mode

### 2. Twilio Signature Enforcement Now Fails Closed

File:

- `backend/api/webhooks.py`

Current behavior:

- if `twilio_auth_token` is unset, `_validate_twilio_signature(...)` now returns
  `False`

Recommended follow-up:

- decide whether production should escalate missing Twilio signature config from
  request-level rejection to startup-time misconfiguration

### 3. Public Allowlist Hygiene

Potential stale or low-confidence allowlist entries should be reviewed regularly.

Examples:

- any future `/api/internal/*` convenience endpoints
- any future `/api/chat/*` routes

Recommended follow-up:

- confirm whether each allowlisted path still has a real mounted route
- remove dead allowlist entries so future handlers do not accidentally inherit
  public exposure

### 4. Copilot Queue Was Previously Public

Files:

- `backend/api/copilot_queue.py`
- `backend/core/public_api_paths.py`

Status:

- fixed in this pass

Why documented:

- this is a reminder that allowlist drift can quietly create unauthenticated
  HITL surfaces

### 5. Owner Statement Computation Endpoint — JWT-Only (Phase A-F gap, added 2026-04-15)

File:

- `backend/api/admin_statements.py`

Current behavior:

- `router = APIRouter()` with no `dependencies` — no role check at router or route level
- The endpoint `GET /api/v1/admin/statements/{owner_id}` is protected only by the
  global JWT middleware (any valid staff token, any role)
- All other statement endpoints in `admin_statements_workflow.py` and
  `admin_charges.py` are correctly gated by `require_manager_or_admin`

Recommended follow-up:

- Add `dependencies=[Depends(require_manager_or_admin)]` to the `APIRouter()` in
  `backend/api/admin_statements.py`
- Add a focused authorization test to `backend/tests/test_route_authorization.py`

Until fixed, any staff role (including `staff`, `reviewer`, `operator`) can invoke
the what-if statement computation endpoint.

## Operational Rules Going Forward

When adding a new route:

1. Decide the surface type first:
   public guest-facing, provider-signed webhook, M2M token, or staff-role
   protected.
2. If the route is privileged, add explicit dependencies in the route or router.
3. If the route is M2M, prefer a dedicated token dependency over staff JWTs.
4. If the route is public, make the allowlist entry explicit and document why.
5. Add a focused authorization test in `backend/tests/test_route_authorization.py`
   or a dedicated auth test file.

## Current Summary

After the Mar 30, 2026 hardening pass:

- the major owner-to-staff/global exposure paths that were identified during the
  live E2E sweep have been closed
- owner sessions were live-tested against a wide set of staff/global routes and
  now receive `401` or `403`
- `email_bridge` now has explicit machine-token auth and a verified positive
  ingest path
- `webhooks_channex` is no longer a ghost mount; it has an explicit signed,
  fail-closed implementation
- Twilio webhook routes now fail closed if signature configuration is missing

The remaining work is mostly:

- implementing the actual Channex downstream event contract
- reviewing any future allowlist additions for drift
- future regression prevention
