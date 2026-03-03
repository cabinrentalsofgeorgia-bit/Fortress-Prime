# Disaster Recovery Runbook

## Recovery Goals
- **RTO:** 60 minutes for core API and orchestration.
- **RPO:** 15 minutes for critical operational data.

## Incident Classes
- Node outage (single DGX unavailable)
- Controller outage (NUC unavailable)
- Data plane outage (DB/queue/vector store unavailable)
- Security incident (credential exposure or unauthorized access)

## Recovery Procedure

### 1) Stabilize and Contain
- Freeze deployments.
- Record start time and affected components.
- Execute:
  - `bash bin/ops_health_snapshot.sh`

### 2) Restore Control Plane (NUC)
- Restore NUC network + docker service.
- Validate orchestrator timer:
  - `systemctl status nuc-cluster-orchestrator.timer`

### 3) Restore Compute Plane (DGX)
- Run from NUC:
  - `bash deploy/compute/nuc_preflight.sh`
  - `bash deploy/compute/nuc_cluster_orchestrator.sh`

### 4) Restore Application Services
- Reconcile compose stack:
  - `docker compose up -d`
- Validate:
  - `curl -sf http://127.0.0.1:8000/health`

### 5) Validate Controls
- `bash bin/governance_gate.sh`
- `bash bin/quality_gate.sh`

### 6) Post-Incident
- Create evidence package with:
  - root cause,
  - timeline,
  - mitigations,
  - rollback details,
  - accepted risks.
