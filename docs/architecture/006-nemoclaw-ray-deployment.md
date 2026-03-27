# 006 NemoClaw Ray Deployment

This document defines the operator path for moving NemoClaw from standalone node-local bootstrap into the live Fortress Prime Ray matrix. It is paired with `deploy/compute/v1.0_nemoclaw_ray_manifest.yaml` and assumes the four-node Ray baseline is already durable:

- `192.168.0.100` head
- `192.168.0.104` worker
- `192.168.0.105` worker
- `192.168.0.106` worker

## Intent

NemoClaw remains a singular sovereign control plane, but its execution substrate moves under Ray governance. The Alpha Orchestrator stays pinned to `spark-node-2` at `192.168.0.100`, while heavyweight execution fans out across Ray workers instead of ad hoc terminal-launched processes.

This preserves the doctrine already established in `005-nemoclaw-swarm-architecture.md`:

- config-driven `nemoclaw_orchestrator_url`
- no public ingress to orchestration
- local-first execution
- Redis and PostgreSQL as authoritative choreography and state layers

## Live Ray Baseline

The cluster is already operating with systemd-managed Ray units:

- `fortress-ray-head.service` on `192.168.0.100`
- `fortress-ray-worker.service` on `192.168.0.104`
- `fortress-ray-worker.service` on `192.168.0.105`
- `fortress-ray-worker.service` on `192.168.0.106`

The canonical health command is:

```bash
tools/cluster/check_ray_cluster_health.sh
```

This command is the preflight gate for every NemoClaw Ray rollout.

## Deployment Contract

The canonical deployment contract lives in:

- `deploy/compute/v1.0_nemoclaw_ray_manifest.yaml`

The contract fixes these deployment truths:

- Head address is `192.168.0.100:6390`
- Ray dashboard is `http://192.168.0.100:8265`
- NemoClaw control-plane boundary is now `http://192.168.0.100:8000`
- OpenShell gateway health remains `http://127.0.0.1:8080/health`
- NemoClaw local dashboard remains `http://127.0.0.1:18789`

## Rollout Sequence

### Strict Rollout Sequence

To deploy Nemoclaw updates across the Ray worker matrix and ensure the local execution lanes are active, you must execute this sequence precisely from the `.100` command node:

1. `./tools/cluster/check_ray_cluster_health.sh`
2. `./tools/cluster/propagate_openshell.sh`
3. `./tools/cluster/launch_nemoclaw.sh`
4. `curl http://192.168.0.100:8000/health`

**Verification Post-Rollout:**

- Ensure the health endpoint returns `openshell_enabled: true` for `.104`, `.105`, and `.106`.
- Repeatedly probe `POST http://192.168.0.100:8000/api/agent/execute` to verify `execution_path=openshell_cli` is utilized by all three workers. Do not rely on LiteLLM fallback unless the local lane critically fails.

### Additional operator steps

- **NemoClaw leader (head only):** `./tools/cluster/bootstrap_nemoclaw_leader.sh` — run when installing or refreshing the leader on `192.168.0.100` (requires `NVIDIA_API_KEY` as documented in that script). This is not part of every rolling propagation but is required for fresh head installs.

- **Propagation details:** `propagate_openshell.sh` writes k3s secret `openshell-client-tls` material to `~/.openshell/profiles/nemoclaw/` (`client.crt`, `client.key`), verifies `openshell status -g nemoclaw`, and runs `openshell sandbox warm my-assistant`. Ray Serve workers detect the local lane via `openshell` binary + `client.key` (see `nemoclaw_serve.py`).

### Operational notes

- Bind Alpha Orchestrator execution to Ray governance: the router stays head-pinned on `.100`; heavy execution fans out through Ray placement.
- Keep the client boundary stable: callers use `Settings.nemoclaw_orchestrator_url` from `fortress-guest-platform/backend/core/config.py`, which resolves to the Ray Serve ingress on `.100:8000`.
- Throttling or disabling the head-node LiteLLM fallback is a **follow-up** only after all three workers are confirmed on the local OpenShell lane.

## Operational Runbook

### NemoClaw intent, prompt, and sandbox changes

Any change to **NemoClaw execution semantics**—including new or altered **`intent`** branches, **system/user prompts**, or the **OpenShell embedded sandbox script** in `fortress-guest-platform/backend/orchestration/nemoclaw_serve.py`—is baked into the Ray Serve deployment. The Kafka **event consumer** continues to POST directives to that orchestrator; it does not hot-reload orchestrator code.

**Required sequence after such changes** (from the `192.168.0.100` command node, repo root):

1. **Redeploy the Ray matrix (NemoClaw on Ray Serve):**
   ```bash
   cd /home/admin/Fortress-Prime
   ./tools/cluster/launch_nemoclaw.sh
   ```
   Wait until the rollout health check shows workers **`.104`**, **`.105`**, and **`.106`** green (and `curl -s http://192.168.0.100:8000/health` reflects `openshell_enabled: true` per worker as expected).

2. **Cycle the event consumer** so in-flight workers and logging align with the new orchestrator revision and any matching backend expectations:
   ```bash
   sudo systemctl restart fortress-event-consumer.service
   ```

3. **Verify telemetry** (optional but recommended during cutover):
   ```bash
   sudo journalctl -t fortress-event-consumer -f
   ```
   Produce a synthetic `reservation.confirmed` (or your staging equivalent) and confirm logs show the consumer dispatching to NemoClaw and persisting structured results.

**Broader rollouts** (OpenShell TLS, worker binaries, or Ray cluster issues) still follow the **Strict Rollout Sequence** in this document—`check_ray_cluster_health.sh`, `propagate_openshell.sh`, then `launch_nemoclaw.sh`—before the consumer restart above.

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

The canonical [`tools/cluster/propagate_openshell.sh`](../../tools/cluster/propagate_openshell.sh) uses **host** `sudo k3s kubectl` to read `openshell-client-tls`. Some recovery flows still use a **Docker** sidecar named `openshell-cluster-nemoclaw-<LAN-last-octet>`; see provision scripts if your worker only exposes kubectl inside that container.

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
