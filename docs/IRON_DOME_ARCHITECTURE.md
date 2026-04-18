# Iron Dome — Fortress-Prime Sovereign AI Defense System

**Version:** 4.0
**Date:** April 18, 2026
**Author:** Gary Knight (with Claude)
**Supersedes:** v3 (commit 0b4730fef)

## Why v4

v3 documented the cluster as four GB10 nodes running a mix of models with no clear mapping from business to compute. The fix-the-routing audit answered "where does deepseek-r1:70b actually live?" but not "which business gets which node?"

v4 is the business-driven architecture. Fortress-Prime operates two enterprise workloads that differ in every meaningful dimension — legal privilege, data volume, query patterns, hardware needs, eval criteria. Running them on shared compute with implicit routing is architecturally wrong. v4 explicitly assigns nodes, vector stores, and distillation targets per business.

## The two businesses

**CROG-VRS (Cabin Rentals of Georgia)**

High-volume, consumer-facing, fast-response. Guest concierge via SMS and email. Rate optimization across 40+ properties. Channel management across Airbnb, VRBO, Booking.com. Damage claim workflows. Listing content. Competitor intelligence.

Query profile: short context, high frequency, conversational voice. Privacy: guest PII, payment data (filtered out at capture). Privilege: none — standard business content.

Eval criteria: response relevance, brand voice consistency, factual accuracy about property details, pricing reasonableness.

**Fortress Legal**

Low-volume, deep-reasoning, privileged. Active litigation (SUV2026000013 Generali v. CROG et al). Deposition preparation, brief drafting, discovery review, case chronology, statute research.

Query profile: long context, low frequency, formal voice. Privacy: attorney-client privilege, attorney work product. Data: pleadings, contracts, discovery documents, chronologies.

Eval criteria: legal accuracy, citation integrity, preservation of argumentative structure, zero hallucination of statutes or case holdings.

These two workloads should share as little as possible.

## Node assignment — final

### spark-2 (192.168.0.100) — Orchestrator + Fast Tier + Embeddings

Role: the cluster's brain. Makes routing decisions, writes embeddings, serves the fast tier. High-frequency small-context work.

Loaded models:
- qwen2.5:7b — concierge replies, OTA responses, message classification
- qwen2.5:0.5b — intent routing, small classification tasks
- nomic-embed-text — universal embedding endpoint

Services:
- fortress-backend, all worker processes
- ai_router decision-making
- k3s control plane
- Model registry (health probes + routing)
- Universal embedding writer (all RAG ingestion hits this endpoint)

Explicitly NOT on spark-2:
- NIM llama-3.1-8b — move to spark-1
- Any training workloads — use business-owned training node
- Deep-tier inference — routes to spark-1/spark-4

Why: the node that routes traffic should be fast and free of heavy inference load. Embeddings are a shared service across both businesses; centralizing them on spark-2 simplifies ingestion pipelines.

### spark-1 (192.168.0.104) — Fortress Legal

Role: Fortress Legal's sovereign compute. Privileged by design.

Loaded models:
- deepseek-r1:70b — deposition prep, brief drafting, complex legal reasoning
- qwen2.5:32b — document review, discovery summarization, mid-weight legal work
- qwen2.5:32b-fortress-legal (future distilled) — routine legal workflows
- nomic-embed-text — legal-domain embeddings
- NIM llama-3.1-8b (migrated from spark-2)

Vector stores on this node:
- Fortress Legal vector store — pleadings, statutes, case law, contracts, chronologies, discovery documents
- Privileged case corpus per active matter

Access control:
- Only legal_council, ediscovery_agent, legal_email_intake, legal_intake modules route here
- model_registry enforces this via source_module check
- Privileged captures from these modules route to restricted_captures (Phase 2 filter)

Why: legal work is the most privilege-sensitive workload in the stack. Physical and logical isolation makes the privilege defense clean. If opposing counsel ever argues privilege waiver, the architecture answer is: legal content lived on a single dedicated node, was never mixed with other business data, and never crossed compute boundaries.

### spark-3 (192.168.0.105) — Ocular (Vision)

Role: anything involving images.

Loaded models:
- llama3.2-vision:90b — damage assessment, property photos, listing QC
- nomic-embed-text — caption and alt-text embeddings

Services:
- Vision API endpoint exposed at :11434 (default Ollama)
- Called directly by damage_claim_workflow, listing_qc_worker, ota_vision_recon

Why: vision is a specialized workload. Keeps image processing from saturating text nodes. spark-3 is dedicated — not active-active, not shared.

### spark-4 (192.168.0.106) — CROG-VRS + Deep Tier Redundancy

Role: CROG-VRS's sovereign compute. Active-active backup for spark-1's general deep tier (non-legal).

Loaded models:
- deepseek-r1:70b — pricing strategy, revenue optimization, competitor analysis
- qwen2.5:32b — market intelligence, damage claim reasoning
- qwen2.5:7b-crog-vrs (future distilled) — routine VRS workflows
- qwen2.5:7b — fallback if spark-2 fast tier saturates
- nomic-embed-text — VRS-domain embeddings

