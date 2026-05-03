# Fortress Legal Qdrant Contract Audit - 2026-05-03

Status: read-only live audit
Scope: Spark-2 Qdrant legal collections, aliases, and backend/script caller contract
Related map: `docs/architecture/runtime-map.md`

No Qdrant aliases, collections, payloads, points, services, or application code were changed during this audit.

## Summary

Live Spark-2 Qdrant has the alias `legal_ediscovery_active -> legal_ediscovery_v2`, but the backend Legal runtime does **not** currently use that alias for e-discovery retrieval or ingest.

The important operational finding is sharper:

- `legal_ediscovery` legacy 768-dim contains 7IL Case I and Case II points.
- `legal_ediscovery_v2` / `legal_ediscovery_active` 2048-dim contains **zero** points for `7il-v-knight-ndga-i` and `7il-v-knight-ndga-ii` when filtered by `case_slug`.
- `legal_privileged_communications` legacy 768-dim contains Case II privileged points.
- `legal_privileged_communications_v2` 2048-dim contains **zero** Case II privileged points when filtered by `case_slug`.

Therefore, for current Fortress Legal 7IL work, the safe contract is:

1. Use legacy `legal_ediscovery` for 7IL work-product evidence retrieval.
2. Use legacy `legal_privileged_communications` for 7IL privileged retrieval.
3. Do not route 7IL e-discovery retrieval through `legal_ediscovery_active` until Case I/II are reindexed into the active target and verified.
4. Keep `legal_caselaw_v2` and `legal_library_v2` as separate accepted 2048-dim legal-reference surfaces.

## Live Qdrant State

Endpoint audited:

- `http://127.0.0.1:6333` on Spark-2
- Qdrant version: `1.13.2`

Live aliases:

| Alias | Target collection |
|---|---|
| `legal_ediscovery_active` | `legal_ediscovery_v2` |

Legal collection metadata snapshot:

| Collection | Dim | Points | Indexed vectors | Status | Runtime meaning |
|---|---:|---:|---:|---|---|
| `legal_ediscovery` | 768 | 823,479 | 830,498 | green | Legacy work-product e-discovery collection; active backend ingest/write target. |
| `legal_ediscovery_v2` | 2048 | 587,604 | 587,604 | green | Alias target for `legal_ediscovery_active`; not populated for 7IL Case I/II by `case_slug`. |
| `legal_privileged_communications` | 768 | 253,157 | 268,928 | green | Legacy privileged communications collection; active backend privileged target. |
| `legal_privileged_communications_v2` | 2048 | 241,167 | 240,192 | green | Reindexed privileged collection; not populated for 7IL Case II by `case_slug`. |
| `legal_caselaw` | 768 | 2,711 | 0 | green | Legacy caselaw collection. |
| `legal_caselaw_v2` | 2048 | 2,711 | 0 | green | Current Council caselaw collection in backend code. |
| `legal_caselaw_federal_v2` | 2048 | 0 | 0 | green | Empty federal caselaw v2 target. |
| `legal_library` | 768 | 3 | 0 | green | Legacy legal library. |
| `legal_library_v2` | 2048 | 3 | 0 | green | Current legal-library/statutory collection in backend code. |
| `legal_headhunter_memory` | 768 | 0 | 0 | green | Counsel/recruiting memory, empty. |
| `legal_headhunter_memory_v2` | 2048 | 0 | 0 | green | Counsel/recruiting v2 target, empty. |
| `legal_hive_mind_memory` | 768 | 4 | 0 | green | Small hive-mind/drafting memory surface. |

Counts are point-count snapshots, not legal completeness findings.

## Case-Scoped Counts

Read-only counts used exact Qdrant `points/count` queries with a payload filter on `case_slug`.

### Work-Product E-Discovery

