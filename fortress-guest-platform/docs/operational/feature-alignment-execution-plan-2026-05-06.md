# Fortress Legal Production Feature Alignment Execution Plan

Date: `2026-05-06`

## Objective

Align the canonical Fortress-Prime production source and deployment path so the authenticated checker can verify:

- `draftWorkProduct:true`
- `learning:true`

This plan is limited to Draft Work Product and Autonomous Learning visibility/alignment. It does not authorize new legal workflows, schema/RLS/policy changes, ingestion, vector creation, counsel signoff, final legal conclusions, or external submission.

## Root Cause

The canonical protected branch after PR `#441` contains the governance/checker layer but not the advanced runtime implementation chain that introduced the matter-page Draft Work Product and Autonomous Learning surfaces.

Advanced Fortress-Prime history contains those implementations, but direct cherry-pick of `dd951021a feat(legal): add draft work product generation` onto the protected base fails because it depends on the missing legal-workbench chain.

Deployment/source drift is also present:

- `crog-ai.com` is not proven to be serving the merged protected branch.
- Local metadata indicates `crog-ai.com` is likely served by a local Command Center runtime, not the repo-level Vercel storefront project.
- Repo-level `.vercel/project.json` points to storefront configuration and must not be used for Command Center deployment alignment.

## Minimal Safe Change Strategy

The safe implementation must use a two-part alignment strategy:

1. Source alignment:
   - Port the existing advanced legal-workbench runtime chain required for Draft Work Product and Autonomous Learning from Fortress-Prime history.
   - Do not invent new product behavior.
   - Do not change schema, RLS, policy, privilege, auth protections, ingestion, vector writes, or legal conclusion/signoff behavior.

2. Deployment alignment:
   - Deploy or restart only from a clean Command Center runtime source after the source alignment PR is reviewed.
   - Do not deploy from the repo-level storefront Vercel project.
   - If the active `crog-ai.com` runtime commit/artifact cannot be proven, stop and document `PRODUCTION_DEPLOYMENT_ALIGNMENT_BLOCKED`.

## Required Source Prerequisites

The two target features depend on the legal-workbench chain. Candidate prerequisite commits from advanced Fortress-Prime history include:

- `920a9a7c2 feat(legal): add counsel review workbench`
- `232055866 fix(legal): surface counsel review workbench in matter UI`
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

This is not feature sprawl if applied as an existing-runtime prerequisite chain, but it is broader than a two-file UI patch. Therefore it must be reviewed as feature alignment, not governance-only documentation.

## Affected File Categories

Expected categories:

- legal matter UI panels
- legal hooks and types
- legal workbench API
- artifact-backed legal services
- CLI wrappers for manifest-backed workflows
- focused legal tests
- operational docs/evidence

Forbidden categories:

- migrations
- RLS/policy files
- auth weakening
- ingestion pipelines
- vector creation jobs
- locked/restricted content extraction
- external submission or filing code
- unrelated CROG/MarketClub/financial/VRS work

## Checker Assertions

Before alignment:

- authenticated route returns `200`
- `COUNSEL_SIGNOFF_PENDING` visible
- Source Integrity Validation visible
- Workbench/Validation visible
- `draftWorkProduct:false`
- `learning:false`

After alignment:

- authenticated route returns `200`
- `COUNSEL_SIGNOFF_PENDING` visible
- Source Integrity Validation visible
- Workbench/Validation visible
- `draftWorkProduct:true`
- `learning:true`
- unauthenticated access remains blocked
- no locked content exposed
- no final legal advice or external submission authority shown

## Validation Commands

Safe candidates:

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
npm --workspace @fortress/command-center exec vitest run \
  src/__tests__/legal/draft-work-product-panel.test.tsx \
  src/__tests__/legal/autonomous-learning-loop-panel.test.tsx \
  src/__tests__/legal/counsel-review-workbench.test.tsx \
  src/__tests__/legal/counsel-validation-workflow.test.tsx \
  src/__tests__/legal/counsel-signoff-decision-workflow.test.tsx
```

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center
npx tsc --noEmit --pretty false
```

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
npm --workspace @fortress/command-center run build
```

```bash
cd /home/admin/Fortress-Prime
CROG_AUTH_STATE=/path/to/external/storage-state.json node scripts/verification/check-crog-fortress-ui.mjs
```

Backend pytest must not be run against production database state. Use only a proven isolated test DB or compile checks for this phase.

## Rollback Plan

Rollback is git-revertable:

1. Revert the source-alignment commits.
2. Revert validation/evidence commits if needed.
3. Redeploy or restart the previous known-good Command Center runtime artifact only if a deployment change was made.
4. Leave NAS manifests, production legal records, auth state, schema, RLS, policies, document rows, vectors, and locked/restricted content unchanged.

## Governance Implications

The implementation must preserve:

- `COUNSEL_SIGNOFF_PENDING`
- `NOT_AUTHORIZED`
- `NOT FINAL LEGAL ADVICE`
- `DRAFT / COUNSEL REVIEW REQUIRED`
- locked/restricted metadata-only boundaries
- 232 unresolved source issues excluded from relied-upon sections

## Current Execution Decision

Status: proceed with source alignment only if the prerequisite chain can be applied cleanly and validated without unrelated file drift.

Deployment alignment status: blocked until the active `crog-ai.com` Command Center runtime source/artifact can be proven or safely rebuilt from a clean reviewed ref.
