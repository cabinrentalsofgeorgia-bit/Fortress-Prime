# Fortress Legal Pilot Governance Certification Framework

Status: PILOT_GOVERNANCE_CERTIFICATION_ACTIVE

## Pilot Mode

The only certified mode is controlled internal operations. The pilot is limited to review queue triage, reviewer onboarding, workload planning, incident escalation, rollback rehearsal, and governance verification.

## Allowed Operations

- queue triage
- reviewer onboarding
- review workload planning
- incident escalation
- rollback rehearsal
- governance verification

## Forbidden Operations

- auto signoff
- final legal conclusion
- external submission
- unrestricted ingestion
- locked content review
- schema/RLS/policy mutation
- unresolved source promotion
- public launch
- unrestricted reviewer access

## Required Boundaries

- COUNSEL_SIGNOFF_PENDING remains visible.
- NOT_AUTHORIZED remains visible.
- NOT FINAL LEGAL ADVICE remains visible.
- Locked/restricted content remains metadata-only.
- Unresolved source issues remain excluded.
- Reviewer accountability and auditability remain required.

## Certification Evidence

Each certification run must retain checker evidence, deployment verifier evidence, validation output, rollback references, and a no-secrets/no-content exposure statement.
