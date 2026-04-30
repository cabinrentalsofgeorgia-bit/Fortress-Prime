# Cluster Network Audit — 2026-04-30 (Step 1, read-only)

**Branch:** `chore/cluster-network-audit-2026-04-30`
**Driver:** MASTER-PLAN v1.7 §5.1 had spark-5 / spark-6 mgmt IPs marked "TBD audit". PR #305 surfaced 192.168.0.109 / 192.168.0.115 as candidates with SSH auth blocked. Before any Phase 2/3 inference cluster work, ground truth is required.
**Scope:** Read-only. No fixes. No config changes. Step 1 of 3 (Step 2 = SSH auth resolution; Step 3 = sustained-bandwidth iperf3 across fabric — both gated on operator authorization).
**Runner:** spark-node-2 (`192.168.0.100`).
**Hard stop encountered:** Ray cluster missing spark-5 worker (see §5).

---

## 1. Executive summary

- **All 6 sparks are ICMP-reachable** on mgmt IPs `[104, 100, 105, 106, 109, 115]/24`.
- **4 of 6 SSH-reachable** (admin key): spark-1/2/3/4. Auth blocked on spark-5 candidate (`192.168.0.109`) and spark-6 candidate (`192.168.0.115`) for both `admin` and `gary`.
- **Spark-5 = `192.168.0.109` confirmed via service signature** — port 8100 returns `{"object":"health.response","message":"ready","status":"ready"}` (BRAIN NIM signature). MAC OUI on `4c:bb:47` = ASUSTeK / DGX hardware family.
- **Spark-6 = `192.168.0.115` candidate** — only SSH-22 open, no NIM / Ollama / Qdrant. Consistent with "no service deployed yet" state. Same OUI family as spark-5.
- **ConnectX fabric is uniformly healthy on all 4 SSH-reachable sparks** — 4×100 Gbps ports per spark, all `state=up`, mlx5_core driver loaded. Fabric A `10.10.10.0/24` and fabric B `10.10.11.0/24` populated for sparks 1–4.
- **BRAIN serving (49B Nemotron Super) on spark-5 is HEALTHY** at `http://192.168.0.109:8100/v1/health/ready`.
- 🛑 **Ray cluster is missing spark-5**. The Ray dashboard API at `192.168.0.100:8265` reports 4 ALIVE nodes (`100, 104, 105, 106`); `192.168.0.109` is not present. BRAIN currently serves via standalone NIM container without Ray orchestration. This gates ADR-003 Phase 3/4 TP=2 sharding work.
- **Spark-6 cable state:** Cannot be confirmed without SSH. ICMP works, SSH-22 listens — implies it has at least mgmt LAN connectivity. Whether it's wired into the ConnectX fabric is unknown until SSH auth is resolved.

## 2. Per-spark detail

### Spark-1 — `192.168.0.104`

- Hostname: `spark-node-1` (Linux kernel `6.17.0-1014-nvidia aarch64`)
- SSH auth: ✅ admin
- Mgmt: `192.168.0.104/24 enP7s7`
- Fabric: `10.10.10.1/24 enp1s0f0np0`, `10.10.11.1/24 enP2p1s0f1np1` (also `10.101.2.1/30 enP2p1s0f0np0`, `10.0.0.31/24 wlP9s9` WiFi)
- ConnectX: 4× mlx5_core ports @ 100 Gbps, all UP
- Ray: WORKER (raylet → GCS `192.168.0.100:6390`); resource budget 39.7 GB / 20 CPU / 1 GPU
- Docker: `fortress-nim-sovereign` (`nvcr.io/nim/meta/llama-3.1-8b-instruct-dgx-spark:latest`, up 10 days), `fortress_portainer-agent`
- systemd: `fortress-brain` (Streamlit), `fortress-nim-sovereign`, `fortress-ray-worker`, `ollama`
- LAN ping spark-2: 0.18 ms
- Fabric ping `10.10.10.2`: 0.17 ms; `10.10.11.2`: 0.31 ms
- **Note:** master plan v1.7 §5.2 update says BRAIN moved from spark-1 → spark-5 on 2026-04-28. Spark-1 still runs `fortress-nim-sovereign` (Llama-3.1-8B), not BRAIN-49B. Consistent with current state.

