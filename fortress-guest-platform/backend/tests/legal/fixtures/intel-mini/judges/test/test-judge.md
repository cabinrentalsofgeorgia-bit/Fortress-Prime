---
schema_version: 1
slug: test-judge
display_name: The Honorable Test Judge
court: test-court
status: active
authoring_mode: manual_seed
sources:
  - source: fixture
    retrieved: 2026-05-01
operator_relevance:
  matters_assigned:
    - test-matter-i
    - test-matter-ii
  prior_dispositions_against_operator: 1
  critical_context: |
    SAME JUDGE for fixture matters I and II. This text is the canonical
    same-judge insight that the resolver surfaces via the @ frontmatter
    field token.
---

## Operator-relevant context

<!-- authoring: manual -->
Body text for the operator-relevant context section. The resolver should
strip the authoring annotation comment above and emit only this prose.

## Standing order summary

Body text for standing order summary — should NOT appear when the default
section set is requested.

## Strategic implications

Body text for strategic implications. Resolver default joins this with
operator-relevant context using a blank-line separator.

## Sources

Auto-generated section — irrelevant to default token resolution.
