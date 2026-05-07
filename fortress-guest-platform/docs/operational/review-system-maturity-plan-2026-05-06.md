# Fortress Legal Review System Maturity Plan - 2026-05-06

## Improvements

- Add Remediation Maturity / Review Queue panel to the Strategy Packet surface.
- Show unresolved counts, missing-source counts, restricted metadata-only counts, evidence-needed counts, counsel-review counts, and verified subset counts.
- Show prioritized human review queue with review lane and confidence state.
- Show explicit `excluded from relied-upon sections` markers.
- Show explicit `metadata only restricted` markers.
- Show Evidence Lineage chain.

## Reviewer Workflow

Reviewer actions remain outside automation:

- attach an existing eligible source reference;
- explicitly exclude item from relied-upon sections;
- return item for revision;
- route contradiction to counsel;
- preserve locked item as metadata-only.

## Governance

No UI element records signoff, final legal conclusions, or external submission authority. The panel is a derived read model and does not mutate evidence.
