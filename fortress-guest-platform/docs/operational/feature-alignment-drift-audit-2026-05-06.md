# Fortress Legal Production Feature Alignment Drift Audit

Date: `2026-05-06`

## Scope

This audit covers the production/source/deploy drift that leaves the authenticated checker reporting:

- `draftWorkProduct:false`
- `learning:false`

The goal is production feature alignment for Draft Work Product and Autonomous Learning only. This audit does not authorize signoff, final legal conclusions, external submission, ingestion, vector creation, schema mutation, RLS mutation, policy mutation, or locked-content review.

## Baseline

- Canonical repo: `/home/admin/Fortress-Prime`
- Working branch: `release/fortress-legal-feature-alignment`
- Canonical base: `safety/foundation-audit-snapshot`
- Base commit for this branch: `7d4f3da8b3b2658ab439e95697985cc8ccf16fb9`
- Canonicalization PR: `#441`, merged
- Production domain: `https://crog-ai.com`
- Matter slug: `fortress-legal-production-review`

## Checker Audit

Checker path:

- `scripts/verification/check-crog-fortress-ui.mjs`

Checker target:

- `https://crog-ai.com/legal/cases/fortress-legal-production-review`

The checker records Draft Work Product visibility when body text contains one of:

- `Draft Work Product`
- `Draft Internal Memo`
- `Draft Statement of Facts`

The checker records Autonomous Learning visibility when body text contains one of:

- `Autonomous Learning`
- `Learning signals`
- `Next-best actions`

The checker uses broad visible-text inspection after authenticated navigation. It does not read `.auth/` contents and must not print cookies, tokens, passwords, auth headers, or storage state.

## Frontend Drift

The merged canonical protected branch currently contains the canonical checker and governance docs but does not contain the advanced Draft Work Product or Autonomous Learning matter-page panels.

The advanced local Fortress-Prime history contains the relevant frontend implementations:

- `dd951021a feat(legal): add draft work product generation`
- `abc837f50 feat(legal): add autonomous learning loop`

Those commits add:

- `draft-work-product-panel.tsx`
- `autonomous-learning-loop-panel.tsx`
- legal hook/type additions
- matter page integration through `case-detail-shell.tsx`
- focused panel tests

The checker strings match the advanced UI labels:

- `Draft Work Product Packet`
- `Autonomous Learning Loop`

Therefore, the current false checker result is not primarily a string mismatch. The stronger finding is source/deploy drift: the protected canonical branch does not yet carry the runtime feature surfaces needed for production to render those labels.

## Backend Drift

The protected canonical branch does not contain `fortress-guest-platform/backend/api/legal_workbench.py`.

The advanced local Fortress-Prime history contains artifact-backed backend implementations for:

- Draft Work Product
- Autonomous Learning
- legal workbench route exposure
- file-backed manifest loading under `/mnt/fortress_nas/audits`

Relevant advanced commits:

- `920a9a7c2 feat(legal): add counsel review workbench`
- `8b7874963 feat(legal): add counsel validation workflow`
- `955a9b88a feat(legal): add counsel signoff strategy packet`
- `26018f5aa feat(legal): add source integrity validation workflow`
- `1a0bea469 feat(legal): add source blocker remediation workflow`
- `b53fe9df1 feat(legal): add source link repair workflow`
- `1a8e6c6d8 feat(legal): add targeted source completion workflow`
- `366923f90 feat(legal): add limited signoff candidate packet`
- `79d84f649 feat(legal): add counsel signoff decision workflow`
- `abc837f50 feat(legal): add autonomous learning loop`
- `dd951021a feat(legal): add draft work product generation`

Directly applying `dd951021a` alone failed because it depends on the missing legal-workbench chain. The conflict was limited to the clean feature-alignment worktree and was reset before any commit.

## Deployment Drift

Production currently returns `200` and the authenticated checker confirms:

- authenticated matter access
- `COUNSEL_SIGNOFF_PENDING`
- Source Integrity Validation
- Workbench/Validation visibility
- auth protections intact

But the canonical protected branch only contains governance/checker docs after PR `#441`. This means the production deployment and canonical protected source are not aligned to one single runtime source of truth. Production appears to have some advanced legal workflow surface available, while the protected canonical branch does not yet carry the complete advanced legal runtime implementation.

## Governance Drift

Required boundaries remain non-negotiable:

- `COUNSEL_SIGNOFF_PENDING`
- `NOT_AUTHORIZED`
- `NOT FINAL LEGAL ADVICE`
- no final legal conclusions
- no external submission authority
- locked/restricted metadata-only handling
- no schema/RLS/policy mutation
- no ingestion/vector/document-row creation

The feature alignment must preserve those labels in UI, docs, evidence, and PR body.

## Root Cause

Root cause: the merged canonical protected branch contains the governance/checker canonicalization layer but not the advanced runtime implementation chain that introduced Draft Work Product and Autonomous Learning. The checker is correctly reporting that the deployed matter page does not expose those target strings, while the local advanced history proves the target implementations already exist and are not new product invention.

## Result

Status: `PRODUCTION_FEATURE_ALIGNMENT_IN_PROGRESS`

The next step is a surgical execution plan that either:

1. ports the minimum required legal-workbench runtime chain from advanced Fortress-Prime history into the canonical branch, or
2. stops if deployment source alignment requires unsafe schema/RLS/auth/secret changes.

No production mutation was performed by this audit.