### Spark-2 — `192.168.0.100` (control plane / runner)

- Hostname: `spark-node-2`
- SSH auth: ✅ admin (self)
- Mgmt: `192.168.0.100/24 enP7s7`
- Fabric: `10.10.10.2/24`, `10.10.11.2/24`, `10.101.2.2/30`, plus `10.101.1.2/24` on lo+fabric0 alias
- ConnectX: 4× mlx5_core ports @ 100 Gbps, all UP
- Ray: **HEAD** (gcs_server on `192.168.0.100:6390`, dashboard `8265`); raylet budget 1.3 GB / 20 CPU / 1 GPU (kept thin to leave room for control-plane services)
- Docker: `fortress_portainer`, `fortress-rag-retriever` (yzy-retriever), `fortress-chromadb`, `fortress-qdrant` (v1.13.2), `fortress_mission_control` (open-webui), `fortress-chroma` — 7 containers
- Listening ports: `5432` (postgres), `6333` (qdrant), `8002` (litellm 127.0.0.1), `6379` (redis), `11434` (ollama)
- systemd: `fortress-arq-worker`, `fortress-backend`, `fortress-channex-egress`, `fortress-console`, `fortress-inference` (active exited), `fortress-ray-head`, `fortress-sentinel`, `fortress-sync-worker`, `litellm-gateway`, `ollama`
- LiteLLM `/health` (no key): returns `401 auth_error` — gateway responding, auth gate enforcing (expected)
- Qdrant root: `qdrant 1.13.2` JSON
- LAN ping self: 0.06 ms; fabric ping self: 0.05 ms

### Spark-3 — `192.168.0.105`

