# Remediation Observability Map

## Metrics

- unresolved issue count;
- review lane counts;
- confidence distribution;
- priority queue depth;
- contradiction review count;
- evidence-needed count;
- locked/restricted metadata-only count;
- verified subset count;
- limited packet availability;
- counsel signoff status.

## Surfaces

- Backend endpoint: `/api/internal/legal/cases/{slug}/remediation-maturity`
- UI panel: Remediation Maturity / Review Queue
- Checker assertions: remediation maturity, review confidence, evidence lineage, unresolved-source exclusion.

## Exposure Rules

Metrics must not include confidential legal text, source excerpts, locked/restricted content, auth state, cookies, tokens, or secrets.
