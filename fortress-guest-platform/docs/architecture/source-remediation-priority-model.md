# Source Remediation Priority Model

## Model

`FORTRESS_SOURCE_REVIEW_PRIORITY_V1` ranks review work only. It does not resolve source issues.

Factors:

- materiality tier;
- item type;
- evidence-needed flag;
- counsel-review flag;
- locked/restricted flag.

## Priority Order

1. High-impact relied-upon gaps.
2. Contradiction candidates.
3. Broken evidence chains.
4. Unresolved signoff blockers.
5. Low-confidence but non-critical items.
6. Excluded metadata-only items.

## Current Queue

- Tier 1: 21
- Tier 2: 81
- Tier 3: 130
- Unsupported/missing source: 230
- Locked metadata-only: 2

## Automation Safety

The engine may compute `priority_score`, `review_lane`, and `confidence_state`. It may not change `source_status`, `signoff_status`, draft reliance, or evidence contents.