- Hostname: `spark-3` (note: lowercase, no `node-` prefix — naming inconsistent with sparks 1/2)
- SSH auth: ✅ admin
- Mgmt: `192.168.0.105/24 enP7s7`
- Fabric: `10.10.10.3/24`, `10.10.11.3/24`
- ConnectX: 4× mlx5_core ports @ 100 Gbps, all UP
- Ray: WORKER; resource budget 45.7 GB / 20 CPU / 1 GPU
- Docker: `fortress-nim-embed` (`llama-nemotron-embed-1b-v2:latest`, up 9 hours — matches PR #300 deployment), `fortress-nim-vision-concierge` (`nemotron-nano-12b-v2-vl`, up 6 days), `ollama`, `docling-shredder` (up 13 days)
- Listening ports: `8101` (vision NIM), `8102` (embed NIM), `11434` (ollama)
- systemd: `fortress-nim-embed`, `fortress-nim-vision-concierge`, `fortress-ray-worker` (note: `ollama` listening but not in fortress-* unit list)
- Health probes: `8101/v1/health/ready` → `{"object":"health.response","message":"Service is ready."}`; `8102/v1/health/ready` → `{"object":"health-response","message":"Service is ready."}`
- LAN ping spark-2: 0.24 ms; fabric ping `10.10.10.2`: 0.18 ms; `10.10.11.2`: 0.30 ms

### Spark-4 — `192.168.0.106`

- Hostname: `Spark-4` (capital S — third naming variant)
- SSH auth: ✅ admin
- Mgmt: `192.168.0.106/24 enP7s7`
- Fabric: `10.10.10.4/24`, `10.10.11.4/24`
- ConnectX: 4× mlx5_core ports @ 100 Gbps, all UP
- Ray: WORKER; resource budget **87.6 GB / 20 CPU / 1 GPU** (largest worker)
- Docker: `fortress-qdrant-vrs` (v latest), `sensevoice` (`fortress/sensevoice:v2-arm64`)
- Listening ports: `6333` (qdrant VRS — distinct from spark-2 qdrant), `11434` (ollama)
- systemd: `fortress-qdrant-vrs`, `fortress-ray-worker`, `ollama`
- Health probes: ollama returns 6 models (`qwen2.5:32b`, `llava`, `mistral`, `nomic-embed-text`, `qwen2.5:7b`, `deepseek-r1:70b`); qdrant root: `1.17.1` JSON
- LAN ping spark-2: 0.40 ms; fabric ping `10.10.10.2`: 0.28 ms; `10.10.11.2`: 0.49 ms

### Spark-5 — `192.168.0.109` (SSH auth blocked; service-side reachable)

- ICMP: ✅ (avg 0.46 ms)
- SSH auth: ❌ both `admin` and `gary` rejected with `Permission denied (publickey,password)`
- ARP: `4c:bb:47:2c:06:90` (ASUSTeK / DGX OUI family)
- TCP probes from spark-2: `22` open, `8100` open, `11434` refused, `8443` refused
- BRAIN health: `curl http://192.168.0.109:8100/v1/health/ready` → `{"object":"health.response","message":"ready","status":"ready"}` ✅ — BRAIN NIM is UP
- Ray: 🛑 **NOT IN RAY CLUSTER** (see §5)
- Cannot verify: hostname, fabric IPs, ConnectX state, docker containers, systemd unit list, Ollama state, fabric pingability without SSH

### Spark-6 — `192.168.0.115` (SSH auth blocked; service-side mostly empty)

- ICMP: ✅ (avg 0.94 ms — slightly higher than other sparks; possibly different switch port or longer cable run)
- SSH auth: ❌ both `admin` and `gary` rejected
- ARP: `4c:bb:47:2b:e8:1e` (same OUI family as spark-5)
- TCP probes from spark-2: `22` open; `8100`, `11434`, `6333` all `Connection refused`
- BRAIN / NIM / Ollama / Qdrant: none listening
- Per master plan: spark-6 expected to be additive in Phase 3; cable into ConnectX fabric is the gating physical blocker for ADR-003 Phase 3/4 TP=2
- Cannot verify any in-host detail without SSH

## 3. Cluster-wide summary table

| Spark | Mgmt IP | SSH (admin) | Hostname | Fabric A IP | Fabric B IP | ConnectX | NIMs running | Ray | Reachable from spark-2 |
|---|---|---|---|---|---|---|---|---|---|
| spark-1 | 192.168.0.104 | ✅ | `spark-node-1` | 10.10.10.1/24 | 10.10.11.1/24 | 4× UP @ 100 Gbps | nim-sovereign (Llama-3.1-8B) :? | WORKER (39.7 GB) | LAN 0.18 ms / fabric 0.17 ms |
| spark-2 | 192.168.0.100 | ✅ (self) | `spark-node-2` | 10.10.10.2/24 | 10.10.11.2/24 | 4× UP @ 100 Gbps | (control plane: litellm 8002, qdrant 6333, postgres, redis, ollama) | **HEAD** (1.3 GB) | self |
| spark-3 | 192.168.0.105 | ✅ | `spark-3` | 10.10.10.3/24 | 10.10.11.3/24 | 4× UP @ 100 Gbps | nim-vision-concierge :8101, nim-embed :8102 | WORKER (45.7 GB) | LAN 0.24 ms / fabric 0.18 ms |
| spark-4 | 192.168.0.106 | ✅ | `Spark-4` | 10.10.10.4/24 | 10.10.11.4/24 | 4× UP @ 100 Gbps | qdrant-vrs :6333, sensevoice, ollama | WORKER (87.6 GB) | LAN 0.40 ms / fabric 0.28 ms |
| spark-5 | 192.168.0.109 | ❌ admin & gary | (unknown) | (unknown) | (unknown) | (unknown) | **brain-nim :8100** ✅ healthy | **NOT IN CLUSTER** 🛑 | LAN 0.46 ms (ICMP only); fabric N/A |
| spark-6 | 192.168.0.115 | ❌ admin & gary | (unknown) | (unknown) | (unknown) | (unknown) | none listening | (unknown) | LAN 0.94 ms (ICMP only); fabric N/A |

## 4. Master-plan v1.7 § 5.1 reconciliation

| Master-plan claim | Audit finding | Status |
|---|---|---|
| Spark-1 = Fortress Legal single-tenant (post ADR-004) | spark-1 runs nim-sovereign (Llama-3.1-8B) + Streamlit BRAIN UI + Ray worker; no DB tenants | ✓ matches |
| Spark-2 = control plane + multi-tenant | spark-2 runs litellm + postgres + qdrant + redis + ollama + open-webui + ray head | ✓ matches |
| Sparks 3/4/5/6 = inference cluster (ADR-004) | sparks 3/4/5 host NIMs; spark-6 has no inference services yet | ✓ partial — spark-6 is the gating blocker per ADR-003 Phase 3 |
| Spark-5 hosts BRAIN-49B (per CLAUDE.md, 2026-04-28 update) | spark-5 :8100 returns `{"status":"ready"}` — BRAIN appears healthy | ✓ matches |
| ADR-003 Phase 3/4 TP=2 sharding | requires Ray membership across all inference sparks; **spark-5 missing from Ray** | ✗ gap (see §5) |
| Spark-6 cable into ConnectX fabric | unverifiable without SSH; only SSH-22 open over mgmt | ⚠ unknown |

## 5. Identified gaps + recommended next-step actions

### Gap 1 (HIGH) — SSH auth on spark-5 / spark-6

**Finding:** Both `admin` and `gary` rejected with `publickey,password` on `192.168.0.109` and `192.168.0.115`. Operator-side resolution required (no Step-1 path).

**Recommended next-step:**
1. Operator side-channel (console / NoMachine / direct keyboard) to inspect `/etc/ssh/sshd_config` and `~/.ssh/authorized_keys` on each.
2. Most likely path: deploy operator's standard `admin` key to `~/.ssh/authorized_keys` on both, restart sshd.
3. Re-run this audit (Step 1) on the same branch; expect §2 spark-5 and §2 spark-6 sections to fill in.
4. Until SSH lands, ConnectX state on spark-5/6 cannot be verified — and Phase 2 / Phase 3 / fabric iperf3 (Step 3) work is gated.

### Gap 2 (HIGH — STOP CONDITION TRIGGERED) — Ray cluster missing spark-5

**Finding:** Ray dashboard API at `192.168.0.100:8265/api/v0/nodes` reports 4 ALIVE nodes:
```
192.168.0.100  state=ALIVE GPU=1 CPU=20 mem_GB=1.3   (head)
192.168.0.104  state=ALIVE GPU=1 CPU=20 mem_GB=39.7  (spark-1)
192.168.0.105  state=ALIVE GPU=1 CPU=20 mem_GB=45.7  (spark-3)
192.168.0.106  state=ALIVE GPU=1 CPU=20 mem_GB=87.6  (spark-4)
```

`192.168.0.109` (spark-5) is **not present**. Ray currently has 4 GPUs / 80 CPUs total across 4 ALIVE nodes; with spark-5 added it should be 5 GPUs / 100 CPUs.

**Production-impact assessment:**
- BRAIN (Llama-3.3-Nemotron-Super-49B-FP8) currently serves correctly on spark-5:8100 via standalone NIM container. Ray is **not on the request path** for single-NIM serving.
- Therefore: BRAIN inference works today.
- **However:** ADR-003 Phase 3/4 plans TP=2 sharding across spark-5 + spark-6 (or spark-3 + spark-5 in Pattern 2). That requires Ray membership of all participating nodes. Phase 3 work cannot start until spark-5's `fortress-ray-worker.service` is enabled and joined to the GCS at `192.168.0.100:6390`.

**Recommended next-step:**
1. SSH access to spark-5 (Gap 1) is prerequisite.
2. Inspect `systemctl status fortress-ray-worker.service` on spark-5; expect either masked, disabled, or stopped.
3. If inactive: enable + start, verify `ray status` from spark-2 sees a 5th worker on `192.168.0.109`.
4. If active but not joining: check spark-5 → spark-2 connectivity on Ray ports (GCS 6390, dashboard 8265, raylet ephemerals 10002–19999) — may interact with the fact spark-5's fabric IPs are unknown, since Ray binds to `--node-ip-address`.
5. Confirm BRAIN container's CPU/memory budget on spark-5 leaves enough headroom for a Ray worker (49B-FP8 typically uses ~80 GB of the spark's 121 GB unified memory).

