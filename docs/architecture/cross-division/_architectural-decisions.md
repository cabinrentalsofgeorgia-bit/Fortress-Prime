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
**Status:** **OPEN — requires operator input**

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

**Recommendation pending operator input:**

- **Captain:** Option A (Spark 2 permanent) — dividing email by mailbox before classification breaks PR I's cross-case disambiguation
- **Council:** Option B (dedicated shared) — Council reads across divisions for cross-matter retrieval (PR G); a dedicated spark gives it room without contention
- **Sentinel:** Option C (per-division replicas) is plausible since each division's NAS scope is already bounded; Option A also fine

**Status:** **AWAITING OPERATOR DECISION.** When picked, this entry gets amended with the chosen option, the supporting reasoning, and a migration plan. Meanwhile every shared-service doc in `../shared/*.md` notes "Current spark: 2 / Target spark: TBD per ADR-002".

---

## How to add an ADR

1. Increment the number (next is ADR-003)
2. Date it (UTC)
3. Set status: LOCKED, OPEN, AMENDED, or SUPERSEDED-BY-ADR-N
4. State the decision in 1-2 sentences
5. Rationale: why this over alternatives
6. Implications: what changes downstream

Last updated: 2026-04-26
