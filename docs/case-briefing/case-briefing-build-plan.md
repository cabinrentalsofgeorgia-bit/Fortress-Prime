# Case Briefing — Build Plan

**Created**: 2026-04-27
**Owner**: Gary Knight (operator)
**Driver**: Case II (`7il-v-knight-ndga-ii`) brief is due now; the tool that should have produced it doesn't exist yet. This plan is the bridge.

---

## Context

The current "case briefing" workflow is hand-curation + a thin string-formatting template (`tools/legal_templates.py:643 tmpl_attorney_briefing`) registered in a manually-started FastAPI service (`tools/legal_case_manager.py` on port 9878). The Fish Trap brief from Feb-Mar 2026 (340 lines, 10 substantive sections) was hand-authored — the template only produces a 42-line skeleton.

For Case II we have:
- 12 ECF Document 1 PDFs curated (operative complaint + 11 exhibits)
- 52 contemporaneous Knight emails recovered from Captain mis-routing
- 70 Case I context files (pleadings, dispositive motion practice, depo exhibits, transcripts, LOAs)
- 4 spec note clusters captured during this curation pass
- 5 GitHub issues filed (T1, T3, T4, T5, T8 — corresponding to GH #257, #259, #260, #261, #262)

Plus 2 outbound drafts (Wilson Pruitt, Pugh) ready for operator to send + 1 already-drafted (Thor James for missing Exhibit G).

This plan covers (a) finishing the Case II brief this week, and (b) building the tool that should have done it for us.

---

## This Week — Case II Brief (Days 3–7)

### Day 3: Brief Skeleton

- Compose top-of-brief sections in `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/draft-brief/`:
  - § 1 Case Summary (table format from complaint metadata + closing date / parties / counts)
  - § 2 Critical Timeline (federal action 2:21-cv-226 → judgment Doc 134/135 → 2025-03-17 unauthorized easement → 2025-06-02 closings → 2026-04-15 Case II filing)
  - § 3 Parties & Counsel (with corrected Buchalter LLP attribution from complaint signature, not stale DB row)
  - § 4 Claims Analysis (8 counts walk-through with statutory anchors)
- Reference the curated set; cite each exhibit by curated filename.

### Day 4: Defenses + Strategy

- § 5 Key Defenses Identified (this is where the analytical work lives — bracketed by what the curated 2025-04 emails show about operator's contemporaneous understanding of repair/easement issues):
  - res judicata / collateral estoppel from Case I (need Order on MSJs `#78` review)
  - failure to plead with particularity (compare Case I's First Amended Complaint vs Case II's framing)
  - PSAs were performed via specific performance order — Counts I/VII may be barred
  - O.C.G.A. § 23-3-40 quia timet requires no adequate legal remedy — Case I judgment was the legal remedy
  - Driveway encroachment theory (Count VI) was identified by surveyor in 2021 — possible statute of limitations / waiver
- § 6 Evidence Inventory (the curated set lives here)
- § 7 Email Intelligence Report (52 mis-routed emails — particularly the "smoking gun" / "would-you-handle-seller-side" / "outstanding repairs and easement issues" threads)
- § 8 Financial Exposure Analysis (transaction value $1.78M from deed transfer taxes; specific damages claimed in Case II; cost of repairs alleged; quantum)

### Day 5: External Inputs

- Operator sends the 3 outbound emails (Thor James, Wilson Pruitt, Pugh) → expect responses Day 6–8.
- Operator pulls personal-side material (Mac, dotloop, Gmail) for: 2025 dotloop-executed PSAs, 2025-06-02 closing documents, defendant correspondence with plaintiff's counsel about repair demands.
- If responses arrive, integrate into Day 4 sections.

### Day 6: § 9 Recommended Strategy

- Position pro-se defendant for response to complaint (FRCP 12(a) — 21 days from service, but service status is unclear → may be more time available).
- Counsel-search status: prior LOAs show Goldberg has been opposing operator since 2022; operator is at counsel-search per `case_phase`. Recommend reaching out to attorneys with prior 7IL-Knight context who are not conflicted (Williams Teusink referral was already explored per the curated emails).
- Decision points:
  - Motion to dismiss vs Answer + Counterclaim
  - Removal / consolidation arguments (Case I court already; ancillary jurisdiction asserted by plaintiff)
  - Discovery posture if going to Answer

### Day 7: § 10 Filing Checklist + Final Pass

- Format brief output (markdown → PDF for handoff to counsel)
- Cross-reference every claim and defense against the curated evidence
- Sanity-check exhibit citations
- Operator review + send to retained counsel (if found by Day 7) or hold for direct response if pro-se

---

## Next Quarter — Tool & Infrastructure

### Layer 1: case_briefing_compose.py (build of v0.1)

Drawn from `case-briefing-tool-spec-v0.1.md` (separate file). Build target: a Python module that, given a `case_slug`, produces a 10-section Markdown brief equivalent to the Fish Trap or Case II hand-authored versions, citing the curated set automatically.

Phases:
- **v0.1 (~3 weeks)**: read `legal.cases` + `case-i-context/` + `02_complaint_exhibits/` and produce sections 1, 2, 3, 6 (mostly mechanical interpolation + provenance citation). Sections 4, 5, 7, 8, 9, 10 stay templated for now (operator hand-authors).
- **v0.2 (~6 weeks)**: integrate Council deliberation (existing `/api/internal/legal/cases/{slug}/deliberate`) for sections 4 (claims analysis) and 5 (defenses identified) — use 9-seat Council for defense analysis, output structured per section.
- **v0.3 (~3 months)**: section 7 (email intelligence) auto-summary from `email_archive` + sidecar tagging; section 8 (financial exposure) from deed records + repair cost estimates.

### Layer 2: Ingestion fixes (independent of Layer 1)

Tracked partly via T8 + spec notes. Concrete:

1. **Captain classifier — multi-bucket tagging** (spec note "Cross-case email mis-routing"). Emails should be tagged with all relevant `case_slug`s, not single-bucketed. New table `legal.email_case_links(email_id, case_slug, confidence, source)`.
2. **`opposing_counsel` JSONB migration** (T8 / GH #262). Schema migration text → JSONB with structured fields. Backfill from existing text. Audit pass against all active cases.
3. **Vault contamination guardrail** (spec note "Vault populated from inbox-dump"). Ingestion should refuse to ingest under `case_slug` if the source is an unfiltered inbox dump. Force operator to organize first OR accept a "raw" bucket marker that doesn't promote to vault.
4. **PACER integration** (spec note "PACER integration as canonical source"). For federal cases, RECAP-style pull on filing date so canonical record exists in vault from day 1, not from when a co-defendant forwards it.
5. **Exhibit-set integrity check** (spec note "Operative pleadings via co-defendant"). When ingesting a sequenced batch (e.g., `01-1` through `01-N`), detect numbering gaps and surface as "incomplete set" before declaring matter ingested.

### Layer 3: Frontend surface (per FLOS Phase 1 audit)

- `/legal/flos` page in command-center consuming `dispatcher/health` + `mail/health` + dead-letter list + posture get (G1 from FLOS frontend audit).
- Per-case "evidence inventory" view: read `curated/documents/<slug>/...` and render the curated tree. Operators can browse + re-open files inline.
- Case-briefing draft viewer: read `draft-brief/<slug>.md` and render with cross-links into the evidence inventory.

### Layer 4: Brief delivery

- PDF export pipeline (markdown → typeset legal brief PDF, with optional table-of-authorities).
- Optionally: integration with operator's e-filing tool / counsel handoff workflow.

---

## Dependencies + Open Issues

| ID | Description | Blocks |
|---|---|---|
| T1 / GH #257 | JWT vs static bearer middleware conflict | FLOS dispatcher health endpoint reachability — blocks Layer 3 frontend |
| T2 / GH #258 | Alembic chain reconciliation | Schema migration discipline — blocks T8 cleanly |
| T3 / GH #259 | gary-crog encoding errors | Captain ingest reliability — soft block on Layer 2 quality |
| T4 / GH #260 | gary-gk SEARCH overflow | Same; can run with current coverage |
| T5 / GH #261 | Stale FORTRESS_DB_* keys in .env | Resolved by patching consumers (soak script done) |
| T8 / GH #262 | opposing_counsel JSONB migration | Layer 1 v0.1 brief generator output quality |
| T9 (not yet filed) | Cross-case email mis-routing | Layer 2 fix #1 |

---

## Sequencing Rationale

This week's brief is a one-off; doing it by hand is faster than trying to build the tool first. But the data we curated this week (134 files in `curated/`) is exactly what the tool needs as a corpus to learn from. Phase 9 created a worked example that v0.1 can be tested against.

The build plan grows from this week's pain points outward — fix the things that bit us, then automate the parts we did manually.

---

## Status Cadence

- Daily during brief-week: appended notes here (no separate file)
- Weekly during build phase: `case-briefing-build-status.md` (to be created)
- Per-issue: GH ticket comments on T1–T8

## Update Log

| Date | Update |
|---|---|
| 2026-04-27 | Plan created. 134 files curated. 5 GH issues open. 3 outbound drafts pending operator send. |