### Gap 3 (MEDIUM) — Hostname inconsistency across cluster

**Finding:** Three different naming conventions in use:
- `spark-node-1`, `spark-node-2` (sparks 1, 2 — kebab-case with `node-` prefix)
- `spark-3` (no `node-` prefix, lowercase)
- `Spark-4` (capital S, no `node-` prefix)
- `(unknown)` for spark-5/6

This is cosmetic but it has bitten before — see memory `project_spark_network_topology.md` documenting the SSH-alias / Linux-hostname / Tailscale-name inversion.

**Recommended next-step:** treat as non-urgent, fold into next ADR / runbook pass; document the canonical SSH-alias → IP mapping (already in `~/.ssh/config`) as the durable identifier.

### Gap 4 (LOW) — Spark-6 fabric state unknown

**Finding:** spark-6 (`192.168.0.115`) is ICMP-reachable on mgmt LAN, but ConnectX fabric ports cannot be verified without SSH. ADR-003 Phase 3 specifically calls out spark-6 cable into the Mikrotik switch as the gating physical blocker.

**Recommended next-step:**
1. Resolve Gap 1 (SSH) first.
2. Once SSH lands, run the same probe to capture: `ip -4 addr show | grep -E "inet 10\."`, `for dev in /sys/class/net/*; do … driver=mlx5_core …`, etc.
3. If ConnectX devices show `state=down` on spark-6, that confirms the cable hasn't been run. If they show `state=up`, cable is in place but fabric IPs may be unconfigured.

