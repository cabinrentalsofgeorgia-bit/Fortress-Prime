# Evidence Lineage Model

## Lineage Chain

1. source_integrity
2. source_remediation
3. source_link_repair
4. targeted_source_completion
5. limited_signoff_candidate_packet
6. remediation_maturity_read_model

## Lineage Fields

Each derived queue item should preserve, where available:

- source validation ID;
- source remediation ID;
- source link repair ID;
- targeted source completion ID;
- limited signoff review ID;
- manifest execution IDs;
- manifest checksums;
- rollback reference.

## Mutation Rules

- Read models may derive queue state.
- Read models may not mutate evidence.
- Silent state transitions are forbidden.
- Any future write must create an additive audit event with rollback identifiers.

## Restricted Handling

Locked/restricted documents remain metadata-only. Agent-accessible lineage may show IDs, flags, and review status only.
