# Shared: Qdrant Collections

Last updated: 2026-04-26

## Technical overview

Qdrant runs as two clusters:

- **`localhost:6333`** — legal collections + `email_embeddings` + `fortress_knowledge`
- **`192.168.0.106:6333`** — VRS dual-write target (`fortress-qdrant-vrs.service`)

All collections share `vector_size=768` (nomic-embed-text via Ollama at `192.168.0.100:11434`) and `Cosine` distance unless noted.

## Collections inventory

| Collection | Cluster | Purpose | Owner | Populator | Points (approx) |
|---|---|---|---|---|---|
| `legal_ediscovery` | localhost | Work-product vault chunks (filings, depositions, evidence, discovery) | fortress-legal | `process_vault_upload` (work-product branch) | 151,313+ (mostly 7IL) |
| `legal_privileged_communications` | localhost | Privileged communications chunks (deterministic UUID5 IDs) | fortress-legal | `process_vault_upload` (privilege branch) | 0 (created PR G; awaits first privileged ingest) |
| `legal_caselaw` | localhost | Georgia state caselaw RAG | fortress-legal | `backend/scripts/ingest_courtlistener.py` | ~2,711 |
| `legal_caselaw_federal` | localhost | Federal CA11 caselaw RAG | fortress-legal | `ingest_courtlistener.py` (fed mode) | 0 (PR #184; awaits ingest) |
| `legal_library` | localhost | Legacy legal docs (per fortress_atlas.yaml) | (legacy) | n/a | ~2,455 (per atlas; not actively grown) |
| `email_embeddings` | localhost | All-mailbox email content embeddings, division-tagged | shared (Captain populates) | Captain pipeline | 651,633+ (per 2026-04-25 audit) |
| `fgp_sent_mail` | localhost | Sent-mail subset (provenance unknown) | crog-vrs (legacy) | unknown | ~600 |
| `fortress_knowledge` | localhost | NAS-walker indexed documents | shared (Sentinel) | `tools/fortress_sentinel.py` (or equivalent) | varies |
| `fgp_knowledge` | (per `qdrant_collection_name` setting) | Default config name; may overlap with `fortress_knowledge` — needs reconciliation | crog-vrs | n/a | varies |
| `legal_ediscovery` (VRS cluster) | 192.168.0.106 | Dual-write VRS-side mirror | crog-vrs | `enable_qdrant_vrs_dual_write` flag | varies |

## Privileged-collection contract

Created in PR G phase C. Distinct from `legal_ediscovery` because:

- **Physical separation** prevents leakage by metadata error: a misconfigured filter on the work-product collection cannot return privileged chunks (they're not in that collection)
- **Deterministic point IDs**: `uuid5(ns=f0a17e55-7c0d-4d1f-8c5a-d3b4f0e9a200, file_hash + chunk_index)` — re-runs are idempotent; never produces duplicates
- **Payload contract**: `case_slug`, `document_id`, `file_name`, `file_hash`, `chunk_num`, `chunk_index`, `text`, `privileged=true`, `privileged_counsel_domain`, `role`, `privilege_type`, `ingested_at`

Work-product collection still uses `uuid4()` (non-deterministic; tracked as Issue #210).

## Consumers

- Council deliberation (`backend/services/legal_council.py`):
  - `freeze_context()` → `legal_ediscovery`
  - `freeze_privileged_context()` → `legal_privileged_communications`
- Vault upload pipeline (`backend/services/legal_ediscovery.py::_upsert_to_qdrant` + `_upsert_to_qdrant_privileged`)
- Caselaw retrieval at `backend/services/legal_council.py::*` for case prep
- Email embedding queries throughout `backend/services/legal_email_intake.py` and Captain code paths
- Sentinel-driven `fortress_knowledge` search

## Contract / API surface

- HTTP at `${QDRANT_URL}/collections/{name}/points/{search,scroll,upsert,delete,count}`
- `qdrant-client` Python SDK in some legacy paths; raw `httpx` / `urllib.request` in newer code (PR D, PR G, PR I)
- All upserts in case-aware code paths must populate `case_slug` payload field for filtering

## Where to read the code

- `backend/services/legal_ediscovery.py` — both upsert paths
- `backend/services/legal_council.py` — both freeze paths
- `backend/core/qdrant.py` — initialization helpers
- `tools/fortress_sentinel.py` — NAS walker (Sentinel)
- `backend/scripts/ingest_courtlistener.py` — caselaw ingest
- `backend/scripts/email_backfill_legal.py` — uses both Qdrant clusters via `_count_qdrant_points` + `_delete_qdrant_points_for_case` helpers

## Cross-references

- [`council-deliberation.md`](council-deliberation.md) — frozen-context retrieval semantics
- [`sentinel-nas-walker.md`](sentinel-nas-walker.md) — `fortress_knowledge` ownership
- [`legal-privilege-architecture.md`](../../runbooks/legal-privilege-architecture.md) §2 — physical-separation rationale
- Issue #207 — work-product UUID5 idempotency (renamed during filing → Issue #210)
- Issue #211 — `migrate_qdrant_chunks.py` for cross-collection moves

Last updated: 2026-04-26
