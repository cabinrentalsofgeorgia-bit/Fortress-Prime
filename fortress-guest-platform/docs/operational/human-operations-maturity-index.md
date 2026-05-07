# Human Operations Maturity Index

## Purpose

This index ties together the controlled human-operations phase for Fortress Legal. It is an internal, governed, metadata-safe review-operations maturity layer. It is not public launch readiness, legal signoff, final legal advice, or external legal operations.

## Active Human Operations Documents

- `human-operations-readiness-audit-2026-05-06.md`
- `reviewer-onboarding-governance-model.md`
- `operational-feedback-capture-model.md`
- `governance-exception-handling-2026-05-06.md`
- `operational-drift-detection-model.md`
- `human-operations-incident-rehearsal-2026-05-06.md`
- `controlled-internal-pilot-execution-plan-2026-05-06.md`
- `internal-pilot-workload-model.md`
- `review-throughput-instrumentation-model.md`
- `internal-pilot-incident-and-rollback-drill-2026-05-06.md`

## Canonical Labels

- `CONTROLLED_HUMAN_OPERATIONS_READY`
- `ONBOARDING_GOVERNANCE_VISIBLE`
- `STRUCTURED_FEEDBACK_READY_NO_FREEFORM_LEGAL_TEXT`
- `EXCEPTION_HANDLING_VISIBLE`
- `DRIFT_DETECTION_ACTIVE_FOR_HUMAN_OPERATIONS`
- `READY_FOR_CONTROLLED_HUMAN_OPERATIONS_TABLETOP_REHEARSAL`

## Allowed Human Operations

- Controlled reviewer onboarding rehearsal.
- Read-only queue traversal.
- Structured operational feedback category review.
- Governance exception tabletop review.
- Drift detection review.
- Incident and rollback tabletop rehearsal.
- Ergonomics review from aggregate operational signals.

## Forbidden Human Operations

- Counsel signoff.
- Final legal conclusions.
- Filing, service, sending, email, or external submission.
- Restricted-content inspection.
- Upload, ingestion, document-row creation, or vector writes.
- Schema/RLS/policy mutation.
- Unresolved-source promotion.
- Uncontrolled reviewer authority escalation.

## Evidence Expectations

Evidence must contain only non-sensitive booleans, counts, paths, and governance labels. It must not include auth material, cookies, tokens, passwords, headers, confidential document text, locked/restricted content, or raw source excerpts.

## Standing State

- Production status target: `PRODUCTION_HUMAN_OPERATIONS_COMPLETE_PENDING_REVIEW`
- Counsel status: `COUNSEL_SIGNOFF_PENDING`
- External submission authority: `NOT_AUTHORIZED`
- Final legal conclusions: `NOT_CREATED`
- Legal advice status: `NOT FINAL LEGAL ADVICE`
- Schema/RLS/policy mutation: `NOT_PERFORMED`
