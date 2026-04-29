# 006 NemoClaw Ray Deployment

This document defines the operator path for moving NemoClaw from standalone node-local bootstrap into the live Fortress Prime Ray matrix. It is paired with `deploy/compute/v1.0_nemoclaw_ray_manifest.yaml`.

> **2026-04-29 — superseding ADR-003 (v2):** the Ray cluster narrows from "all four current nodes" to **the dedicated inference cluster only — Sparks 4, 5, 6**. The 2026-04-29 ADR-003 (Dedicated inference cluster on Sparks 4/5/6) explicitly carves inference compute out of app-tier Sparks 1, 2, 3. NemoClaw's orchestrator boundary remains on spark-2 control plane (`100.80.122.100:8000`) — the orchestrator dispatches to the inference cluster but is **not** a Ray host itself.

## Intent

NemoClaw remains a singular sovereign control plane, but its execution substrate moves under Ray governance. The Alpha Orchestrator stays pinned to **spark-node-2 control plane** (`100.80.122.100:8000`), while heavyweight execution fans out across the dedicated inference Ray cluster (Sparks 4/5/6 per ADR-003 v2) instead of ad hoc terminal-launched processes.

This preserves the doctrine already established in `005-nemoclaw-swarm-architecture.md`:

- config-driven `nemoclaw_orchestrator_url`
- no public ingress to orchestration
- local-first execution
- Redis and PostgreSQL as authoritative choreography and state layers

## Live Ray Baseline (post-ADR-003 v2)

The Ray cluster is the inference-tier cluster only. Worker placement follows ADR-003's phased rollout:

| Service | Host | Spark | Phase |
|---|---|---|---|
| `fortress-ray-head.service` | spark-5 (`192.168.0.109`) | Spark-5 | **Phase 1+** (active today) |
| `fortress-ray-worker.service` | spark-6 (`192.168.0.115`) | Spark-6 | **Phase 2** (cable-gated — 10GbE → ConnectX) |
| `fortress-ray-worker.service` | spark-4 (`192.168.0.106`) | Spark-4 | **Phase 3** (Acquisitions/Wealth co-tenancy gated) |

**Removed (no longer Ray hosts under ADR-003 v2):**
- `192.168.0.100` (spark-2) — was head; now the **NemoClaw orchestrator + LiteLLM gateway** host. Dispatches to the inference cluster, does not host Ray.
- `192.168.0.104` (spark-1) — was worker; now the **Fortress Legal app** host. No inference tenancy.
- `192.168.0.105` (spark-3) — was worker; now the **Financial + Acquisitions + Wealth app** host (when provisioned). No inference tenancy.

The canonical health command is:

```bash
tools/cluster/check_ray_cluster_health.sh
```

This command is the preflight gate for every NemoClaw Ray rollout.

## Deployment Contract

The canonical deployment contract lives in:

- `deploy/compute/v1.0_nemoclaw_ray_manifest.yaml`

The contract fixes these deployment truths:

- Head address is `spark-5:6390` (post-ADR-003 v2; was `192.168.0.100:6390` under the four-node baseline)
- Ray dashboard is `http://spark-5:8265`
- **NemoClaw orchestrator** control-plane boundary remains `http://192.168.0.100:8000` (spark-2 control plane). Orchestrator dispatches to the Ray inference cluster on spark-5; it is not itself a Ray node.
- OpenShell gateway health remains `http://127.0.0.1:8080/health`
- NemoClaw local dashboard remains `http://127.0.0.1:18789`

## Rollout Sequence

### Deployment rollout sequence (decentralized execution)

To ensure worker-local OpenShell lanes are armed before Ray Serve replicas start failing over to head inference, execute in this strict order:

1. **Ray matrix verification:** `./tools/cluster/check_ray_cluster_health.sh`  
   Ensure `192.168.0.100`, `192.168.0.104`, `192.168.0.105`, and `192.168.0.106` are healthy and Ray reports them `ALIVE`.

2. **NemoClaw leader (head only):** `./tools/cluster/bootstrap_nemoclaw_leader.sh`  
   Run when installing or refreshing the leader on `192.168.0.100` (requires `NVIDIA_API_KEY` as documented in that script).

3. **Worker propagation:** `./tools/cluster/propagate_openshell.sh`  
   On each worker (`.104`, `.105`, `.106`), re-extracts OpenShell client TLS from the local k3s secret `openshell-client-tls`, refreshes `~/.config/openshell/gateways/nemoclaw/mtls/`, verifies `openshell status -g nemoclaw`, and warms the `my-assistant` sandbox.  
   Do not deploy Serve before this step if you expect all workers to report `openshell_enabled: true` in health.

