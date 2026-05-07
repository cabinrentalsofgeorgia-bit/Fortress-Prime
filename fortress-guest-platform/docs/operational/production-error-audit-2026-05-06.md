# Fortress Legal Production Error Audit - 2026-05-06

## Standing State

- Production domain: `https://crog-ai.com`
- Matter: Fortress Legal Production Review
- Matter slug: `fortress-legal-production-review`
- Starting production status: `PRODUCTION_FEATURE_ALIGNMENT_COMPLETE_PENDING_REVIEW`
- Target phase: `PRODUCTION_OPERATIONAL_HARDENING_IN_PROGRESS`
- Counsel status: `COUNSEL_SIGNOFF_PENDING`
- External submission authority: `NOT_AUTHORIZED`
- Final legal conclusions: `NOT_CREATED`
- Legal advice status: `NOT FINAL LEGAL ADVICE`
- Schema/RLS/policy mutation: `NOT_PERFORMED`

## Hard-Stop Evaluation

- Auth state: authenticated checker available; auth state not printed or committed.
- Locked/restricted content: not inspected; metadata-only boundary preserved.
- Confidential legal text: not printed in evidence.
- Raw document upload/ingest/vector creation: not performed.
- Schema/RLS/policy mutation: not performed.
- Counsel signoff/final legal conclusion/external submission: not performed.
- Result: no hard stop.

## Observed Errors

Evidence:

- `fortress-guest-platform/docs/operational/evidence/2026-05-06-operational-hardening/checker-after-hardening.json`
- `fortress-guest-platform/docs/operational/evidence/2026-05-06-operational-hardening/deployment-verification.json`

The authenticated checker still confirms:

- `ok: true`
- `featureAlignmentOk: true`
- Draft Work Product visible
- Autonomous Learning visible
- `COUNSEL_SIGNOFF_PENDING` visible
- no final legal advice label
- no external submission authority label

The remaining production errors are now classified:

| Status | Route | Classification | Severity | Root Cause | Action |
| --- | --- | --- | --- | --- | --- |
| 404 | `/vrs/leads?_rsc=...` | `missing_route` | Medium | Navigation exposed a VRS leads index route, but the source tree only had the detail route `/vrs/leads/[id]`. Sidebar/Next prefetch surfaced the missing index while Gary was reviewing the legal matter. | Add a safe index redirect to `/vrs/hunter` and disable sidebar prefetch for production navigation links; verify after deployment. |
| 500 | `/api/properties/?limit=1000` | `backend_or_bff_failure` | Medium | Global command palette loads property data on every dashboard page, including the Fortress Legal matter page. The legal workflow does not require the property roster at page load. | Defer command-palette property/guest/work-order queries until the palette is opened; keep real property route behavior unchanged. |

Additional request failures were aborted RSC prefetches for unrelated operations pages. They are not legal workflow failures, but they add noise to production diagnostics.

## Root Cause Classes

- Route prefetch noise: non-current operations routes are prefetched from legal review context.
- Global data-fetch noise: command palette eagerly fetches operational datasets on every authenticated page.
- Observability gap: prior checker output reported only generic console errors, not the failing URLs or classifications.
- Deployment repeatability gap: production verification lacked one command that tied public routes, auth guards, service health, and authenticated UI evidence together.

## Fix Priority

1. Record exact failing URL/status classifications in the checker.
2. Remove auth token prefixes from BFF operational logs.
3. Defer non-legal global data fetches until user action.
4. Disable sidebar route prefetch to reduce stale route and missing artifact noise.
5. Add deployment verification script with route, guard, service, and checker evidence.
6. Document deployment and rollback gates before any broader runtime restart policy changes.

## Post-Deployment Verification

Evidence:

- `fortress-guest-platform/docs/operational/evidence/2026-05-06-operational-hardening/checker-after-deploy.json`
- `fortress-guest-platform/docs/operational/evidence/2026-05-06-operational-hardening/deployment-verification-after-deploy.json`

Post-deploy authenticated checker result:

- `ok: true`
- `featureAlignmentOk: true`
- `draftWorkProduct: true`
- `learning: true`
- `httpErrors: []`
- `errorSummary: {}`

Deployment verifier result:

- `/` returned 200.
- matter route returned 200.
- unauthenticated Draft Work Product API returned 401.
- unauthenticated Autonomous Learning API returned 401.
- frontend, backend, and tunnel services were active.
- no signoff, final legal conclusion, external submission authority, schema/RLS/policy mutation, document upload, ingest, or vector creation occurred.

## Rollback

Rollback is git-revertable:

- revert the checker/deployment-verification commit to restore previous checker behavior;
- revert the UI operational-noise commit to restore eager command palette loading and sidebar prefetch;
- no database, schema, RLS, policy, vector, document, or signoff state is changed.
