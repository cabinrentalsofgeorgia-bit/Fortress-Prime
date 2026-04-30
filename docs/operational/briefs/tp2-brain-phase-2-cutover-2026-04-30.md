# TP=2 BRAIN Phase 2 Cutover Brief — spark-5 + spark-4

**Date:** 2026-04-30
**Status:** DRAFTED — awaiting operator authorization for execution
**Driver:** ADR-006 (PR opening this brief)
**Stacks on:** PR #310 fabric cutover prep, ADR-003, ADR-004 v2, ADR-006

## 1. Mission

Cut over BRAIN serving from single-spark TP=1 (spark-5:8100, NIM 2.0.1)
to distributed TP=2 across spark-5 + spark-4 via vLLM. Single
OpenAI-compatible endpoint at spark-5:8000 (or Ray-managed VIP) over
ConnectX RDMA NCCL. LiteLLM legal-brain alias updated to point at TP=2
endpoint. Target: 1.5×–2× throughput vs current TP=1, with retained
quality per Phase A5 BRAIN+RAG probe semantic-equivalence determinism.

This is the ADR-006 execution brief. Operator authorizes by approving
this PR; cutover happens in a follow-up PR that runs the steps in §4.

## 2. Prerequisites

Hard prerequisites — all must be satisfied before cutover starts:

- [ ] **ADR-006 LOCKED on main.** Architectural authorization required.
- [ ] **Spark-5 fabric B cable cutover complete.** PR #310 runbook
      executed; spark-5 has both 10.10.10.5 + 10.10.11.5 active.
      Validates via `ssh admin@192.168.0.109 'ip -4 addr show | grep 10.10'`.
- [ ] **Spark-4 working set under 70GB.** Pre-cutover snapshot:
      `ssh admin@192.168.0.106 'free -h && ps aux --sort=-rss | head -10'`.
      (Read-only verification 2026-04-30 found spark-4 at 5.6 GiB —
      well under the 70GB ceiling.)
- [ ] **Ray cluster healthy.** Head on spark-2 alive, workers on
      spark-1/3/4 in ALIVE state. Validates: `ssh admin@192.168.0.100
      'ray status'`.
- [ ] **vLLM container on NAS.** `nvcr.io/nvidia/vllm:25.09-py3` pulled
      via W1/W3 pattern, tarball at canonical NAS path. Operator
      authorizes pull if not already cached.
- [ ] **NIM weights on NAS.** Llama-3.3-Nemotron-Super-49B-v1.5-FP8
      weights at /mnt/fortress_nas/nim-cache/... already cached (used
      by current spark-5 NIM, no fresh pull needed).
- [ ] **LiteLLM legal-brain config snapshot.** /etc/fortress/litellm_config.yaml
      backed up to .pre-tp2-2026-04-30 suffix for rollback.
- [ ] **Phase B work paused.** No case_briefing_compose runs during
      cutover window — TP=2 startup involves BRAIN restart.

## 3. Architecture & design

```
                ┌──────────────────────────────────────┐
                │ LiteLLM gateway (spark-2:8002)       │
                │ legal-brain → http://<TP2_EP>:8000/v1│
                └─────────────────┬────────────────────┘
                                  │
                                  ▼
                      ┌───────────────────┐
                      │ vLLM TP=2         │
                      │                   │
                      │ Half model        │ Half model
                      │ on spark-5        │ on spark-4
                      │ (host: 10.10.10.5)│ (host: 10.10.10.4)
                      └───────────────────┘
                      NCCL/RDMA over ConnectX fabric A (10.10.10.0/24)
                      Fabric B (10.10.11.0/24) as NCCL secondary

                      Ray cluster choice (decision §3.2):
                      - Option A: leverage existing spark-2 Ray head
                      - Option B: spin up dedicated TP=2 Ray cluster
                        with head on spark-5
```

### 3.1 Pattern selection

This is **Pattern 1 from ADR-003 §"Tensor-parallel sizing at 3 nodes"
applied to a 2-node Phase 2 build**: TP=2 single instance, no hot
replica yet (hot replica = Phase 3 when spark-6 hardware resolves).

vLLM `--tensor-parallel-size 2` distributes the 49B FP8 model across
both nodes' GPUs. Each node holds 32 of 64 attention heads. NCCL handles
cross-node tensor exchange during forward pass.