### Gap 5 (LOW — observation only) — `fortress-inference` on spark-2 is `active exited`

**Finding:** `systemctl list-units` on spark-2 shows `fortress-inference.service` as `loaded active exited`. This is a oneshot or completed unit — not a running service.

**Recommended next-step:** non-urgent. Decide whether to mark as `Type=oneshot RemainAfterExit=yes` if intended as a marker, or leave as-is. Operator decision.

## 6. Operator decisions needed

1. **SSH auth resolution path for spark-5 / spark-6** — operator-side (out of audit scope). Once resolved, this audit can be re-run to fill in spark-5 / spark-6 detail and confirm ConnectX fabric state.
2. **Spark-5 Ray worker enablement** — depends on (1). Decide whether to enable `fortress-ray-worker` on spark-5 ahead of Phase 3 or wait until Phase 3 brief.
3. **Spark-6 cable timing** — separately authorize physical cable run + fabric IP assignment if not already done.
4. **Step 2 / Step 3 authorization** — Step 2 = SSH resolution; Step 3 = fabric iperf3 (sustained-bandwidth verification across fabric A and B). Both are separate authorizations after this Step 1 lands.

## 7. What this audit does NOT do

- No SSH config changes
- No service / NIM / systemd modifications
- No network config changes (no ip / route / iptables / sysctl)
- No iperf3 or other bandwidth tests (Step 3, separate authorization)
- No modifications to MASTER-PLAN.md or any other doc beyond this new audit doc
- No PR / branch / Phase A reindex / Phase B v0.2 work touched

## 8. Appendix — raw ARP, OUI, and TCP probe data

ARP table (for the auth-blocked IPs):
```
192.168.0.115 dev enP7s7 lladdr 4c:bb:47:2b:e8:1e DELAY
192.168.0.109 dev enP7s7 lladdr 4c:bb:47:2c:06:90 DELAY
```

OUI `4c:bb:47` — ASUSTeK Computer Inc. (commonly the manufacturer for DGX-class hardware).

