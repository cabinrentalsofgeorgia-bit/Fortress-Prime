# Fortress Legal Review Queue Maturity Model

Status: CONTROLLED_REVIEW_QUEUE_MODEL_ACTIVE

## Purpose

The review queue model improves reviewer throughput without changing legal conclusions or evidence state. It derives queue views from existing remediation and limited-signoff manifests.

## Queue Families

- Remediation review: all unresolved source issues, prioritized for human review.
- Contradiction review: contradiction candidates grouped by materiality and severity.
- Evidence navigation: metadata-safe pivots for timeline, entity dossier, and evidence binder items.
- Escalation review: items requiring counsel review or metadata-only restricted handling.

## Queue Item Fields

- item ID and type
- materiality tier
- blocker type
- source status
- confidence state
- review lane
- priority score
- owner placeholder
- age/staleness indicator
- audit state
- exclusion marker

## Allowed Operations

- View queue priority.
- Filter by review lane, confidence state, materiality, item type, and escalation status.
- Route human attention to high-impact source blockers.
- Preserve evidence lineage and exclusion labels.

## Forbidden Operations

- Auto-resolving source issues.
- Promoting unresolved items into relied-upon sections.
- Creating counsel signoff.
- Creating final legal conclusions.
- Authorizing filing, service, sending, email, or external submission.
- Inspecting locked/restricted document contents.
- Mutating schema, RLS, policies, vectors, ingestion, or document rows.

## Rollback

The model is read-only and code-backed. Revert the UI/API/checker commits and verify the prior Remediation Maturity panel remains visible.
