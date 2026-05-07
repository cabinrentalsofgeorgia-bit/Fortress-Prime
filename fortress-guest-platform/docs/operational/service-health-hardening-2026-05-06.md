# Fortress Legal Service Health Hardening - 2026-05-06

## Findings

- Canonical production uses `crog-ai-frontend.service`, `fortress-backend.service`, and `cloudflared.service`.
- Services were active during operational verification.
- Deployment source remains historically split between root systemd tooling and guest-platform systemd tooling.
- Several restart scripts restart services bluntly without readiness gates.
- A stale legacy systemd drop-in references a legacy path and should be removed or profile-gated in a later dedicated infrastructure cleanup.

## Implemented Hardening

- Added request ID propagation on backend request state.
- Added deployment fingerprint payloads to backend health surfaces.
- Added structured BFF operational logs without bearer-token prefixes.
- Added deployment verification script covering route smoke, unauthenticated guards, systemd service activity, and authenticated checker evidence.
- Reduced non-legal page-load error noise by deferring command-palette operational data queries until the palette is opened.
- Disabled sidebar route prefetch to avoid stale-route diagnostics while reviewing legal pages.

## Production Verification

After deployment, the authenticated checker reported no `httpErrors`, no request failures, and no console errors. `verify-production-deployment.mjs` confirmed route reachability, unauthenticated guard behavior, service activity, and governance invariants.

## Deferred Items

- Do not alter systemd units in this phase without a separate deployment window.
- Do not remove stale legacy drop-ins until host profile ownership is confirmed.
- Do not change Cloudflare tunnel routing in this phase; document port drift and verify before mutation.

## Rollback

All changes are source-level and git-revertable. No DB, schema, RLS, vector, ingestion, document, signoff, or external-submission state was changed.
