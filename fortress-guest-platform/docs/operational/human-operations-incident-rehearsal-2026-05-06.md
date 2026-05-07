# Human Operations Incident Rehearsal - 2026-05-06

## Classification

`TABLETOP_READ_ONLY_HUMAN_OPERATIONS_REHEARSAL`

## Scenarios

### Reviewer Confusion Escalation

- Detection: reviewer marks `operational_confusion`.
- Immediate action: pause the queue exercise.
- Escalation: queue manager review.
- Evidence: feedback category, queue name, governance label snapshot.
- Standing label: `PRODUCTION_HUMAN_OPERATIONS_IN_PROGRESS`.

### Queue Overload

- Detection: queue aging or depth exceeds pilot threshold.
- Immediate action: prioritize source and contradiction lanes.
- Escalation: workload balancing review.
- Evidence: queue metrics only, no legal text.

### Contradiction Explosion

- Detection: contradiction backlog anomaly or clustered high severity.
- Immediate action: human contradiction review only.
- Escalation: senior reviewer or counsel review queue.
- Forbidden: auto-select legal interpretation.

### Remediation Backlog Spike

- Detection: unresolved-source aging anomaly.
- Immediate action: triage by source defect and materiality.
- Forbidden: promote unresolved issues into relied-upon sections.

### Governance Ambiguity

- Detection: reviewer cannot classify operation as allowed.
- Immediate action: halt.
- Escalation: governance exception review.

### Rollback Coordination Failure

- Detection: rollback artifact cannot be located or verifier fails after rollback rehearsal.
- Immediate action: stop deploy-related activity.
- Escalation: platform owner.

### Operational Drift Detection

- Detection: checker, deployment verifier, or pilot simulation mismatch.
- Immediate action: classify drift and rerun safe verification.

### Restricted-Content Warning

- Detection: restricted content appears beyond metadata-only handling.
- Immediate action: hard stop.
- Escalation: privilege/governance review.

### Unauthorized-Access Warning

- Detection: unauthenticated endpoint returns non-401/403 or unexpected public legal data.
- Immediate action: hard stop and rollback if caused by deployment.

### Checker Failure During Active Review Operations

- Detection: authenticated checker `ok:false` or missing governance labels.
- Immediate action: pause human operations.
- Escalation: platform owner with evidence summary.

## Rehearsal Result

`READY_FOR_CONTROLLED_HUMAN_OPERATIONS_TABLETOP_REHEARSAL`
