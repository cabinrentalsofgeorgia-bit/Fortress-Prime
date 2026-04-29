## ADR-003 — Dedicated inference cluster on Sparks 4/5/6

**Date:** 2026-04-29
**Status:** **LOCKED** — operator decision 2026-04-29
**Phase 3 sizing (locked at decision time):** **Pattern 1 — TP=2 + 1 hot replica** (see "Tensor-parallel sizing at 3 nodes" below). Operator selected this default at lock time; Pattern 2 / Pattern 3 remain documented but not active.

**Supersedes:** Earlier ADR-003 (2026-04-26 — "Inference plane: shared swarm across all sparks") in `_architectural-decisions.md`. The shared-swarm decision was made before the dedicated-inference-cluster topology was on the table; this ADR replaces it.
**Amends:**
- **ADR-001 (one spark per division)** — app-tenancy rule remains in force; this ADR carves out a shared inference tier that ADR-001 did not anticipate. Acquisitions + Wealth co-tenant on Spark-3 with Financial until Spark-7+ lands.
- **ADR-002 (Captain/Council/Sentinel placement)** — reverses the 2026-04-26 Council → Spark-4 Option B decision. Council now joins Captain and Sentinel on the spark-2 control plane (Option A across the board). Spark-4 becomes an inference-tier node, not a Council host.

---

### Decision

Sparks **4, 5, and 6** form a dedicated inference cluster. No division apps tenant on these nodes. App workloads consolidate to Sparks 1/2/3. All BRAIN-tier and TITAN-tier inference traffic from any division terminates on the 4/5/6 cluster via LiteLLM gateway.

**Final allocation:**

| Spark | Fabric | Role | Tenants |
|---|---|---|---|
| Spark 1 | ConnectX | App | Fortress Legal |
| Spark 2 | ConnectX | App + control plane | CROG-VRS, Captain, Sentinel, Postgres, Qdrant (legal), Redis, ARQ, FastAPI |
| Spark 3 | ConnectX | App | Financial (Master Accounting + Market Club replacement); Acquisitions + Wealth co-tenant until further hardware |
| Spark 4 | ConnectX | Inference | Ray worker (Phase 3) |
| Spark 5 | ConnectX | Inference | Ray head, Nemotron-Super-49B-FP8 NIM today |
| Spark 6 | 10GbE → ConnectX (pending cable) | Inference | Ray worker (Phase 2+) |

---

### Phased rollout

**Phase 1 — TODAY (spark-5 only on fast fabric)**
- Spark-5 serves Nemotron-Super-49B-FP8 NIM, TP=1, port 8100
- Spark-6 staged on 10GbE: Docker, NGC login, NIM image cached to NAS, no inference traffic
- Apps on 1/2 call spark-5 via LAN
- LiteLLM gateway on spark-2 routes BRAIN tier → spark-5
- **Action:** cut LiteLLM legal routes from cloud → spark-5 NIM (closes audit finding A-02)

**Phase 2 — Spark-6 cable cutover**
- Spark-5 (head) + Spark-6 (worker) = Ray cluster
- vLLM `--tensor-parallel-size 2` over NCCL/RDMA on `enp1s0f1np1`
- Container `nvcr.io/nvidia/vllm:25.09-py3` or current
- Single OpenAI-compatible endpoint, 128K context, 2× throughput
- Reference: `build.nvidia.com/spark/vllm/stacked-sparks` (`run_cluster.sh`)

**Phase 3 — Spark-4 joins inference cluster**
- Software-only cutover (Spark-4 already on ConnectX)
- Whatever division was planned for Spark-4 (Acquisitions or Wealth) co-tenants on Spark-3 with Financial, or defers until Spark-7+
- Three-node inference cluster — see "tensor-parallel sizing" below

---

### Tensor-parallel sizing at 3 nodes

**Constraint:** Nemotron-Super-49B-v1.5-FP8 has 64 attention heads. TP requires `n_heads % tp_size == 0`. 64 is not divisible by 3. Literal TP=3 with this model will not run.

**Resolution at Phase 3 — three patterns, pick at cutover time:**