4. **Serve redeployment:** `./tools/cluster/launch_nemoclaw.sh`  
   Materializes the FastAPI orchestrator on the Ray head and distributes pinned worker replicas.

5. **Health verification:** `curl -s http://192.168.0.100:8000/health`  
   Confirm each worker target lists `openshell_enabled: true` after propagation.

6. **Canary:** Run a masked low-risk `POST /api/agent/execute` and confirm `execution_path=openshell_cli` when the round-robin lands on each worker.

### Operational notes

- Bind Alpha Orchestrator execution to Ray governance: the router stays head-pinned on `.100`; heavy execution fans out through Ray placement.
- Keep the client boundary stable: callers use `Settings.nemoclaw_orchestrator_url` from `fortress-guest-platform/backend/core/config.py`, which resolves to the Ray Serve ingress on `.100:8000`.
- Throttling or disabling the head-node LiteLLM fallback is a **follow-up** only after all three workers are confirmed on the local OpenShell lane.

## OpenShell Worker IaC

The OpenShell worker sidecar is now treated as repository-managed infrastructure instead of an ad hoc export tarball. The canonical template lives in:

- `deploy/compute/openshell/worker-sidecar-template.yaml`

This template intentionally excludes Kubernetes `Secret` objects. Node-local OpenShell PKI must be minted first, then injected into the target cluster at provision time. This keeps secrets out of Git while still making the workload shape declarative and repeatable.

### New Spark node lifecycle

1. Join the node to the LAN and UFW policy.
2. Generate node-local OpenShell PKI on the worker.
3. Run `./tools/cluster/provision_worker.sh <IP>` from the head or operator host.
4. Run `./tools/cluster/propagate_openshell.sh` to refresh local client TLS material and warm `my-assistant`.
5. Redeploy Ray Serve with `./tools/cluster/launch_nemoclaw.sh`.

The provisioning script materializes the template with the worker's octet, creates or updates the required TLS secrets from the node-local PKI, writes `metadata.json` for the local OpenShell client profile, and applies the rendered manifest directly to the target cluster over SSH.

Example:

```bash
./tools/cluster/provision_worker.sh 192.168.0.105
./tools/cluster/provision_worker.sh 192.168.0.106
```

If the worker exposes host `k3s`, the script uses `sudo k3s kubectl`. If the worker instead exposes the OpenShell runtime through the Docker container convention `openshell-cluster-nemoclaw-<octet>`, the script applies through `docker exec ... kubectl`. This preserves the repo-driven workflow across both currently observed worker layouts.

## Non-Negotiables

- Do not hardcode worker-node identity into clients.
- Do not expose ports `8080`, `18789`, `8000`, `6390`, or `8265` publicly.
- Do not regress from systemd-supervised Ray back to terminal-launched workers.
- Do not bypass Redis/PostgreSQL choreography with process-local state.
- Do not send raw sovereign payloads outside the local trust boundary.

## Current Known Quirk

Ray may retain a historical `DEAD` node record after a worker restart. The health gate treats the `ALIVE` node IP set as authoritative and validates that it matches the four-node baseline. This is acceptable for rollout so long as:

- `tools/cluster/check_ray_cluster_health.sh` passes
- total cluster resources remain `80 CPU / 4 GPU`
- expected `ALIVE` nodes are `.100`, `.104`, `.105`, and `.106`

## APPENDIX: OpenShell sidecar disaster recovery

The Kubernetes YAML for the `openshell` namespace, `openshell-client-tls` secret, and related workloads is **not** checked into this repository. If a DGX Spark worker is reprovisioned or loses k3s state, operators must rebuild the sidecar from a surviving node (typically `192.168.0.104`) or from an offline backup of the export tarball.

The Ray automation in [`tools/cluster/propagate_openshell.sh`](../../tools/cluster/propagate_openshell.sh) assumes a **Docker** container on each worker named `openshell-cluster-nemoclaw-<LAN-last-octet>` (e.g. `openshell-cluster-nemoclaw-105` on `192.168.0.105`). Mutate exported manifests so names and labels match that convention on the target host.

### 1. Binary mirror (global path)

Run from the command center or head (`192.168.0.100`), with SSH access to workers:

