# Fortress Legal Internal Pilot Workload Model

Status: SYNTHETIC_READ_ONLY_WORKLOAD_MODEL_ACTIVE

## Model

The internal pilot workload model uses existing metadata-safe review-operation counts plus synthetic workload descriptors. It does not include legal document text, locked/restricted content, source excerpts, secrets, or auth material.

## Workload Samples

- Review queue sample: top remediation queue items by priority score.
- Remediation queue sample: unresolved source issues grouped by review lane and confidence state.
- Contradiction queue sample: contradiction candidates grouped by severity.
- Evidence navigation sample: timeline, entity dossier, and evidence binder metadata groups.
- Confidence-band sample: source_missing, restricted_metadata_only, counsel_interpretation_required, unresolved_unsupported.
- Escalation sample: items in escalate_if_unassigned or queue_manager_review states.
- Incident sample: hard-stop tabletop scenarios.
- Rollback sample: git revert and runtime artifact rollback verification.

## Current Baseline Counts

- Unresolved source issues: 232
- Limited verified subset: 65
- Contradiction candidates: 14
- Locked/restricted items: 2 metadata-only
- Counsel signoff: COUNSEL_SIGNOFF_PENDING
- External submission authority: NOT_AUTHORIZED

## Prohibited Data

The workload model must not contain confidential legal text, document body text, privileged content, locked/restricted content, raw source excerpts, passwords, tokens, cookies, auth headers, database URLs, or service keys.

## Mutation Boundary

The workload model is read-only. It must not create document rows, vectors, ingestion runs, source-resolution records, reviewer assignment records, signoff records, or schema/RLS/policy changes.
