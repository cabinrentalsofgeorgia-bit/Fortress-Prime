# Case Briefing Tool — Spec v0.1

**Status**: forming spec. Drawn from spec notes accumulated during 2026-04-27 Case II curation. Not yet a build doc; will grow as more notes are captured.

**Companion docs**:
- `case-briefing-tool-spec-notes.md` (raw observations, append-only)
- `case-briefing-build-plan.md` (week + quarter operational plan)

---

## Goal

Given a `case_slug`, produce a 10-section Markdown attorney briefing package equivalent to the Fish Trap (`fish-trap-suv2026000013`) or 7IL Case II (`7il-v-knight-ndga-ii`) hand-authored versions, citing curated evidence with provenance and surfacing operator decision points.

Replaces the existing `tools/legal_templates.py:tmpl_attorney_briefing` (42-line skeleton) with a structured output that combines:
- mechanical interpolation (case metadata, parties, counts, statutory anchors)
- structured evidence citation (curated set inventory with hashes + source provenance)
- Council-deliberated analysis (claims, defenses)
- automated intelligence summarization (emails, financial exposure)

---

## Inputs

### Required (must be present in DB / filesystem)

- `legal.cases` row for `case_slug`
- Curated documents tree at `/mnt/fortress_nas/.../<case_slug>/curated/documents/`
- Curated emails tree at `/mnt/fortress_nas/.../<case_slug>/curated/emails/`
- Operative complaint PDF (text-extractable)

### Optional (improves output quality)

- Curated `case-i-context/` subtree (for related-matter cases)
- `.metadata.json` sidecars on emails (provenance enrichment)
- Council deliberation API access (`/api/internal/legal/cases/{slug}/deliberate`)
- Live `email_archive` access for cross-classification
- Recorded-deed OCR (transfer tax → consideration extraction)

### Outputs

- `<case_slug>.md` — the brief itself (10 sections)
- `<case_slug>.json` — structured machine-readable companion (same data, different format)
- `<case_slug>-evidence-inventory.md` — separate file listing every curated artifact with hash + provenance + relevance tag

---

## 10 Sections

| # | Section | v0.1 (mechanical) | v0.2 (Council) | v0.3 (intel) |
|---|---|:-:|:-:|:-:|
| 1 | Case Summary | ✅ | — | — |
| 2 | Critical Timeline | ✅ | — | — |
| 3 | Parties & Counsel | ✅ | — | — |
| 4 | Claims Analysis | template | ✅ | — |
| 5 | Key Defenses Identified | template | ✅ | — |
| 6 | Evidence Inventory | ✅ | — | — |
| 7 | Email Intelligence Report | template | template | ✅ |
| 8 | Financial Exposure Analysis | template | template | ✅ |
| 9 | Recommended Strategy | template | ✅ | — |
| 10 | Filing Checklist | ✅ (rule-based) | — | — |

---

## Architectural Constraints (from spec notes)

These are non-negotiable, learned from this curation pass:

### From "Bucketing by file_name keyword alone catches email junk"
- Stratify by `mime_type` first, never apply legal-keyword classifiers to `.eml`. Documents and emails are separate corpora at the input layer.

### From "Vault contamination from unfiltered inbox pull"
- Tool MUST refuse to read directly from a `case_slug` that is contaminated. Detection: > 50% `.eml` files with content matching unfiltered-inbox patterns (newsletter, receipt, travel, financial). Surface a "Curation required first" error and require explicit operator override.
- Tool reads from `curated/`, not raw `vault_documents` or NAS case folder root.

### From "Keyword bucketing fragility"
- Anchor keywords to position (`STARTS WITH`, not `CONTAINS`).
- Multi-word phrases for ambiguous terms.
- Use file_name + mime_type + ingestion source for confidence scoring.

### From "Opposing counsel metadata staleness" (T8)
- Source counsel info from operative complaint signature block by automatic OCR + signature-block parser. Compare against `legal.cases.opposing_counsel`. Surface mismatch for operator to confirm before generating brief.
- After T8 JSONB migration, opposing_counsel will be structured; pre-migration, output a warning when generating.

### From "Cross-case email mis-routing"
- Tool should query `legal.email_case_links` (post-migration, many-to-many) for email evidence, not assume single-bucket classification. Pre-migration, fall back to `email_archive.case_slug` + manual recovered-from-misroute supplement.

### From "Operative pleadings via co-defendant email, not ECF/direct service"
- Sequenced batch integrity check: detect numbering gaps in exhibit set ingested. Surface "Exhibit set incomplete: missing 1-7" before brief generation. Brief output should NOTE missing exhibits explicitly in section 6.

