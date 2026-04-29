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
- `docs/operational/briefs/spark-3-4-wipe-and-rebuild-2026-04-29.md` — operational brief for the spark-3/4 wipe execution (superseded — see Amendment 2026-04-29 below)

---

## Amendment 2026-04-29 — Retain-and-Document supersedes Wipe-and-Rebuild

**Driver:** Read-only audits of spark-3 and spark-4 on 2026-04-29 confirmed both nodes are already 90% inference-cluster members operationally. ADR-004's wipe-and-rebuild plan was over-engineered for the actual state. An attempted "cleanup-and-verify" path (remove redundant ollama) hit a production-callers issue and was rolled back cleanly within minutes. Both nodes return to operational baseline; this amendment codifies the resulting policy.

**Revised disposition:**

| Spark | Original ADR-004 plan | Amendment v2 plan |
|---|---|---|
| Spark-3 | Wipe + reinstall + Ray worker join | Retain all current workloads. Document state. Plan service consolidation only after caller migration. |
| Spark-4 | Wipe + reinstall + Ray worker join | Retain all current workloads. Document state. Plan service consolidation only after caller migration. |

**Spark-3 current state (operator-confirmed, RETAINED):**

| Service | Status | Production callers |
|---|---|---|
| Vision NIM (`fortress-nim-vision-concierge`) | Active 6+d | Production sovereign workload |
| ollama (Docker container, port 11434) | Active | `crog_concierge_engine.HYDRA_32B_URL` default, `persona_template.HYDRA_HEAD_3` default, `fortress_atlas.yaml` (vision_specialist), other doc references |
| ollama models | qwen2.5:7b (privilege classifier), llama3.2-vision:90b, llama3.2-vision:latest, nomic-embed-text:latest | Various |
| `fortress-ray-worker.service` | Active, enabled | Inference cluster member |
| docling-shredder container | Active 13+d | Legal PDF parser |
| llama.cpp build | Present | TITAN-tier serving infrastructure |
| nccl-tests | Present | Fabric verification |
| Cached NIM images | nv-embedqa-e5-v5 (4.27 GB), deepseek-r1-distill-llama-70b (15 GB), cosmos-reason2-2b, nemotron-3-super-120b weights | Future deployment candidates |
| ConnectX 100Gbps fabric | UP, RoCE enumerated cleanly | Inference cluster |
| Postgres / app data | none | — |

**Spark-4 current state (operator-confirmed, RETAINED):**

| Service | Status | Production callers |
|---|---|---|
| ollama.service (systemd, port 11434) | Active, enabled | `fortress-guest-platform/.env` SWARM_URL + HYDRA_FALLBACK_URL, `ingest_taylor_sent_tarball.py`, `reclassify_other_topics.py`, `sent_mail_retriever.py`, `crog_concierge_engine.HYDRA_120B_URL` default, `persona_template.HYDRA_HEAD_4` default, `fortress_atlas.yaml` (deep_reasoning_redundancy + vrs_fast_primary) |
| ollama models | qwen2.5:7b, qwen2.5:32b, deepseek-r1:70b, nomic-embed-text:latest, llava:latest, mistral:latest | SWARM tier per fortress_atlas.yaml |
| `fortress-qdrant-vrs.service` | Active 4+d | VRS dual-write target |
| SenseVoice container (ARM64) | Active 4+d | Deposition ASR (current, replace when NIM ASR ARM64 ships) |
| `fortress-ray-worker.service` | Active, enabled | Inference cluster member |
| llama.cpp build | Present | TITAN serving |
| nccl-tests | Present | Fabric verification |
| ConnectX 100Gbps fabric | Link UP, RDMA enumeration empty (P3 follow-up) | Inference cluster |
| Postgres / app data | none | — |

**What CHANGES under this amendment:** nothing in production. Both nodes stay as-is.

**What this amendment SETTLES:**

1. Both spark-3 + spark-4 are formally inference-cluster members per ADR-004 boundary. Their app-tier services (ollama, qdrant-vrs, sensevoice) are retained as inference-adjacent capabilities.
2. The "spark-2 = canonical SWARM" doc story is incorrect. Reality: SWARM is distributed across spark-2, spark-3, spark-4 ollama instances. The doc story will be reconciled in a separate fortress_atlas.yaml + CLAUDE.md update PR.
3. Service consolidation (collapsing multiple ollama instances onto fewer nodes) is a future migration that requires caller-rewrite work before any service removal. Not happening in this PR or this session.

**Open follow-ups (filed as separate issues):**
- Spark-4 RDMA enumeration debug (`ibstat` empty) — P3
- VRS dual-write retirement triggers fortress-qdrant-vrs migration to spark-2 — P5 monitoring
- NIM ASR ARM64 availability triggers SenseVoice replacement — P3 monitoring
- Doc/config reconciliation — fortress_atlas.yaml + CLAUDE.md need updating to match reality. P3.
- Ollama consolidation migration — proper caller-migration plan before any service removal. P4.

**Rationale for amendment v2:**

The wipe-and-rebuild assumption was that spark-3/4 were dirty app nodes needing cleanup. Reality:
- App cruft requiring removal — confirmed absent
- Driver/CUDA stack stale — confirmed current (driver 580.142, GB10 GPU, RDMA modules loaded)
- Storage clutter — confirmed minor (17% used spark-3, 7% used spark-4)
- Not on inference fabric — confirmed FALSE (both on dedicated 10.10.10.x and 10.10.11.x)
- Services redundant with spark-2 — confirmed FALSE (ollama on spark-3/4 hosts models spark-2 doesn't have, called by hardcoded URLs)

Wipe-and-rebuild would have destroyed the working SWARM tier. Cleanup-and-verify (the first amendment attempt) destroyed it temporarily (10 minutes), caught fast, rolled back clean. Retain-and-document is the correct shape.

**Cross-references for the amendment:**
- Lessons-learned doc: `docs/operational/incident-2026-04-29-ollama-removal.md`
- Retained-state record + caller surface: `docs/operational/spark-3-4-retained-state-2026-04-29.md`
- Original wipe brief (header-noted as superseded): `docs/operational/briefs/spark-3-4-wipe-and-rebuild-2026-04-29.md`

Last updated: 2026-04-29 (Amendment v2 — retain-and-document supersedes wipe-and-rebuild)
