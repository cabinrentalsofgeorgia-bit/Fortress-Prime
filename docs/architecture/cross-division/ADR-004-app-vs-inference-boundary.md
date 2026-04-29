# ADR-004 — App vs Inference Boundary

**Date:** 2026-04-29
**Status:** **LOCKED** — operator decision 2026-04-29

**Supersedes:** Partial supersession of ADR-001's "one spark per division" rule. The cross-division services portion of ADR-002 stays resolved (Captain/Council/Sentinel on spark-2 control plane, Option A). ADR-003's inference cluster designation expands from Sparks 4/5/6 to **Sparks 3/4/5/6**.

---

## Decision

The boundary that drives spark allocation is **app vs inference**, not division-per-spark. Division-per-spark is abandoned for everything except **Fortress Legal** (which keeps its own spark for sovereignty + privilege isolation).

### Final allocation

| Spark | Fabric | Role | Tenants |
|---|---|---|---|
| Spark 1 | ConnectX | App — single tenant | Fortress Legal (sovereignty + privilege isolation) |
| Spark 2 | ConnectX | App — control plane + multi-tenant | CROG-VRS, Captain, Sentinel, Postgres, Qdrant (legal), Redis, ARQ, FastAPI, LiteLLM gateway, **Financial** (Master Accounting + Market Club replacement), **Acquisitions**, **Wealth** |
| Spark 3 | ConnectX | **Inference (post-wipe)** | Ray worker (joins inference cluster) |
| Spark 4 | ConnectX | **Inference (post-wipe)** | Ray worker (joins inference cluster) |
| Spark 5 | ConnectX | Inference (active) | Ray head; Nemotron-Super-49B-FP8 NIM |
| Spark 6 | 10GbE → ConnectX (cable pending) | Inference (Phase 2) | Ray worker; TP=2 partner with Spark 5 |

---

## Rationale

- **Inference is the choke point** for the white-shoe-grade legal output produced by Fortress Legal. A 4-node inference cluster (3/4/5/6) on Pattern 1 (TP=2 + hot replica) gives two production 49B instances + headroom for TITAN (DeepSeek-R1) when it lands. ADR-003's 3-node cluster was a stepping stone.

- **Spark-2 has historically carried all enterprises.** The "one spark per division" rule (ADR-001) was an aspirational target that assumed enough hardware to enforce it. Reality: spark-3 was never provisioned, spark-4 was lightweight (Qdrant VRS + SenseVoice + scratch). Migrating the planned divisions to dedicated sparks costs hardware + operational complexity and produces no measurable benefit for non-Legal divisions.

- **Fortress Legal is the exception.** Privileged communications, attorney-client work product, sovereign legal inference — these have audit + compliance + privilege-waiver concerns that justify dedicated hardware. Spark-1 is the only single-tenant app spark.

- **Per-division resource budgeting becomes a spark-2 operational concern, not an architectural rule.** Postgres roles, Qdrant collections, FastAPI routers, ARQ queues — each enterprise has its own logical isolation; physical isolation isn't required for non-Legal work.

- **Closes the "spark-3 timeline" question.** Spark-3 was the gating dependency for Financial migration under ADR-001. Under ADR-004, that migration is canceled — Financial stays on spark-2 permanently.

---

## Tradeoffs accepted

- **Spark-2 carries more load.** All non-Legal enterprises + control plane + LiteLLM gateway. Memory + CPU + I/O budget tightens. Mitigated by per-division logical isolation already in place (schemas, queue prefixes, Qdrant collection separation) and by inference workload moving entirely off spark-2 (BRAIN currently on spark-5; LiteLLM gateway is lightweight).

- **No inter-enterprise blast-radius isolation on spark-2.** A Master Accounting bug could in principle disrupt CROG-VRS bookings if it crashes shared infrastructure (Postgres, Redis). Mitigated by separate database roles, schema isolation, and process isolation. Trade is acceptable; the alternative (separate sparks for low-traffic enterprises) costs more than it saves.

- **Acquisitions + Wealth never get dedicated sparks.** They co-tenant on spark-2 with everyone else. Operator-accepted; both are early-stage divisions where blast-radius isolation is overkill.

- **Spark-3 + Spark-4 require wipe-and-rebuild** to join inference cluster. Not a migration (those nodes have minimal app load). Operational brief follows at `docs/operational/briefs/spark-3-4-wipe-and-rebuild-2026-04-29.md`.

---

## Implications already in motion

- ADR-001 amended: division-per-spark rule is retired except for Fortress Legal on Spark 1.
- ADR-003 expanded: inference cluster grows from 4/5/6 to **3/4/5/6**.
- Financial / Acquisitions / Wealth division docs updated: spark allocation changes from "Spark 3 / Spark 4 PLANNED" to "Spark 2 — co-tenant with control plane".
- `infrastructure.md` topology table updated.
- `system-map.md` redrawn (current state + target state both).
- Tensor-parallel sizing at 4 nodes — see "Phase 4 sizing" below.

---

## Phase 4 sizing — 4-node inference cluster

Nemotron-Super-49B-v1.5-FP8 has **64 attention heads**. TP=4 divides cleanly (16 heads per node). Three patterns at 4 nodes:

1. **TP=4 single instance** — max throughput per request. 49B distributed across all four. Single point of failure for the cluster: if any node drops, the instance dies.

2. **TP=2 + TP=2 (recommended default)** — Two independent TP=2 instances. LiteLLM load-balances. One instance can fail without taking the other down. This is Pattern 1 from ADR-003 scaled to 4 nodes — same logic, more capacity.

3. **TP=2 + 2× single-Spark instances** — Maximum failure-domain isolation. Three model-serving instances, LiteLLM load-balances. Lower per-request throughput than TP=4 or TP=2+TP=2 but more parallelism for concurrent requests.

**Default to Pattern 2 (TP=2 + TP=2)** — best balance of throughput, redundancy, and complexity. Pattern 1 is reserved for if BRAIN-tier latency becomes the bottleneck. Pattern 3 is reserved for if concurrent legal-app calls saturate the cluster.

---

## Phase rollout

| Phase | Node | Status | Action |
|---|---|---|---|
| Phase 1 (TODAY) | Spark 5 | ACTIVE | Single-spark BRAIN serving via NIM |
| Phase 2 | Spark 6 | BLOCKED on cable | Joins TP=2 with Spark 5 |
| Phase 3 | Spark 4 | PLANNED | Wipe + join inference cluster (TP=2 + TP=2 with Spark 3, OR TP=4 across 5/6+4) |
| Phase 4 (this ADR) | Spark 3 | PLANNED | Wipe + join inference cluster |

**Phase order:** Spark 6 first (Phase 2 — cable land), then 3 + 4 together (one wipe-rebuild cycle). Don't wipe 3 or 4 before 6 lands — TP=4 across 4 nodes needs all four on ConnectX fabric.

---

## Cross-references

- ADR-001 (LOCKED, partially superseded by this ADR for non-Legal divisions)
- ADR-002 (LOCKED, amended 2026-04-29 by ADR-003 v2 — Council on spark-2 Option A)
- ADR-003 (LOCKED 2026-04-29 — dedicated inference cluster; **expanded** by this ADR from 4/5/6 to 3/4/5/6)
- `docs/operational/briefs/spark-3-4-wipe-and-rebuild-2026-04-29.md` — operational brief for the spark-3/4 wipe execution (not run in this PR)

Last updated: 2026-04-29
