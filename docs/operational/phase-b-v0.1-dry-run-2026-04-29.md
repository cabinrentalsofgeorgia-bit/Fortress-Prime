# Phase B v0.1 Dry-Run — 2026-04-29

**Driver:** PR #290 ships orchestrator; this dry-run proves end-to-end pipeline.
**Test target:** `7il-v-knight-ndga-i` (Case I — closed 2:21-CV-00226, judgment against).
**Output (dry-run, NOT published to canonical filings/outgoing/):** `/tmp/phase-b-7il-v-knight-ndga-i/Attorney_Briefing_Package_7IL_Properties_LLC_v_Knight_Case_I_v1_20260429.md` + staged copy at `/mnt/fortress_nas/legal-briefs/7il-v-knight-ndga-i-v3-2026-04-29.md` (md5 `bce8484bec36c55095db5a86d8dfa037`).
**Branch:** `feat/phase-b-v01-case-i-dry-run-2026-04-29`

## Pre-flight

Carrying forward from PR #299 pre-flight checklist (PARTIAL_FAIL — BRIEF DRIFT, functional ALL_PASS):

- BRAIN sovereign route: PASS (HTTP 200; 4 legal-* aliases on `localhost:8002`)
- Cloud egress (3-min window before run): 0 hits in `litellm-gateway` journal ✓
- Phase B import: PASS via `backend.services.case_briefing_compose.compose`
- Phase B CLI: PASS (`backend.scripts.case_briefing_cli {inspect, compose, assemble}`)
- Case I `inspect` packet (run 2026-04-29 21:36 EDT, 3 sec):
  - vault_documents_count: **820**
  - work_product_chunks: **30**
  - privileged_chunks: **0** → `contains_privileged: false` (FYEO must be ABSENT)
  - related_matters: `["7il-v-knight-ndga-ii"]`
  - curated_clusters: contracts 21, correspondence 6, depositions 17, exhibits 80, filings 38, inspections 7, other 614

## Execution

`python3 -m backend.scripts.case_briefing_cli compose --case-slug 7il-v-knight-ndga-i --dry-run` (the CLI is non-interactive by design — no `--auto-accept-mechanical` or `--non-interactive` flag needed; brief drift item).

| Field | Value |
|---|---|
| Started | 2026-04-30T01:37:37Z |
| Finished | 2026-04-30T02:17:43Z |
| Total elapsed | **40 min 6 sec** |
| Sections produced | 10 / 10 |
| Output file size | 46,097 bytes (557 lines) |

Per-section TTFT/token counts not captured: orchestrator emits a terse stdout summary (`sections_count`, `contains_privileged`, `vault_documents`, `work_product_chunks`, `privileged_chunks` only — no per-section telemetry). LiteLLM gateway logs at startup only at default verbosity (no per-request timing). Per-section timing harvest would require either bumping LiteLLM `set_verbose=True` or adding instrumentation to `case_briefing_compose.py` (out of scope here).

| Section | Type | Lines | Citations |
|---|---|---:|---:|
| 1 Case Summary | mechanical | 43 | 0 |
| 2 Critical Timeline | synthesis | 79 | **18** |
| 3 Parties & Counsel | mechanical | 18 | 0 |
| 4 Claims Analysis | synthesis | 116 | **21** |
| 5 Key Defenses Identified | synthesis | 87 | **18** |
| 6 Evidence Inventory | mechanical | 26 | 0 |
| 7 Email Intelligence Report | synthesis | 81 | **22** |
| 8 Financial Exposure Analysis | synthesis | 87 | **28** |
| 9 Recommended Strategy | placeholder | 10 | 0 |
| 10 Filing Checklist | mechanical | 23 | 0 |
| **Total** | | **557** | **107** citations across 5 synthesis sections |

Citation format: `[filename.pdf]` with optional page reference (e.g., `[#13 Joint Preliminary Statement.pdf, p. 5]`).

## Validation

