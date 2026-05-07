# Fortress Legal Source Of Truth Consolidation - 2026-05-06

Timestamp: `2026-05-06T20:57:09-04:00`

## Decision

Fortress-Prime is the canonical production repository for Fortress Legal.

- Canonical repo: `/home/admin/Fortress-Prime`
- Canonical branch base: `safety/foundation-audit-snapshot`
- Canonicalization branch: `release/fortress-legal-canonicalization`
- Legacy/foundation repo: `/home/admin/fortress-legal-production-work/fortress-legal-app`
- Wiki repo: `/home/admin/fortress-legal-production-work/fortress-legal-wiki`
- Production domain: `https://crog-ai.com`
- Matter slug: `fortress-legal-production-review`

## Rationale

Fortress-Prime contains the advanced Fortress Legal production implementation and evidence lineage:

- Counsel Review Workbench, Counsel Validation Workflow, Counsel Signoff Strategy Packet, and Counsel Signoff Decision Workflow.
- Source Integrity Validation, Source Remediation, Source Link Repair, Targeted Source Completion, and Limited Signoff Candidate Packet.
- Autonomous Learning Loop and Draft Work Product Generation.
- File-backed operational manifests under `/mnt/fortress_nas/audits`.
- Production legal UI surfaces under the Command Center legal matter route.
- Operational evidence docs under `fortress-guest-platform/docs/operational`.

`fortress-legal-app` remains a clean Supabase/Next foundation and future extraction target, but it is not feature-equivalent. Porting the advanced workflows into that repo now would be higher risk than normalizing Fortress-Prime because it would require reimplementing backend services, UI panels, manifest loaders, rollback evidence, and governed workflow history.

## Current Production Drift

Authenticated Playwright verification from the canonical checker confirms:

- Production route HTTP 200.
- Authenticated matter page visible.
- Gary CROG `super_admin` session visible.
- `COUNSEL_SIGNOFF_PENDING` visible.
- Strategy, Validation, Workbench, Panopticon, Deliberation, and Vanguard tabs visible.
- Source Integrity Validation visible.
- Document/workbench baseline visible.

Known drift remains:

- The checker reports `draftWorkProduct: false`.
- The checker reports `learning: false`.
- This indicates production/source/deploy drift for the latest Fortress-Prime handoff features.

## Hard Boundaries

Canonicalization does not authorize:

- Counsel signoff.
- Final legal conclusions.
- Filing, service, sending, email, or external submission.
- New document upload or ingestion.
- Duplicate document rows or Qdrant/vector points.
- Schema, RLS, policy, or privilege mutation.
- Locked/restricted content review.

Required standing boundaries:

- `COUNSEL_SIGNOFF_PENDING` remains preserved.
- `DRAFT / COUNSEL REVIEW REQUIRED` remains preserved.
- `EXTERNAL SUBMISSION NOT AUTHORIZED` remains preserved.
- Locked/restricted documents remain metadata-only.

## Rollback

Rollback for this decision:

- Revert canonicalization commits on `release/fortress-legal-canonicalization`.
- Continue using the prior local worktrees without changing production services.
- Do not delete `/mnt/fortress_nas/audits` manifests.
- Do not rewrite operational evidence history.

## Next Phases

1. Normalize the Fortress Legal architecture index and operational runbook index.
2. Move authenticated checker infrastructure into governed Fortress-Prime paths without auth state.
3. Preserve the `fortress-legal-app` repo as a foundation/future extraction target.
4. Update the wiki with this canonical decision.
5. Validate the canonical checker, legal UI tests, backend compile, and evidence docs.
6. Resolve production/source/deploy drift for Draft Work Product and Autonomous Learning visibility.

## Final Standing Labels

- Production status: `PRODUCTION_SOURCE_OF_TRUTH_CANONICALIZATION_IN_PROGRESS`
- Product status: `FORTRESS_PRIME_CANONICAL_LEGAL_PRODUCTION_REPO`
- Counsel status: `COUNSEL_SIGNOFF_PENDING`
- External submission authority: `NOT_AUTHORIZED`
- Final legal conclusions: `NOT_CREATED`
- Schema/RLS/policy mutation: `NOT_PERFORMED`
