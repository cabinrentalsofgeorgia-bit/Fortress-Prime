# Phase B — Drafting Orchestrator (case_briefing_compose.py)

**Target:** Claude Code on spark-2
**Branch:** `feat/phase-b-drafting-orchestrator`
**Date:** 2026-04-29
**Driver:** Track A Case II briefing v2 has Sections 4/5/8 unfilled. Hand-curated synthesis for one case is the proof; Phase B is the tool that turns curated evidence + sovereign inference into white-shoe-grade briefing packages reproducibly.

**Stacks on:** PR #285 (LiteLLM legal cutover), PR #286 (ADR-004), PR #281 (Track A Case II v2)
**Maps to:** Case II Build Plan §B6 (`case_briefing_compose.py`)

---

## 1. Mission

Ship the orchestrator that produces 10-section attorney briefing packages from a curated evidence set + sovereign BRAIN inference. Stage 0 (curate) and Stage 4 (assemble final) bracket Stages 1-3 (grounding + synthesis + operator review).

This is the tool that operationalizes "the system knows the case better than they do." Single operator runs `case_briefing_compose --case-slug X` and gets a deliverable that out-prepares a top-3 firm. Today's Track A v2 brief was hand-curated; Phase B reproduces that quality on demand.

---

## 2. Scope

**In scope:**
- `backend/services/case_briefing_compose.py` — orchestrator module (Stage 0 → Stage 4)
- `backend/scripts/case_briefing_cli.py` — operator CLI wrapper
- `backend/services/case_briefing_synthesizers.py` — per-section synthesizer functions (mechanical + LLM-grounded)
- `backend/tests/test_case_briefing_compose.py` — unit tests (mocked LLM, mocked retrieval)
- `docs/runbooks/case-briefing-compose-runbook.md` — operator runbook
- `docs/operational/briefs/phase-b-drafting-orchestrator-2026-04-29.md` — this brief, archived
- One executed dry-run on `7il-v-knight-ndga-ii` producing v3 brief, output captured

**Out of scope:**
- Modifying existing `legal_council.py` (Council has its own consumer-cutover Phase B follow-up — separate PR)
- Modifying retrieval primitives (`freeze_context`, `freeze_privileged_context` — read-only consumer)
- Ingesting new evidence
- Multi-case batching
- Web UI integration (CLI only for v1)
- Production deployment as a service (CLI runs ad-hoc by operator)

---

## 3. Architecture (matches Case II Build Plan §B6)

```
┌─────────────────────────────────────────────────────────────┐
│ STAGE 0 — CURATE                                             │
│ Cluster vault by mime_type + keyword + LLM-classify         │
│ ambiguous; deduplicate against email_archive                │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 1 — ASSEMBLE GROUNDING PACKET                         │
│ Pull case metadata, related_matters, vault docs, email      │
│ archive hits, NAS curated set into structured packet        │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 2 — SYNTHESIZE PER-SECTION                            │
│ Mechanical sections (1, 3, 6, 10): deterministic templates  │
│ Synthesis sections (2, 4, 5, 7, 8): BRAIN with grounded     │
│   retrieval + streaming + grounding-citation enforcement    │
│ Section 9 (operator-written): placeholder for hand-edit     │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 3 — OPERATOR REVIEW                                    │
│ Per-section accept/edit/regenerate via CLI prompts          │
│ Operator marks each section complete before assembly        │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 4 — ASSEMBLE FINAL                                    │
│ Compose markdown package, write to                          │
│ /mnt/fortress_nas/.../filings/outgoing/                     │
│ Privilege/FYEO warnings preserved                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. File-level changes

| file | role | new/modified |
|---|---|---|
| `backend/services/case_briefing_compose.py` | orchestrator (~400 lines, Stage 0 → 4 dispatcher) | NEW |
| `backend/services/case_briefing_synthesizers.py` | per-section synthesizers (~600 lines) | NEW |
| `backend/scripts/case_briefing_cli.py` | argparse CLI | NEW |
| `backend/tests/test_case_briefing_compose.py` | 12+ tests | NEW |
| `backend/core/config.py` | `CASE_BRIEFING_OUTPUT_ROOT` env binding | MODIFIED |
| `.env.example` | new env var | MODIFIED |
| `docs/runbooks/case-briefing-compose-runbook.md` | operator runbook | NEW |

No alembic. No service touches. No spark-5 changes. No Qdrant or Postgres writes.

---

## 5. Module structure — `case_briefing_compose.py`

### 5.1 Constants + dataclasses

```python
COMPOSER_NAME    = "case_briefing_compose"
COMPOSER_VERSION = "v1"
TEN_SECTIONS = [
    ("section_01_case_summary", "mechanical"),
    ("section_02_critical_timeline", "synthesis"),
    ("section_03_parties_and_counsel", "mechanical"),
    ("section_04_claims_analysis", "synthesis"),
    ("section_05_key_defenses_identified", "synthesis"),
    ("section_06_evidence_inventory", "mechanical"),
    ("section_07_email_intelligence_report", "synthesis"),
    ("section_08_financial_exposure_analysis", "synthesis"),
    ("section_09_recommended_strategy", "operator_written"),
    ("section_10_filing_checklist", "mechanical"),
]