Container: `nvcr.io/nvidia/vllm:25.09-py3` (or current per
build.nvidia.com/spark/vllm/stacked-sparks reference).

### 3.2 Ray topology decision point

Ray head currently lives on spark-2 (per PR #309 audit; ADR-003 §5.1
originally placed it on spark-5 but reality differs). vLLM TP=2 needs
Ray-managed worker placement.

**Option A: Use existing spark-2 Ray head.** Spark-5 + spark-4 join as
worker pair with placement-group constraint that pins TP=2 vLLM workers
to that pair. Existing Ray workers (spark-1/3/4) stay registered.

**Option B: Spin up dedicated TP=2 Ray sub-cluster.** New Ray head on
spark-5, single worker on spark-4. Spark-2's existing Ray cluster
unaffected.

**Recommendation: Option B.**
- Cleaner separation of concerns (inference Ray vs orchestration Ray)
- Doesn't disturb existing workers spark-1/3/4 (control-plane Ray)
- vLLM container manages its own Ray daemon lifecycle naturally
- Ray head migration to spark-5 (per ADR-003 design) lands on inference
  cluster only, separate from control plane Ray which moves with MS-01
  migration

Operator confirms A or B at cutover time. Brief assumes Option B for
the rest of §4.

### 3.3 GPU + RAM math

**Spark-5 post-TP=2:**
- BRAIN-half: ~25GB (49B FP8 / 2)
- vLLM container overhead: ~3GB
- Ray daemon: ~1GB
- OS + buffer: ~10GB
- Total committed: ~39GB
- Headroom: ~89GB (vs 92% utilization today)

**Spark-4 post-TP=2:**
- BRAIN-half: ~25GB
- vLLM container overhead: ~3GB
- Ray daemon (sub-cluster worker): ~1GB
- Existing services (Ollama deep-reasoning + SWARM + qdrant-vrs +
  SenseVoice + Ray worker for spark-2 cluster): ~30GB working set
  estimate; **read-only verification 2026-04-30 observed 5.6 GiB
  actual RSS** (Ollama is idle, no models loaded into memory — true
  steady-state working set is much lighter than the conservative
  estimate)
- OS + buffer: ~10GB
- Total committed: ~30–69GB
- Headroom: ~59–98GB

Both nodes have meaningful headroom. Spark-4 was the tighter of the
two on paper — verification shows it has more headroom than estimated.

**GPU exclusivity:** vLLM TP=2 wants both spark-5 and spark-4 GPUs
exclusively. Spark-4's existing Ollama deep-reasoning + SenseVoice
services use the GPU (when active). Decision: **stop Ollama and
SenseVoice on spark-4 before TP=2 startup.** SWARM moves to spark-3
(already runs ollama). SenseVoice tracking depends on whether it's
actively in use — operator confirms.

### 3.4 Fabric NIC name divergence (flag, not blocker)

Audit and read-only verification (2026-04-30):

