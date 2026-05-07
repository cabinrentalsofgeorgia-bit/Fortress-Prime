# Fortress Legal Review Analytics Model

Status: REVIEW_ANALYTICS_ACTIVE_FOR_METADATA_SAFE_OPERATIONS

## Purpose

Review analytics give operators and counsel a safe operational picture of queue health and confidence distribution. Analytics are derived from manifest metadata and do not include legal document contents.

## Metrics

- remediation queue depth
- contradiction queue depth
- evidence navigation item count
- high-priority item count
- unassigned reviewer-owner placeholder count
- excluded-source ratio
- verified subset count
- confidence distribution
- review lane distribution
- item type distribution
- human-review-required count
- safe auto-resolution count

## Confidence Bands

- source_missing
- restricted_metadata_only
- counsel_interpretation_required
- unresolved_unsupported

## Throughput Model

The initial model records:

- baseline queue depth
- completed this phase
- safe auto-resolutions
- human review required

All current unresolved items remain human-review or evidence-review candidates. No unresolved item is auto-resolved.

## Privacy and Governance

- Analytics contain IDs, types, counts, tiers, statuses, and labels only.
- Analytics contain no source excerpts, document bodies, secrets, auth state, or locked/restricted contents.
- Analytics do not imply counsel signoff or final legal conclusions.
