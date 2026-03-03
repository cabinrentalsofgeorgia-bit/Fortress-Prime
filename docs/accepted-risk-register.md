# Accepted Risk Register

## Purpose
Track explicitly accepted residual risks with ownership, review date, and monitoring controls.

## Active Risks

| Risk ID | Severity | Description | Owner | Mitigation / Control | Review Date | Status |
|---|---|---|---|---|---|---|
| AR-001 | Medium | Scoped backend coverage is below strategic target (current baseline gate passes, target remains higher). | Engineering Lead | Enforced `bin/quality_gate.sh` + warning threshold in `bin/run_coverage.sh`; ongoing targeted test expansion for low-coverage modules. | 2026-03-15 | Accepted (time-boxed) |
| AR-002 | Medium | Some legacy modules still contain transitional compatibility aliases (to avoid breaking older scripts). | Platform Lead | Governance scanner blocks forbidden runtime references in core governed files; compatibility aliases documented and scheduled for deprecation. | 2026-03-20 | Accepted (time-boxed) |
| AR-003 | Low | CROG coverage step can be skipped if pytest is unavailable in host Python environment. | DevOps Lead | Explicit skip messaging in coverage gate, dependency bootstrap attempt, and manual follow-up in release checklist. | 2026-03-10 | Accepted |

## Review Workflow
1. Review all active risks weekly.
2. Convert accepted risks to fixed items when mitigation lands.
3. Escalate any expired risk without extension approval.
