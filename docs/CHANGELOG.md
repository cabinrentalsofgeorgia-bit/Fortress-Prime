# Changelog

All notable changes to Fortress Prime are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project does not yet adhere to [Semantic Versioning](https://semver.org/)
because there's no public consumer surface — internal architecture changes
are documented by date and PR rather than by version number.

---

## [Unreleased]

Nothing pending.

---

## 2026-04-26 — Email backfill (PR I), Vanderburge case row, overnight followups

### Merged PRs

- **PR #225** (`297c37267`) — case-aware IMAP email backfill (PR I):
  `backend/scripts/email_backfill_legal.py` with 27 tests, classifier
  with rule precedence (docket > domain > username + date window),
  Sanker cross-case disambiguation (Case I / Case II / Vanderburge /
  quarantine), per-case rollback support, IngestRunTracker integration,
  lock + state files. Production run not yet executed — gated for
  explicit operator authorization.

### Database changes

- **Vanderburge case row INSERT:** `case_slug='vanderburge-v-knight-fannin'`,
  `status='closed_settled'`, `privileged_counsel_domains=["msp-lawfirm.com"]`,
  `related_matters` cross-references both 7IL cases. Applied to
  `fortress_prod` and `fortress_db` (md5-identical content,
  `ON CONFLICT (case_slug) DO NOTHING` for idempotency).

### Issues filed

- **#218** — `imap_party_audit` pre-2018 archive folder skip
  (~3-4 min runtime savings per audit invocation)
- **#219** — PR #214 body still references the legacy
  `masp-lawfirm.com` typo (docs cleanup)
- **#220** — `fortress_shadow_test` schema sync gap (legal.*
  migrations need manual apply)
- **#221** — PAT scope upgrade (`issues:write` +
  `pull-requests:write` for cleanup operations)
- **#222** — `crog` `gmail_watcher` cron failing on
  `prompts.judge_parser` ModuleNotFoundError
- **#224** — Vanderburge case row TBD backfills (`case_number`,
  `judge`, claim basis, opposing-counsel firm)

### Documentation

- This CHANGELOG entry
- PR I architecture plan at
  `/mnt/fortress_nas/audits/pr-i-email-backfill-plan-20260426.md`
- Email coverage audit (party-term backfill scope) at
  `/mnt/fortress_nas/audits/email-coverage-inventory-20260425b.md`

---

## 2026-04-25 — Legal stack: 7IL two-case restructure + privileged communications architecture

This is the largest legal-platform change since the original `legal.cases`
schema landed. **PR #214 (PR G)** is the headline; six supporting PRs
delivered the substrate it depends on.

### Headline — PR #214 (PR G): privileged communications architecture