Vector stores on this node:
- CROG-VRS vector store — property inventory, guest history, pricing patterns, SOPs, OTA responses, damage claim history

Services:
- VRS API endpoint at :11434
- Called by vrs_agent_dispatcher, quote_engine, concierge_worker, reactivation_hunter, damage_claim_workflow

Active-active behavior: if spark-1's non-legal deep tier fails, model_registry routes those calls to spark-4. Legal calls never route here regardless of spark-1 health.

## RAG architecture — domain-isolated

### Why isolation

Cross-domain RAG retrieval is the number-one way privilege leaks in production LLM systems. A query about "wedding cancellation" from a guest messaging flow retrieves a passage from a deposition prep memo if they share a vector store. Domain isolation prevents this at the retrieval layer, not just the filter layer.

### Vector store topology

**CROG-VRS store:** on spark-4 or NAS-pinned and mounted at spark-4. Contains:
- Property inventory (location, amenities, photos metadata)
- Guest conversation history (filtered for PII)
- Pricing analysis archive
- Competitor intelligence
- OTA response templates and history
- SOPs and operational playbooks
- Damage claim corpus
- Market research (Blue Ridge, Fannin County, North Georgia)

**Fortress Legal store:** on spark-1, physically not replicated elsewhere. Contains:
- Active case pleadings
- Statutes (Georgia state, federal)
- Case law (Georgia appellate, federal circuit)
- Contract corpus (lease agreements, OTA contracts, vendor agreements)
- Discovery document production sets (per matter)
- Chronologies
- Privileged work product (briefs, memos, strategy notes)

**Shared entities store:** on NAS, accessible from spark-2. Contains:
- Property registry (name, address, owner, management contract)
- Contact registry (guests, vendors, owners, counsel)
- Calendar/event data
- Any data that exists identically in both business contexts

### Query-time retrieval rules

1. Query source module determines which stores are eligible:
   - legal_council → Fortress Legal store only
   - vrs_agent_dispatcher → CROG-VRS store + shared entities only
   - concierge_worker → CROG-VRS store + shared entities only
   - General queries → shared entities only

2. Cross-domain retrieval is prohibited at the query layer, not just advised.

3. Embedding writes follow the same isolation:
   - Legal module writes → legal embedding endpoint (spark-1)
   - VRS module writes → VRS embedding endpoint (spark-4)
   - Generic writes → spark-2 embedding endpoint

### Privacy at retrieval

Legal store retrieval never returns content flagged with specific matter IDs to queries from non-authorized personas. Matter-level access control is finer-grained than persona-level — documents in SUV2026000013 corpus are retrievable only by matter participants.

## Distillation — two businesses, two models

### CROG-VRS distillation

**Target model:** qwen2.5:7b → qwen2.5:7b-crog-vrs

