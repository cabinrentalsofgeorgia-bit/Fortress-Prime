# Fortress Prime Overnight Audit

## Scope

End-to-end audit pass across:

- Fortress Legal
- CROG VRS / The Glass
- Sovereign infrastructure bindings

Primary verification commands executed:

- `.uv-venv/bin/python -m pytest backend/tests/test_admin_insights_api.py backend/tests/test_vrs_api.py backend/tests/test_fast_quote_and_hold.py -q`
- `.uv-venv/bin/python -m pytest backend/tests/test_route_authorization.py -q`
- `npx tsc --noEmit`
- `bash -n deploy/systemd/run-fortress-backend.sh deploy/systemd/run-fortress-dashboard.sh deploy/systemd/run-fortress-event-consumer.sh deploy/systemd/run-fortress-channex-egress.sh`

## Division 1: Fortress Legal

### Findings

- `backend/api/legal_cases.py` had no role dependency at all. Owners could hit legal list/detail endpoints, and reviewer/operator denial tests were failing because the router fell through into live handlers instead of failing closed.
- `backend/api/legal_graph.py` and `backend/api/legal_cases.py` both define:
  - `POST /api/internal/legal/cases/{slug}/graph/refresh`
  - `GET /api/internal/legal/cases/{slug}/graph/snapshot`
- `backend/api/legal_discovery.py` and `backend/api/legal_cases.py` both define:
  - `POST /api/internal/legal/cases/{slug}/discovery/draft-pack`
- `backend/api/legal_cases.py` still exposes `GET /cases/{slug}/sanctions/drafts`, while the dedicated sanctions router is built around the v2 sanctions paths and tables.

### Fixes Applied

- Added router-level auth enforcement to `backend/api/legal_cases.py` using `require_manager_or_admin`.
- Re-ran authorization coverage:
  - `backend/tests/test_route_authorization.py -q` -> `64 passed`

### Remaining Legal Risks

- Route ownership has been resolved: internal legal and adjudication endpoints now live under `/api/internal/legal` and are reserved for the CROG AI Command Center surface.
- Functional overlap still exists between some legal modules, so future cleanup should consolidate duplicate handlers behind the now-explicit internal namespace rather than reintroducing the retired public legal namespace.

## Division 2: CROG VRS, The Glass, Stripe, AI Matrix, OTA Egress

### Findings

- The frontend VRS command center calls:
  - `GET /api/vrs/queue`
  - `GET /api/vrs/adjudications/{id}`
  - `POST /api/vrs/adjudications/{id}/override-dispatch`
- Those handlers existed in `backend/api/vrs.py`, but the production app only mounted `backend/api/vrs_operations.py`, which exposed `GET /api/vrs/operations/ping`.
- The admin dashboard calls `GET /api/admin/insights`, but `backend/main.py` imported `backend.api.admin_insights` while the module was missing from disk.
- NemoClaw did not support the `guest_concierge` intent requested in the mission directive and only emitted `result_payload.draft_body`, not a `draft_email` key.
- Direct-booking Stripe finalization converted holds into reservations but did not emit `reservation.confirmed`, leaving the event-driven ingress chain incomplete.
- There is no `AiInsightWidget.tsx` in the current frontend. The live consumer is `useAdminInsights()` from the admin dashboard page.
- `backend/workers/channex_egress.py` correctly subscribes to `inventory.availability.changed`, uses `enable_auto_commit=False`, and only commits offsets after successful push or deterministic skip.
- `backend/services/channex_calendar_export.py` does build the 18-month window (`548` days) used by Channex ARI payload generation.

### Fixes Applied

- Mounted the real VRS command center router in `backend/main.py`.
- Recreated `backend/api/admin_insights.py` with the derived snapshot contract expected by the frontend and existing test suite.
- Added `guest_concierge` compatibility in `backend/orchestration/nemoclaw_serve.py` and emitted:
  - `result_payload.draft_body`
  - `result_payload.draft_email`
  - `result_payload.schema = fortress.guest_concierge.draft_email.v1`
- Added `reservation.confirmed` event emission in `backend/services/booking_hold_service.py` for both:
  - client-side hold confirmation
  - Stripe webhook hold conversion
- Hardened `backend/api/admin.py` prime snapshot so Channex attention lookup degrades safely instead of failing the whole snapshot when the audit model/service wiring is unavailable under test stubs.

### Verification

- `backend/tests/test_admin_insights_api.py backend/tests/test_vrs_api.py backend/tests/test_fast_quote_and_hold.py -q` -> `27 passed`
- `backend/tests/test_route_authorization.py -q` -> `64 passed`

## Division 3: Sovereign Infrastructure

### Findings

- `frontend-next/package.json` does not define a `type-check` script, so `npm run type-check` fails by script lookup, not by code correctness.
- A real frontend TypeScript failure existed in `src/app/(dashboard)/vrs/hunter/page.tsx`:
  - `AlertDialog*` components were imported from `@/components/ui/card` instead of `@/components/ui/alert-dialog`
  - `onOpenChange` had an implicit `any`
- There was no `fortress-channex-egress.service` even though the Channex egress worker exists and is part of the audited event flow.
- Existing systemd service files lacked explicit `EnvironmentFile=` references.
- `fortress-guest-platform` had `.env.dgx.example` but no base `.env.example`.
- Example env coverage is still incomplete relative to `backend/core/config.py`:
  - `.env.example`: `12` aliased config vars documented, `82` aliased vars still undocumented
  - `.env.dgx.example`: `12` aliased config vars documented, `82` aliased vars still undocumented
- Retired root `docker-compose.yml` was inconsistent with the declared sovereign stack before it was renamed to `docker-compose.local.yml` for local-only use:
  - uses `postgres:15-alpine`
  - uses legacy DB name/user `fortress_db` / `miner_bot`
  - contains hardcoded credentials

### Fixes Applied

- Fixed `src/app/(dashboard)/vrs/hunter/page.tsx` imports and typing.
- Added `fortress-guest-platform/.env.example` as the missing baseline env contract.
- Added explicit `EnvironmentFile=` lines to:
  - `deploy/systemd/fortress-backend.service`
  - `deploy/systemd/fortress-dashboard.service`
  - `deploy/systemd/fortress-event-consumer.service`
- Added Channex egress systemd artifacts:
  - `deploy/systemd/fortress-channex-egress.service`
  - `deploy/systemd/run-fortress-channex-egress.sh`
- Updated `deploy/systemd/install_fortress_services.sh` to install, enable, restart, and print status for the new Channex egress unit.

### Verification

- `npx tsc --noEmit` -> passed
- `bash -n` on all systemd run scripts -> passed

## Manual Intervention / Still Critical

- `backend/main.py` route ownership decision has been made: the legal/adjudication surface is isolated to `/api/internal/legal`, and stale legacy legal-route references should be retired rather than preserved.
- The former root `docker-compose.yml`, now retired in favor of `docker-compose.local.yml` for local-only use, is a legacy/insecure artifact and does not match the current Postgres 16 + fortress role model. Production deployment must continue to rely on systemd units and bare-metal services.
- Env documentation remains partial. Creating `.env.example` fixed the missing base template, but the current config surface is much larger than what either example file documents.
- The admin insights replacement contract note string is preserved to satisfy the existing regression contract, but the repository now also contains an `ai_insights` migration, so that note no longer reflects full repository reality.