### From "PACER integration as canonical source"
- Future: pull canonical PDF from RECAP if available, prefer over forwarded copies.

### From "Operative pleadings arrived via co-defendant"
- Two-property scope detection: parse complaint for property addresses; verify all referenced properties have evidence. Surface "Property X has zero evidence in curated set" if a property is named but unrepresented.

---

## Data Model Sketch

### Existing tables (mostly fine)

- `legal.cases` — needs `opposing_counsel` JSONB migration (T8)
- `legal.case_actions` — append-only timeline
- `legal.case_evidence` — current count source (used by existing template)
- `legal.deadlines` — needs population for active cases
- `legal.vault_documents` — vault-staging; tool consumes via `curated/` path, not directly

### New tables (post-spec, post-build)

- `legal.email_case_links(email_id, case_slug, confidence, source, created_at)` — many-to-many email-to-case (post-T9)
- `legal.exhibit_completeness(case_slug, exhibit_label, expected, present, missing_reason)` — track ECF docket gaps
- `legal.case_briefing_runs(id, case_slug, version, generated_at, output_path, hash)` — audit log for each brief generation

### Filesystem conventions (canonical)

```
/mnt/fortress_nas/.../<case_slug>/
├── raw/                              ← whatever ingested first (inbox dumps, vendor exports)
└── curated/
    ├── documents/
    │   ├── 01_operative_pleadings/
    │   ├── 02_complaint_exhibits/
    │   ├── 03_civil_cover/
    │   ├── 04_property_records/      ← deeds, surveys (post-curation)
    │   ├── 05_inspections/
    │   ├── 06_psas_closing/
    │   ├── 07_easement_evidence/
    │   ├── 08_correspondence/
    │   ├── 09_other_evidence/
    │   └── case-i-context/           ← for related-matter cases (numbered sub-dirs match parent pattern)
    │       ├── 01_pleadings/
    │       ├── 01_pleadings/loas/
    │       ├── 02_dispositive_motions/
    │       ├── 03_judgment_and_orders/
    │       ├── 04_deposition_exhibits_<related-slug>/
    │       ├── 05_psas/
    │       ├── 06_easements/
    │       ├── 07_surveys/
    │       ├── 08_discovery/
    │       ├── 09_depositions/<deponent>/
    │       └── 10_findings_conclusions/
    └── emails/
        ├── from-vanderburge-misroute/    ← cross-case recovered (with .metadata.json sidecars)
        ├── from-email-archive/           ← Captain-ingested (DB-resident)
        └── from-personal-pull/           ← operator-supplied (Mac, dotloop, etc.)
```

Tool reads only from `curated/`. Tool never modifies `raw/` or curated source files; it produces additive output to `draft-brief/<case_slug>.md`.

---

## CLI Surface (v0.1 target)

```
case_briefing_compose <case_slug> [options]

Options:
  --output-dir <path>          Default: /mnt/fortress_nas/.../<slug>/draft-brief/
  --section <n[,m,...]>        Generate only specific sections (default: all)
  --no-council                 Skip Council-deliberation calls (v0.2+)
  --dry-run                    Validate inputs only; report missing data
  --council-timeout <secs>     Default: 600s for sections 4/5/9 in v0.2+
  --include-related <slug>     Pull case-i-context/ from related slug into output
```

Exit codes:
- 0: brief generated successfully, all sections present
- 1: incomplete generation (some sections fell back to template)
- 2: vault contamination detected (curation required first)
- 3: missing required input (no operative complaint, no curated set)
- 4: opposing_counsel mismatch detected, user must confirm before regeneration
- 5: Council unreachable (v0.2+) and `--no-council` not specified

---

## Open Questions / TBD

1. **Section 7 (Email Intelligence)** — what's the right summarization model? Council deliberation is heavy for routine email summaries; might need a smaller model (Qwen2.5 7B from SWARM, or a fine-tuned legal-instruct adapter).
2. **Section 8 (Financial Exposure)** — currently no source of structured cost-of-repair estimates. Manual operator input expected via JSON sidecar?
3. **Multi-property cases** (like Case II) — should section 6 split evidence inventory by property, or by claim, or by date?
4. **Pro-se vs counsel-of-record** — tool output should differ. Pro-se brief is informational scaffolding for the operator; counsel-of-record brief should be litigation-quality. Toggle via case posture? Operator preference flag?
5. **Privilege handling** — `vault_documents.processing_status = 'locked_privileged'` exists. Brief generator must NOT cite privileged docs. Filter at curation reading time + sanity-check at output time.
6. **Brief versioning** — should each `case_briefing_compose` run create a new versioned output? Yes (timestamp-suffixed filenames + audit row in `legal.case_briefing_runs`).

---

## Open spec questions (for v1.0)

