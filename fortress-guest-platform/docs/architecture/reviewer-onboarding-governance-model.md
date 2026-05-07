# Reviewer Onboarding Governance Model

## Purpose

Define controlled reviewer onboarding for Fortress Legal without granting signoff authority, final legal authority, unrestricted escalation authority, or restricted-content access.

## Reviewer Flow

1. Confirm authenticated internal access.
2. Read governance boundaries.
3. Confirm role tier and allowed queue lanes.
4. Review prohibited operations.
5. Review escalation and halt conditions.
6. Rehearse queue traversal using read-only/synthetic workload.
7. Capture structured operational feedback without confidential text.
8. Confirm rollback and incident reporting path.

## Capability Tiers

- `operator_reviewer`: may traverse queues, flag friction, and request escalation.
- `source_reviewer`: may triage source status and recommend remediation, but cannot promote unresolved sources into relied-upon sections.
- `senior_reviewer`: may classify escalation priority and contradiction severity, but cannot create final legal conclusions.
- `counsel_reviewer`: may review legal questions, but signoff remains a separate explicit workflow.

## Required Acknowledgments

- `COUNSEL_SIGNOFF_PENDING` remains active.
- `NOT_AUTHORIZED` external submission boundary remains active.
- `NOT FINAL LEGAL ADVICE` remains active.
- Locked/restricted items remain metadata-only.
- Unresolved source issues remain excluded.
- Feedback must not include confidential document text.
- Reviewer actions must remain auditable and rollback-aware.

## Prohibited Operations

- Auto-signoff.
- Final legal conclusions.
- Filing, service, sending, email, or external submission.
- Restricted-content inspection.
- Upload, ingestion, document-row creation, or vector writes.
- Schema/RLS/policy mutation.
- Unresolved-source promotion.
- Uncontrolled reviewer authority escalation.

## Storage Boundary

This phase exposes onboarding readiness and structured feedback categories as read-only operational state. Persistent reviewer assignments or production feedback writes remain deferred unless separately approved with rollback and governance controls.