Merge SHA: `51991ddc1`. Followup fixes: `8f3656676` (PR #215), `3cd87f692` (PR #216).

**What changed end-to-end:**

- **Schema:** `legal.cases` extended with three columns — `case_phase TEXT`,
  `privileged_counsel_domains JSONB`, `related_matters JSONB`. New table
  `legal.case_slug_aliases (old_slug, new_slug, created_at)` for backward-
  compat after renames.
- **Data:** the existing 7IL case row was renamed from `7il-v-knight-ndga`
  to `7il-v-knight-ndga-i` (closed phase, judgment against). A new row
  `7il-v-knight-ndga-ii` was inserted (active, counsel_search phase) for
  the post-judgment matter. 634 Thor James-related vault files were
  migrated to Case II. Qdrant payload `case_slug` values were updated for
  the migrated chunks across both `legal_ediscovery` and the new
  `legal_privileged_communications` collections.
- **Privileged Qdrant track:** new collection
  `legal_privileged_communications` (vector_size 768, distance Cosine)
  receives privileged chunks with deterministic UUID5 point IDs, namespaced
  under `f0a17e55-7c0d-4d1f-8c5a-d3b4f0e9a200` (file_hash + chunk_index).
  Re-runs are idempotent — no duplicate vectors. Payload includes
  `privileged=true`, `privileged_counsel_domain`, `role` (case-specific
  attorney role tag), and `privilege_type` (`attorney_client` |
  `work_product` | `joint_defense`).
- **Council retrieval:** `run_council_deliberation` reads two env vars at
  deliberation time (not at startup, so they flip without a backend
  restart):
  - `COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL` (default `true`) — queries the
    privileged collection in addition to `legal_ediscovery`
  - `COUNCIL_INCLUDE_RELATED_MATTERS` (default `true`) — expands retrieval
    to every slug in the case's `related_matters` JSONB array
  The frozen context gets a separate `=== PRIVILEGED COMMUNICATIONS ===`
  section; per-chunk tags `[PRIVILEGED · counsel-domain · role]` survive
  every downstream pipeline (PDF, copy/paste, search results).
- **FOR YOUR EYES ONLY warning:** any deliberation that retrieves at least
  one privileged chunk emits a `contains_privileged: true` SSE flag and
  appends a fixed-text warning block to `consensus_summary`. The structured
  flag drives the command-center UI's FYEO Card; the in-band text protects
  PDF exports and downstream pipelines.
- **Backward-compat alias resolution:**
  `_resolve_case_slug(session, slug)` in `backend/api/legal_cases.py`
  transparently resolves legacy slugs against `legal.case_slug_aliases`.
  URLs do not redirect; the URL stays at the old slug, the data resolves
  to the new canonical row. 12 case-detail endpoints covered today;
  remaining 11 endpoints tracked as Issue #208/#213.
- **UI surfaces (apps/command-center):**
  - Privileged-counsel domain badges in case-detail header
  - FYEO warning Card on the Council deliberation panel
  - Vault dropzone filter (all / evidence / privileged)
  - Lock icon + "Privileged" badge on `locked_privileged` documents
- **Tests:** 37 backend pytest cases + 20 UI Vitest cases shipped with PR G.
- **Runbook:** new at `fortress-guest-platform/docs/runbooks/legal-privilege-architecture.md`
  (12 sections, ~550 lines) covering the privilege model, two-collection
  architecture, Council retrieval policy, FYEO semantics, at-issue waiver
  handling for Terry Wilson (Knight's reliance defense theory), spousal vs.
  attorney-client distinction for Lissa Knight, the add-counsel workflow,
  privilege-waiver scenarios, alias semantics, cross-matter retrieval.

### Supporting PRs that landed today

- **#185** (`340911937`) — `feat(legal-cases): per-case nas_layout for real-world folder layout` — JSONB column on `legal.cases` mapping logical subdirs to physical NAS paths. Foundation for case-aware file listing.
- **#186** (`8bb76c48a`) — `feat(legal-cases): add 7IL Properties LLC v. Knight + Thor James row` — original case row insertion (later renamed to `-i` in PR G).
- **#188** (`bf931deaf`) — `feat(legal): OCR sweep script for case files` — `backend/scripts/ocr_legal_case.py` adds in-place text layers to image-only PDFs via `ocrmypdf --skip-text`. Idempotent; fine-grained lock file; quality presets.
- **#190** (`0a39aeb91`) — `feat(legal): add ingest_runs audit table and tracker` (PR D-pre1) — `legal.ingest_runs` audit table with `IngestRunTracker` context manager (retry/backoff/degrade pattern).
- **#193** (`991bc1b00`) — `feat(legal): vault_documents schema integrity (FK, dedup, status CHECK)` (PR D-pre2) — FK to `legal.cases.case_slug`, named UNIQUE constraint on `(case_slug, file_hash)`, union-vocabulary CHECK on `processing_status`. Established the 9-value bilingual vocabulary tracked for cleanup as Issue #194.
- **#195** (`a0b17a818`) — `feat(legal): vault ingestion script for case files` (PR D) — `backend/scripts/vault_ingest_legal_case.py`: physical-path dedup, 8-gate pre-flight, dual-DB write (fortress_db + fortress_prod), rollback path, lock file. 17 tests. Used the same day to ingest the 1457-file 7IL corpus (149,681 Qdrant points, 6h46m runtime).
- **#196** (`8e2e3bc41`) — `fix(legal): vault_ingest_legal_case writes to fortress_db (LegacySession)` — fixes a session-target bug in PR #195 that targeted `fortress_shadow` instead of `fortress_db`.
- **#197** (`15e4d16e5`) — `fix(legal): vault_ingest pre-flight uses real case_slug for ingest_runs probe` — fixes an FK violation in the PR D-pre1 audit-row probe.
- **#214** (`51991ddc1`) — **PR G: 7IL two-case restructure + privileged communications architecture** (this release).
- **#215** (`8f3656676`) — `docs(legal): correct PR G runbook issue cross-references` — fixes followup-issue numbers in the Phase G runbook.
- **#216** (`3cd87f692`) — `fix(legal): correct Sanker domain in _DOMAIN_TO_ROLE — masp → msp` — same-day correction after live email review confirmed the actual domain is `msp-lawfirm.com` (no leading 'a'). Companion DB UPDATE applied to both `fortress_prod` and `fortress_db` for `legal.cases.privileged_counsel_domains`.

### Operational artifacts produced today

- **Vault ingestion manifest:** `/mnt/fortress_nas/audits/vault-ingest-7il-v-knight-ndga-20260425T193416Z.json` — 1,457 files processed (1,396 completed, 10 ocr_failed, 48 failed, 2 duplicates, 1 over size cap). 149,681 Qdrant points indexed. Note: manifest filename uses the pre-rename slug because the ingestion run started before PR G phase C executed.
- **OCR sweep manifests:** `ocr-sweep-7il-v-knight-ndga-20260425T103934Z.json` (initial) and `…T110313Z.json` (retry).

### Followups filed today

- **#194** — `legal.vault_documents` vocabulary cleanup (collapse the bilingual `processing_status` set)
- **#198** — vault_ingest pre-process exceptions don't create vault_documents row
- **#200** — `.ptx` Summation deposition format support (also #199 stub, will close as duplicate)
- **#201** — vault_ingest qdrant_upsert_failed should set `processing_status='qdrant_pending'`
- **#208** — alias resolution missing on 11 case-detail endpoints (also #213 duplicate)
- **#209** — `legal.ingest_runs` row lost during PR G phase C rename CASCADE
- **#210** — work-product Qdrant idempotency (UUID4 → UUID5)
- **#211** — `migrate_qdrant_chunks.py` (privileged ↔ work-product collection moves)
- **#212** — formal at-issue waiver schema (`privilege_waivers` table)
- **#217** — broader Sanker domain audit (post-correction cleanup tracking)
- **#218** — pre-2018 dated archive folder skip in `imap_party_audit.py`
- **#219** — PR #214 body still references the legacy `masp-lawfirm.com` typo
- **#220** — `fortress_shadow_test` schema sync gap (legal.* migrations need manual apply)
- **#221** — PAT scope upgrade (create-only → read-write for issues + PRs)
- **#222** — gmail_watcher cron failing on `prompts.judge_parser` ModuleNotFoundError

### Known limitations

- The `_DOMAIN_TO_ROLE` dict in `backend/services/legal_ediscovery.py` is module-level; adding a new privileged counsel domain requires a backend restart for the in-memory map to update. Future iteration may move this to a runtime DB read — see Issue #194 + privilege classification rule documentation.
- The 11 case-detail endpoints in Issue #208 don't yet run alias resolution; bookmarks pointing at `7il-v-knight-ndga` for those specific routes will 404. Workaround: use the new slug `7il-v-knight-ndga-i` directly.
- Case II (`7il-v-knight-ndga-ii`) is `counsel_search` phase — `privileged_counsel_domains` array is empty until counsel is engaged. Council deliberation on Case II will surface privileged chunks from Case I via `related_matters` cross-reference.

### Migration applied via raw SQL (not alembic)

Phase B (schema columns + alias table) and Phase C (data rename + JSONB
populates + Qdrant payload migration) were applied via raw SQL to
`fortress_prod` and `fortress_db` because the rename couldn't be
expressed cleanly as a versioned alembic migration. `fortress_shadow`
was skipped per Issue #204 (chain divergence). `fortress_shadow_test`
was manually brought up to date (tracked as Issue #220 for permanent
fix).
