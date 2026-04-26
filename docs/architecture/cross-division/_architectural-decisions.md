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

---

## ADR-003 — Inference plane: shared swarm across all sparks

**Date:** 2026-04-26
**Status:** **LOCKED 2026-04-26**

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

## How to add an ADR

1. Increment the number (next is ADR-004)
2. Date it (UTC)
3. Set status: LOCKED, OPEN, AMENDED, or SUPERSEDED-BY-ADR-N
4. State the decision in 1-2 sentences
5. Rationale: why this over alternatives
6. Implications: what changes downstream

Last updated: 2026-04-26