@dataclass
class GroundingPacket:
    case_slug: str
    case_metadata: dict        # legal.cases row
    related_matters: list[str]
    vault_documents: list[dict]   # legal.vault_documents rows for this case + related
    email_archive_hits: list[dict]
    curated_nas_files: list[dict]
    privileged_chunks: list[dict] # from legal_privileged_communications
    work_product_chunks: list[dict] # from legal_ediscovery
    contains_privileged: bool

@dataclass  
class SectionResult:
    section_id: str
    mode: str                  # "mechanical" / "synthesis" / "operator_written"
    content: str
    grounding_citations: list[str]   # vault_document_ids or email_archive_ids
    retrieval_chunk_ids: list[str]
    contains_privileged: bool
    operator_status: str       # "draft" / "accepted" / "edited" / "regenerated"
```

### 5.2 Stage 0 — Curate

Read-only. No modification of vault. Returns a CuratedSet structure:

```python
async def stage_0_curate(case_slug: str) -> CuratedSet:
    """
    Cluster vault by mime_type + keyword + LLM-classify ambiguous.
    Deduplicate against email_archive (some emails appear in both).
    Returns ordered list of evidence with provenance + relevance score.
    """
```

Logic:
1. Pull all `legal.vault_documents` for case_slug + related_matters
2. Cluster by `mime_type` (PDF, .eml, .docx, .txt, image)
3. Within each mime_type, keyword-classify (filings, depositions, exhibits, correspondence, evidence, contracts)
4. For ambiguous classifications, call SWARM tier (qwen2.5:7b) with a relevance prompt
5. Deduplicate vault_documents against email_archive by Message-ID where applicable
6. Assign relevance score (0-1) using BRAIN call against case theme summary

Output: ordered curated set, ready for Stage 1.

### 5.3 Stage 1 — Grounding packet

```python
async def stage_1_grounding_packet(case_slug: str, curated: CuratedSet) -> GroundingPacket:
    """
    Pull case metadata, related_matters, retrieval chunks into structured packet.
    Reuses freeze_context + freeze_privileged_context from legal_council.py (read-only).
    """
```

Logic:
1. Read `legal.cases` row including `nas_layout`, `case_phase`, `privileged_counsel_domains`, `related_matters`
2. Read `legal.vault_documents` for primary + related
3. For each section that needs retrieval, call `freeze_context()` and `freeze_privileged_context()`
4. Pull email_archive hits via existing query patterns (reuse PR I tooling)
5. Walk NAS curated set for files referenced in vault but not yet ingested
6. Set `contains_privileged` flag if any privileged chunk retrieved

### 5.4 Stage 2 — Synthesize

```python
async def stage_2_synthesize(packet: GroundingPacket, sections: list = TEN_SECTIONS) -> dict[str, SectionResult]:
    """
    Per-section dispatch. Mechanical sections deterministic.
    Synthesis sections call BRAIN with grounded retrieval + streaming.
    """
