# Fortress Legal Operational Runbook Index

Last updated: `2026-05-06`

## Purpose

This index is the canonical operator entry point for Fortress Legal production-review work in Fortress-Prime. It links the governed workflows without exposing secrets, legal document contents, or auth state.

## Production Verification

Primary authenticated checker:

```bash
node scripts/verification/check-crog-fortress-ui.mjs
```

If auth state is externally provisioned outside the repo:

```bash
CROG_AUTH_STATE=/path/to/.auth/crog-ai-gary.json node scripts/verification/check-crog-fortress-ui.mjs
```

Rules:

- Do not commit `.auth/`.
- Do not print auth storage state.
- Do not print cookies, tokens, passwords, auth headers, or session values.
- The checker confirms authenticated UI visibility only.
- The checker does not authorize signoff or external use.

## Deployment Verification

Production route:

- `https://crog-ai.com`
- `https://crog-ai.com/legal/cases/fortress-legal-production-review`

Expected standing checks:

- Authenticated matter page visible.
- `COUNSEL_SIGNOFF_PENDING` visible.
- `DRAFT / COUNSEL REVIEW REQUIRED` visible where draft/review items appear.
- Locked/restricted documents metadata-only.
- No public legal data exposure.
- Unauthenticated APIs return 401/403.

## Rollback Workflow

Rollback references:

- `fortress-guest-platform/docs/operational/fortress-legal-production-rollback-plan-2026-05-05.md`
- Manifest-level rollback blocks under `/mnt/fortress_nas/audits/*.json`
- Vercel/provider rollback notes in deployment evidence docs where applicable.

Canonical rollback posture:

- Revert code/docs commit for UI/API/doc-only changes.
- Delete only the manifest explicitly named in a rollback block when an approved rollback scope exists.
- Do not delete evidence history.
- Do not mutate production DB, Qdrant, NAS legal data, schema, RLS, or policies unless separately approved.

## Evidence Capture Workflow

Evidence docs live under:

- `fortress-guest-platform/docs/operational/fortress-legal-*.md`

Evidence must record:

- Execution ID.
- Manifest path.
- Source manifests used.
- Counts and status summaries.
- Tests/checks.
- Mutation invariants.
- Locked/restricted handling.
- Public exposure check.
- Rollback/delete identifiers.
- Final standing labels.

Evidence must not include:

- Confidential document body text.
- Locked/restricted document contents.
- Secrets or auth state.
- Cookies, tokens, passwords, auth headers, storage state, service keys, or DB URLs.

## Counsel / Operator Decision Capture

Decision workflow:

- Backend: `legal_counsel_signoff_decision.py`
- API/UI: `legal_workbench.py`, `counsel-signoff-decision-workflow.tsx`
- Evidence: `fortress-legal-counsel-signoff-decision-workflow-2026-05-06.md`

Allowed decision outcomes include:

- Operator acknowledgment.
- Counsel review acknowledgment.
- Counsel limited approval for internal review use.
- Partial approval.
- Rejection.
- Revision request.
- Return to source remediation.
- Deferred signoff.

Forbidden outcomes without later explicit approval:

- Final legal conclusion.
- Filing authorization.
- Service authorization.
- Email/sending authorization.
- External submission authorization.
- Unrestricted production legal approval.

## Source Remediation Workflow

Sequence:

1. Counsel Review Workbench.
2. Counsel Validation Workflow.
3. Counsel Signoff Strategy Packet.
4. Source Integrity Validation.
5. Source Remediation.
6. Source Link Repair.
7. Targeted Source Completion.
8. Limited Signoff Candidate Packet.

Current open source blocker status:

- 232 source issues remain unresolved and excluded from relied-upon draft sections.

Rules:

- Use existing eligible non-locked source metadata/chunks only.
- Do not rerun ingestion.
- Do not create new vectors.
- Do not inspect locked/restricted contents.
- Do not erase unsupported/conflicting uncertainty.

## Draft Work Product Review Workflow

Draft work product:

- Backend: `legal_draft_work_product.py`
- Script: `fortress_draft_work_product.py`
- UI: `draft-work-product-panel.tsx`
- Evidence: `fortress-legal-draft-work-product-2026-05-06.md`

Rules:

- Use limited source-verified subset only.
- Exclude unresolved source issues from relied-upon sections.
- Preserve `NOT FINAL LEGAL ADVICE`.
- Preserve `NOT AUTHORIZED FOR FILING, SERVICE, SENDING, EMAIL, OR EXTERNAL SUBMISSION`.
- Counsel review remains required.

## Autonomous Learning Workflow

Autonomous learning:

- Backend: `legal_autonomous_learning_loop.py`
- Script: `fortress_autonomous_learning_loop.py`
- UI: `autonomous-learning-loop-panel.tsx`
- Evidence: `fortress-legal-autonomous-learning-loop-2026-05-06.md`

Rules:

- Bounded cycles only.
- Metadata/manifest learning only.
- No external model training on confidential legal data.
- No auto-signoff.
- Human approval required for high-risk proposals.

## Controlled Human Operations Workflow

Human operations are controlled internal pilot review operations only:

- Readiness audit: `human-operations-readiness-audit-2026-05-06.md`
- Maturity index: `human-operations-maturity-index.md`
- Reviewer onboarding: `reviewer-onboarding-governance-model.md`
- Operational feedback: `operational-feedback-capture-model.md`
- Governance exceptions: `governance-exception-handling-2026-05-06.md`
- Drift detection: `operational-drift-detection-model.md`
- Incident rehearsal: `human-operations-incident-rehearsal-2026-05-06.md`

Rules:

- Keep feedback structured and free of confidential document text.
- Halt on governance ambiguity, restricted-content warnings, unauthorized access, signoff/final-advice controls, or external-submission authority.
- Use checker, deployment verifier, and controlled pilot simulation before expanding any human review exercise.
- Persistent reviewer assignment writes remain deferred unless separately approved and rollbackable.

## Hard Stops

Stop and write a hard-stop report if:

- Auth is broken or expired.
- Production matter route is unreachable.
- A step requires locked/restricted document content.
- A step would expose confidential document text.
- A step requires upload, ingestion, duplicate vectors, schema/RLS/policy mutation, or privilege changes.
- A step attempts signoff, final legal conclusions, or external submission authority.
- Auth state or secrets would be printed or committed.
- Rollback identifiers are unavailable for a write.

## Standing Labels

During canonicalization:

- Production status: `PRODUCTION_SOURCE_OF_TRUTH_CANONICALIZATION_IN_PROGRESS`
- Product status: `FORTRESS_PRIME_CANONICAL_LEGAL_PRODUCTION_REPO`
- Counsel status: `COUNSEL_SIGNOFF_PENDING`
- External submission authority: `NOT_AUTHORIZED`
- Final legal conclusions: `NOT_CREATED`
- Schema/RLS/policy mutation: `NOT_PERFORMED`
