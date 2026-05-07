# Fortress Legal Controlled Internal Pilot Execution Plan - 2026-05-06

Status: CONTROLLED_INTERNAL_PILOT_PLAN_READY

## Objective

Exercise Fortress Legal under controlled internal pilot conditions to measure reviewer throughput, remediation throughput, contradiction-review throughput, evidence-navigation efficiency, escalation behavior, and rollback readiness.

## Scope

This pilot is internal, read-only, metadata-safe, and governance-bound. It uses existing review-operation summaries and synthetic/read-only pilot exercises. It does not perform legal signoff, source resolution, ingestion, evidence mutation, or external legal operations.

## Allowed Operations

- read-only review queue traversal
- remediation queue triage simulation
- contradiction review simulation
- evidence-navigation exercise
- source-confidence review exercise
- escalation-path simulation
- rollback tabletop drill
- incident-response tabletop drill
- deployment verification rehearsal
- reviewer onboarding rehearsal

## Forbidden Operations

- counsel signoff
- final legal conclusion
- filing, service, sending, email, or external submission
- upload, ingestion, or vector writes
- schema/RLS/policy mutation
- locked/restricted content inspection
- unresolved-source promotion
- public or external user enablement
- persistent production reviewer assignment writes

## Reviewer Roles

- operator_reviewer
- source_reviewer
- counsel_or_senior_reviewer
- privilege_counsel_metadata_review

## Queue Types

- remediation review
- contradiction review
- evidence navigation
- escalation review
- source-confidence review
- incident and rollback drill queues

## Metrics

- queue depth
- queue aging/SLA bands
- remediation triage count
- contradiction review count
- evidence navigation count
- reviewer handoff count
- escalation count
- unresolved-source count
- excluded-source count
- confidence distribution
- completion readiness

## Evidence Requirements

- authenticated checker summary
- deployment verifier summary
- pilot simulation summary
- queue metrics summary
- governance assertions
- incident and rollback drill summary
- validation results
- no-secrets scan
- no-auth-file scan

## Stop Conditions

Stop if secret exposure, privileged-content exposure, restricted-content boundary violation, auth failure, production instability, rollback impossibility, schema/RLS mutation requirement, uncontrolled legal automation risk, public/external access requirement, ingestion/upload/vector requirement, or confidential-content exposure is detected.

## Success Criteria

- checker passes with internal pilot visibility
- deployment verifier passes
- unauthenticated legal APIs remain blocked
- pilot simulation runner passes
- unresolved sources remain excluded
- no signoff/final/external controls exposed
- rollback references captured

## Failure Criteria

- any hard stop occurs
- governance labels are missing
- unresolved-source exclusion is not visible
- checker or deployment verifier cannot be safely restored
- simulation runner detects signoff/final/external authority exposure
