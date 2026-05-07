# Fortress Legal Contradiction Review Model

Status: HUMAN_CONTRADICTION_REVIEW_REQUIRED

## Scope

Contradiction review organizes contradiction candidates for human assessment. It does not resolve contradictions automatically and does not select a legal interpretation.

## Inputs

The model uses existing manifest metadata:

- contradiction IDs
- conflict type
- materiality score or tier
- confidence score/state
- counsel-review flag
- source reference identifiers
- required next action

No document body text or locked/restricted content is read.

## Severity Levels

- Critical: tier 1 high-materiality contradiction.
- Elevated: tier 2 contradiction.
- Standard: remaining contradiction candidate.

## Review States

- human_review_required
- contradiction_review
- evidence_pending
- counsel_interpretation_required
- excluded_from_relied_upon_sections

## Audit Requirements

Every contradiction review action in a future mutating workflow must preserve:

- source reference lineage
- reviewer safe label
- review timestamp
- decision scope
- rollback reference
- unresolved-source exclusion status until explicitly reviewed

## Governance Boundaries

- COUNSEL_SIGNOFF_PENDING remains preserved.
- Contradictions are draft review topics, not final legal conclusions.
- External submission authority remains NOT_AUTHORIZED.
- Restricted materials remain metadata-only.
