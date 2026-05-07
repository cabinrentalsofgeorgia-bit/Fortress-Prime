# Fortress Legal Reviewer Workload Balancing Model

Status: METADATA_ONLY_WORKLOAD_BALANCING_ACTIVE

## Model

Reviewer workload balancing is derived from safe queue metadata. The model calculates workload weight from priority score and displays distribution by reviewer role hint.

## Metrics

- total workload weight
- unassigned items
- source-review items
- counsel/senior-review items
- privilege metadata-review items
- critical SLA items
- role-hint distribution

## Use

Queue managers may use workload metrics to plan internal review coverage. The metrics are operational only and do not change legal status or evidence status.

## Boundaries

- No persistent assignment is created.
- No source issue is resolved.
- No item is promoted into a relied-upon section.
- No legal conclusion or signoff is inferred.
- No locked/restricted content is accessed.

## Future Write Path Requirements

A future assignment write path must be separately authorized, authenticated, audit logged, rollback-capable, and constrained to review routing only.
