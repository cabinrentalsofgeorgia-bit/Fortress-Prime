# Source Remediation Governance Model

## Purpose

The source remediation maturity system turns unresolved source issues into a governed review queue. It does not resolve legal questions, verify facts finally, or promote unsupported material into relied-upon sections.

## Lifecycle States

- `unresolved`
- `triaged`
- `automation_candidate`
- `human_review_required`
- `evidence_pending`
- `contradiction_review`
- `remediation_complete`
- `excluded`
- `locked_restricted_no_review`

## Confidence States

- `verified_review_use`: source-linked for review only.
- `source_missing`: no safe eligible source link.
- `counsel_interpretation_required`: factual source may exist but legal interpretation remains open.
- `restricted_metadata_only`: locked/restricted material cannot be content-reviewed by agents.
- `unresolved_unsupported`: unresolved and excluded from relied-upon sections.

## Escalation Rules

- Tier 1 unresolved issue: human source review first.
- Contradiction candidate: contradiction review lane.
- Issue matrix or theory packet gap: high-materiality source review.
- Evidence binder/entity/timeline gap: evidence attachment lane unless locked.
- Locked/restricted issue: counsel-only metadata review.

## Automation Boundaries

Allowed:

- classify;
- count;
- rank;
- route;
- show lineage;
- generate summary-safe review queues.

Forbidden:

- auto-accept source repairs into relied-upon sections;
- silently mutate evidence lineage;
- inspect locked/restricted content;
- rerun ingestion/vectorization;
- create final legal conclusions;
- record counsel signoff;
- authorize external submission.

## Audit Requirements

Every remediation action must record the source manifest chain, reviewer-safe label, action type, status before/after, rollback reference, and governance invariants.