| Check | Result | Detail |
|---|---|---|
| Cloud outbound during run (strict — `api.anthropic.com` / `api.openai.com` / `generativelanguage.googleapis.com` / `api.x.ai`) | **PASS — 0 hits** | First-pass shell-script bug counted internal Python module path `litellm.llms.openai.common_utils.OpenAIError` as a match; corrected with strict URL patterns |
| Grounding citations ≥3 per synthesis section | **PASS** | All 5 synthesis sections far exceed the floor (18 / 21 / 18 / 22 / 28) |
| Section 7 defense-counsel exclusion (Underwood, Podesta, FGP, Sanker, Argo, DRAlaw) | **PASS** | 0 hits in §7 — privilege filter holds |
| FYEO warning behavior | **PASS** | Correctly absent (Case I has zero privileged chunks per inspect) |

## Synthesizer regression — `<think>` tag + model-planning leakage

**FAIL** — non-trivial reasoning-trace leakage in synthesis sections. Counts:

- 9 `<think>` / `</think>` tags survived assembly (lines 36, 133, 231, 249, 285, 362, 402, 443, 483)
- 22 instances of model first-person planning ("I should note", "user instruction", "user is asking", "I need to") in body text

Root cause: BRAIN model is `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8` (a reasoning model — emits `<think>...</think>` chain-of-thought blocks; CLAUDE.md note: "All callers MUST supply a system prompt e.g. `'detailed thinking on'` — the model returns garbled output without one"). The synthesizer (`case_briefing_synthesizers.py`) is not stripping these tags + planning prose before incorporating into the final brief.

Required fix (synthesizer-side, NOT a model issue):
- Strip everything between `<think>` and `</think>` (inclusive) before any text is appended to a `SectionResult`
- Optional belt-and-suspenders: regex-strip patterns like `^(I should|I need to|The user|Let me|Now, |So, )` lines that survived `</think>`-stripping

Filed as the v0.2 fix scope.

## Quality assessment

- **No Case I v2 brief exists** at `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/` — that directory is empty. Brief §5.4 assumed a v2 reference; reality is the v2 was for Case II (`Attorney_Briefing_Package_7IL_NDGA_II_DRAFT_v2_2026-04-29.md`, 692 lines / 64 KB).
- v3 length: 557 lines / 46 KB. Cross-case structural-only sanity check vs. Case II v2: ~80% of v2's length (Case I is the smaller closed matter; ratio is reasonable).
- Spot-check on §4 Claims Analysis: 21 citations across 4 plaintiff counts (Specific Performance, Breach of Contract, Breach of Warranty of Title, Negligent Misrepresentation), each with element-by-element analysis, defense-theory framing, and supporting/adverse evidence breakdown. White-shoe-grade structure when the model-reasoning leak is filtered.
- Operator review required for substance (factual accuracy, citation correctness, narrative quality). Automated quality grading on legal briefs is out of scope.

## Outcome

**OUTCOME B — Phase B v0.1 needs minor fixes.**

End-to-end pipeline works; sovereignty boundary holds; grounding citations strong; privilege filters hold; FYEO behavior correct. **Synthesizer post-processor is missing reasoning-trace stripping** — non-blocking for the pipeline itself but blocking for white-shoe-grade output (a top-3 firm reading "the user is asking..." mid-claim-analysis is unacceptable).

Scope of v0.2:
- Strip `<think>...</think>` blocks in `case_briefing_synthesizers.py` before each `SectionResult` is finalized.
- Belt-and-suspenders: optional second-pass cleanup of model-planning prose surviving stripping.
- Re-run dry-run on Case I → expect **OUTCOME A** then.

DO NOT proceed to Case II run until v0.2 lands.

## Cross-references

- Brief: `/home/admin/phase-b-v01-dry-run-brief.md`
- Pre-flight checklist (PR #299): `docs/operational/runbooks/phase-b-v01-preflight-checklist.md`
- Phase B orchestrator (PR #290): `fortress-guest-platform/backend/services/case_briefing_compose.py`
- Council retrieval (PR #289): `fortress-guest-platform/backend/services/legal_council.py`
- LiteLLM legal-* aliases (PR #285): `litellm_config.yaml`
- BRAIN model note: `CLAUDE.md` DEFCON 3 / BRAIN tier ("All callers MUST supply a system prompt e.g. 'detailed thinking on'")

---

End of dry-run analysis.
