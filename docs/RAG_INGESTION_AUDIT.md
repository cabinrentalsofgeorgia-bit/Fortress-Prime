# Fortress Prime — RAG Ingestion Audit
*Generated 2026-04-19 as part of Phase 5a Part 1. Used to sequence the VRS Qdrant migration.*

## Qdrant instances

| Host | Port | Version | Role |
|---|---|---|---|
| spark-2 (192.168.0.100) | 6333/6334 | v1.13.2 | **Current production** — all live traffic |
| spark-4 (192.168.0.106) | 6333/6334 | latest | **New VRS instance** — empty, ready for cutover |

All writes currently target `settings.qdrant_url` (spark-2).

---

## Write site audit

| file:line | service/worker | collection | trigger / frequency |
|---|---|---|---|
| `backend/workers/vectorizer.py:136` | `VectorizerWorker` (arq job) | `fgp_knowledge` | Event-driven: on every `PropertyKnowledge` row insert/update. Batched via arq queue. |
| `backend/services/knowledge_retriever.py:253,258` | `sync_knowledge_base_to_qdrant()` | `fgp_knowledge` | Manual or admin-triggered full resync. Rebuilds all vectors from `property_knowledge` table. |
| `backend/services/legal_vector_sync.py:381` | `LegalVectorSync` | `legal_library` | Event-driven: on legal document ingest/update. Uses `qdrant_client` SDK. |
| `backend/services/legal_vector_sync.py:286` | `reset_qdrant_collection()` | `legal_library` | Manual reset — destructive, admin-only. |
| `backend/services/legal_ediscovery.py:309` | eDiscovery evidence ingestion | `legal_ediscovery` | On evidence upsert via eDiscovery API route. |
| `backend/core/vector_db.py:61` | `ensure_qdrant_collection()` | `historical_quotes` | Startup / on-demand collection creation only. |
| `backend/api/s2s_voice_stream.py:138` | Voice stream handler (read) | `guest_golden_responses` | Read-only search at query time — not a write path. |
| `backend/api/elevenlabs_tools.py:72` | ElevenLabs tools (read) | `guest_golden_responses` | Read-only search at query time — not a write path. |

**VRS-domain write paths (Phase 5a scope):**
- `VectorizerWorker → fgp_knowledge` — **primary, high frequency**
- `sync_knowledge_base_to_qdrant → fgp_knowledge` — secondary, manual

**Out of scope for Phase 5a (legal / finance / agent stays on spark-2):**
- `legal_library`, `legal_ediscovery`, `historical_quotes`, `guest_golden_responses`
- All `*_intel`, `email_embeddings`, `fortress_*` collections (market/legal intelligence)

---

## Read site audit

| file:line | service | collection | call frequency |
|---|---|---|---|
| `backend/services/knowledge_retriever.py:83` | `_qdrant_search()` | `fgp_knowledge` | **Every concierge/VRS query** — hot path |
| `backend/services/knowledge_retriever.py:320` | `_qdrant_legal_search()` | `legal_library` | On every legal reasoning request |
| `backend/services/agentic_orchestrator.py:544` | `OrchestratorAgent` | `fgp_knowledge` (via `knowledge_retriever`) | On every agent turn that needs property context |
| `backend/services/dgx_tools.py:170` | DGX semantic search tool | `fgp_knowledge` | Agent tool use — moderate |
| `backend/services/crog_concierge_engine.py:204` | ConciergeEngine | `fgp_knowledge` | Per concierge chat turn |
| `backend/services/prompt_engineer.py:185` | PromptEngineer | `fgp_knowledge` | Per cloud-bound prompt compilation |
| `backend/services/damage_workflow.py:118` | DamageWorkflow | `fgp_golden_claims` | On damage claim processing |
| `backend/services/agent_swarm/nodes.py:97` | AgentSwarm nodes | `historical_quotes` | Per agent swarm invocation |
| `backend/api/s2s_voice_stream.py:138` | Voice stream | `guest_golden_responses` | Per voice interaction |
| `backend/api/elevenlabs_tools.py:72` | ElevenLabs tools | `guest_golden_responses` | Per ElevenLabs tool call |

---

## Hardcoded references that must change during cutover

All VRS paths use `settings.qdrant_collection_name` (default: `"fgp_knowledge"`) via `COLLECTION_NAME` in `backend/core/qdrant.py`. This is the **single configuration point** for collection name. The target collection on spark-4 is named `fgp_vrs_knowledge`.

**Two env vars control all VRS Qdrant traffic:**
```
QDRANT_URL       → currently points to spark-2
QDRANT_COLLECTION_NAME → currently "fgp_knowledge"
```

The legal paths (`legal_vector_sync`, `legal_ediscovery`) hardcode their collection names as module constants and use `settings.qdrant_url` for the host. They are **NOT** controlled by `QDRANT_COLLECTION_NAME` and are unaffected by the VRS cutover.

---

## Cutover strategy recommendation

### Option A — Dual-write (RECOMMENDED)

**Phase 5a Part 2:** Add a secondary write target.
- Introduce `QDRANT_VRS_URL` env var pointing to spark-4.
- When `QDRANT_VRS_URL` is set, `VectorizerWorker` and `sync_knowledge_base_to_qdrant` write to both `settings.qdrant_url` (old, `fgp_knowledge`) and `QDRANT_VRS_URL` (new, `fgp_vrs_knowledge`).
- Run both in parallel for 1–2 weeks; monitor spark-4 ingestion lag.

**Phase 5a Part 3:** Data migration + read cutover.
- Run `sync_knowledge_base_to_qdrant` against `fgp_vrs_knowledge` to backfill existing 168 points.
- Once spark-4 point count matches spark-2, flip `QDRANT_URL` to spark-4 and `QDRANT_COLLECTION_NAME` to `fgp_vrs_knowledge`.
- Remove dual-write code.

**Why not Option B (hard cutover)?**
The VRS concierge (`_qdrant_search`) is called on every guest interaction — zero downtime tolerance. A hard flip requires atomic migration + env var change in a narrow maintenance window. One bad deployment rolls back cleanly with dual-write; a hard cutover in a failing state degrades all guest queries.

**Why not Option C (dual-read/single-write)?**
Reading from spark-2 while writing to spark-4 creates a divergence window where concierge reads stale data from spark-2. Dual-write keeps both in sync during transition; dual-read does not.

---

## Current spark-2 collection inventory (21 collections)

VRS-domain (Phase 5a scope):
- `fgp_knowledge` — 168 points, 768d Cosine, 4 payload indexes
- `fgp_golden_claims` — (size TBD)
- `guest_golden_responses`

Legal-domain (out of scope):
- `legal_library`, `legal_ediscovery`, `legal_headhunter_memory`, `legal_hive_mind_memory`

Market/finance intelligence (out of scope):
- `raoul_intel`, `jordi_intel`, `permabear_intel`, `fed_watcher_intel`, `lyn_intel`, `black_swan_intel`, `sound_money_intel`, `vol_trader_intel`, `market_intelligence`, `real_estate_intel`

Other:
- `historical_quotes`, `email_embeddings`, `fortress_knowledge`, `fortress_documents`
