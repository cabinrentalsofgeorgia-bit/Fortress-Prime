# Fortress Legal Internal Pilot Incident and Rollback Drill - 2026-05-06

Status: TABLETOP_DRILLS_READY

All drills are tabletop/read-only unless a real production safety issue requires rollback.

| Scenario | Detection | Immediate Action | Escalation | Rollback Path | Evidence Required | Standing Label |
| --- | --- | --- | --- | --- | --- | --- |
| Reviewer sees unsupported assertion | Excluded-source marker or source_missing confidence | Keep item excluded | Source reviewer | None unless UI regression | item ID/category only | COUNSEL_SIGNOFF_PENDING |
| Source link breaks | checker/API or source lane flag | Keep unresolved | Source reviewer | Revert source-link UI/code if regression | sanitized route/status | NOT_AUTHORIZED |
| Contradiction severity escalates | contradiction queue severity | Human contradiction review | counsel/senior reviewer | None unless UI regression | contradiction ID only | NOT FINAL LEGAL ADVICE |
| Draft work product relies on excluded source | governance/checker mismatch | Stop review use of section | counsel/operator | revert offending code/data view | section ID only | BLOCKED until corrected |
| Checker fails feature alignment | checker output | Stop pilot | platform owner | revert latest deployment | checker JSON | PRODUCTION_INTERNAL_PILOT_BLOCKED |
| Deployment verifier fails | verifier output | Stop pilot | platform owner | runtime rollback artifact | verifier JSON | PRODUCTION_INTERNAL_PILOT_BLOCKED |
| Unauthenticated endpoint returns non-401 | verifier guard failure | Stop pilot immediately | security/platform | rollback and inspect route guard | path/status only | PRODUCTION_INTERNAL_PILOT_BLOCKED |
| Restricted-content boundary warning | metadata-only mismatch | Stop affected workflow | privilege/counsel | rollback UI/API exposing risk | no content excerpts | PRODUCTION_INTERNAL_PILOT_BLOCKED |
| Rollback required after bad deploy | service/checker regression | Restore rollback artifact | platform owner | frontend/backend rollback references | service/checker status | prior standing label |
| Queue backlog exceeds threshold | throughput metrics | prioritize triage | queue manager | no rollback unless regression | aggregate counts only | IN_PROGRESS |

## Governance

No drill authorizes signoff, final legal conclusions, external submission, source promotion, ingestion, upload, vector writes, schema/RLS mutation, or locked-content inspection.