**Training data source:**
- llm_training_captures filtered to VRS source_modules
- Backfilled historical captures (PR #53)
- Approved concierge response templates
- Approved OTA response patterns

**Training location:** spark-4 GB10, during low-traffic window (2am EST, current timer slot)

**Serving location:** spark-4 Ollama with LoRA adapter applied

**Eval criteria:**
- Response relevance >= 0.85 cosine similarity to frontier on holdout
- Brand voice consistency (no tone regressions)
- Zero fabrication of property details (fact-checked against inventory)
- Pricing reasonableness (no quotes outside defined ranges)

**Promotion:** gated by eval harness (Phase 4b), manual approval for first N promotions until signal is trusted.

### Fortress Legal distillation

**Target model:** qwen2.5:32b → qwen2.5:32b-fortress-legal

**Training data source:**
- NOT llm_training_captures or restricted_captures directly (too small, privileged content cannot train a model that serves future queries about unrelated matters — cross-matter contamination risk)
- Public Georgia case law (searchable via casetext, Georgia Supreme Court archives)
- Georgia statutes (OCGA)
- Federal Rules of Civil Procedure, Evidence, Local Rules for Northern District of Georgia
- Anonymized briefs from prior matters (all matter-identifying details redacted before training)
- Legal style guide (Bluebook, local court preferences)

**Why not privileged content:** training on privileged material creates risk the model regurgitates matter-specific details in unrelated future queries. Public legal corpus is safer and probably sufficient for style and structural quality improvements.

**Training location:** spark-1 GB10, off-hours (requires moving the current trainer from spark-2 to spark-1)

**Serving location:** spark-1 Ollama with LoRA adapter

**Eval criteria:**
- Citation accuracy (100% — cited cases must exist and stand for the proposition claimed)
- Statutory reference accuracy
- Zero hallucination of precedent
- Argumentative structure preservation

**Promotion:** gated by human review for legal accuracy. Distillation cannot promote without attorney sign-off.

## Phase plan v4

### Phase 1 — Plumbing deployed (DONE)

### Phase 2 — Privilege filter (DONE, but improve)
Current filter catches legal personas and legal modules. Extend to check source node: if a legal module attempts to route to spark-4 or use VRS vector store, block and log.

### Phase 2.5 — Model registry (DONE)

### Phase 3 — Flywheel capture (DONE + retagged April 18)
Captures continue. served_by_endpoint and served_vector_store columns added to both tables (PR #64, migration 1a0d5cfa13e5). NULL for pre-retag rows — intentional. served_vector_store remains NULL until Phase 5a.

### Phase 4a — CROG-VRS distillation (NEW)
Retarget trainer from Llama-3.3-70B-FP4 to qwen2.5:7b. Train on spark-4. Serve from spark-4.

### Phase 4b — Eval harness (DONE)
Reusable for both CROG-VRS and Fortress Legal distillation cycles.

### Phase 4c — Adapter routing (DONE, simplify)
Refactor to support per-business adapter routing. VRS modules → qwen2.5:7b-crog-vrs on spark-4. Legal modules → qwen2.5:32b-fortress-legal on spark-1 (when that exists). PCT per adapter, not global.

### Phase 4d — Fortress Legal distillation (NEW, later)
Build public-corpus training pipeline. Requires legal corpus acquisition (casetext API, OCGA scraping, or licensed source). Ship after Phase 4a stabilizes.

### Phase 5a — RAG architecture migration (NEW)
Build CROG-VRS vector store on spark-4. Build Fortress Legal vector store on spark-1. Update retrieval code to respect domain boundaries. Migrate existing shared vectors (if any) into domain-specific stores.

### Phase 5b — Node role migration (from v3 Phase 5)
Move NIM off spark-2 to spark-1. Requires maintenance window.

### Phase 6 — Multi-node observability (from v3, unchanged)

## Migration sequence

Recommended order with exit criteria:

1. Phase 3 retag — add served_by_endpoint and served_vector_store columns to capture tables. Trivial migration. (~30 min)

2. Phase 5a part 1 — spark-4 VRS vector store provisioning and ingestion of existing VRS content. (~2-3 hours including content audit)

3. Phase 4a — CROG-VRS trainer retarget to qwen2.5:7b on spark-4 with VRS data. First real distillation for the actual production target. (~2-3 hours)

4. Phase 4c refactor — per-business adapter routing. Enable VRS adapter at PCT=5 after Phase 4a's first promotion. (~1-2 hours)

5. Phase 5a part 2 — spark-1 legal vector store provisioning and ingestion of legal corpus. Slower work; requires matter-level access controls. (~multiple sessions)

6. Phase 5b — NIM migration off spark-2. Maintenance window. Production impact. (~2-3 hours)

7. Phase 4d — Fortress Legal distillation. After Phase 5a part 2 and legal corpus acquisition. (~multi-session project)

8. Phase 6 — observability, incremental and ongoing.

## Decision log (April 18, 2026)

1. Two businesses, two distilled models. Not one shared distillation target. CROG-VRS gets qwen2.5:7b-crog-vrs, Fortress Legal gets qwen2.5:32b-fortress-legal. Trained separately, served separately, evaluated separately.

2. Domain-isolated RAG. Cross-domain retrieval prohibited at the query layer, not just advised. Vector stores physically separated on different nodes.

3. spark-1 dedicated to legal. Single-purpose node for privilege defense.

4. spark-4 dedicated to VRS. Also serves as active-active deep-tier backup for spark-1 non-legal work.

5. spark-2 dedicated to orchestration + fast tier + embeddings. No heavy inference. No training. No vector stores.

6. spark-3 dedicated to vision. Unchanged from v3.

7. Legal distillation uses public corpus, not privileged captures. Prevents cross-matter contamination risk.

8. Training moves to the business's own node. CROG-VRS trains on spark-4. Legal trains on spark-1. Not a shared training node.

## Risks live after v4

R1-R5 from v2 unchanged (secrets rotation, etc.). R6-R8 from v3 unchanged.

New risks from v4:

R9 — Cross-domain RAG leakage. If any query code path retrieves from both stores, privilege is at risk. Mitigation: test-driven development at the retrieval layer. Every retrieval call must specify source_module; registry enforces the mapping.

R10 — Training data volume per business. CROG-VRS has more volume (~74 captures post-backfill). Fortress Legal has none eligible for training (everything is in restricted_captures). Legal distillation blocked on public corpus acquisition. Mitigation: accept this order — ship VRS distillation first, legal after corpus is secured.

R11 — Dedicated-node failure equals dedicated-workload outage. If spark-1 dies, legal has no fallback (spark-4 will not serve privileged content). Mitigation: manual failover plan. Legal calls degrade to cloud (frontier models) during spark-1 outage, with explicit privilege warning in ai_router. Not automatic active-active for legal — too risky for privilege argument.

R12 — NIM migration during maintenance window risks. Moving NIM from spark-2 to spark-1 requires coordinated stop/start across services. Mitigation: scheduled maintenance, documented rollback, verify legal_council traffic is paused during window.

## What this document does

This is the architecture Fortress-Prime is building toward. Every PR from here should cite which phase of v4 it implements, which exit criterion it advances, and which risk it touches.

Future Gary or future Claude reading this should be able to understand which node handles which business, see why RAG is domain-isolated, know which model distillation targets which workload, and identify what ships next and in what order.

This replaces v3 as the single source of architectural truth.
