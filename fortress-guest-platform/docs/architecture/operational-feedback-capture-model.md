# Operational Feedback Capture Model

## Purpose

Capture human operational feedback safely so reviewer friction and governance ambiguity can improve the system without exposing confidential legal text or creating uncontrolled production writes.

## Feedback Categories

- `reviewer_friction`
- `queue_friction`
- `evidence_navigation_friction`
- `contradiction_review_friction`
- `escalation_friction`
- `operational_confusion`
- `governance_ambiguity`
- `rollback_confusion`
- `checker_or_verifier_gap`

## Safe Capture Shape

Each feedback signal should use structured values only:

- feedback type
- queue or panel name
- severity band
- role safe label
- action requested
- governance boundary involved
- confidential-text-free note category
- status
- rollback reference

## Forbidden Feedback Content

- Confidential document text.
- Privileged or locked/restricted contents.
- Auth state, cookies, tokens, passwords, headers, or secrets.
- Final legal conclusions.
- Filing/service/external-submission instructions.
- Raw source excerpts.

## Operational Feedback Dashboard

The human-operations panel reports aggregate feedback readiness, friction categories, heatmap-style severity counts, and safe next actions. It does not persist production reviewer feedback in this phase.

## Governance

Feedback can recommend improvements, escalation, or remediation review. Feedback cannot resolve source issues, approve legal conclusions, alter evidence lineage, or authorize external use.