```

Per-section dispatcher:

| Section | Mode | Synthesizer |
|---|---|---|
| 01 Case Summary | mechanical | `synthesize_section_01_mechanical(packet)` — pulls case_metadata into table |
| 02 Critical Timeline | synthesis | `synthesize_section_02_brain(packet, mode="deterministic_table")` — extracts dated events from packet, grounded list |
| 03 Parties & Counsel | mechanical | `synthesize_section_03_mechanical(packet)` — counsel timeline + party blocks |
| 04 Claims Analysis | synthesis | `synthesize_section_04_brain(packet)` — BRAIN call with claims + elements + grounded weakness analysis |
| 05 Key Defenses | synthesis | `synthesize_section_05_brain(packet)` — BRAIN with affirmative defenses grounded against precedent (caselaw retrieval) |
| 06 Evidence Inventory | mechanical | `synthesize_section_06_mechanical(packet)` — table from curated set + email_archive |
| 07 Email Intelligence | synthesis | `synthesize_section_07_brain(packet)` — BRAIN with adversary correspondence + third-party-actor callouts; defense counsel excluded per privilege |
| 08 Financial Exposure | synthesis | `synthesize_section_08_brain(packet)` — BRAIN with damages math + exposure scenarios |
| 09 Recommended Strategy | operator_written | placeholder; operator hand-edits in Stage 3 |
| 10 Filing Checklist | mechanical | `synthesize_section_10_mechanical(packet)` — pulled from case_phase + deadlines |

All synthesis sections use `BrainClient` from PR #280 (streaming default, max_tokens 4000). Grounding citations enforced — every claim must cite a packet element. Citations validated post-generation; sections with <3 grounded citations get flagged FAIL_GROUNDING.

### 5.5 Stage 3 — Operator review

CLI-driven loop. For each section in TEN_SECTIONS:

```
$ case_briefing_compose --case-slug 7il-v-knight-ndga-ii --section section_04_claims_analysis

[Section 04 Claims Analysis]
[Mode: synthesis]
[Retrieved 12 chunks; 8 grounded citations]
[contains_privileged: false]

<full section content streamed to stdout>

Action: [accept] [edit] [regenerate] [skip] [show citations] >
```

Operator marks each section. State persists to `/tmp/case_briefing_<slug>/sections/` between invocations so operator can review across multiple sittings.

### 5.6 Stage 4 — Assemble final

```python
async def stage_4_assemble(case_slug: str, sections: dict[str, SectionResult]) -> Path:
    """
    Compose markdown package, write to NAS canonical path.
    Privilege warnings preserved. FYEO warning appended if any section contains_privileged.
    """
```

Output path: `/mnt/fortress_nas/Corporate_Legal/Business_Legal/<case_slug>/filings/outgoing/Attorney_Briefing_Package_<CASE_NAME>_v<N>_<YYYYMMDD>.md`

Version increments based on existing files in directory. v1 was overnight 2026-04-27. v2 was Track A 2026-04-29. Phase B produces v3+.

---

## 6. CLI design — `case_briefing_cli.py`

```bash
# Full pipeline (interactive)
python -m backend.scripts.case_briefing_cli compose --case-slug 7il-v-knight-ndga-ii

# Single section
python -m backend.scripts.case_briefing_cli section --case-slug 7il-v-knight-ndga-ii --section 04

# Re-assemble from saved sections (after operator edits)
python -m backend.scripts.case_briefing_cli assemble --case-slug 7il-v-knight-ndga-ii --version 3