TCP probes from spark-2 (`</dev/tcp/IP/PORT`):
```
192.168.0.109:8100  open       ← BRAIN NIM
192.168.0.109:11434 refused
192.168.0.109:22    open
192.168.0.109:8443  refused

192.168.0.115:22    open
192.168.0.115:8100  refused
192.168.0.115:11434 refused
192.168.0.115:6333  refused
```

Ray dashboard API node list captured 2026-04-30T06:29Z: 9 entries total (4 ALIVE, 5 DEAD/stale). DEAD entries are historical worker/driver registrations; the 4 ALIVE entries enumerated in §5 are the canonical cluster membership.

---

## 9. Audit completion 2026-04-30 (post-SSH-resolution)

After §1–§8 was committed, operator-side SSH auth was restored on spark-5 and spark-6 (fortress pubkey installed). This section captures the data §1–§8 could not.

### 9.1 Spark-5 — `192.168.0.109` (now SSH-reachable)

- Hostname: **`spark-5`** (lowercase, no `node-` prefix — matches spark-3/Spark-4 convention rather than spark-1/2)
- SSH auth: ✅ admin
- **Mgmt: TWO IPs on different interfaces** ⚠
  - `192.168.0.109/24 enP7s7` — primary mgmt LAN
  - `192.168.0.111/24 enP2p1s0f1np1` — **a 192.168.0.x address bound to a ConnectX port** (should be a `10.10.x.x` fabric IP, not a mgmt-LAN address — see Gap 6)
- **Fabric A only:** `10.10.10.5/24 enp1s0f1np1`
- **Fabric B: not configured** (no `10.10.11.x` IP)
- **ConnectX state — 2 of 4 ports DOWN:** ⚠
  ```
  enp1s0f0np0      driver=mlx5_core  speed=-1Mbps     state=down
  enp1s0f1np1      driver=mlx5_core  speed=100000Mbps state=up    ← 10.10.10.5 fabric A
  enP2p1s0f0np0    driver=mlx5_core  speed=-1Mbps     state=down
  enP2p1s0f1np1    driver=mlx5_core  speed=100000Mbps state=up    ← 192.168.0.111 (mis-bound)
  ```
- **Ray: NO PROCESSES** (`pgrep -af "ray::|raylet|gcs_server"` returned no matches) — confirms §5 STOP-condition finding from the dashboard side
- Docker: `fortress-nim-brain` (`nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:latest`, up 26 hours)
- Listening port: 8100 only (BRAIN)
- systemd: `fortress-nim-brain.service` — **description text says `"on spark-1"`** but the service is actually running on spark-5 (stale unit description, see Gap 7)
- LAN ping spark-2: 0.32 ms ✓
- Fabric ping `10.10.10.2` (fabric A): 0.23 ms ✓
- **Fabric ping `10.10.11.2` (fabric B): NO RESPONSE** — fabric B not wired or not configured on spark-5

### 9.2 Spark-6 — `192.168.0.115` (now SSH-reachable)

- Hostname: **`spark-6`**
- SSH auth: ✅ admin
- Mgmt: `192.168.0.115/24 enP7s7` only
- **NO fabric IPs** (10.x ranges empty)
- **NO ConnectX devices visible** — `for dev in /sys/class/net/*; case driver in mlx5_core|mlx4_core` returned nothing. Either ConnectX hardware isn't installed or driver isn't loaded.
- No Ray, no Docker containers running, no NIM/Ollama/Qdrant ports listening, no fortress/nim/ray/qdrant/ollama systemd units
- LAN ping spark-2: 0.54 ms ✓
- **Fabric ping `10.10.10.2`: NO RESPONSE**
- **Fabric ping `10.10.11.2`: NO RESPONSE**

**Spark-6 is currently a bare host with mgmt-LAN connectivity only.** This confirms §5 Gap 4: ConnectX cable into the fabric is the gating physical blocker for ADR-003 Phase 3 — and additionally the ConnectX hardware is either uninstalled or its driver is not loaded.

### 9.3 Updated cluster summary table