```bash
# Clone openshell from .104 to .105 (binary must exist on .104, e.g. ~/.local/bin or PATH)
ssh admin@192.168.0.104 'cat "$(command -v openshell)"' | ssh admin@192.168.0.105 'cat > /tmp/openshell && chmod +x /tmp/openshell && sudo mv /tmp/openshell /usr/local/bin/openshell'

# Clone openshell from .104 to .106
ssh admin@192.168.0.104 'cat "$(command -v openshell)"' | ssh admin@192.168.0.106 'cat > /tmp/openshell && chmod +x /tmp/openshell && sudo mv /tmp/openshell /usr/local/bin/openshell'
```

Non-interactive SSH often has a minimal `PATH`, so `command -v openshell` may be empty on `.104` even when the binary exists. If `cat` fails with “No such file or directory”, use the canonical path:

```bash
SRC=/home/admin/.local/bin/openshell
ssh admin@192.168.0.104 "cat $SRC" | ssh admin@192.168.0.105 'cat > /tmp/openshell && chmod +x /tmp/openshell && sudo mv /tmp/openshell /usr/local/bin/openshell'
ssh admin@192.168.0.104 "cat $SRC" | ssh admin@192.168.0.106 'cat > /tmp/openshell && chmod +x /tmp/openshell && sudo mv /tmp/openshell /usr/local/bin/openshell'

# Verify
ssh admin@192.168.0.105 'command -v openshell && openshell --version'
ssh admin@192.168.0.106 'command -v openshell && openshell --version'
```

If your canonical install matches Ray’s default (`/home/admin/.local/bin/openshell`), mirror to that path instead and ensure login shells include it in `PATH`, or set `NEMOCLAW_OPENSHELL_BIN` in the Ray worker environment.

### 2. Kubernetes DNA extraction (on the surviving worker, e.g. `.104`)

On `.104`, use whichever `kubectl` can reach the cluster (host `k3s kubectl`, or `kubectl` inside the OpenShell tooling container if that is how you manage the namespace). Example using host `kubectl` against k3s:

```bash
mkdir -p /tmp/openshell-export
cd /tmp/openshell-export

kubectl get namespace openshell -o yaml | grep -v -e '^  uid:' -e '^  resourceVersion:' -e '^  creationTimestamp:' -e '^status:' > 01-namespace.yaml
kubectl -n openshell get secret openshell-client-tls -o yaml | grep -v -e '^  uid:' -e '^  resourceVersion:' -e '^  creationTimestamp:' > 02-secret.yaml
kubectl -n openshell get deployment -o yaml | grep -v -e '^  uid:' -e '^  resourceVersion:' -e '^  creationTimestamp:' -e '^status:' -e '^  generation:' > 03-workload.yaml
```

Review `03-workload.yaml` for **Services**, **ConfigMaps**, or other objects; export and scrub them the same way if the deployment depends on them. Stripping fields with `grep` is quick but imperfect for nested YAML; for production backups prefer `kubectl get ... -o yaml` plus manual edit, or tools such as `kubectl-neat`, after verifying the output applies cleanly.

Package for transfer:

```bash
tar -czvf openshell-manifests.tar.gz *.yaml
```

### 3. Mutation and deploy (on each new worker, e.g. `.105` then `.106`)

Copy `openshell-manifests.tar.gz` to the target, extract, **mutate node-specific strings** (container or deployment names, hostnames, or image pull secrets as required by your export), then apply:

```bash
tar -xzvf openshell-manifests.tar.gz
# Example: align names with the octet for this host (adjust pattern to match your YAML)
sed -i 's/nemoclaw-104/nemoclaw-105/g' 03-workload.yaml

sudo k3s kubectl apply -f 01-namespace.yaml
sudo k3s kubectl apply -f 02-secret.yaml
sudo k3s kubectl apply -f 03-workload.yaml
```

Repeat on `.106` with `s/nemoclaw-104/nemoclaw-106/g` (or the appropriate substitution).

Confirm:

```bash
sudo k3s kubectl get pods -n openshell -o wide
docker ps --format '{{.Names}}' | grep openshell-cluster-nemoclaw
```

### 4. Arm Ray workers (from head)

After sidecars and binaries are correct on **all** workers:

```bash
./tools/cluster/check_ray_cluster_health.sh
./tools/cluster/propagate_openshell.sh
./tools/cluster/launch_nemoclaw.sh
curl -s http://192.168.0.100:8000/health
```

Expect `[SUCCESS]` from `propagate_openshell.sh` for `192.168.0.104`, `.105`, and `.106`, and `openshell_enabled: true` for each worker in the health JSON.