1. **Citation format**: footnotes? inline parenthetical? Both? The Fish Trap brief used inline references like "Email #132598" — that pattern works if we have stable ids. Decision: probably inline parenthetical for compactness + a "References" footnoted appendix for full citation chain.

2. **Missing-evidence handling**: e.g., Case II's Wilson Pruitt closing files are not yet on hand. Tool must produce sections that explicitly mark "**PENDING: awaiting Wilson Pruitt File 25-0170**" rather than hallucinating around the gap. Markers should be machine-readable so subsequent regeneration can detect resolved gaps.

3. **PDF conversion**: should pandoc render happen automatically or be on-demand? Auto adds ~30s; on-demand is one extra command. Decision leaning toward on-demand (`case_briefing_render <slug>`) — preserves the markdown as canonical and lets operator iterate without rebuild cycles.

4. **Brief versioning**: when the operator regenerates a section weeks later (e.g., after Wilson Pruitt files arrive), should there be a v2 alongside v1? **Yes** — the first brief sent to a lawyer is a citable artifact. Filename pattern: `<slug>-vNNN-YYYY-MM-DD.md`. Each version row in `legal.case_briefing_runs` references the input set hash so we can audit what changed.

5. **Privilege handling**: `legal.privilege_log` entries in the curated set need explicit marking in the brief. Tool must refuse to cite privileged materials in external-facing sections; should cite them only in privileged-counsel-eyes-only sections that are output as a separate file (`<slug>-privileged.md`) with file permissions 0600.

---

## Test cases (for v1.0)

When tool is built, validate against:

- **Fish Trap** (`fish-trap-suv2026000013`) — known good output exists at `/mnt/fortress_nas/sectors/legal/fish-trap-suv2026000013/filings/outgoing/Attorney_Briefing_Package_SUV2026000013.md`. Tool should reproduce **comparable depth** (340 lines, 10 substantive sections, citations to specific email IDs and exhibits). Note: vault is currently empty for this case_slug — see open Curation Notes about missing vault ingestion for Fish Trap.

- **Case II** (`7il-v-knight-ndga-ii`) — primary proving ground. Hand-built brief from Days 3–7 of the build plan is the comparison. Validates that:
  - Two-property scope detection works (Fish Trap + River Heights co-equal)
  - Cross-case email mis-routing recovery (52 vanderburge emails) flows through to section 7
  - Case I context (70 files) feeds section 5 defenses (res judicata / collateral estoppel)
  - Stale `opposing_counsel` mismatch is surfaced + corrected via complaint signature parse

- **Vanderburge v Knight (Fannin)** (`vanderburge-v-knight-fannin`) — different case shape (state court, different plaintiff), validates tool isn't over-fit to the 7IL pattern. Tool should produce a coherent brief even when many of its emails were re-routed away (since they actually belong to Case II).

---

## Spec notes traceability

Each spec note in `case-briefing-tool-spec-notes.md` maps to a tool capability or upstream fix:

| Spec note (date — case — title) | Tool capability layer |
|---|---|
| 2026-04-27 — 7il-ii — Bucketing by file_name keyword catches email junk | **Stage 0** — mime_type stratification before legal-keyword classification |
| 2026-04-27 — 7il-ii — Vault contamination from unfiltered inbox pull | **B1 ingestion gate** (upstream of tool) — case-slug guard refuses contaminated vault |
| 2026-04-27 — 7il-ii — Keyword bucketing fragility | **Stage 0** — multi-word phrases + position-anchored matching ("STARTS WITH") |
| 2026-04-27 — 7il-ii — Opposing counsel metadata staleness | **B4 JSONB migration** (upstream) — T8 / GH #262 |
| 2026-04-27 — 7il-ii — Cross-case email mis-routing | **B2 link table** (upstream) — `legal.email_case_links` many-to-many |
| 2026-04-27 — 7il-ii — Case II vault lacks document-type organization | **B5 case-opening protocol** (upstream) — auto-create per-case subdirs at row creation |
| 2026-04-27 — 7il-ii — Operative pleadings arrived via co-defendant email | **B3 PACER integration** (upstream) — RECAP pull on filing date |
| (future) — vault populated from plaintiff's exhibits | **B5 case-opening protocol** + Stage 0 defendant-record check (vault should not be filled exclusively from plaintiff-supplied exhibits without operator-side cross-set) |

Each upstream fix (B1–B5) has its own work item / GitHub issue track. The tool itself (this spec) only consumes the post-fix world; partial implementations work but produce more "PENDING" markers.

---

## Update Log

| Date | Spec note source | Change |
|---|---|---|
| 2026-04-27 | All 6 spec notes from Case II curation | Initial v0.1 outline |
