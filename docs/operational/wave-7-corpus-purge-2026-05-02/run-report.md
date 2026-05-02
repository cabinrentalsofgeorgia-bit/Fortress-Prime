# Wave 7 Corpus Purge Run Report — 2026-05-02

## Pre-delete counts (`legal_ediscovery_v2`)

| case_slug | points |
|---|---:|
| `7il-v-knight-ndga-i` | 91,245 (mixed real PDFs/MSGs/DOCXs + MP4/JPEG binary garbage; almost no inbox spam) |
| `7il-v-knight-ndga-ii` | 60,068 (~100% operator inbox spam mis-tagged as Case II — newsletters, Ticketmaster, Epoch Times, Facebook notifications, hotmail-personal) |
| **subtotal removed** | **151,313** |
| `vanderburge-v-knight-fannin` (untouched) | 586,739 |
| `fish-trap-suv2026000013` (untouched) | 858 |

## Blast radius check (smart, document_id ↔ disk UUID prefix)

The Qdrant payload schema has only 5 keys (`case_slug`, `document_id`, `file_name`, `chunk_index`, `text`) — no path field. Original "starts-with-prefix" heuristic in the brief was unworkable. Substituted: cross-reference each distinct `document_id` against UUID-prefixed disk basenames under `/mnt/fortress_nas/{legal_vault,Corporate_Legal/Business_Legal,Business_Prime/Legal}/`.

| metric | Case I | Case II |
|---|---:|---:|
| distinct (document_id, file_name) pairs in v2 | 614 | 616 |
| matched by `document_id` UUID prefix on disk | 614 | 616 |
| matched by direct basename | 0 | 0 |
| unmatched binary-garbage extensions | 0 | 0 |
| **unmatched real-evidence extensions (LOSS)** | **0** | **0** |

**100% recoverable.** Every chunk in v2 corresponds to a UUID-prefixed source file preserved on disk. Deletion is information-equivalent to "compress + reingest" — no source content is lost; the embeddings are deterministically rebuildable.

## Post-delete counts

| case_slug | points |
|---|---:|
| `7il-v-knight-ndga-i` | 0 |
| `7il-v-knight-ndga-ii` | 0 |
| **v2 total** | **587,604** (delta −151,313) |
| `vanderburge-v-knight-fannin` | 586,739 (unchanged ✓) |
| `fish-trap-suv2026000013` | 858 (unchanged ✓) |

Qdrant `delete by filter` operation IDs: `11548` (Case I), `11549` (Case II). Wall: 1.3 s + 0.8 s respectively. Status `COMPLETED` on both.

## Critical follow-on finding (NOT a runtime issue tonight, but blocks PART C/D re-ingest)

The legitimate-and-poisoned distinction does NOT live in the disk file set. Both real legal evidence AND operator inbox spam are stored side-by-side under `/mnt/fortress_nas/legal_vault/7il-v-knight-ndga/` (1,525 files; mixed). The poison wasn't manufactured at ingest from clean disk — it was a **bulk ingest of the operator's full inbox into the case directory**, then chunked + tagged with the run-time `--case-slug` value.

Implication: **re-ingesting from `legal_vault/7il-v-knight-ndga/` will replay the same poison** unless source-path scoping is added. The truly-clean Case II content is under `Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/curated/` (~145 files including the operative complaint + 11 exhibits per pre-flight audit). Case I clean content is under `Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/` and possibly `Business_Prime/Legal/# Pleadings - GAND/`.

## Re-ingest path is BLOCKED tonight

PART C/D as drafted in the Wave 7 corpus rebuild brief is blocked on **two** independent things:

1. **GH #363 — schema reconciliation** is required first. `vault_ingest_legal_case.py` reads `legal.cases.nas_layout` (table missing) and writes `legal.ingest_runs` (table missing). Preflight check raises `PreflightError` before any file is processed. Operator-side `alembic upgrade head` after schema PR lands.

2. **Source-path scoping** is required to avoid replaying the poison. The ingest invocation needs a `--source-root` flag (or equivalent) limiting walk to `Corporate_Legal/Business_Legal/<slug>/curated/`. The current script reads `legal.cases.nas_layout` (missing); even if that table existed, the `nas_layout` JSONB likely points at the legacy `legal_vault/7il-v-knight-ndga/` mixed dir.

PART C/D therefore cannot run autonomously after this purge PR merges. They wait for #363 + a source-path-scoping change.

## Artifacts preserved

- `case-i-v2-pre-delete-filenames.txt` — 607 distinct file_names that were tagged Case I in v2 pre-delete
- `case-ii-v2-pre-delete-filenames.txt` — 612 distinct file_names that were tagged Case II in v2 pre-delete
- `case-i-real-evidence-loss-list.txt` — empty (no loss)
- `case-ii-real-evidence-loss-list.txt` — empty (no loss)

## Cross-references

- GH #364 — Qdrant case_slug poisoning finding (root cause of this purge)
- GH #363 — schema reconciliation (blocks PART C/D re-ingest)
- GH #361 — pre-existing §5/§9-aug non-determinism (unrelated)
- Constitution §11.1 (`case_slug` payload contract — re-validated post-purge)
- Constitution §12.3 (regression discipline — Track A v3 baseline must be re-baselined post re-ingest)

## What's next

1. Operator merges this PR from iMac.
2. Operator drives GH #363 schema reconciliation (alembic CLI repair, missing tables, naming reconciliation, `alembic upgrade head`). Sunday work.
3. Operator decides source-path scoping for re-ingest (likely a small `vault_ingest_legal_case.py` patch adding `--source-root` flag, or operator-side curation of `legal.cases.nas_layout` JSONB once that table exists).
4. PART C re-ingest of Case II from `Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/curated/` only.
5. PART D re-ingest of Case I from clean source dirs.
6. Track A v3 re-baseline run (Constitution §12.3).
7. Wave 7 v2 regen on cleaned corpus.
