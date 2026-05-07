# Fortress Legal Repository Drift Inventory

Last updated: `2026-05-06`

## Canonical Standing

Fortress-Prime is the canonical Fortress Legal production repository for the current consolidation phase.

- Canonical repo: `/home/admin/Fortress-Prime`
- Canonical base branch: `safety/foundation-audit-snapshot`
- Canonicalization branch: `release/fortress-legal-canonicalization`
- Legacy/foundation app repo: `/home/admin/fortress-legal-production-work/fortress-legal-app`
- Wiki repo: `/home/admin/fortress-legal-production-work/fortress-legal-wiki`
- Auth checker worktree: `/home/admin/Fortress-Prime-auth-verify`

This inventory does not move, delete, or normalize unrelated dirty files. It records the split-brain state so cleanup can happen through explicit scoped follow-up work.

## Fortress-Prime Status

- Branch at phase start: `safety/foundation-audit-snapshot`
- Active consolidation branch: `release/fortress-legal-canonicalization`
- Remote: `git@github.com:cabinrentalsofgeorgia-bit/Fortress-Prime.git`
- Remote fetch status: blocked by host SSH public-key denial during this run.
- Advanced Fortress Legal systems present: yes.
- Authenticated checker canonicalized into `scripts/verification/check-crog-fortress-ui.mjs`.

Fortress Legal relevant dirty or untracked files observed before canonicalization:

- `fortress-guest-platform/docs/operational/fortress-legal-source-link-repair-2026-05-06.md`
- `fortress-guest-platform/docs/operational/fortress-legal-targeted-source-completion-2026-05-06.md`
- `fortress-guest-platform/backend/scripts/fortress_autonomous_legal_intake.py`
- `fortress-guest-platform/docs/operational/fortress-legal-operator-environment-blocker-2026-05-05.md`
- `docs/operational/MASTER-PLAN.md`

Unrelated dirty files to avoid:

- `crog-ai-backend/**`
- `fortress-guest-platform/apps/command-center/src/__tests__/components/financial-hedge-fund-shell.test.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/financial/hedge-fund/_components/hedge-fund-signals-shell.tsx`
- `fortress-guest-platform/apps/command-center/src/lib/hooks.ts`
- `fortress-guest-platform/apps/command-center/src/lib/types.ts`

Unrelated untracked files to avoid:

- `crog-ai-backend/alembic/versions/0004_shadow_review_decisions.py`
- `crog-ai-backend/alembic/versions/0005_promotion_dry_run_acceptances.py`
- `crog-ai-backend/app/signals/whipsaw_risk.py`
- `crog-ai-backend/deploy/sql/marketclub_promotion_dry_run_acceptances.sql`
- `crog-ai-backend/deploy/sql/marketclub_shadow_review_decisions.sql`
- `crog-ai-backend/docs/MARKETCLUB-SHADOW-REVIEW-RUNBOOK.md`
- `crog-ai-backend/docs/reports/dochia-v0-3-rolling-whipsaw-holdout-2026-05-03.md`
- `crog-ai-backend/docs/reports/dochia-v0-3-rolling-whipsaw-review-2026-05-03.md`
- `crog-ai-backend/scripts/review_rolling_whipsaw_candidates.py`
- `crog-ai-backend/tests/test_whipsaw_risk.py`

## Legacy App Repo Status

- Repo: `/home/admin/fortress-legal-production-work/fortress-legal-app`
- Branch: `release/fortress-legal-production-readiness`
- Remote: `https://github.com/cabinrentalsofgeorgia-bit/fortress-legal-app.git`
- Dirty files: `package.json`, `package-lock.json`
- Recent branch state: retrieval observability and synthetic retrieval commits are present.
- Feature parity with Fortress-Prime: not equivalent for advanced Fortress Legal production workflows.

Current role: foundation/future extraction target, not canonical production source for advanced Fortress Legal.

## Wiki Repo Status

- Repo: `/home/admin/fortress-legal-production-work/fortress-legal-wiki`
- Branch: `release/fortress-legal-production-readiness`
- Remote: `https://github.com/cabinrentalsofgeorgia-bit/fortress-legal-wiki.git`
- Dirty files: none at phase start.
- Recent branch state: retrieval audit and controlled activation records are present.

Current role: public/standing evidence index for governed product state, not runtime source.

## Auth Checker Worktree Status

- Repo: `/home/admin/Fortress-Prime-auth-verify`
- HEAD: detached at `2e655a681`
- Dirty files: `.gitignore`
- Untracked files: `node_modules/`, `package.json`, `package-lock.json`, `scripts/check-crog-fortress-ui.mjs`, `scripts/save-crog-auth-state.mjs`
- Auth state: `.auth/` is ignored and must remain untracked.

The checker script has been copied into the canonical repo. Auth state was not copied and must remain externally provisioned.

## NAS Evidence Status

Observed audit manifests under `/mnt/fortress_nas/audits` include:

- `fortress-autointake-20260506-015341.json`
- `fortress-intel-20260506-041839.json`
- `fortress-counsel-review-20260506-073330.json`
- `fortress-validation-20260506-081435.json`
- `fortress-signoff-packet-20260506-084028.json`
- `fortress-source-integrity-20260506-090537.json`
- `fortress-source-remediation-20260506-092630.json`
- `fortress-source-link-repair-20260506-095253.json`
- `fortress-targeted-source-completion-20260506-151821.json`
- `fortress-limited-signoff-candidate-20260506-153336.json`
- `fortress-signoff-decision-20260506-162035.json`
- `fortress-learning-loop-20260506-163734.json`
- `fortress-draft-work-product-20260506-165701.json`

The inventory records manifest names only. It does not reproduce confidential document text.

## Production Checker Caveats

The canonical checker verifies authenticated access, production matter visibility, staff session state, key Fortress Legal tabs, signoff-pending labels, and source-integrity visibility.

Known caveat at consolidation time:

- `draftWorkProduct:false`
- `learning:false`

This indicates production/source/deploy drift remains for those UI signals. It is not treated as signoff failure and does not authorize final legal conclusions or external use.

## Cleanup Backlog

1. Resolve Fortress-Prime SSH remote access so fetch, push, and PR creation can be performed from the canonical branch.
2. Decide whether legacy app repo dependency drift in `package.json` and `package-lock.json` should be reverted, committed, or preserved for retrieval work.
3. Decide whether auth-verify worktree should remain as a disposable auth bootstrap workspace after the canonical checker is validated.
4. Audit Fortress Legal relevant untracked docs/scripts and either integrate them in focused commits or archive them through a separate evidence pass.
5. Confirm whether `draftWorkProduct` and `learning` should be visible in production checker expectations after canonical deployment catches up.
6. Keep unrelated MarketClub/Dochia/CROG backend and financial hedge-fund dirty files out of Fortress Legal canonicalization commits.

## Standing Labels

- Production status: `PRODUCTION_SOURCE_OF_TRUTH_CANONICALIZATION_IN_PROGRESS`
- Product status: `FORTRESS_PRIME_CANONICAL_LEGAL_PRODUCTION_REPO`
- Counsel status: `COUNSEL_SIGNOFF_PENDING`
- External submission authority: `NOT_AUTHORIZED`
- Final legal conclusions: `NOT_CREATED`
- Schema/RLS/policy mutation: `NOT_PERFORMED`
