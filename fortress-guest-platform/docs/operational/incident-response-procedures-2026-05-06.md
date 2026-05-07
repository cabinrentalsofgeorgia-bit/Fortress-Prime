# Fortress Legal Incident Response Procedures - 2026-05-06

Status: INCIDENT_RESPONSE_READY_FOR_CONTROLLED_INTERNAL_PILOT

## Stop Conditions

Stop the pilot workflow and escalate if any of these occur:

- secret exposure
- privileged-content exposure
- restricted-content boundary violation
- auth failure
- production instability
- rollback impossibility
- uncontrolled legal automation
- attempted auto-signoff
- attempted final legal conclusion
- attempted external submission

## Immediate Response

1. Stop the active operation.
2. Preserve sanitized evidence.
3. Do not print secrets, auth state, document contents, source excerpts, or locked/restricted content.
4. Capture route, status, timestamp, component, and governance boundary implicated.
5. Notify the operator/counsel review owner.
6. Execute rollback if production safety is affected.
7. Re-run authenticated checker and deployment verifier after mitigation.

## Evidence Requirements

- timestamp
- safe route/component identifier
- sanitized error classification
- rollback reference
- checker/verifier status
- governance labels
- no secret exposure statement
- no document-content exposure statement

## Governance

Incident response never creates counsel signoff, final legal conclusions, external submission authority, or source promotion.