| Spark | Mgmt IP | SSH (admin) | Hostname | Fabric A | Fabric B | ConnectX | NIMs | Ray | Notes |
|---|---|---|---|---|---|---|---|---|---|
| spark-1 | 192.168.0.104 | ✅ | spark-node-1 | 10.10.10.1 | 10.10.11.1 | 4× UP | nim-sovereign | WORKER | — |
| spark-2 | 192.168.0.100 | ✅ (self) | spark-node-2 | 10.10.10.2 | 10.10.11.2 | 4× UP | (control plane) | HEAD | — |
| spark-3 | 192.168.0.105 | ✅ | spark-3 | 10.10.10.3 | 10.10.11.3 | 4× UP | nim-vision, nim-embed | WORKER | — |
| spark-4 | 192.168.0.106 | ✅ | Spark-4 | 10.10.10.4 | 10.10.11.4 | 4× UP | qdrant-vrs, sensevoice | WORKER | — |
| **spark-5** | 192.168.0.109 | ✅ | **spark-5** | **10.10.10.5** | **MISSING** ⚠ | **2 UP / 2 DOWN** ⚠ | brain-nim :8100 | **NOT IN CLUSTER** 🛑 | also 192.168.0.111 mis-bound on fabric port |
| **spark-6** | 192.168.0.115 | ✅ | **spark-6** | — | — | **NO DEVICES** ⚠ | none | none | mgmt-LAN only — no fabric, no ConnectX |

### 9.4 New gaps surfaced

#### Gap 6 (HIGH) — Spark-5 fabric is half-wired and one port is mis-bound

- Two of four ConnectX ports `state=down` on spark-5 — physical cable check needed
- The ConnectX port that IS up but lacks a fabric IP (`enP2p1s0f1np1`) is bound to `192.168.0.111/24` — a mgmt-LAN address. Either (a) DHCP from the ER8411 leased it a mgmt IP because no static fabric config existed, or (b) misconfiguration.
- Fabric B (`10.10.11.0/24`) has no spark-5 endpoint, so any caller using fabric B for spark-5 communication will fail.

