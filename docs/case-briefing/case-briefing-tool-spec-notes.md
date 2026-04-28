# Case Briefing Tool — Spec Notes

Operational observations captured during hand-curation of case briefing packages. Each entry is dated and case-tagged. The eventual case_briefing_compose.py tool draws its specification from these.

Convention: append entries chronologically; don't rewrite prior entries. When an observation is fixed by a tool change later, link the fix in a follow-up note rather than editing the original.

---

## 2026-04-27 — 7il-v-knight-ndga-ii — Bucketing by file_name keyword alone catches email junk

Bucketing the 634 vault docs by file_name keyword caught email noise where legal terms appeared as sender domains or newsletter headlines:

- "service" matched `service-z6-app-com` (kitchenware newsletter sender) → A_SERVICE
- "answer" matched a "questions and answers" newsletter → B_ANSWER
- "order" matched the headline "Trump issues psychedelic drug order" → B_ORDER_JUDGMENT

System should stratify by mime_type first (PDF/DOCX vs .eml), then apply legal keyword classifiers only to documents, not correspondence. This is a Day-1 friction point: 60+ items in fake A/B buckets that the operator has to manually reject.

## 2026-04-27 — 7il-v-knight-ndga-ii — Vault contamination from unfiltered inbox pull

634 "Case II" vault docs include 117+ obvious junk (newsletters, receipts, travel confirmations) and 495 M_UNKNOWN docs that pattern-matched too weakly to bucket.

Root cause: bulk ingestion of an unfiltered cPanel inbox pull labeled as Case II material. The case_slug was assigned to a noisy pull, not a curated evidence set.

Tool implications:
- Ingestion pipeline needs a relevance gate BEFORE assigning case_slug. Current model accepts case_slug as authoritative; reality is the operator pointed an ingester at an inbox dump and the case_slug was applied to everything in the dump.
- Curation tool should:
  (a) Stratify by mime_type before any keyword bucketing
  (b) Treat .eml from inbox pulls as candidate-emails, not vault documents, and route them through email_archive instead
  (c) Flag any case_slug where >50% of vault docs are .eml as "ingestion likely contaminated — manual curation required"
  (d) Provide a "demote from vault" operator action that moves a doc from legal.vault_documents to a quarantine/review pile without deleting

## 2026-04-27 — 7il-v-knight-ndga-ii — Keyword bucketing fragility

Single-word keyword matching on file_name alone produces false positives even on real PDFs. Examples observed:

- "service" matched a sender domain (service-z6-app-com)
- "answer" matched newsletter content
- "order" matched a news headline

Tool implications:
- Anchor keywords to position (filename starts with, not contains)
- Require multi-word phrases for ambiguous terms ("service of process" not "service")
- Use file_name AND mime_type AND ingestion source (legal_vault_ingest.py vs Captain dump) for confidence scoring
- Consider a small classifier model (Qwen2.5 or similar) trained on Case I's curated set as ground truth, applied to candidate vault docs at ingestion time

## 2026-04-27 — 7il-v-knight-ndga-ii — Opposing counsel metadata staleness

**Tracked:** GH #262 (https://github.com/cabinrentalsofgeorgia-bit/Fortress-Prime/issues/262)

`legal.cases.opposing_counsel` was a free-text best-guess value populated during initial case row creation. Reality (from operative complaint signature block, Document 1 p.18) differs significantly — wrong firm (Freeman Mathis & Gary LLP vs actual Buchalter LLP), wrong email domain (`fmglaw.com` vs `buchalter.com`). Brief generator and Captain classifier (which uses `opposing_counsel.firm` to flag inbound mail as legal-track) are both compromised by this drift.

Tool implications:
- Counsel metadata should be extracted from the operative complaint's signature block automatically during ingestion of the complaint into the vault, not entered manually.
- Update should propagate to `legal.cases.opposing_counsel` AND to Captain's domain-allowlist for the legal route.
- Mismatch detector: when complaint signature differs from current `opposing_counsel`, surface alert to operator.
- Audit pass: rerun across all active cases to confirm `opposing_counsel` accuracy against signature blocks of operative pleadings on file.

