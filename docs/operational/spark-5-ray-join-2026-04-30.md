# spark-5 Ray cluster join — discovery + plan

**Date:** 2026-04-30
**Branch:** `chore/spark-5-ray-join-2026-04-30`
**Driver:** PR #309 / PR #310 audits found spark-5 BRAIN healthy on
`:8100` but absent from the Ray cluster. ADR-003 §5.1 designated
spark-5 as Ray head; current reality is spark-2 holds the head role
and spark-5 is detached. Operator decision: keep head on spark-2,
**add spark-5 as a worker**.

> **Status: DISCOVERY ONLY. Ray join NOT performed.** The brief
> required halting before any state-changing action on spark-5 once
> the absence of a `fortress-ray-worker.service` unit was confirmed.
> Operator review of §3 (deploy plan) is required before the join is
> executed.

---

## 1. Pre-join Ray cluster (spark-2 head)

| Field | Value |
|---|---|
| Head node IP | `192.168.0.100` (spark-2) |
| Head GCS port | `6390` (NOT default 6379 — spark-2 has redis on 6379) |
| Dashboard | `192.168.0.100:8265` |
| Ray version (head) | **2.54.0** |
| Ray binary path | `/home/admin/.local/bin/ray` |
| Cluster total nodes (records) | 9 |
| **ALIVE nodes** | **4** |
| Stale DEAD records | 5 (ghost nodes from prior crashes/reboots) |
| Resources (totals) | 80 CPU, **4 GPU (GB10)**, 162.36 GiB memory, 69.58 GiB object store |

### Live members (pre-join)

| Node IP | Role | GPU | CPU | Memory | Notes |
|---|---|---|---|---|---|
| 192.168.0.100 | Head (spark-2) | 1 GB10 | 20 | 1.18 GiB | Head process is bookkeeping-only; spark-2 is busy with control plane. |
| 192.168.0.104 | Worker (spark-1 per hostname `spark-node-1`) | 1 GB10 | 20 | 37.01 GiB | active |
| 192.168.0.105 | Worker (spark-3 per hostname `spark-3`) | 1 GB10 | 20 | 42.55 GiB | active |
| 192.168.0.106 | Worker (Spark-4 per hostname) | 1 GB10 | 20 | 81.62 GiB | active |

> **Note on naming inversion** (memory `project_spark_network_topology.md`):
> SSH/hostname names do not align with the IP-based naming used in
> ops docs. IP `192.168.0.109` = SSH hostname `spark-5` — that is the
> target for this work.

### Stale DEAD records (cleanup candidates, not blocking)

5 entries on 192.168.0.104, 105, 106 with state DEAD (`missing too many
heartbeats`). These are old node IDs from prior reboots/crashes still
visible in `ray list nodes`. They do not affect scheduling but bloat
the listing. **Out of scope for this PR.**

---

## 2. spark-5 current state (`192.168.0.109`, hostname `spark-5`)

| Item | Value |
|---|---|
| Hostname | `spark-5` |
| Architecture | aarch64 (ARM64) |
| GPU | NVIDIA GB10 (Spark) |
| RAM | **121 GiB total, 112 GiB used, 1.5 GiB free** ← already at 92% utilization |
| Swap | 0 B (none configured) |
| BRAIN service health | `{"object":"health.response","message":"ready","status":"ready"}` — healthy |
| BRAIN port | `:8100` (note: not in `ss -tlnp` output, likely bound inside docker netns) |
| Fortress-Prime repo | present at `/home/admin/Fortress-Prime`, on `main`, **stale at commit `5399896` (Feb 2026)** |
| `tools/cluster/run_ray_worker.sh` | present (came with Feb checkout) |
| `tools/cluster/ray_runtime_common.sh` | present |
| Python | `/usr/bin/python3` 3.12.3, pip 24.0 |
| **Ray installed?** | **NO.** `ModuleNotFoundError: No module named 'ray'`; no `/home/admin/.local/bin/ray`. |
| `fortress-ray-worker.service` unit | does not exist |
| `/etc/default/fortress-ray-worker` env | does not exist |
| Ray processes | none running |

### Why this matters

The brief expected to find a dormant `fortress-ray-worker.service` that
just needed `enable + start`. **The reality is that spark-5 was never
provisioned as a Ray worker** — Ray itself is not installed, and no
unit exists. This is a heavier change than a one-line systemctl, which
is why the brief's halt-condition is met.

---

