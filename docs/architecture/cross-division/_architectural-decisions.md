# Architectural Decisions Log (ADR)

A log of major architectural decisions for Fortress Prime, plus open questions awaiting operator confirmation. Each entry is dated; locked decisions are immutable once committed (amend with a new ADR if reversal is needed).

Format inspired by [Michael Nygard's ADR template](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions): each entry has a date, status, decision, rationale.

---

## ADR-001 — One spark per division

**Date:** 2026-04-26
**Status:** **LOCKED**

**Decision:** Each business division gets its own dedicated DGX Spark node. Division ↔ spark is a 1:1 mapping; cross-division services run on a shared infrastructure host (placement TBD per ADR-002).

**Allocation:**

| Spark | Role | Status |
|---|---|---|
| Spark 1 (`192.168.0.X`) | Fortress Legal | **ACTIVE** — hosts Legal email intake, vault ingestion, privileged communications, Council legal retrieval |
| Spark 2 (`192.168.0.100`, control plane @ `100.80.122.100`) | CROG-VRS + current Fortress-Prime monorepo | **ACTIVE — but TEMPORARY HOME** of Market Club replacement scaffolding (Financial division) until Spark 3 is provisioned |
| Spark 3 | Financial (Master Accounting + Market Club replacement) | **PLANNED — not yet provisioned** |
| Spark 4 | TBD; likely Acquisitions or Wealth | **PLANNED** |

**Rationale:**

- **Blast-radius isolation:** a Legal-side bug or Sanker-class regression cannot poison CROG-VRS bookings or Master Accounting ledger writes. Division failures stay in division-shaped boxes.
- **Per-division resource budgeting:** Legal ingestion (process_vault_upload + privilege classifier + Qdrant upsert) consumed ~3 hr CPU on the 7IL run. Sharing that with CROG-VRS guest-traffic peaks would be a noisy-neighbor problem.
- **Per-division scaling:** Financial's Spark 3 can be sized for hedge-fund signal compute without inflating CROG-VRS hardware.
- **Compliance + auditability:** the sovereign immutable ledger lives on Financial; legal vault rows live on Legal; the trust boundaries follow the hardware boundaries.

**Tradeoff:** more hardware, more cross-spark connectivity to manage, more secrets to coordinate. Accepted in exchange for the boundary clarity.

**Implications already in motion:**
- Fortress Legal's email backfill (PR #225) targets Legal infrastructure
- Financial division's `master-accounting.md` was renamed to `financial.md` to reflect both Master Accounting AND the Market Club replacement co-tenancy
- Spark 3 provisioning is the gating dependency for the Spark 2 → Spark 3 migration of `division_a.*` + `hedge_fund.*`

**Amended 2026-04-29 by ADR-003 (2026-04-29 — Dedicated inference cluster):** ADR-001's "one spark per division" rule applies to *app* divisions. Inference is a shared cross-division resource hosted on a dedicated cluster (Sparks 4/5/6) per ADR-003. Acquisitions and Wealth co-tenant on Spark-3 with Financial until Spark-7+ lands.

**Partially superseded 2026-04-29 by ADR-004 (App vs Inference Boundary):** the "one spark per division" rule is retired except for **Fortress Legal on Spark 1**. All non-Legal app workloads (CROG-VRS + control plane + Financial + Acquisitions + Wealth) co-tenant on Spark 2 permanently. Spark 3 and Spark 4 leave the app tier entirely and join the inference cluster (post-wipe). The allocation table in this ADR-001 entry above is **historical** — see the ADR-004 entry below for the current allocation. ADR-001 is preserved in this log (per the "locked decisions are immutable" rule); ADR-004 records the supersession explicitly.

---

## ADR-002 — Where do shared services (Captain, Council, Sentinel) live in the target state?

**Date:** 2026-04-26
**Status:** **LOCKED 2026-04-26**

**Question:** With ADR-001 locking division ↔ spark as 1:1, where do the cross-cutting shared services run?

**The three services:**

- **Captain** — live IMAP email-intake daemon. Polls cPanel mailboxes, classifies, writes to `public.llm_training_captures` + division-tagged routing. Currently on Spark 2.
- **Council** — multi-LLM deliberation engine. Reads from `legal_ediscovery` + `legal_privileged_communications` + general Qdrant collections, runs persona panel, returns SSE stream + `consensus_summary`. Currently on Spark 2.
- **Sentinel** — NAS document indexer. Walks `/mnt/fortress_nas/`, embeds, writes to `fortress_knowledge`. Currently on Spark 2.

**Three options (operator confirms):**

### Option A — Permanent Spark 2 control plane

Captain, Council, Sentinel stay on Spark 2 forever. Spark 2 becomes the canonical "control plane host" alongside its CROG-VRS division duty.

**Pros:** Lowest disruption. Existing code paths keep working. No cross-spark connectivity rework needed.
**Cons:** Spark 2 is already double-duty as CROG-VRS host AND temp Financial host until Spark 3 provisions. Adding "permanent control plane" is a third hat. Resource pressure could grow over time. Also: a CROG-VRS bug could disrupt cross-cutting services that other divisions depend on.

### Option B — Dedicated shared-infrastructure spark

A 5th spark (Spark 5? or repurpose Spark 4 if Acquisitions/Wealth deferred) hosts only Captain + Council + Sentinel + maybe Auth/MCP/secrets.

**Pros:** Clean separation. Each spark has one "audience" (a division, or "everyone"). CROG-VRS bug doesn't disrupt cross-cutting flows.
**Cons:** More hardware. Latency penalty on CROG-VRS workflows that hit Council. Cross-spark Postgres reads needed (probably read-replicas or pgbouncer pools) since the shared services touch every division's data.

### Option C — Replicate per division

Each spark runs its own division-scoped Captain (only that division's mailboxes), Council instance (only that division's Qdrant collections), Sentinel walker (only that division's NAS folders).

**Pros:** Maximum blast-radius isolation. Per-division ownership of cross-cutting tooling.
**Cons:** 4× the operational surface. Email classification spans divisions — Captain by definition sees every mailbox, so dividing it artificially risks miscategorization. Probably wrong for Captain specifically; could work for Sentinel (per-division NAS folders are already well-bounded).

**Decisions (LOCKED 2026-04-26):**

### Captain → **Option A — Spark 2 permanent**

Cross-mailbox classification IS the value of Captain. Dividing it before classification breaks cross-case disambiguation (PR #225 Sanker routing logic relies on seeing every mailbox to compute date-window fallbacks). Centralization is correct architecture, not a compromise.

### Council → **Option B — Spark 4 dedicated (with co-located intermittent divisions)**

**Refinement of Option B:** rather than provisioning a 5th spark for Council alone, Spark 4 hosts **Council + the planned Acquisitions division + the planned Wealth division**. These three workloads are compatible:

- Council: cross-division read-heavy LLM deliberation, bursty workload (drives spark only when an operator initiates a deliberation)
- Acquisitions: intermittent deal-pipeline analysis (per-deal bursts)
- Wealth: lower-frequency intelligence (periodic, not continuous)

Co-locating shared services with intermittent divisions on one spark avoids hardware sprawl while preserving the architectural goal of Council not contending with CROG-VRS guest-traffic peaks.

**New architectural classification:** Spark 4 is the first instance of "shared services + intermittent divisions" — an allowable exception to the strict ADR-001 "one spark per division" rule. Documented in `divisions/_template.md` as a recognized pattern. Future sparks may follow the same pattern if a similar workload-compatibility window appears.

### Sentinel → **Option A — Spark 2 permanent**

Sentinel walks NAS. NAS mounts identically from any spark — there is no per-spark file-system locality benefit. Per-division replicas (Option C) would 4× the file-system traffic on the Synology, 4× the Qdrant collections to sync, 4× the failure modes — for **no architectural benefit** since per-division NAS paths are already cleanly separated by directory tree (`Corporate_Legal/` vs `Business_Prime/` vs `Financial_Ledger/` etc.). Centralization on Spark 2 is correct.

### Updated final architecture (target state)

| Spark | Role | Hosts |
|---|---|---|
| **Spark 1** | Single-division | Fortress Legal |
| **Spark 2** | Multi-purpose: division + shared services | CROG-VRS + **Captain** + **Sentinel** + control plane (Postgres, Qdrant for legal collections, NAS mount, Redis, ARQ, FastAPI) |
| **Spark 3** | Single-division | Financial — Master Accounting + Market Club replacement |
| **Spark 4** | Shared services + intermittent divisions | **Council** + Acquisitions + Wealth |

### Migration plan

1. **Stage 1 (gating):** Spark 4 hardware provisioned. Captain + Sentinel remain on Spark 2 forever (no migration needed for them).
2. **Stage 2:** Stand up Council on Spark 4 as warm-spare (no traffic). Council on Spark 2 keeps serving deliberations.
3. **Stage 3:** Verification — run Council on both sparks in parallel for one week; compare frozen-context outputs for byte-equality on the same case_slug input. Read-replica latency from Spark 4 → Spark 2's Qdrant must stay under the existing per-deliberation latency budget.
4. **Stage 4:** Cutover — `apps/command-center` switches its deliberation API endpoint from Spark 2 to Spark 4. Spark 2 Council instance retires after a 7-day soak.
5. **Stage 5:** Spark 4 onboards Acquisitions and Wealth as the divisions ramp (independent of Council; their schemas may live on Spark 4's Postgres with cross-spark access from Spark 2 if needed).

### Implications already documented downstream

- `shared/captain-email-intake.md` header → Current: Spark 2 / Target: Spark 2 (permanent)
- `shared/council-deliberation.md` header → Current: Spark 2 / Target: Spark 4 (post-Spark-4 provisioning)
- `shared/sentinel-nas-walker.md` header → Current: Spark 2 / Target: Spark 2 (permanent)
- `shared/infrastructure.md` Spark allocation table reflects target state with Spark 4 multi-purpose classification
- `divisions/_template.md` documents the multi-purpose Spark 4 exception pattern
- `system-map.md` target diagram + 5-stage migration includes the Spark 4 Council step

**Amended 2026-04-29 by ADR-003 (2026-04-29 — Dedicated inference cluster):** the **Council → Spark-4 (Option B with Acquisitions+Wealth co-location)** decision is reversed. Council joins Captain and Sentinel on the **spark-2 control plane (Option A across the board)**. Spark-4 becomes an inference-tier node — not a Council host, not a co-tenant of Acquisitions/Wealth. Acquisitions and Wealth co-tenant on Spark-3 with Financial until Spark-7+ lands. The "shared services + intermittent divisions" multi-purpose-Spark-4 pattern documented above no longer describes the target state; the target Council host is spark-2 control plane permanently.

---

## ADR-003 (2026-04-26) — Inference plane: shared swarm across all sparks

**Date:** 2026-04-26
**Status:** **SUPERSEDED-BY ADR-003 (2026-04-29)** — see entry below. Original "shared swarm across all sparks" decision is no longer the target state; inference now consolidates on a dedicated 4/5/6 cluster.

**Decision:** Inference compute (LLM + embedding) is a shared cluster-wide resource, distributed across all 4 sparks. Division-owned data and business logic remain isolated per ADR-001. ADR-002 service placement unchanged.

**Data plane / inference plane separation:**

Data plane (per-division, ADR-001 unchanged):
- Spark 1 owns Legal data, schemas, code
- Spark 2 owns CROG-VRS data, schemas, code
- Spark 3 owns Financial data, schemas, code (when provisioned)
- Spark 4 owns Council deliberation logic + Acquisitions + Wealth (per ADR-002)

Inference plane (cluster-wide, shared):
- All 4 sparks contribute LLM + embedding capacity
- LiteLLM proxy (already running on Spark 2) load-balances inference across all endpoints
- Any division can consume inference from any spark
- Council deliberation, embedding ingestion, and other LLM workloads route through LiteLLM, not direct endpoint calls
- 100Gbps ConnectX interconnect makes cross-spark inference calls operationally fine

**Rationale:**

- Maximizes hardware utilization (idle division inference capacity available to busy divisions)
- Decouples inference scaling from division scaling (add more sparks for compute without restructuring division ownership)
- Single LiteLLM control point for cost/usage accounting per division (virtual keys per division → per-division usage tracking)
- Resolves Issue #228 root cause path: parallel embedding dispatch across endpoints reduces per-message latency, currently the Vanderburge ingestion bottleneck
- Compatible with existing infrastructure (LiteLLM already running, Ollama already on Spark 2)

**Implementation roadmap (NOT executing today, just documenting):**

### Phase 1 — Endpoint multiplication
- Install Ollama (or vLLM) on Spark 1, Spark 3 when provisioned, Spark 4 when provisioned
- Each spark hosts its own embedding model (`nomic-embed-text`) + an LLM
- Register endpoints with LiteLLM proxy
- Verify inference works from any spark targeting LiteLLM

### Phase 2 — Embedding queue
- Redis-backed queue (Spark 2 hosts Redis, per ADR-002 control plane location)
- Worker processes on each spark consume from queue
- `process_vault_upload` enqueues chunks instead of synchronous embedding calls
- Workers dispatch to local Ollama endpoint OR via LiteLLM (TBD per implementation)

### Phase 3 — Council load balancing
- Council deliberation steps route through LiteLLM
- Multi-LLM deliberation can use different endpoints for different personas in parallel

### Phase 4 — Per-division usage accounting
- LiteLLM virtual keys per division
- Cost/token tracking per case_slug, per deliberation, per ingestion
- Surface in admin dashboard

Each phase is its own PR with explicit operator authorization. ADR-003 LOCKED captures architectural direction; implementation phases are deliberate, gated work.

**Cross-references:**

- ADR-001 (one-spark-per-division) **UNCHANGED**
- ADR-002 (Captain/Council/Sentinel placement) **UNCHANGED**
- Council on Spark 4 still owns deliberation logic; ADR-003 just means it can dispatch inference workload to any spark
- Sentinel on Spark 2 still owns NAS walking; ADR-003 lets it use cluster-wide embedding for indexing
- Captain on Spark 2 still owns email intake classification; ADR-003 lets it use cluster-wide inference for any LLM-assisted classification

**Open questions deferred to implementation phases:**

- Direct endpoint calls vs. LiteLLM-only routing (worker dispatch pattern)
- Embedding queue implementation (Redis vs. another queue)
- Failure semantics when an endpoint is unavailable (retry, circuit-break, degraded mode)
- Per-division rate limiting via LiteLLM
- Observability (metrics per endpoint, per division, per workload type)

---

## ADR-003 (2026-04-29) — Dedicated inference cluster on Sparks 4/5/6

**Date:** 2026-04-29
**Status:** **LOCKED** — operator decision 2026-04-29
**Phase 3 sizing:** **Pattern 1 — TP=2 + 1 hot replica** (locked at decision time)
**Supersedes:** ADR-003 (2026-04-26 — "Inference plane: shared swarm across all sparks") above. The shared-swarm decision was made before the dedicated-inference-cluster topology was on the table; this ADR replaces it.
**Amends:** ADR-001 (one spark per division — see amendment paragraph in ADR-001 entry). **Amends:** ADR-002 (Council placement — see amendment paragraph in ADR-002 entry; Council moves from Spark-4 Option B back to spark-2 Option A).

**Canonical document:** `docs/architecture/cross-division/ADR-003-inference-cluster-topology.md` (full decision text, rationale, tradeoffs, Phase 1/2/3 rollout, tensor-parallel sizing analysis).

**Decision (one-paragraph summary for registry readers):**
Sparks **4, 5, and 6** form a dedicated inference cluster. No division apps tenant on these nodes. App workloads consolidate to Sparks 1/2/3 (1 = Legal; 2 = CROG-VRS + control plane permanently hosting Captain + Council + Sentinel + LiteLLM; 3 = Financial + Acquisitions + Wealth co-tenants until Spark-7+). All BRAIN-tier and TITAN-tier inference traffic from any division terminates on the 4/5/6 cluster via the LiteLLM gateway on spark-2.

**Phased rollout:**

- **Phase 1 (this PR):** Spark-5 serves Nemotron-Super-49B-FP8 NIM at port 8100. LiteLLM gateway on spark-2 routes BRAIN tier → spark-5. Closes audit finding A-02 (cloud legal inference).
- **Phase 2:** Spark-6 cable cutover (10GbE → ConnectX). Spark-5 (head) + Spark-6 (worker) form a Ray cluster running vLLM with `--tensor-parallel-size 2` over NCCL/RDMA. Single OpenAI-compatible endpoint, 128K context, 2× throughput.
- **Phase 3:** Spark-4 joins inference cluster (software-only — Spark-4 already on ConnectX). **Phase 3 sizing locked: Pattern 1 — TP=2 + 1 hot replica.** Two Sparks tensor-parallel one 49B instance, third Spark runs a second 49B instance, LiteLLM load-balances. Doubles throughput, gives a live failover node, no model-architecture constraint (49B's 64 attention heads are not divisible by 3, so literal TP=3 will not run).

**Allocation (post-Phase 3):**

| Spark | Fabric | Role | Tenants |
|---|---|---|---|
| Spark 1 | ConnectX | App | Fortress Legal |
| Spark 2 | ConnectX | App + control plane | CROG-VRS, Captain, Sentinel, **Council** (post-revert), Postgres, Qdrant (legal), Redis, ARQ, FastAPI, **LiteLLM gateway** |
| Spark 3 | ConnectX | App | Financial; Acquisitions + Wealth co-tenant pending Spark-7+ |
| Spark 4 | ConnectX | Inference | Ray worker (Phase 3) |
| Spark 5 | ConnectX | Inference | Ray head; Nemotron-Super-49B-FP8 NIM |
| Spark 6 | 10GbE → ConnectX (cable pending) | Inference | Ray worker (Phase 2+) |

**Rationale (capsule — full text in canonical doc):**
- Boundary clarity: inference is a shared cross-division resource; tying it to a division Spark creates noisy-neighbor risk and memory pressure (the spark-1 ≥99% memory under BRAIN load symptom from 2026-04-23 is the example).
- NVIDIA reference path: Ray + vLLM + NIM over ConnectX-7 is what `build.nvidia.com/spark` documents.
- Closes audit A-02: legal inference moves from cloud to spark-5 NIM in Phase 1.
- Frees spark-1 for Fortress Legal app work (vault ingestion, privilege classification, Qdrant upserts, Council orchestration).

**Implications:**
- `shared/infrastructure.md` DEFCON tier table: BRAIN tier moves spark-1 → spark-5 (and 5+6 at Phase 2; 4/5/6 at Phase 3).
- `system-map.md`: redrawn for app/inference split — current state and target state.
- `006-nemoclaw-ray-deployment.md`: Ray worker list narrows to spark-4/5/6 only. Orchestrator stays on spark-2 control plane.
- `IRON_DOME` v6.1: sovereignty claim becomes accurate after Phase 1 cutover.
- LiteLLM config (Phase 1): legal routes cloud → `http://spark-5:8100/v1`.

**Open question deferred to Phase 2 completion:** what event moves Spark-4 from "app spark for Acquisitions or Wealth" to "inference cluster member"? Suggested triggers: (a) Acquisitions/Wealth workloads stay light enough to co-tenant on Spark-3, OR (b) BRAIN-tier traffic outgrows TP=2 throughput. Operator confirms criterion at Phase 2 completion.

**Expanded 2026-04-29 by ADR-004 (App vs Inference Boundary):** the inference cluster grows from **3 nodes (4/5/6)** to **4 nodes (3/4/5/6)**. Open question above is closed: Spark-4 is now an inference-cluster member by allocation, not by trigger event; Acquisitions/Wealth co-tenant on Spark-2 instead. Phase 4 sizing default is **TP=2 + TP=2** (two independent TP=2 instances, LiteLLM load-balances). See the ADR-004 entry below for the full sizing analysis (Pattern 1/2/3 at 4 nodes).

---

## ADR-004 (2026-04-29) — App vs Inference Boundary

**Date:** 2026-04-29
**Status:** **LOCKED** — operator decision 2026-04-29
**Supersedes:** Partial supersession of ADR-001's "one spark per division" rule (retired except for Fortress Legal on Spark 1). Cross-division services portion of ADR-002 stays resolved (Captain/Council/Sentinel on spark-2 control plane, Option A across the board per ADR-003 v2 amendment).
**Expands:** ADR-003's inference cluster designation grows from Sparks 4/5/6 to **Sparks 3/4/5/6**.

**Canonical document:** `docs/architecture/cross-division/ADR-004-app-vs-inference-boundary.md` (full decision text, rationale, tradeoffs, Phase 4 sizing analysis, phase rollout).

**Decision (one-paragraph summary for registry readers):**

The boundary that drives spark allocation is **app vs inference**, not division-per-spark. Division-per-spark is abandoned for everything except **Fortress Legal** (which keeps its own spark for sovereignty + privilege isolation). Spark 1 is the only single-tenant app spark. Spark 2 carries CROG-VRS + control plane + LiteLLM gateway + Financial + Acquisitions + Wealth permanently. Sparks 3/4/5/6 form the dedicated inference cluster (post-wipe of 3 and 4 — operational brief at `docs/operational/briefs/spark-3-4-wipe-and-rebuild-2026-04-29.md`, gated on Spark-6 cable cutover).

**Allocation (post-wipe of 3+4):**

| Spark | Fabric | Role | Tenants |
|---|---|---|---|
| Spark 1 | ConnectX | App — single tenant | Fortress Legal |
| Spark 2 | ConnectX | App — control plane + multi-tenant | CROG-VRS, Captain, Sentinel, Postgres, Qdrant (legal), Redis, ARQ, FastAPI, **LiteLLM gateway**, **Financial** (Master Accounting + Market Club replacement), **Acquisitions**, **Wealth** |
| Spark 3 | ConnectX | Inference (post-wipe) | Ray worker |
| Spark 4 | ConnectX | Inference (post-wipe) | Ray worker |
| Spark 5 | ConnectX | Inference (active) | Ray head; Nemotron-Super-49B-FP8 NIM |
| Spark 6 | 10GbE → ConnectX (cable pending) | Inference (Phase 2) | Ray worker |

**Phase 4 sizing (4-node cluster):** default **Pattern 2 — TP=2 + TP=2** (two independent TP=2 instances, LiteLLM load-balances; one instance can fail without taking the other down). Pattern 1 (TP=4 single instance) reserved for if BRAIN-tier latency becomes the bottleneck. Pattern 3 (TP=2 + 2× single-Spark instances) reserved for if concurrent legal-app calls saturate the cluster.

**Rationale (capsule — full text in canonical doc):**
- Inference is the choke point for white-shoe-grade legal output. A 4-node inference cluster (3/4/5/6) on Pattern 2 doubles ADR-003's 3-node cluster capacity at the same Pattern-1 redundancy floor.
- Spark-2 has historically carried all enterprises. The "one spark per division" rule was an aspirational target that assumed enough hardware to enforce it; in reality non-Legal divisions share spark-2 already and the migration cost beats the marginal benefit.
- Fortress Legal is the exception. Privilege + audit + waiver concerns justify dedicated hardware. Spark-1 stays single-tenant.
- Per-division resource budgeting becomes a spark-2 operational concern, not an architectural rule. Logical isolation (Postgres roles, Qdrant collections, ARQ queues) is sufficient.
- Closes the "spark-3 timeline" question. Financial's spark-3 migration under ADR-001 is canceled — Financial stays on spark-2 permanently.

**Tradeoffs accepted:**
- Spark-2 carries more load (mitigated by per-division logical isolation; inference workload is entirely off-box on the spark-3/4/5/6 cluster).
- No inter-enterprise blast-radius isolation on spark-2 (mitigated by separate database roles, schema isolation, process isolation).
- Acquisitions + Wealth never get dedicated sparks (operator-accepted; both are early-stage).
- Spark-3 + Spark-4 require wipe-and-rebuild to join the inference cluster (operational brief is the execution doc; not run from this PR).

**Implications already in motion:**
- ADR-001's allocation table is historical (supersession note added above).
- ADR-003's inference cluster designation expanded (expansion note added above).
- `docs/architecture/divisions/financial.md`, `acquisitions.md`, `wealth.md`, `market-club.md` updated: spark allocation changes from "Spark 3 / Spark 4 PLANNED" to "Spark 2 — co-tenant with control plane".
- `docs/architecture/shared/infrastructure.md` topology table updated.
- `docs/architecture/system-map.md` redrawn (current state + target state).
- `docs/operational/MASTER-PLAN.md` §5 architectural foundation table + §6 work tracks updated.

**Phase rollout:**

| Phase | Node | Status | Action |
|---|---|---|---|
| Phase 1 (TODAY) | Spark 5 | ACTIVE | Single-spark BRAIN serving via NIM |
| Phase 2 | Spark 6 | BLOCKED on cable | Joins TP=2 with Spark 5 |
| Phase 3 | Spark 4 | PLANNED | Wipe + join inference cluster (TP=2 + TP=2 with Spark 3, OR TP=4 across 5/6+4) |
| Phase 4 (this ADR) | Spark 3 | PLANNED | Wipe + join inference cluster |

Phase order: Spark 6 first (Phase 2 — cable land), then 3 + 4 together (one wipe-rebuild cycle). Don't wipe 3 or 4 before 6 lands — TP=4 across 4 nodes needs all four on ConnectX fabric.

### Amendment 2026-04-29 — Retain-and-Document supersedes Wipe-and-Rebuild

Read-only audits of spark-3 and spark-4 on 2026-04-29 confirmed both nodes are already 90% inference-cluster members operationally. ADR-004's wipe-and-rebuild plan was over-engineered for the actual state. An attempted "cleanup-and-verify" path (remove redundant ollama on spark-3 + spark-4) hit a production-callers issue and was rolled back cleanly within ~10 minutes. Both nodes back to baseline; this amendment codifies the resulting policy.

**Revised disposition:** Spark-3 + Spark-4 retain all current workloads. Document state. Plan service consolidation only after caller migration. No production changes from this amendment.

**What it settles:**
1. Spark-3 + Spark-4 are formally inference-cluster members per the ADR-004 boundary; their app-tier services (ollama, qdrant-vrs, sensevoice) are retained as inference-adjacent capabilities.
2. The "spark-2 = canonical SWARM" doc story is incorrect. Reality: SWARM is distributed across spark-2, spark-3, spark-4 ollama instances. Doc/config reconciliation is filed as a separate P3 issue.
3. Service consolidation (collapsing multiple ollama instances) is a future migration that requires caller-rewrite work first. Filed P4. Not happening in this PR or session.

**Why amendment v2:** the wipe-and-rebuild assumption was that spark-3/4 were dirty app nodes needing cleanup; reality is neither node has app cruft, drivers are current, fabric is dedicated, and ollama on spark-3/4 hosts models spark-2 doesn't have (called by hardcoded URLs). Wipe-and-rebuild would have destroyed the working SWARM tier. Retain-and-document is the correct shape.

**Companion docs (this PR):**
- Canonical amendment text: `docs/architecture/cross-division/ADR-004-app-vs-inference-boundary.md` § Amendment 2026-04-29
- Incident lessons: `docs/operational/incident-2026-04-29-ollama-removal.md`
- Retained-state record + caller surface: `docs/operational/spark-3-4-retained-state-2026-04-29.md`
- Original wipe brief is header-noted as superseded; not deleted.

**Open follow-ups (filed as separate issues):** Spark-4 RDMA enumeration debug (P3), VRS Qdrant migration trigger (P5 monitoring), NIM ASR ARM64 monitor (P3), doc/config reconciliation (P3), ollama consolidation migration (P4).

---

## ADR-006 (2026-04-30) — Phase 2 Partner Reassignment (spark-5 + spark-4 in lieu of spark-5 + spark-6)

**Date:** 2026-04-30
**Status:** **LOCKED 2026-04-30** — operator concurrence Gary Knight
**Supersedes:** ADR-003 §Phase 2 partner choice. ADR-003's overall inference cluster intent (Sparks 4/5/6 expanded to 3/4/5/6 per ADR-004 amendment v2) remains in force. ADR-003 Pattern 1 sizing (TP=2 + hot replica) remains the locked Phase 3 sizing decision.
**Relates to:** ADR-001 (LOCKED, amended), ADR-002 (LOCKED, resolved by ADR-003), ADR-003 (LOCKED 2026-04-29 + Phase 1 cutover PR #285), ADR-004 amendment v2 (LOCKED 2026-04-29, retain-and-document, PR #293).

**Canonical document:** `docs/architecture/cross-division/ADR-006-phase-2-partner-reassignment.md` (full decision text, rationale, tradeoffs, consequences).

**Decision (one-paragraph summary for registry readers):**

Phase 2 TP=2 BRAIN partnership is reassigned from spark-5 + spark-6 to **spark-5 + spark-4**. Spark-6 is deferred to Phase 3+ as hot replica once its ConnectX hardware status resolves. The spark-6 hardware gap (`lspci | grep -i mellanox` returns nothing per PR #309 audit) makes its Phase 2 partnership operator-paced and unbounded; spark-4 has working ConnectX fabric (10.10.10.4 + 10.10.11.4, 100Gbps, MTU 9000, Ray worker active) and is available today. ADR-003 Pattern 1 sizing (TP=2 + hot replica) remains the locked Phase 3 design — only the partner identity changes.

**Rationale (capsule — full text in canonical doc):**
- Spark-6 hardware gap is operator-paced; waiting risks counsel-hire critical path (~46 days remaining per master plan §2 case clock).
- Spark-4 has working ConnectX fabric per audit + RDMA driver srcversion matching cluster canonical.
- Spark-4 RAM headroom permits TP=2 partnership (working set estimate ~30GB; read-only verification 2026-04-30 measured 5.6 GiB actual RSS; 128GB envelope; BRAIN-half ~25GB → total ~30–55GB committed, ~70–95GB headroom).
- Spark-5 RAM headroom IMPROVES under TP=2 (92% utilization standalone → ~25GB BRAIN-half post-split).
- ADR-004 v2's retain-and-document intent is satisfied: spark-4 keeps existing services, TP=2 added additively, no wipe.
- Spark-6 path not abandoned — joins Phase 3 hot replica when hardware resolves.

**Tradeoffs accepted:**
- Spark-4's app workload co-tenants with TP=2 BRAIN-half (memory pressure ~30GB → ~55GB; acceptable within 128GB envelope).
- Optional Ollama migration off spark-4 deferred to operational brief execution.
- qdrant-vrs + SenseVoice stay on spark-4 (no inference contention expected).
- Phase 2 deviates from ADR-003's locked design — operator-locked decisions amended via subsequent ADRs.
- Spark-6 hot replica delivery date unknown; Phase 3 + Phase 4 gated on hardware resolution.

**Consequences:**
- Master plan §5.1 cluster IP truth table needs spark-4 role updated to "App + Inference partner" post-cutover.
- Master plan §5.2 inference tier table: BRAIN service updates from "spark-5:8100 standalone NIM" to "spark-5+spark-4 TP=2 vLLM endpoint spark-5:8000 (or VIP)".
- Master plan §6.2 inference platform: ADR-003 Phase 2 status moves from "BLOCKED on cable" to "EXECUTING per ADR-006".
- ADR-003 Phase 3 (hot replica) + Phase 4 (4-node sizing) status: gated on spark-6 hardware resolution, not just cable.
- Spark-4 RDMA enumeration debug Issue #294 becomes higher priority — spark-4 is now an RDMA endpoint.
- ADR-004 v2 retain-and-document scope extended: spark-4 now holds inference + app co-tenancy, not just app + Ray worker.

**Companion docs (this PR):**
- Canonical ADR text: `docs/architecture/cross-division/ADR-006-phase-2-partner-reassignment.md`
- Operational cutover brief: `docs/operational/briefs/tp2-brain-phase-2-cutover-2026-04-30.md` (drafted; execution is a separate authorized PR)

---

## How to add an ADR

1. Increment the number (next is ADR-007)
2. Date it (UTC)
3. Set status: LOCKED, OPEN, PROPOSED, AMENDED, or SUPERSEDED-BY-ADR-N
4. State the decision in 1-2 sentences
5. Rationale: why this over alternatives
6. Implications: what changes downstream

Last updated: 2026-04-30 (ADR-006 LOCKED — Phase 2 partner reassignment from spark-6 to spark-4, operator concurrence Gary Knight; ADR-004 LOCKED + amended v2 retain-and-document; ADR-001 partially superseded for non-Legal divisions; ADR-003 expanded from 4/5/6 to 3/4/5/6)
