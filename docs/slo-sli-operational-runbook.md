# SLO/SLI Operational Runbook

## Scope
Applies to NUC controller, DGX compute nodes, core API services, and observability services.

## Service Objectives

| Service | SLI | SLO Target | Measurement Window |
|---|---|---|---|
| NUC Orchestrator | Successful reconciliation runs | >= 99% successful runs | 30 days |
| DGX Node Availability | Preflight healthy nodes / total nodes | >= 99.5% | 30 days |
| Gateway API | `/health` success rate | >= 99.9% | 30 days |
| Gateway Latency | p95 `/health` and core API routes | <= 300ms | 7 days |
| Inference (SWARM/HYDRA) | Successful inference responses | >= 99.0% | 30 days |
| Coverage Gate Stability | `bin/quality_gate.sh` pass rate on release candidates | >= 95% | 30 days |

## Alert Thresholds
- Critical: Availability below SLO for 15 continuous minutes.
- High: Error rate > 3% over 10 minutes.
- Medium: p95 latency breach for 30 minutes.

## On-Call Actions
1. Confirm health:
   - `bash bin/ops_health_snapshot.sh`
2. Validate governance and release checks:
   - `bash bin/governance_gate.sh`
   - `bash bin/quality_gate.sh`
3. Recover compute if degraded:
   - `bash deploy/compute/nuc_preflight.sh`
   - `bash deploy/compute/nuc_cluster_orchestrator.sh`
4. Escalate if unresolved:
   - Infrastructure lead + security lead + owner.

## Evidence Retention
- Store all gate outputs under `docs/ops-evidence/` per incident or release.
- Keep at least 90 days of evidence.