# Show curated grounding packet (read-only audit)
python -m backend.scripts.case_briefing_cli inspect --case-slug 7il-v-knight-ndga-ii
```

---

## 7. Test surface

`backend/tests/test_case_briefing_compose.py`:

| test | covers |
|---|---|
| `test_stage_0_curate_clusters_by_mime` | mime-type clustering + dedup with mocked vault rows |
| `test_stage_1_grounding_packet_contains_privileged_flag` | privilege flag set when privileged chunks retrieved |
| `test_stage_2_mechanical_section_01` | deterministic template populates correctly |
| `test_stage_2_synthesis_section_04_calls_brain` | BRAIN client called with streaming, grounded prompt |
| `test_stage_2_grounding_citation_enforcement` | section with <3 citations gets FAIL_GROUNDING |
| `test_stage_2_section_07_excludes_defense_counsel` | privilege filter enforced |
| `test_stage_4_assembly_appends_fyeo_warning` | FYEO if contains_privileged anywhere |
| `test_stage_4_version_increment` | v1 + v2 exist → produces v3 |
| `test_full_pipeline_dry_run_with_mocks` | Stage 0 → 4 with all external services mocked |
| `test_cli_compose_command` | argparse + dispatch to orchestrator |
| `test_cli_inspect_shows_packet` | inspect mode read-only output |
| `test_cli_assemble_from_saved_sections` | re-assembly after operator edit |

All tests mock `BrainClient`, Qdrant, Postgres, NAS reads. No real spark-5 connectivity required for tests.

---

## 8. Dry-run on Case II — produces v3 brief

After tests pass + PR opens, run:

```bash
python -m backend.scripts.case_briefing_cli compose \
  --case-slug 7il-v-knight-ndga-ii \
  --auto-accept-mechanical \
  --output /tmp/phase-b-dry-run-v3.md 2>&1 | tee /tmp/phase-b-dry-run.log
```

`--auto-accept-mechanical` means sections 01, 03, 06, 10 auto-accept (operator can review later). Sections 02, 04, 05, 07, 08 still pause for operator review. Section 09 stays operator_written placeholder.

Capture the dry-run output as PR appendix. Do NOT commit dry-run brief to NAS canonical path — it's a dry-run, not a publish.

PR description includes:
- Dry-run latency per section (TTFT, total)
- Grounding citations per synthesis section
- contains_privileged flag final state
- Time budget vs Track A v2 (Phase B should be faster than overnight session)

---

## 9. Hard constraints

- **DO NOT** write to NAS canonical filings/outgoing/ during dry-run (dry-run goes to /tmp)
- **DO NOT** modify `legal_council.py` (separate Council consumer-cutover PR)
- **DO NOT** modify `freeze_context` or `freeze_privileged_context` — read-only consumer
- **DO NOT** ingest new vault evidence
- **DO NOT** write to any Qdrant collection or Postgres table
- **DO NOT** open more than one PR
- **DO NOT** use cloud models — all synthesis goes through BrainClient (post-cutover sovereign)
- **DO NOT** include defense counsel correspondence in Section 7 (privilege filter required)
- **DO NOT** ship without grounding citation enforcement (every synthesis claim must cite)
- On any STOP condition (BRAIN unreachable, retrieval returns 0 chunks for synthesis section, dry-run produces token salad): commit code as far as it works, surface, do not push partially-broken pipeline

---

## 10. Definition of done

- Branch + PR opened
- All 12+ tests in `test_case_briefing_compose.py` PASS
- Dry-run on `7il-v-knight-ndga-ii` produces output at `/tmp/phase-b-dry-run-v3.md`
- Grounding citations enforced (each synthesis section has ≥3)
- Section 7 excludes defense counsel (privilege filter test passes)
- FYEO warning appended when contains_privileged
- Operator runbook committed
- PR description includes dry-run summary
- PR merge BLOCKED on operator review

---

## 11. Closing report

When PR is open:

| Item | Result |
|---|---|
| Branch + PR number + URL | |
| Tests | N/12+ passing |
| Dry-run output path | |
| Section 02 grounding citations | N |
| Section 04 grounding citations | N |
| Section 05 grounding citations | N |
| Section 07 grounding citations | N |
| Section 08 grounding citations | N |
| Section 07 defense counsel excluded | yes/no |
| FYEO warning | appended/not_needed |
| BRAIN streaming all calls | yes/no |
| Time elapsed | |

PR title: `Phase B: drafting orchestrator (case_briefing_compose.py)`

Mark "merge BLOCKED on operator review."

---

End of brief.
