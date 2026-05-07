# Fortress Legal Source Remediation Operating Model - 2026-05-06

## Current Backlog

- Source integrity blockers started: 297
- Source-link repair verified: 15
- Targeted source completion verified: 50 additional items
- Remaining unresolved source issues: 232
- Unsupported or missing source-link items: 230
- Locked/privilege-limited metadata-only items: 2

## Operating Principle

The remaining 232 issues are a governed source-work queue, not an automated legal conclusion queue.

## Lanes

| Lane | Count | Handling |
| --- | ---: | --- |
| Missing/unsupported source links | 230 | Operator/counsel source-reference attachment, explicit exclusion, or return to remediation. |
| Locked/privilege-limited | 2 | Counsel-only metadata review. No agent content access. |

## Safe Automation

Allowed:

- count and classify backlog items;
- generate summary-safe queue reports;
- check manifest invariants;
- create next-action recommendations;
- record rollback/evidence metadata.

Forbidden:

- inspect locked/restricted content;
- rerun ingestion or vectorization;
- silently mark unsupported items verified;
- change relied-upon draft sections;
- create final legal conclusions;
- record counsel signoff.

## Resolution Labels

Use review-scope labels only:

- `corrected_verified_for_review_use`
- `excluded_from_relied_upon_sections`
- `counsel_returned_for_revision`
- `locked_metadata_only_preserved`
- `unsupported_source_needed`

Avoid final-proof or final-advice language.

## Evidence Requirements

Every future remediation pass must record:

- execution ID;
- source manifests used;
- item count processed;
- added/changed/remained counts;
- locked-content boundary;
- no ingestion/vector/schema/signoff mutation;
- rollback identifiers.