| Case slug | `legal_ediscovery` | `legal_ediscovery_v2` | `legal_ediscovery_active` |
|---|---:|---:|---:|
| `7il-v-knight-ndga-i` | 91,245 | 0 | 0 |
| `7il-v-knight-ndga-ii` | 214,612 | 0 | 0 |
| `7il-v-knight-ndga` | 0 | 0 | 0 |
| `vanderburge-v-knight-fannin` | 516,756 | 586,739 | 586,739 |
| `fish-trap-suv2026000013` | 859 | 858 | 858 |
| `prime-trust-23-11161` | 0 | 0 | 0 |

### Privileged Communications

| Case slug | `legal_privileged_communications` | `legal_privileged_communications_v2` |
|---|---:|---:|
| `7il-v-knight-ndga-i` | 0 | 0 |
| `7il-v-knight-ndga-ii` | 81,188 | 0 |
| `7il-v-knight-ndga` | 0 | 0 |
| `vanderburge-v-knight-fannin` | 171,969 | 241,167 |
| `fish-trap-suv2026000013` | 0 | 0 |
| `prime-trust-23-11161` | 0 | 0 |

Payload sampling confirmed `legal_ediscovery_v2` points can carry `case_slug`, `chunk_index`, `document_id`, `file_name`, and `text`. The zero 7IL counts therefore appear to be content/reindex coverage, not merely a missing `case_slug` field.

## Repo Caller Contract

### E-Discovery Ingest / Write Paths

| File | Collection contract | Meaning |
|---|---|---|
| `fortress-guest-platform/backend/services/legal/qdrant_contract.py` | `LEGAL_WORK_PRODUCT_COLLECTION = "legal_ediscovery"`; `LEGAL_PRIVILEGED_COMMUNICATIONS_COLLECTION = "legal_privileged_communications"`; `LEGAL_LEGACY_VECTOR_SIZE = 768` | Central source of truth for the current 7IL legacy-stable Qdrant contract. |
| `fortress-guest-platform/backend/services/legal_ediscovery.py` | Imports work-product and privileged collection names from `qdrant_contract.py` | Canonical single-file vault upload writes legacy 768-dim work-product and privileged collections. |
| `fortress-guest-platform/backend/scripts/vault_ingest_legal_case.py` | Imports work-product collection and expected vector size from `qdrant_contract.py` | Batch ingest preflight requires legacy 768-dim work-product collection. |
| `fortress-guest-platform/backend/scripts/email_backfill_legal.py` | Imports work-product, privileged, and vector-size contract from `qdrant_contract.py` | Email backfill follows the same legacy ingest contract. |
| `fortress-guest-platform/backend/scripts/backfill_vector_ids.py` | Imports work-product and privileged collection names from `qdrant_contract.py` | Backfill/support tooling targets legacy collections. |

### Legal Retrieval Paths

| File | Collection contract | Meaning |
|---|---|---|
| `fortress-guest-platform/backend/services/legal_council.py` | `LEGAL_COLLECTION` imports `LEGAL_WORK_PRODUCT_COLLECTION` from `qdrant_contract.py` | Council e-discovery context freezing still retrieves from legacy 768-dim `legal_ediscovery`. |
| `fortress-guest-platform/backend/services/legal_council.py` | `PRIVILEGED_COLLECTION` imports `LEGAL_PRIVILEGED_COMMUNICATIONS_COLLECTION` from `qdrant_contract.py` | Council privileged retrieval still retrieves from legacy 768-dim privileged collection. |
| `fortress-guest-platform/backend/services/legal_council.py` | `CASELAW_COLLECTION = "legal_caselaw_v2"` | Council precedent retrieval uses 2048-dim v2 caselaw. |
| `fortress-guest-platform/backend/services/knowledge_retriever.py` | `LEGAL_COLLECTION = "legal_library_v2"` | Legal-library retrieval uses 2048-dim v2 legal library. |
| `fortress-guest-platform/backend/services/legal_auditor.py` | `STATUTORY_COLLECTION = "legal_library_v2"` | Statutory/legal-auditor retrieval uses 2048-dim v2 legal library. |

