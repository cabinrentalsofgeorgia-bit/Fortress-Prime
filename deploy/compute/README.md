# Crog-Fortress-AI Compute Orchestration

This directory implements a NUC-master, DGX-worker deployment pattern.

## Design Rules Enforced

- NUC acts as controller only (`ssh` + scheduling + proxy), not a heavy inference node.
- DGX nodes run NVIDIA-accelerated containers with `nvidia-container-toolkit`.
- Orchestration tolerates transient DGX network loss via retry/backoff SSH operations.

## Files

- `nodes.env.example` - controller and DGX inventory template.
- `node_inventory.env.example` - canonical Spark/DGX management IP inventory.
- `nuc_cluster_orchestrator.sh` - run on NUC to bootstrap and deploy DGX workloads.
- `nuc_preflight.sh` - run on NUC to verify DGX connectivity + NVIDIA runtime readiness.
- `dgx_remote_setup.sh` - pushed/executed remotely to enforce Docker + NVIDIA runtime.
- `docker-compose.compute.yml` - DGX-side inference compose template.

## Quick Start

1. Copy and edit environment config:
   - `cp deploy/compute/nodes.env.example deploy/compute/nodes.env`
   - Optional canonical inventory:
     - `cp deploy/compute/node_inventory.env.example deploy/compute/node_inventory.env`
2. Review DGX image and profile in:
   - `deploy/compute/docker-compose.compute.yml`
   - Optional: set per-node role profiles in `deploy/compute/nodes.env` via `DGX_NODE_PROFILES`.
   - Ensure `NGC_API_KEY` is set in `deploy/compute/nodes.env` or root `.env`.
   - Ensure `/mnt/fortress_nas/nim_cache` exists and is writable on every DGX node.
3. Run preflight from the NUC:
   - `bash deploy/compute/nuc_preflight.sh`
4. Run from the NUC:
   - `bash deploy/compute/nuc_cluster_orchestrator.sh`

## Per-Node Roles

Use profile overrides to pin workloads to specific DGX nodes.

- Global profile for all nodes:
  - `DGX_COMPOSE_PROFILE="swarm"`
- Per-node overrides:
  - `DGX_NODE_PROFILES="192.168.0.100:swarm,192.168.0.104:hydra,192.168.0.105:embeddings"`

If a node has an override, that profile is used; otherwise the global profile is used.

### Built-in Compose Profiles

- `swarm` - locked baseline profile (`nim-swarm`) currently on `nv-embedqa-e5-v5` for stability.
- `hydra` - deep-reasoning model (`nim-hydra`).
- `embeddings` - embedding service (`nim-embeddings`).
- `inference` - compatibility alias that currently maps to `nim-swarm`.

## Systemd Operation (NUC)

To run as a managed controller loop:

1. Install unit files:
   - `sudo cp deploy/compute/nuc-cluster-orchestrator.service /etc/systemd/system/`
   - `sudo cp deploy/compute/nuc-cluster-orchestrator.timer /etc/systemd/system/`
2. Reload and enable timer:
   - `sudo systemctl daemon-reload`
   - `sudo systemctl enable --now nuc-cluster-orchestrator.timer`
3. Inspect status:
   - `systemctl status nuc-cluster-orchestrator.timer`
   - `journalctl -u nuc-cluster-orchestrator.service -n 200 --no-pager`

## Notes

- If a DGX node is temporarily unreachable, orchestration retries with exponential backoff and reports failed nodes at the end.
- Script exit code is non-zero when one or more DGX nodes fail bootstrap/deploy.
- Preflight exits non-zero when one or more DGX nodes fail connectivity/runtime checks.

## Failure Matrix

### Orchestrator reasons (`nuc_cluster_orchestrator.sh`)

- `mkdir_failed`: could not create remote stack directory.
- `setup_script_copy_failed`: failed to transfer `dgx_remote_setup.sh`.
- `remote_setup_failed`: remote setup script returned non-zero.
- `compose_copy_failed`: compose file transfer failed.
- `compose_missing`: local compose file path missing.
- `registry_login_failed`: private registry auth failed.
- `compose_deploy_failed`: `docker compose pull/up` failed remotely.
- `post_deploy_health_timeout`: services failed health probe window.

### Preflight reasons (`nuc_preflight.sh`)

- `ssh_unreachable`: DGX node not reachable over SSH.
- `docker_or_nvidia_missing`: missing `docker` or `nvidia-smi`.
- `nvidia_runtime_validation_failed`: GPU container runtime check failed.

Both scripts print machine-readable summary lines suitable for ops snapshots:

- `PREFLIGHT_SUMMARY total=... reachable=... healthy=...`
- `PREFLIGHT_NODE host=... state=... reason=...`
- `node result summary (host|reason|code)` from orchestrator logs

## Remediation Runbook (Non-Destructive)

1. Run preflight from NUC:
   - `bash deploy/compute/nuc_preflight.sh`
2. For nodes with `ssh_unreachable`:
   - verify LAN route/VPN, host IP, `DGX_SSH_USER`, `DGX_SSH_PORT`.
3. For `docker_or_nvidia_missing`:
   - run orchestrator once to bootstrap runtime prerequisites.
4. For `nvidia_runtime_validation_failed`:
   - check remote `docker info` includes NVIDIA runtime.
   - re-run `dgx_remote_setup.sh` on affected node.
5. For deploy-stage failures:
   - verify compose profile mapping in `DGX_COMPOSE_PROFILE` / `DGX_NODE_PROFILES`.
   - confirm model image accessibility and registry credentials.
6. Re-run:
   - `bash deploy/compute/nuc_cluster_orchestrator.sh`

## Non-Destructive Operating Procedure

- These scripts are designed for reconcile/bootstrap only; they do not wipe disks or remove host data.
- Avoid manual destructive actions (`docker system prune -a`, filesystem cleanup) during orchestration windows.
- To disable post-deploy health probing temporarily (for debugging only):
  - set `DGX_POST_DEPLOY_HEALTHCHECK=false` in `nodes.env`.
- Keep NUC lightweight:
  - controller responsibilities only (SSH, scheduling, orchestration, proxy).
  - no persistent heavy inference/training workloads on NUC.