1. **TP=2 + 1 hot replica (recommended default).** Two Sparks tensor-parallel for one 49B instance, third Spark runs a second 49B instance. LiteLLM load-balances. Doubles throughput, gives a live failover node, no model-architecture constraint.
2. **TP=2 + 1 second-model node.** Spark-4 hosts a different model (e.g., DeepSeek-R1 671B distributed via llama.cpp RPC paired with Spark-5 when invoked, or Nemotron-Nano-30B-A3B-FP8 for SWARM-tier offload). Highest model diversity.
3. **PP=3 / TP=1 hybrid.** Pipeline-parallel across all three. Works with any model. Adds latency. Avoid unless throughput requirements force it.

**Default to Pattern 1** unless TITAN-tier (DeepSeek-R1 671B) becomes a daily workload, in which case Pattern 2 wins.

---

### Rationale

- **Boundary clarity.** Inference is a shared cross-division resource; tying it to a division Spark (current state: BRAIN on spark-1) creates noisy-neighbor risk and memory pressure. spark-1 at ≥99% memory after 49B load is the symptom (per `infrastructure.md` 2026-04-23 note).
- **Per-division resource budgeting still holds.** App Sparks 1/2/3 keep their division boundaries; inference is a service consumed via LiteLLM, not a tenant.
- **NVIDIA reference path.** Ray + vLLM + NIM over ConnectX-7 is what `build.nvidia.com/spark` documents. This ADR aligns Fortress Prime with NVIDIA's stacked-Sparks playbook.
- **Closes audit A-02.** Legal inference currently routes to cloud (Anthropic/OpenAI) per the 2026-04-22 audit. Phase 1's LiteLLM cutover makes IRON_DOME's "sovereign Legal inference" claim true.
- **Frees spark-1 for Fortress Legal app work.** Vault ingestion, privilege classification, Qdrant upserts, Council orchestration — the legal app is plenty to fill spark-1 without sharing memory with a 49B model.

---

### Tradeoffs accepted

- **Acquisitions + Wealth lose dedicated Sparks** at Phase 3. They co-tenant on Spark-3 (Financial) or defer until Spark-7+. ADR-001's "one spark per division" becomes "one spark per *app* division, with three divisions co-tenanting one Spark" until more hardware lands.
- **Inference cluster is a single failure domain.** If Sparks 4/5/6 all go down, every division loses BRAIN/TITAN. Mitigated by Pattern 1's hot replica at Phase 3 and by SWARM-tier (qwen2.5:7b on spark-2) staying live for degraded operation.
- **Cross-Spark inference adds LAN latency vs. localhost.** ConnectX-7 RDMA makes this negligible (<1ms); 10GbE during Phase 1 → Phase 2 transition is acceptable for the brief window.
- **Cable dependency for Phase 2.** Spark-6 stuck on 10GbE blocks TP=2. Don't attempt RDMA over 10GbE — kills the throughput gain. Phase 1 holds until cable lands.

---

### Implications already in motion

- **Audit A-02 fix** (cloud → spark-5 NIM cutover) becomes Phase 1's first action item.
- **infrastructure.md DEFCON table needs update**: BRAIN tier moves from `spark-1` to `spark-5` (and spark-5+6 cluster at Phase 2).
- **system-map.md needs redraw** to reflect app/inference split.
- **NemoClaw orchestrator placement (doc 006)** stays correct: head on `.100` (spark-2 control plane). Ray Serve replicas pin to inference Sparks 4/5/6 instead of being distributed across all four current workers.
- **ADR-002 (Captain/Council/Sentinel placement)** narrows: those services run on spark-2 control plane (Option A from ADR-002). They consume inference from spark-5 cluster but don't host it.

---

### Open question for operator

- **Phase 3 trigger:** what event moves Spark-4 from "app division (Acquisitions/Wealth)" to "inference cluster member"? Suggested triggers: (a) Acquisitions/Wealth workloads stay light enough to co-tenant on Spark-3, OR (b) BRAIN-tier traffic outgrows TP=2 throughput. Confirm criterion at Phase 2 completion.

---

### Related work

- `infrastructure.md` — current topology table needs Phase 1 update
- `system-map.md` — current/target diagrams need redraw
- `006-nemoclaw-ray-deployment.md` — Ray worker list narrows to spark-4/5/6
- LiteLLM config — legal routes cloud → spark-5 NIM
- IRON_DOME v6.1 doctrine — sovereignty claim becomes accurate after Phase 1

Last updated: 2026-04-29
