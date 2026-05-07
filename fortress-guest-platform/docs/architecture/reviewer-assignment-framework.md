# Fortress Legal Reviewer Assignment Framework

Status: DERIVED_ASSIGNMENT_FRAMEWORK_ACTIVE

## Purpose

The reviewer assignment framework provides safe role hints for controlled internal review operations. It does not persist assignments, grant authority, change evidence status, or create legal signoff.

## Reviewer Groups

- operator_reviewer: general queue triage and operational routing.
- source_reviewer: source attachment, source-chain review, and evidence-pending workflow.
- counsel_or_senior_reviewer: contradiction review, legal-interpretation-needed items, and high-materiality escalation.
- privilege_counsel_metadata_review: metadata-only review for locked/restricted items.

## Assignment Inputs

- review lane
- materiality tier
- confidence state
- locked/restricted flag
- counsel-review flag
- priority score
- evidence-needed flag

## Forbidden Effects

Assignments may not:

- auto-resolve source issues
- promote unresolved issues into relied-upon sections
- record counsel signoff
- create final legal conclusions
- authorize filing, service, sending, email, or external submission
- bypass metadata-only restricted handling

## Audit Boundary

Future persistent assignment must include reviewer safe label, role, timestamp, item ID, scope, rollback reference, and no-content evidence boundary. This phase records role-hint visibility only.