## 2026-04-27 — 7il-v-knight-ndga-ii — Operative pleadings arrived via co-defendant email, not ECF/direct service

The complete Case II ECF Document 1 set (operative complaint + 12 exhibits + civil cover sheet) arrived only via 5 sequential emails from co-defendant Thor James (`sigma.thorjames@gmail.com`) on 2026-04-23, 12:38–12:47 EDT. There was no direct service to the operator visible in the inbox dump, no ECF/PACER pull, and no court-mailed copy.

This pattern is specific to the case posture: when a case is in `counsel_search` phase with no attorney of record, ECF account access doesn't exist for the defendant pro se; co-defendant courtesy or court-mailed service is the only inbound path. One email in the batch arrived without exhibit `01-7.pdf` (Exhibit G — 2025 River Heights Inspection), so the curated set is incomplete by one exhibit pending re-request.

Tool implications:
- Ingestion needs to flag email attachments matching plaintiff/case-name patterns as high-priority service-of-process candidates.
- Co-defendant relationship detection: when a sender's name matches a `case_name` co-defendant (parsed from `legal.cases.case_name`), elevate that sender's emails + attachments to top-tier ingestion priority.
- Exhibit-set integrity check: when ingesting a sequenced batch (e.g., `01-1` through `01-N`), detect numbering gaps and surface as "exhibit set incomplete — request missing parts".
- Closing date / closing attorney / transaction value can be derived from recorded warranty deeds (transfer tax × $1000 ≈ consideration in GA). Worth auto-extracting from any deed-attachment OCR.

## 2026-04-27 — 7il-v-knight-ndga-ii — Cross-case email mis-routing

14+ emails substantively about Case II events (April 2025 easement drafting, repair issues with 7IL) live in `legal_vault/vanderburge-v-knight-fannin/` instead of `legal_vault/7il-v-knight-ndga-ii/`. Discovered during Phase 9 NAS hunt. Captain classifier likely keyed on something in the email content that matched Vanderburge first (Knight + easement + Padrutt context appears in both matters; classifier resolves to a single bucket).

Tool implications:
- Captain classifier should not be single-bucket: emails can pertain to multiple matters and should be tagged with all relevant `case_slug`s, not forced into one.
- Reclassification audit: when a new case is opened (like Case II in April 2026), review all prior classifications during the substantive period (e.g., 12 months before complaint date) for potential re-routing.
- Cross-case email link table: `legal.email_case_links(email_id, case_slug, confidence, source)` — many-to-many, not the current implicit single-classification model.

## 2026-04-27 — 7il-v-knight-ndga-ii — Case II vault lacks document-type organization

Case I has parallel structure: `legal_vault/<slug>/` (UUID-staging from ingester) AND `Business_Legal/{Depositions, Discovery, # Pleadings - GAND}/` (operator-organized by document type with Bates-numbered exhibits). Case II has only the inbox dump under `Business_Legal/7il-v-knight-ndga-ii/` — no `Discovery/`, no `Depositions/`, no `Pleadings/`.

Tool implications:
- Case-creation workflow should auto-create the per-case document-type subdirectory structure (Depositions, Discovery, Pleadings, Correspondence, Outgoing).
- Ingestion should refuse to label files with `case_slug` if they're going into the inbox-dump path; force operator to organize first or accept a "raw" bucket marker.
- Brief generator's evidence inventory section should distinguish "organized record" from "ingestion bucket" so a lawyer reading the inventory understands what's curated vs raw.

## 2026-04-27 — 7il-v-knight-ndga-ii — PACER integration as canonical source

Operator pro se in counsel-search has no ECF access. Co-defendant Gmail forward is the only canonical source for the operative complaint. The 12 .pdf set extracted from 5 forwarded emails was found to have a numbering gap (`01-7.pdf` / Exhibit G missing) — defendant cannot independently verify completeness without ECF.

Tool implications:
- Fortress should integrate PACER pull (RECAP, free reads when allowed) for federal cases automatically so the canonical filed record exists in the vault from filing date onward, not from when a co-defendant forwards it.
- For state-court cases, equivalent: e-courts integration where available; otherwise operator-side scan/upload workflow with attestation.
- Completeness check at vault-ingest time: when a sequenced batch is ingested (e.g., `01-1` through `01-N`), detect numbering gaps and flag for operator follow-up before declaring the matter "ingested".

