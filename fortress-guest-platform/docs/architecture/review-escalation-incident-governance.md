# Fortress Legal Review Escalation and Incident Governance

Status: HUMAN_ESCALATION_AND_INCIDENT_GOVERNANCE_ACTIVE

## Escalation Model

Escalation is human-only. The system may flag an item for review attention, but it may not change legal/evidence state automatically.

## Escalation Triggers

- high-materiality source blockers
- contradiction candidates
- counsel-review-required items
- locked/restricted metadata-only items
- auth boundary failure
- public exposure risk
- restricted-content boundary risk
- schema/RLS/policy change request
- attempted auto-signoff
- attempted final legal conclusion
- attempted external submission

## Incident Stop Conditions

Stop and escalate if any of the following occur:

- secret exposure
- privileged-content exposure
- restricted-content boundary violation
- auth failure
- production instability
- uncontrolled legal automation
- rollback impossibility

## Required Incident Evidence

- timestamp
- route or component affected
- sanitized status/error classification
- governance boundary implicated
- rollback reference
- reviewer/operator safe label when available
- no document body text
- no secrets/auth material

## Governance

COUNSEL_SIGNOFF_PENDING, NOT_AUTHORIZED, NOT FINAL LEGAL ADVICE, metadata-only restricted handling, unresolved-source exclusion, and evidence lineage must remain preserved during any escalation.