**Recommended next-step:**
1. Check `/etc/netplan/*.yaml` (or systemd-networkd config) on spark-5 to see what fabric IPs were intended.
2. Run a physical cable inventory: which spark-5 ConnectX ports are cabled into the Mikrotik switch? Are spark-5 down-ports genuinely unconnected, or is the cable plugged but link negotiation failing?
3. Decide whether spark-5 should have both fabric A + fabric B (matching sparks 1-4) or just fabric A (which is what's currently configured).
4. Remove the spurious `192.168.0.111/24` binding from the ConnectX port — that IP collides with the mgmt-LAN subnet and could cause routing ambiguity.

#### Gap 7 (LOW) — `fortress-nim-brain.service` description names wrong host

- Service description on spark-5 reads: *"Fortress NIM Brain — nvidia/Llama-3.3-Nemotron-Super-49B-v1.5-FP8 **on spark-1** (Tier 2 sovereign reasoning)"*
- The service actually runs on spark-5 (per master-plan v1.7 §5.2 update — BRAIN moved spark-1 → spark-5 on 2026-04-28)
- Cosmetic but documentation-debt: anyone reading the unit will assume spark-1 host

**Recommended next-step:** edit `Description=` field in `/etc/systemd/system/fortress-nim-brain.service` on spark-5 to say "on spark-5". Non-urgent.

#### Gap 8 (LOW) — Spark-6 ConnectX hardware absent or driver not loaded

- `ls /sys/class/net/` shows no mlx5/mlx4 devices on spark-6
- Either: (a) ConnectX adapter not physically installed, or (b) `mlx5_core` kernel module not loaded for some reason

**Recommended next-step:** operator checks physical chassis on spark-6. If adapter is present but driver missing, `lspci | grep Mellanox` will show the device — then `modprobe mlx5_core`. If adapter is absent, this is a hardware-procurement / install task.

### 9.5 id_ed25519 regen blast radius (Part B)

Operator regenerated `~/.ssh/id_ed25519` on spark-2 admin at **2026-04-30 06:49** (timestamp on key file). Per the brief, surface any orphaned references.

#### Key inventory on spark-2

```
-rw-------  411 Apr 30 06:49  id_ed25519              ← REGENERATED (today)
-rw-r--r--  100 Apr 30 06:49  id_ed25519.pub          ← REGENERATED (today)
-rw-------  432 Mar  2 07:44  id_ed25519_fortress     ← original cluster-wide canonical key
-rw-r--r--  116 Mar  2 07:44  id_ed25519_fortress.pub
-rw------- 2602 Feb  5 15:43  id_rsa                  ← legacy
-rw-r--r--  572 Feb  5 15:43  id_rsa.pub
```

#### `~/.ssh/config` IdentityFile mappings (spark-2 admin)

```
spark-1 / spark-1-mgmt              → id_ed25519_fortress
spark-2 / spark-2-fabric / spark-2-mgmt  → id_rsa
spark-3 / spark-3-mgmt              → id_ed25519_fortress
spark-4 / spark-4-mgmt              → id_ed25519_fortress
github.com                          → id_ed25519_fortress
192.168.0.* 10.10.10.* 10.10.11.* 10.101.*  → id_ed25519_fortress (wildcard)
192.168.0.104 (spark-1 IP literal)  → id_rsa  (stale; wildcard above wins for other IPs)
```

**No entry references plain `id_ed25519` (no suffix).**

#### Filesystem search for `id_ed25519` (no `_fortress` suffix)

- Searched: `~/.ssh/`, `~/Fortress-Prime/` (excluded `.bak`, `.backup`, `known_hosts`, `authorized_keys`, `.git/`, `node_modules`, `.uv-venv`, `.venv`, `__pycache__`)
- **Result: 0 references found**

#### Active-service health checks

- **Tailscale:** `tailscale status` reports spark-2 online (`100.80.122.100 spark-2 cabin.rentals.of.georgia@ linux -`); other peer state intact (Mac mini, iMac online; ds1825-1 + fortress-linux offline as before this session). Tailscale does not use SSH keys — auth unaffected by `id_ed25519` regen.
- **Git remote SSH (`origin git@github.com:cabinrentalsofgeorgia-bit/Fortress-Prime.git`):** `ls-remote origin HEAD` returns `cfea55b0b3a2cb9b6b47bff1e734a82d2cf81ed3` → **WORKS**. The wildcard `Host github.com → IdentityFile ~/.ssh/id_ed25519_fortress` keeps GitHub auth functional. Pushes / fetches via SSH are unaffected by `id_ed25519` regen.
- **`~/.ssh/authorized_keys` on spark-2:** 11 lines, last 3 entries reference `admin@spark-node-1`, `knight@garys-mac-mini`, `admin@spark-6-fabric-20260426` — peer pubkeys, not affected by spark-2's own private-key regen.

#### Conclusion

**The regenerated `id_ed25519` is functionally orphaned.** No active service or config references the unsuffixed key — every cluster + GitHub auth path uses `id_ed25519_fortress` (or `id_rsa` for spark-2's self-loops). Tailscale doesn't use SSH keys. Git remote works.

**Recommended action: SAFE — no fix needed.** Operator may delete the new `id_ed25519` and `id_ed25519.pub` if confident they were created in error, or leave them in place — neither breaks anything. If the regen was *intentional* and meant to replace `id_ed25519_fortress` going forward, that would be a separate operator decision (would require updating `~/.ssh/config` IdentityFile lines + redeploying the new pubkey to all spark `authorized_keys`).

### 9.6 Updated operator decisions needed

In addition to §6:

5. Spark-5 fabric B wiring + 192.168.0.111 mis-bind cleanup (Gap 6) — physical cable + netplan inspection
6. Spark-6 ConnectX presence (Gap 8) — physical chassis check, `lspci | grep Mellanox`
7. id_ed25519 disposition — delete or repurpose (decision after §9.5 review)
8. fortress-nim-brain.service description edit on spark-5 (Gap 7) — non-urgent

---

End of audit completion section.