| Spark | Fabric A IP | Fabric A NIC name | Fabric B IP | Fabric B NIC name |
|---|---|---|---|---|
| spark-4 | 10.10.10.4 | `enp1s0f0np0` | 10.10.11.4 | `enP2p1s0f1np1` |
| spark-5 | 10.10.10.5 | `enp1s0f1np1` | (pending PR #310) | (pending) |

**Note:** spark-5 fabric A is on `enp1s0f1np1`; spark-4 fabric A is on
`enp1s0f0np0`. Different physical port names on each host but same
fabric-A subnet. NCCL only needs the correct device name on each
host. The brief's reference to `NCCL_SOCKET_IFNAME=enP2p1s0f1np1`
is correct **for spark-4** (its fabric-B device); on spark-5 the NCCL
device name will differ. Container env override may need to be
per-host or use NCCL's pattern-matching syntax (`NCCL_SOCKET_IFNAME=enp1s0f0np0,enp1s0f1np1,enP2p1s0f1np1`).

This is an implementation detail the cutover PR will pin precisely; not
a blocker for ADR-006.

## 4. Cutover sequence

### 4.1 Pre-cutover (T-2h)

- Confirm prerequisites all met
- Snapshot LiteLLM legal-brain config to
  /etc/fortress/litellm_config.yaml.pre-tp2-2026-04-30
- Drain spark-4 Ollama traffic — point any callers at spark-3 ollama
- Stop spark-4 Ollama: `sudo systemctl stop ollama` (per ADR-004 v2
  retained-state record, the unit name on spark-4 is `ollama.service`)
- Stop spark-4 SenseVoice if not actively used
- Verify spark-4 RAM working set drops to under 30GB after stops

### 4.2 vLLM container deploy

- Verify vLLM container cached on NAS, or pull via W1/W3 if not
- `docker load` on spark-5 + spark-4 from NAS tarball
- Pre-flight: vLLM single-spark test on spark-5 with TP=1 to confirm
  weights mount + container starts before bringing spark-4 in

### 4.3 Ray cluster reshape (Option B)

- On spark-5: `ray start --head --node-ip-address=10.10.10.5
  --port=6380` (port 6380 to avoid collision with spark-2 Ray head
  on default 6379, and with spark-2 Ray GCS on 6390)
- On spark-4: `ray start --address=10.10.10.5:6380`
- Verify: `ssh admin@192.168.0.109 'ray status'` from inside container
  shows 2-node TP=2 sub-cluster

### 4.4 vLLM TP=2 startup

Reference NVIDIA's `run_cluster.sh` from
`build.nvidia.com/spark/vllm/stacked-sparks`. Approximate command
(operator validates exact flags before running):

```bash
docker run -d \
  --name vllm-brain-tp2 \
  --gpus all \
  --network host \
  -v /mnt/fortress_nas/nim-cache/.../weights:/model \
  --shm-size=64g \
  -e NCCL_IB_DISABLE=0 \
  -e NCCL_NET_GDR_LEVEL=2 \
  -e NCCL_SOCKET_IFNAME=enP2p1s0f1np1 \
  -e RAY_ADDRESS=10.10.10.5:6380 \
  nvcr.io/nvidia/vllm:25.09-py3 \
    --model /model \
    --tensor-parallel-size 2 \
    --pipeline-parallel-size 1 \
    --port 8000 \
    --host 0.0.0.0 \
    --distributed-executor-backend ray
```

Confirm exact NIC name (`enP2p1s0f1np1` is from PR #309 audit on
spark-4; on spark-5 the canonical fabric-A NIC is `enp1s0f1np1`. Use
NCCL pattern-matching or per-host overrides to handle the divergence.)
Confirm Ray address before run.

### 4.5 Stop spark-5 NIM (T-0)

vLLM TP=2 listens on :8000. spark-5 NIM listens on :8100. They can
co-exist briefly on different ports, but spark-5 RAM can't fit both
serving simultaneously (each is ~25GB of weights). Decision:

- **Option (a): Stop NIM before TP=2 startup.** Simpler, BRAIN downtime
  ~5-10 min during TP=2 startup. Acceptable if Phase B work is paused
  per prerequisites.
- **Option (b): Keep NIM running, swap LiteLLM alias atomically after
  TP=2 health probe passes, then stop NIM.** Zero BRAIN downtime; but
  spark-5 RAM goes to 99%+ during overlap window.

**Recommendation: Option (a).** Cleaner, lower OOM risk.

### 4.6 Health probe

- `curl http://10.10.10.5:8000/v1/health/ready` → expected `ready`
- `curl http://10.10.10.5:8000/v1/models` → confirm 49B model loaded,
  TP=2 reflected in metadata
- Single inference call: simple legal prompt → confirm 200 + tokens

### 4.7 Quality probe (vs TP=1 baseline)

- Re-run Phase A5 BRAIN+RAG probe (PR #280) against TP=2 endpoint
- Confirm semantic-equivalence determinism passes
- Confirm streaming default works
- Confirm legal classification output matches TP=1 baseline within
  expected variance

### 4.8 LiteLLM cutover

- Edit /home/admin/Fortress-Prime/litellm_config.yaml (gitignored,
  active config — separate from deploy/ template)
- legal-brain alias: change endpoint from spark-5:8100 to
  spark-5:8000 (or VIP if Option B exposes one)
- `sudo systemctl restart litellm-gateway.service`
- Smoke test: 3 calls through LiteLLM legal-brain → confirm route
  to TP=2 endpoint via gateway logs

### 4.9 Throughput validation

- Run 10-prompt batch through TP=2 endpoint; record total time + p50/p95
- Compare to same batch on archived TP=1 timing (Phase A5 baseline)
- Target: 1.5×–2× throughput improvement
- If <1.2× improvement: investigate (NCCL config, RDMA path, FP8
  compatibility) before declaring success

### 4.10 Rollback path

If cutover fails at any step in 4.4-4.9:

- LiteLLM legal-brain alias reverted to spark-5:8100 (single-spark NIM)
- Restart spark-5 NIM service: `sudo systemctl start fortress-nim-brain.service`
- Restore spark-4 services (Ollama back, SenseVoice if stopped)
- Stop vLLM containers on spark-5 + spark-4
- Stop TP=2 Ray sub-cluster
- Estimated rollback time: 15-30 min

## 5. Risk matrix

| Risk | Likelihood | Mitigation |
|---|---|---|
| TP=2 startup fails (NCCL/weights/container) | Medium | Pre-flight vLLM single-spark test (§4.2) catches most; rollback to spark-5 NIM clean |
| Spark-4 OOM with BRAIN-half + retained services | Low | Stop Ollama/SenseVoice before TP=2 (§4.1); RAM math leaves 59-98GB headroom (verification confirms 5.6 GiB current actual) |
| Spark-5 OOM during overlap if Option (b) chosen | Medium | Default to Option (a) per recommendation §4.5 |
| LiteLLM downtime during alias swap | Low | Sub-second; legal-brain in-flight calls retry-handled by callers |
| BRAIN serving outage 5-10 min during cutover | Defined | Phase B work paused per prerequisites; operator acknowledges window |
| ConnectX RDMA path issue spark-5 ↔ spark-4 | Low | Audit confirmed driver parity + fabric A up; enable NCCL_DEBUG=INFO, fall back to TCP if RDMA broken (10× slower but works) |
| Spark-5 firmware drift (audit gap from PR #310) | Low | Operator-console verification of `ethtool -i` should resolve before cutover |
| Spark-4 RDMA enumeration empty (Issue #294) | Medium | Spark-4 is now an RDMA endpoint; debug Issue #294 elevated. NCCL may fall back to TCP if RDMA path unenumerable. |
| spark-4 Ray worker conflict with TP=2 sub-cluster | Medium | Option B uses dedicated sub-cluster on different port (6380); spark-4 retains spark-2 Ray worker membership |
| NCCL_SOCKET_IFNAME divergence between spark-5 + spark-4 | Low | Per-host env override or NCCL pattern-matching syntax handles different physical port names |
| Throughput gain <1.2× | Low | Investigate NCCL config; if model FP8 is the limit, accept and proceed (still doubles capacity for concurrent requests) |

## 6. Definition of done

- vLLM TP=2 container running on spark-5 + spark-4
- OpenAI-compatible endpoint at spark-5:8000 (or VIP) responding
- Health probe + model probe + inference probe all PASS
- Phase A5 BRAIN+RAG probe passes against TP=2 endpoint
- LiteLLM legal-brain alias points at TP=2 endpoint
- Smoke test confirms route via gateway logs
- Throughput >= 1.5× TP=1 baseline (or accepted variance with rationale)
- No regression on Vision NIM or Embed NIM (spark-3 unaffected)
- No regression on Phase A retrieval (caselaw_v2, library_v2)
- Documentation updated:
  - master plan §5.1 spark-4 role
  - master plan §5.2 BRAIN tier (TP=2 endpoint)
  - master plan §5.4 NIM deployment pattern (TP=2 vLLM variant)
  - infrastructure.md DEFCON tier
- PR description includes throughput numbers + Phase A5 probe results
- Rollback path documented + tested at least conceptually
- spark-5 NIM service stopped (or kept as standby — operator decides)

## 7. Out of scope

- Spark-6 hot replica (Phase 3, gated on ConnectX hardware resolution)
- 4-node TP=2+TP=2 (ADR-003 §Phase 4 sizing)
- TITAN service path (DeepSeek-R1 or alternative)
- Spark-4 Ollama/SenseVoice permanent migration (this brief only stops
  them for TP=2; long-term placement is separate)
- Ray head migration off spark-2 (separate track tied to MS-01 control
  plane)
- F5 root cause fix (operator-side ER8411 walkthrough, separate)
- Spark-5 firmware verification close-out (audit gap, operator-console
  task)

---

End of brief.
