# Fortress Legal Controlled Review Pilot Readiness - 2026-05-06

Status: CONTROLLED_INTERNAL_REVIEW_PILOT_READY_PENDING_REVIEW

## Readiness Checklist

- Authenticated production matter access: required.
- Authenticated checker: required.
- Deployment verifier: required.
- COUNSEL_SIGNOFF_PENDING: preserved.
- NOT_AUTHORIZED external submission boundary: preserved.
- NOT FINAL LEGAL ADVICE label: preserved.
- Unresolved-source exclusion: preserved.
- Locked/restricted handling: metadata-only.
- Rollback path: git revert plus deployment re-verification.
- Incident response: stop on auth failure, public exposure, secret exposure, restricted-content exposure, schema/RLS mutation requirement, data-loss risk, or uncontrolled legal automation risk.

## Pilot Scope

The pilot scope is controlled internal review operations only:

- review queue triage
- contradiction review triage
- evidence navigation
- confidence review
- remediation prioritization
- audit and evidence preservation

## Forbidden Operations

- public legal review access
- autonomous counsel signoff
- final legal conclusions
- filing, service, sending, email, or external submission
- raw document upload or ingestion
- duplicate document rows or vectors
- schema/RLS/policy mutation
- locked/restricted content inspection
- silent evidence lineage mutation

## Escalation Procedure

Escalate to the operator/counsel review owner if:

- a queue item needs legal interpretation
- a contradiction requires narrative resolution
- source support is unavailable
- restricted materials are implicated
- a public exposure or auth boundary concern appears
- any requested action would change evidence state or legal status

## Final Standing

The controlled review operations phase prepares the platform for governed internal pilot review. It does not authorize external or public legal operations.