## 3. Worker template (verbatim from spark-1/3/4)

All three live workers run an identical unit + script + env-file
triplet. The only per-host variable is `RAY_NODE_IP` in the env file.

### 3.1 `/etc/systemd/system/fortress-ray-worker.service`

```ini
[Unit]
Description=Fortress Ray Worker
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=60
StartLimitBurst=10

[Service]
Type=simple
User=admin
Group=admin
WorkingDirectory=/home/admin/Fortress-Prime
Environment=HOME=/home/admin
EnvironmentFile=-/etc/default/fortress-ray-worker
ExecStartPre=/bin/bash -lc '/home/admin/Fortress-Prime/tools/cluster/stop_ray_runtime.sh >/dev/null 2>&1 || true'
ExecStart=/home/admin/Fortress-Prime/tools/cluster/run_ray_worker.sh
ExecStop=/home/admin/Fortress-Prime/tools/cluster/stop_ray_runtime.sh
Restart=always
RestartSec=5
KillMode=mixed
TimeoutStartSec=30
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
LimitNOFILE=65536
SyslogIdentifier=fortress-ray-worker
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 3.2 `/etc/default/fortress-ray-worker` (spark-5 specific)

```env
RAY_NODE_IP=192.168.0.109
RAY_HEAD_ADDRESS=192.168.0.100:6390
RAY_BIN=/home/admin/.local/bin/ray
```

(Other workers use 192.168.0.104 / 105 / 106 for their respective
`RAY_NODE_IP`. Head address + binary path are identical.)

### 3.3 `tools/cluster/run_ray_worker.sh` (already in repo, no change)

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/ray_runtime_common.sh"

RAY_BIN="$(resolve_ray_bin)"
RAY_NODE_IP="${RAY_NODE_IP:?RAY_NODE_IP must be set}"
RAY_HEAD_ADDRESS="${RAY_HEAD_ADDRESS:?RAY_HEAD_ADDRESS must be set}"

exec "${RAY_BIN}" start \
  --address="${RAY_HEAD_ADDRESS}" \
  --node-ip-address="${RAY_NODE_IP}" \
  --disable-usage-stats \
  --block
```

---

## 4. Deploy plan (operator to approve before execution)

### Step A — install Ray on spark-5

```bash
ssh admin@192.168.0.109 'pip3 install --user "ray==2.54.0"'
ssh admin@192.168.0.109 '/home/admin/.local/bin/ray --version'  # expect 2.54.0
```

> Ray 2.54.0 publishes ARM64 wheels for Python 3.12 on PyPI. No build-from-source needed.

### Step B — write env file (spark-5 specific IP)

```bash
ssh admin@192.168.0.109 'sudo tee /etc/default/fortress-ray-worker <<EOF
RAY_NODE_IP=192.168.0.109
RAY_HEAD_ADDRESS=192.168.0.100:6390
RAY_BIN=/home/admin/.local/bin/ray
EOF
sudo chmod 644 /etc/default/fortress-ray-worker'
```

### Step C — install systemd unit (verbatim copy from spark-1/3/4)

Either:
1. `scp` from a live worker:
   ```bash
   ssh admin@192.168.0.104 'sudo cat /etc/systemd/system/fortress-ray-worker.service' \
     | ssh admin@192.168.0.109 'sudo tee /etc/systemd/system/fortress-ray-worker.service >/dev/null'
   ```
2. Or paste the §3.1 body via a `sudo tee` heredoc.

Then:
```bash
ssh admin@192.168.0.109 '
  sudo systemctl daemon-reload
  sudo systemctl enable fortress-ray-worker.service
  sudo systemctl start fortress-ray-worker.service
  sleep 5
  systemctl status fortress-ray-worker.service --no-pager | head -20
'
```

### Step D — verify from spark-2 (head)

```bash
ssh admin@192.168.0.100 '/home/admin/.local/bin/ray status 2>&1 | head -30'
ssh admin@192.168.0.100 '/home/admin/.local/bin/ray list nodes --limit 30 2>&1 | head -60'
```

Expected:
- spark-5 (`192.168.0.109`) appears as `IS_HEAD_NODE: False`, `STATE: ALIVE`.
- ALIVE node count goes from 4 → **5**.
- `Total Usage` line shows 100.0 CPU, **5.0 GPU**, ~280+ GiB memory.

### Step E — BRAIN regression check (defensive)

