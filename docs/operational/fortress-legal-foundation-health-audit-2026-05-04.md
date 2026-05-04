# Fortress Legal Foundation Health Audit - 2026-05-04

Status: foundation verification pass after PR #405 merge.

This audit is documentation-only. It does not ingest, promote, extract, move evidence, write to Qdrant, or change operational database rows.

## Executive Result

Fortress Legal is in a healthier foundation state after this pass:

- PR #405, the database foundation contract cleanup, was squash-merged into `main`.
- A clean worktree was created from fresh `origin/main` for this verification branch.
- The earlier apparent database contradiction was resolved as an audit-script DSN issue.
- Corrected live checks confirm the core Legal runtime tables and selected-ingest evidence rows exist in the expected databases.
- Remaining blockers are review/quality gates, not missing foundation tables.

## Repository State

- Dirty primary worktree preserved untouched: `/home/admin/Fortress-Prime`.
- Primary worktree branch at audit time: `safety/foundation-audit-snapshot`, ahead of origin with unrelated MarketClub and financial edits.
- Clean verification worktree: `/home/admin/Fortress-Prime-foundation-health-20260504`.
- Verification branch: `codex/foundation-health-audit-2026-05-04`.
- Base commit after PR #405 merge: `fea7e6503` (`Fix database foundation contract (#405)`).

## PR State

| PR | Status | Result |
|---|---|---|
| #366 Schema reconciliation | merged | Case layout/schema reconciliation is on main. |
| #405 Database foundation contract | merged 2026-05-04 | Duplicate DB implementation cleanup is on main. |
| #416 DB/Qdrant source of truth | merged | Legal DB/Qdrant source-of-truth work remains authoritative. |
| #419 Email intake foundation | merged | Manifest-only source-drop planner is on main. |
| #420 Native `.msg` inventory | merged | Outlook-native inventory support is on main. |
| #421 Outlook `.msg` parser | merged | Parser path is on main where parser dependency is available. |

Open legacy/draft Legal PRs still need separate disposition, especially the draft Qdrant purge/reindex PRs. This pass did not close or merge them.

## Database Verification

Corrected live audit path: parse spark-2 secret overlay, normalize async Postgres URLs to psycopg-compatible URLs, then retarget the same host/role/port to the intended runtime database.

Important environment finding:

- `POSTGRES_API_URI` and `POSTGRES_ADMIN_URI` default to `fortress_shadow`, but Legal helpers deliberately retarget them to `fortress_db` and `fortress_prod`.
- `DATABASE_URL` still points at legacy `fortress_guest` with user `fgp_app`; that role cannot inspect runtime Alembic metadata and should not be used for Legal foundation audits.

### `fortress_db`

- Connected as `fortress_api` and `fortress_admin`.
- Core Legal tables present:
  - `legal.cases`
  - `legal.ingest_runs`
  - `legal.vault_documents`
  - `legal.privilege_log`
- Counts observed:
  - `legal.cases`: 6
  - `legal.ingest_runs`: 17
  - `legal.vault_documents`: 2,175
  - `legal.privilege_log`: 240
- Selected Case II document rows present:
  - `92 inspection.pdf`, status `completed`, chunk count 60
  - `Inspection Comments(89340812.1).xlsx`, status `completed`, chunk count 12
  - `Inspection of 92 Fish Trap.pdf`, status `completed`, chunk count 76
- Selected ingest run present:
  - script `selected_doc_ingest_only`
  - status `complete`
  - `files_processed=3`
  - `files_succeeded=3`
  - `files_failed=0`
  - manifest `/mnt/fortress_nas/audits/selected-doc-ingest-7il-v-knight-ndga-ii-20260504T020815Z.json`

### `fortress_prod`

- Connected as `fortress_api` and `fortress_admin`.
- Core Legal tables present:
  - `legal.cases`
  - `legal.ingest_runs`
  - `legal.vault_documents`
  - `legal.privilege_log`
- Counts observed:
  - `legal.cases`: 6
  - `legal.ingest_runs`: 0
  - `legal.vault_documents`: 2,177
  - `legal.privilege_log`: 0
- Selected Case II document rows present with the same document ids/statuses/chunk counts as `fortress_db`.
- Empty `legal.ingest_runs` is expected for this design because `IngestRunTracker` writes canonical lifecycle rows to `fortress_db`.

### `fortress_shadow`

- Not the Legal evidence runtime.
- Contains legacy/minimal Legal tables.
- Treat as app/session infrastructure unless a migration explicitly targets Legal there.

## NAS Verification

Case II curated source root:

- `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/curated`
- Exists.
- Current observed content: 56 `.eml` files, 0 `.msg` files, 82 PDFs.

Wilson Pruitt / Argo native drop folders exist but are still empty:

- `01_wilson_pruitt_pre_closing`: 0 `.eml`, 0 `.msg`, 0 PDFs.
- `02_wilson_pruitt_post_closing`: 0 `.eml`, 0 `.msg`, 0 PDFs.
- `05_terry_wilson_production`: 0 `.eml`, 0 `.msg`, 0 PDFs.
- `06_argo_native_exports`: 0 `.eml`, 0 `.msg`, 0 PDFs.

## Qdrant Verification

Spark-2 Qdrant was reachable.

- `legal_ediscovery_v2`: 587,604 points.
- `legal_ediscovery`: 823,627 points.

The selected Case II ingest slice uses legacy `legal_ediscovery` for the three verified selected document ids.

## Evidence / Intake Gates

Completed:

- Selected-only Case II ingest for three inspection/repair documents.
- Real-ingest verification packet confirms six DB verification rows across `fortress_db` and `fortress_prod`.
- Chain-of-custody and retrieval smoke-test packets exist.

Still blocked:

- No Wilson Pruitt / Argo native exports have landed in the dedicated drop folders.
- No Packet 31B / Packet 32 email rows are cleared for promotion.
- SC37-02 `Foot Path Easement 21-0510.pdf` remains blocked pending operator visual comparison and explicit privilege/source-separation clearance.
- Alicia Argo easement draft/redline materials remain privilege-first holds.
- XLSX extraction quality is not yet adequate for white-shoe-grade semantic retrieval; spreadsheet cell extraction must be improved before relying on the indexed XLSX text.

## Current Health Judgment

Foundation health is acceptable for controlled review work and manifest-only planning.

Do not resume broad feature work yet. The next healthiest moves are:

1. Keep this audit/runtime-map update landed on `main` before returning to feature work.
2. Confirm the dirty safety snapshot tree remains preserved and out of the Legal lane.
3. Improve XLSX extraction before relying on spreadsheet retrieval.
4. Wait for native Wilson Pruitt / Argo exports, then run manifest-only planning.
5. Complete Packet 43 visual comparison before any SC37-02 extraction or promotion.