### Alias Usage

`legal_ediscovery_active` appears in operational docs and the Constitution, but no backend caller found in this audit uses it directly. That means the alias exists in Qdrant but is not yet the backend runtime e-discovery contract.

## Current Contract Decision

Until a separate caller-migration/reindex PR changes the code and proves coverage, treat this as the current contract:

| Surface | Current safe collection | Reason |
|---|---|---|
| 7IL Case I/II e-discovery retrieval | `legal_ediscovery` | Contains 7IL Case I/II points; backend uses it. |
| 7IL Case II privileged retrieval | `legal_privileged_communications` | Contains Case II privileged points; backend uses it. |
| Legal caselaw retrieval | `legal_caselaw_v2` | Backend code already targets v2. |
| Legal library/statutory retrieval | `legal_library_v2` | Backend code already targets v2. |
| `legal_ediscovery_active` | Not safe for 7IL yet | Alias points to v2, but Case I/II `case_slug` counts are zero. |
| `legal_privileged_communications_v2` | Not safe for 7IL yet | Case II privileged `case_slug` count is zero. |

## Why Direct Write To V2 Is Not A Small Fix

Directly changing ingest from `legal_ediscovery` to `legal_ediscovery_v2` is not a safe one-line change:

- Current ingest uses `nomic-embed-text` / 768-dim embeddings.
- `legal_ediscovery_v2` is 2048-dim and expects `legal-embed` passage embeddings.
- The current `process_vault_upload()` path also writes deterministic UUID5 IDs keyed to the legacy collection contract.
- A direct cutover must update embedding, collection target, validation, tests, rollback, and probably reindex/backfill semantics together.

Safer options are:

1. Keep ingest on legacy 768 and run a controlled reindex into v2 after ingest batches.
2. Build an explicit dual-embed write path that writes both legacy 768 and v2 2048, with separate verification and rollback.
3. Migrate readers to `legal_ediscovery_active` only after v2 Case I/II coverage is proven and regression-tested.

## Open Risks

1. `legal_ediscovery_active` is live but misleading for 7IL work because it points to a v2 collection with zero Case I/II `case_slug` points.
2. Documentation claims that production retrieval uses `legal_ediscovery_active`, but backend code still uses `legal_ediscovery`.
3. The 2048-dim v2 collection appears mostly populated for `vanderburge-v-knight-fannin` and `fish-trap-suv2026000013`, not 7IL.
4. `legal_privileged_communications_v2` is populated for `vanderburge-v-knight-fannin`, but not for 7IL Case II.
5. If an operator or script manually queries `legal_ediscovery_active` for 7IL, retrieval will silently miss known legacy evidence.
6. The reindex tool found in `src/reindex_legal_qdrant_to_legal_embed.py` covers `legal_caselaw`, `legal_library`, and `legal_privileged_communications`; it does not list `legal_ediscovery` in its `TEXT_FIELD` map in the audited branch.

## Recommended Next Move

Do **not** change runtime Qdrant aliases as part of foundation cleanup.

Next migration PR should choose one of these paths:

1. **Legacy-stable path:** keep enforcing that 7IL runtime retrieval remains on `legal_ediscovery` / `legal_privileged_communications` until Wave 7 reindex completes.
2. **V2 migration path:** reindex 7IL Case I/II work-product and privileged points into v2, verify case counts and retrieval quality, then migrate code callers to `legal_ediscovery_active` with matching 2048-dim query embeddings.
3. **Dual-write path:** preserve legacy reads while adding a tested 2048-dim v2 write/update path for new ingest.

Given the current 7IL priority, the least-risk near-term choice is the legacy-stable path: leave runtime on legacy collections, prevent any 7IL process from relying on `legal_ediscovery_active`, and schedule v2 migration separately after Case II ingest scope is stable. A follow-up hardening PR centralized the legacy-stable collection names in `backend/services/legal/qdrant_contract.py` so future caller changes have a single place to review.
