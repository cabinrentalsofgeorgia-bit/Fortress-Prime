# Fortress Legal Reviewer and Remediation Lineage Model

Date: 2026-05-06

## Purpose

Reviewer and remediation lineage makes review queues, remediation posture, contradiction governance, feedback categories, and incident triggers traversable without resolving sources automatically or granting reviewer authority.

## Lineage Nodes

- unresolved source backlog
- remediation queue
- contradiction cluster
- reviewer feedback ledger foundation
- governance exception classes
- incident rehearsal categories
- validation runs

## Lineage Edges

- `blocks`: unresolved-source backlog blocks full relied-upon expansion.
- `excluded_by`: unresolved items remain excluded by governance boundary.
- `governed_by`: review queues and feedback categories are governed by no-signoff/no-final/no-external rules.
- `escalated_to`: contradiction and governance exceptions escalate to human review.
- `validated_by`: checker/verifier/simulation validates visibility and boundary preservation.

## Boundaries

- No auto-resolution.
- No source promotion.
- No persistent reviewer authority escalation.
- No confidential legal text.
- No restricted-content inspection.
