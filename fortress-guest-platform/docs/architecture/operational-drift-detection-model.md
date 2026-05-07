# Operational Drift Detection Model

## Purpose

Detect human-operations drift without punitive automation, legal automation, source promotion, or restricted-content inspection.

## Drift Signals

- `queue_depth_drift`
- `queue_aging_drift`
- `escalation_drift`
- `governance_label_drift`
- `deployment_drift`
- `reviewer_behavior_anomaly`
- `unresolved_source_aging_anomaly`
- `contradiction_backlog_anomaly`
- `review_throughput_anomaly`
- `feedback_volume_anomaly`

## Detection Inputs

- Authenticated checker.
- Deployment verifier.
- Controlled pilot simulation verifier.
- Review operations read model.
- Internal pilot throughput metrics.
- Human operations aggregate feedback categories.
- Evidence and rollback manifests.

## Drift Responses

- `observe`: continue and record evidence.
- `queue_manager_review`: review operational queue, no state mutation.
- `governance_exception_review`: halt relevant exercise and escalate.
- `rollback_tabletop`: rehearse rollback path.
- `runtime_rollback_required`: only if a deployed change caused production instability.

## Forbidden Automation

- No automatic source resolution.
- No automatic legal conclusion.
- No automatic counsel signoff.
- No automatic external submission authority.
- No punitive reviewer scoring or enforcement.
- No locked/restricted content inspection.
