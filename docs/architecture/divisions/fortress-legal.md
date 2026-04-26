# Division: Fortress Legal (Sector 05 — "Fortress JD")

Owner: Gary Mitchell Knight (operator)
Status: **active** — most heavily developed division as of 2026-04-26
Spark allocation:
- **Current:** **Spark 1 (`192.168.0.X`) — ACTIVE.** Hosts Legal email intake, vault ingestion, privileged communications, Council legal retrieval. Per ADR-001 (one-spark-per-division).
- **Target:** Same — Spark 1 is Fortress Legal's permanent home.
Last updated: 2026-04-26

## Purpose

Legal intelligence + case management across all active matters. Ingests filings, correspondence, depositions, exhibits into a privilege-aware vault; runs Council deliberation against case-scoped retrieval with mandatory FOR YOUR EYES ONLY warnings on privileged content; tracks deadlines, opposing counsel, court orders, settlements.

The platform was designed first around a single legal matter (`7il-v-knight-ndga`) and grew during 2026-Q2 to support multi-case, multi-counsel, multi-jurisdiction operations.

## Active cases (as of 2026-04-26)

| `case_slug` | Status | Phase | Notes |
|---|---|---|---|
| `7il-v-knight-ndga-i` | closed_judgment_against | closed | Federal NDGA, docket 2:21-CV-00226-RWS. 1,396 vault docs ingested. |
| `7il-v-knight-ndga-ii` | active | counsel_search | Federal NDGA, docket 2:26-CV-00113-RWS. Post-judgment matter. |
| `vanderburge-v-knight-fannin` | closed_settled | closed_settled | Fannin County GA. Property easement dispute, settled. Defense: Sanker. Co-defendant: Lissa Knight (spouse). |
| `fish-trap-suv2026000013` | active | (none) | Generali matter. 2 vault docs (test corpus). |
| `prime-trust-23-11161` | active | (none) | Prime Trust matter. |
| `legal-fortress-mvp` | active | (none) | Placeholder for early MVP work. |

Legacy alias: `7il-v-knight-ndga` → `7il-v-knight-ndga-i` (in `legal.case_slug_aliases`).

## Key data stores

### Postgres (cross-DB)

- `legal.cases` — case metadata: docket, court, judge, opposing counsel, `privileged_counsel_domains` JSONB, `related_matters` JSONB, `case_phase`, `nas_layout` JSONB
- `legal.vault_documents` — every ingested file's row (FK `case_slug`, UNIQUE `(case_slug, file_hash)`, CHECK on 9-status processing vocabulary). [`runbooks/legal-vault-documents.md`](../../runbooks/legal-vault-documents.md) is the schema runbook.
- `legal.case_slug_aliases` — backward-compat after slug renames (PR G phase C).
- `legal.privilege_log` — audit trail for every privilege classification (immutable).
- `legal.ingest_runs` — audit trail for every script invocation (PR D-pre1).
- `legal.correspondence`, `legal.deadlines`, `legal.filings`, `legal.case_actions`, `legal.case_evidence`, `legal.case_watchdog`, `legal.case_precedents` — supporting tables (legacy + active)

Cross-links to [`shared/postgres-schemas.md`](../shared/postgres-schemas.md) for full table inventory.

### Qdrant

- `legal_ediscovery` — work-product chunks (filings, depositions, evidence, discovery responses). 151,313+ points as of 2026-04-26 (mostly 7IL).
- `legal_privileged_communications` — privileged chunks (attorney-client communications, work-product memos, JDA traffic). Created in PR G phase C; deterministic UUID5 point IDs.
- `legal_caselaw` — Georgia state caselaw corpus (~2,711 chunks).
- `legal_caselaw_federal` — Federal CA11 caselaw corpus (created in PR #184; awaiting real ingest).

Cross-links to [`shared/qdrant-collections.md`](../shared/qdrant-collections.md).

### NAS

- `/mnt/fortress_nas/Corporate_Legal/Business_Legal/` — case files (Pleadings, Discovery, Correspondence, Depositions, etc.). Per-case `nas_layout` JSONB on `legal.cases` maps logical subdirs to physical paths.
- `/mnt/fortress_nas/legal_vault/<case_slug>/` — vault NFS copies of every ingested file
- `/mnt/fortress_nas/legal-corpus/courtlistener/` — CourtListener-backed caselaw cache
- `/mnt/fortress_nas/audits/` — every script invocation's manifest
- `/mnt/fortress_nas/models/legal-instruct-*` — fine-tuned legal adapter checkpoints

## Key services consumed

- [Captain](../shared/captain-email-intake.md) — inbound email capture; routes legal-keyword emails to the legal pipeline
- [Council](../shared/council-deliberation.md) — case-aware deliberation with privileged-track retrieval + FYEO warnings
- [Sentinel](../shared/sentinel-nas-walker.md) — does NOT own legal vault content (legal owns its own ingestion pipeline)
- [Privilege classifier](../shared/council-deliberation.md#privilege-classifier) — Qwen2.5 ≥ 0.7 confidence gate inside `process_vault_upload`
- [MCP servers](../shared/mcp-servers.md) — TBD if legal consumes any MCP tooling

## Key services exposed

- `backend/api/legal_cases.py` — case detail, files, deadlines, correspondence, timeline, war-room state, deliberation orchestration. 23 endpoints (12 alias-resolved + 11 unresolved per Issue #208/#213).
- `backend/api/legal_counsel_dispatch.py` — Council deliberation API + retrieval endpoints
- `backend/services/legal_ediscovery.py::process_vault_upload` — canonical ingestion entry point
- `backend/scripts/ocr_legal_case.py` — OCR sweep for image-only PDFs (PR C / #188)
- `backend/scripts/vault_ingest_legal_case.py` — case-scoped vault ingestion (PR D / #195)
- `backend/scripts/email_backfill_legal.py` — case-aware IMAP email backfill (PR I / #225)

## Recent merged PRs (2026-04-25 → 2026-04-26)

`#185` `#186` `#188` `#190` `#193` `#195` `#196` `#197` `#214` `#215` `#216` `#225` — see [`../../CHANGELOG.md`](../../CHANGELOG.md)

## Open questions for operator

- `legal-fortress-mvp` placeholder slug — is this still needed or can it be retired?
- Q3-2026 roadmap — which case takes priority once #225 production runs land?
- Onward — does Fortress Legal expose anything to external counsel review pipelines, or is it fully internal?

## Cross-references

- Privilege architecture runbook: [`../../runbooks/legal-privilege-architecture.md`](../../runbooks/legal-privilege-architecture.md)
- Vault documents schema: [`../../runbooks/legal-vault-documents.md`](../../runbooks/legal-vault-documents.md)
- Vault ingestion: [`../../runbooks/legal-vault-ingest.md`](../../runbooks/legal-vault-ingest.md)
- Email backfill: [`../../runbooks/legal-email-backfill.md`](../../runbooks/legal-email-backfill.md)
- Atlas entry: [`../../../fortress_atlas.yaml`](../../../fortress_atlas.yaml) Sector 05
- Followup issues: #194 (vocabulary), #198 (pre-process exception), #200 (.ptx), #201 (qdrant_pending), #208 (alias coverage), #209 (CASCADE), #210 (UUID5), #211 (chunks tooling), #212 (waiver schema), #217 (Sanker audit), #224 (Vanderburge TBDs)

Last updated: 2026-04-26