```bash
curl -sS --max-time 5 http://192.168.0.109:8100/v1/health/ready
# expect: {"object":"health.response","message":"ready","status":"ready"}
```

---

## 5. Risks the operator needs to weigh before approving

| # | Risk | Severity | Notes |
|---|---|---|---|
| R1 | spark-5 RAM is at **92% utilization** before any Ray daemon. Raylet + gcs_server + plasma store typically consume ~1–2 GiB. Adding Ray workloads (remote tasks scheduled here) could exhaust memory and OOM-kill BRAIN. | **HIGH** | Mitigation: cap object store via `RAY_OBJECT_STORE_MEMORY` env, or add `--memory` / `--object-store-memory` to the worker `ray start` invocation. Brief did not authorize unit-file edits — surface this and let operator decide. |
| R2 | Ray version drift: head is 2.54.0; spark-5 install must match exactly or join fails with "version mismatch" warnings. | MED | Pin `ray==2.54.0`. Verified head version explicitly above. |
| R3 | Fortress-Prime repo on spark-5 is **stale** (Feb 2026 commit `5399896` vs current main). `tools/cluster/run_ray_worker.sh` is present today, so deploy works — but a future `git pull` on spark-5 could move scripts and break the unit. | LOW (now) / MED (future) | Worker scripts are stable. After cutover, plan a controlled `git pull` on spark-5 with BRAIN considered. |
| R4 | Adding spark-5 as Ray worker exposes its GPU to remote scheduling. If Ray jobs are submitted that target `accelerator_type:GB10`, they may land on spark-5 and contend with BRAIN for GPU memory. | MED | BRAIN already owns the GPU. Ray cannot dispatch CUDA tasks unless invoked with `num_gpus=1`. Verify no current production job pins `accelerator_type:GB10`. |
| R5 | swap=0 on spark-5 means OOM is hard. With BRAIN at 112 GiB RSS, any Ray-scheduled task that allocates > 1.5 GiB will trigger OOM. | HIGH (paired with R1) | Same mitigation as R1: bound Ray's footprint. |
| R6 | `pip install --user` on spark-5 runs as `admin` and is a state change. | LOW (single user-local install) | Brief defers to operator. |
| R7 | Stale DEAD nodes in `ray list` already (5 of them). Adding spark-5 won't increase noise but also won't fix it. | NONE | Out of scope. |

### Recommended operator decision

**Before approving the deploy plan, decide:**

1. Is BRAIN's 92% RAM headroom acceptable for a Ray worker? (If not, reduce BRAIN RAM allocation first, or skip this work.)
2. Do you want spark-5's GPU to be scheduleable by Ray, or should the worker advertise CPU-only to keep BRAIN-isolated?  Add `--num-gpus=0 --resources='{"BRAIN": 1}'` to keep the node visible without GPU contention.
3. Is the immediate Ray join worth the spark-5 install state change, or should this wait until the control-plane MS-01 migration when spark-5 may be re-provisioned?

---

## 6. Definition of done — current status

| Item | Status |
|---|---|
| Branch + PR | ✅ created |
| Ray head on spark-2 status | ✅ running (4 ALIVE nodes, 4 GPU) |
| Pre-join cluster nodes | 4 ALIVE |
| Post-join cluster nodes | **N/A — join not performed** |
| spark-5 Ray method | **N/A — install + unit deploy needed; halted for operator approval** |
| Reboot survivable | will be (systemd unit + enable) — pending |
| BRAIN still serving | ✅ `ready` (verified read-only) |
| Resources advertised by spark-5 | **N/A — not joined** |
| Doc committed | ✅ this file |
| PR opened, merge BLOCKED | ✅ |

## 7. Master plan §5.1 IP truth table — proposed update

After successful join, `MASTER-PLAN.md` cluster column for spark-5
should change from "BRAIN only / no Ray" to **"BRAIN + Ray worker"**.
**Not editing the master plan in this PR** — that update belongs in
the post-join PR once the join is verified.

---

## 8. Audit telemetry

- Pre-join `ray status` on spark-2: `/tmp/ray-status-pre.txt` (captured 08:31 EDT)
- Pre-join `ray list nodes`: `/tmp/ray-nodes-pre.txt`
- spark-5 state probe: `/tmp/ray-spark5-state.txt`
- Worker templates from spark-1/3/4: `/tmp/ray-worker-templates.txt`
- Total wall-clock: ~6 minutes
- No state changes made on any host. BRAIN re-verified healthy at end.
