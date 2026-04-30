# ADR-006 — Phase 2 Partner Reassignment (spark-5 + spark-4 in lieu of spark-5 + spark-6)

**Date:** 2026-04-30
**Status:** **LOCKED 2026-04-30** — operator concurrence Gary Knight

**Supersedes:** ADR-003 §Phase 2 partner choice. ADR-003's overall
inference cluster intent (Sparks 4/5/6 expanded to 3/4/5/6 per ADR-004
amendment v2) remains in force. ADR-003 Pattern 1 sizing (TP=2 + hot
replica) remains the locked Phase 3 sizing decision.

**Relates to:** ADR-001 (LOCKED 2026-04-26, amended), ADR-002 (LOCKED
2026-04-29, resolved by ADR-003), ADR-003 (LOCKED 2026-04-29 + Phase 1
cutover PR #285), ADR-004 amendment v2 (LOCKED 2026-04-29, retain-and-
document, PR #293)

---

## Decision

Phase 2 TP=2 BRAIN partnership is reassigned from spark-5 + spark-6 to
**spark-5 + spark-4**. Spark-6 is deferred to Phase 3+ as hot replica
once its ConnectX hardware status resolves.

## Context

ADR-003 §Phase 2 (LOCKED 2026-04-29) specified:
> Spark-5 (head) + Spark-6 (worker) = Ray cluster. vLLM
> --tensor-parallel-size 2 over NCCL/RDMA on enp1s0f1np1.

That plan assumed spark-6 would have working ConnectX fabric once cables
landed. Today's reality (2026-04-30 audit, PR #309 + PR #310):

- Spark-5: ConnectX active, fabric A up at 10.10.10.5; fabric B link
  pending today's fs.com cable arrival.
- Spark-6: `lspci | grep -i mellanox` returns NOTHING. ConnectX hardware
  is not visible to the kernel. Either unseated, undetected, or absent.
  Today's cable swap will plug fiber into a node with no NIC at the
  spark-end.
- Spark-4: ConnectX fully connected (10.10.10.4 + 10.10.11.4), MTU 9000,
  driver srcversion matching cluster canonical, Ray worker active.

Per ADR-004 amendment v2 (PR #293, retain-and-document), spark-3 and
spark-4 are designated for additive inference participation — no wipe
required, app workloads retained, inference services added on top.
ADR-004 v2 was specifically intended to allow this kind of flexibility.

Per ADR-003 §"Tensor-parallel sizing": Llama-3.3-Nemotron-Super-49B-FP8
has 64 attention heads. TP=2 = 32 heads/node, divides cleanly. Same
constraint satisfied by spark-5 + spark-4 as by the original spark-5
+ spark-6 plan.

Per master plan §3 priority order: P1 inference platform reliability
is operator-prioritized as accelerating. Waiting on spark-6 hardware
resolution (reseat / RMA / replace) imposes unbounded delay on Phase 2.
Spark-4 is available today.

## Rationale

1. **Spark-6 hardware gap is operator-paced.** Reseat may resolve;
   RMA or replace may not. Waiting is risk to counsel-hire critical
   path (~46 days remaining per master plan §2 case clock).

2. **Spark-4 has working ConnectX fabric.** Audit confirms 100Gbps
   link state, MTU 9000, NCCL-compatible driver. RDMA path
   spark-5 ↔ spark-4 over enP2p1s0f1np1 (or canonical fabric NIC name
   per current netplan) meets ADR-003 Phase 2's RDMA requirement.

3. **Spark-4 RAM headroom permits TP=2 partnership.** Per audit:
   - Spark-4 currently runs Ollama deep-reasoning, SWARM-tier
     qwen2.5:7b/32b, qdrant-vrs, SenseVoice, Ray worker
   - Working set estimate: ~30GB committed (light); read-only
     verification 2026-04-30 measured **5.6 GiB actual RSS** (Ollama
     idle with no models loaded into memory — even more headroom than
     estimated)
   - 128GB unified RAM available
   - BRAIN-half post TP=2 split: ~25GB
   - Total committed: ~30–55GB
   - Headroom: ~70–95GB. Acceptable.

4. **Spark-5 RAM headroom IMPROVES under TP=2.** Currently spark-5
   is at 92% RAM utilization with BRAIN running standalone (full 49B
   FP8 ~50GB). Post TP=2 split, spark-5 holds ~25GB BRAIN-half,
   freeing ~25GB headroom for Ray daemon + scheduling overhead.

5. **ADR-004 v2's "retain-and-document" intent is satisfied.** Spark-4
   keeps its existing services. TP=2 BRAIN is added additively. No
   wipe, no service eviction beyond optional Ollama relocation
   (decision deferred to operational brief).

6. **Spark-6 path NOT abandoned.** When ConnectX hardware resolves,
   spark-6 joins as Phase 3 hot replica per ADR-003 §"Tensor-parallel
   sizing at 3 nodes" Pattern 1. This ADR enables Phase 2 today with
   the hardware that exists; it does not preclude Phase 3.

## Tradeoffs accepted

- **Spark-4's app workload co-tenants with TP=2 BRAIN-half.** Memory
  pressure increases on spark-4 from ~30GB to ~55GB committed.
  Acceptable within 128GB envelope but reduces spark-4's headroom
  for future workload growth.

- **Optional Ollama migration off spark-4.** spark-3 already runs
  Ollama (vision-specialist). SWARM-tier (qwen2.5:7b) could
  consolidate to spark-3 if spark-4 RAM pressure becomes a concern.
  Decision deferred to operational brief execution time.

- **qdrant-vrs stays on spark-4.** Light load per master plan §5.2,
  no inference contention.

- **SenseVoice stays on spark-4** unless audio workload conflicts
  with TP=2 (unlikely — SenseVoice is GPU work but at different
  scheduling priority).

- **Phase 2 deviates from ADR-003's locked design.** Operator-locked
  decisions can be amended via subsequent ADRs; this ADR explicitly
  supersedes the §Phase 2 partner choice while preserving everything
  else. Operator approval required.

- **Spark-6 hot replica delivery date unknown.** Phase 3 (hot replica
  + 3-node sizing) is gated on hardware resolution. Phase 4 (4-node
  TP=2+TP=2 per ADR-003 §Phase 4 sizing) further deferred.

## Consequences

- ADR-003 §Phase 2 partner choice is superseded; rest of ADR-003
  remains in force.
- ADR-004 v2 retain-and-document scope extended: spark-4 now holds
  inference + app co-tenancy, not just app + Ray worker.
- Master plan §5.1 cluster IP truth table needs spark-4 role updated
  to "App + Inference partner" post-cutover.
- Master plan §5.2 inference tier table: BRAIN service updates from
  "spark-5:8100 standalone NIM" to "spark-5+spark-4 TP=2 vLLM endpoint
  spark-5:8000 (or VIP)".
- Master plan §6.2 inference platform: ADR-003 Phase 2 status moves
  from "BLOCKED on cable" to "EXECUTING per ADR-006".
- ADR-003 Phase 3 (hot replica) and Phase 4 (4-node sizing) status
  updated: gated on spark-6 hardware resolution, not just cable.
- Spark-4 RDMA enumeration debug Issue #294 (per master plan §6.5)
  becomes higher priority — spark-4 is now an RDMA endpoint.

## Closed audit findings

- ADR-003 §Phase 2 unblocked despite spark-6 hardware gap
- Phase 2 TP=2 sizing (Pattern 1, ADR-003 §"Tensor-parallel sizing at
  3 nodes") remains the design; partner identity changes only

---

Last updated: 2026-04-30 (LOCKED — operator concurrence Gary Knight)