## 2026-04-28 — 7il-v-knight-ndga-ii — Email archive coverage gap (1500+ unclassified hits)

Stage 3 of the overnight curation pass ran 5 keyword/sender queries against `public.email_archive` and surfaced ~1,528 raw hits across queries (with overlap) — Query A (prior counsel) 37, Query B (parties + opposing counsel) 685, Query C (third parties — Wilson Pruitt / Pugh / Alpha Surveying / dotloop / McBee / Ansley RE) **only 1 hit**, Query D (content keywords — fish trap / river heights / easement / 7il / specific performance / 2:21-cv / 2:26-cv) 524, Query E (2025 critical period, knight/cabin-rentals senders) 281.

Vast majority of these emails carry **no `case_slug` classification at all** — they're sitting in `email_archive` un-routed to any matter. Only 52 emails were misrouted to Vanderburge folder (already recovered). The much larger pool is just unfiltered.

Tool implications:
- Captain classifier coverage is not just *mis-routing* (single-bucket-wrong) but also *under-routing* (single-bucket-empty). Most matter-relevant emails never get tagged with any `case_slug`.
- Combined with the existing many-to-many email_case_links table (B2 fix), a re-classification batch job is needed to walk the existing `email_archive` and propose case_slug attachments for operator review.
- Query C's near-zero result for third parties (Wilson Pruitt / Pugh / Alpha Surveying) suggests those communications never landed in `email_archive` at all — they live in operator's personal email outside Captain's reach. Spec implication: Captain's source pool needs explicit personal-mailbox enumeration, OR ingestion needs an operator-supplied direct-import path for personal email exports.

## 2026-04-28 — 7il-v-knight-ndga-ii — Defendant-record completeness check missing for closings

Stage 4 of the overnight curation confirmed: **NAS has zero 2025-cycle Wilson Pruitt closing files**, **zero 2025 dotloop archives**, **zero May 2025 Pugh inspection (River Heights)**, **zero defendant-side signed PSA copies**. The entire 2025 transactional record (which Counts I, II–V, VI, VII all turn on) is outside Fortress's reach — it's in operator's Gmail / Mac / dotloop dashboard.

Pattern observed: **operator-completed transactions don't generate vault-resident records** unless the transaction documents are deliberately exported. Past matters (Higginbotham, Case I 2021 cycle) have records on NAS because they were litigated and produced through discovery. The 2025 7IL closing wasn't litigation-yet; the records never made it to NAS.

Tool implications:
- Case-creation workflow should include a "transactional records sourcing" prompt: identify all transactions referenced in the operative pleading, prompt operator to confirm each transaction's records are on NAS or initiate an explicit personal-records import.
- Brief generator's evidence inventory section should distinguish "in vault" / "in personal email" / "request from third party" so a reading lawyer understands what's accessible.
- A "transactional record sweep" companion script — given a case_slug + date range — could surface all closings/contracts/inspections referenced and check for vault presence. Calls personal-Gmail-export integration if not present.

## 2026-04-28 — 7il-v-knight-ndga-ii — Image-only Case I MSJ exhibits

Stage 5.3 OCR-coverage audit found 14 PDFs in the curated set are image-only (pdftotext yields <200 chars in 2pp preview). Concentrated in Case I MSJ supporting exhibits (#63-9 through #63-13) and the 2021 inspection report for River Heights (Exhibit E from Case II — 121 pp).

Tool implications:
- Pre-ingestion OCR should be standard for MSJ-era discovery production. Producing parties (here, 7IL) often serve scanned PDFs; without OCR they're not searchable, which constrains brief synthesis (LLM can't extract facts from images).
- `vault_documents.processing_status` should distinguish `complete` (text-extractable, vector-indexed) from `complete_image_only` (visually present but not text-searchable). Currently both end up in same status.
- Brief generator should refuse to cite a fact "from Exhibit E" if the cited page is image-only without verifying the citation through OCR or operator-supplied summary.
