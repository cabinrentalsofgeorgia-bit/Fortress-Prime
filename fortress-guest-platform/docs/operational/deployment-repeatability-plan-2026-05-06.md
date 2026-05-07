# Fortress Legal Deployment Repeatability Plan - 2026-05-06

## Deployment Gate

Before deployment:

1. Confirm branch and commit.
2. Confirm no `.auth/` files are staged.
3. Confirm no secret-shaped values are staged.
4. Run frontend typecheck/build and backend compile checks.
5. Run authenticated checker from a governed local auth state.
6. Run deployment verifier.
7. Record rollback artifact paths before restart.

## Restart Order

1. Build frontend artifact.
2. Stage frontend artifact rollback copy.
3. Update frontend artifact.
4. Stage backend source rollback copy for changed backend files.
5. Update backend runtime files.
6. Restart backend if backend runtime changed.
7. Restart frontend if frontend runtime changed.
8. Verify services with `systemctl is-active` only; do not print journal logs containing request/auth context.
9. Run public route smoke.
10. Run unauthenticated guard smoke.
11. Run authenticated checker.

## Verification

Use:

```bash
CROG_AUTH_STATE=/path/to/.auth/crog-ai-gary.json node scripts/verification/verify-production-deployment.mjs
```

Expected:

- `/` returns 200.
- matter route returns 200.
- unauthenticated draft/autonomous APIs return 401/403.
- frontend/backend/tunnel services are active.
- authenticated checker returns `ok: true`.
- `COUNSEL_SIGNOFF_PENDING` remains visible.
- external submission authority remains `NOT_AUTHORIZED`.

## Rollback

Rollback order:

1. Restore backend changed files from rollback copy if backend changed.
2. Restore frontend `.next` artifact from rollback copy if frontend changed.
3. Restart affected services only.
4. Run deployment verifier.
5. Record rollback evidence.

## Boundaries

No deployment step may upload documents, rerun ingestion, create vectors, mutate schema/RLS/policies, record signoff, create final legal conclusions, or authorize external submission.

## 2026-05-06 Runtime Alignment Evidence

- Source commit deployed: `c2a7f92fc78f122caf352581a246f73ea6a658a1`
- Frontend rollback artifact: `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next.rollback-20260506-215100-operational-hardening`
- Backend rollback artifact: `/home/admin/Fortress-Prime-runtime-main-20260504/operational-hardening-backend-rollback-20260506-215100-operational-hardening`
- Restarted services: `fortress-backend.service`, `crog-ai-frontend.service`
- Active services after restart: frontend, backend, tunnel
- Post-deploy checker: pass with no classified HTTP errors
