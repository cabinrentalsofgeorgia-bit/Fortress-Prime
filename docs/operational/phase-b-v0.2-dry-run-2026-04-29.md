# Phase B v0.2 Dry-Run — 2026-04-29 (synthesizer ``<think>``-block stripping, Pass 1 only)

**Driver:** Phase B v0.1 dry-run (PR #302) produced Outcome B — pipeline worked end-to-end but output contained 9 leaked ``<think>...</think>`` blocks. v0.2 strips them at the synthesizer level before SectionResult finalize.
**Stacks on:** PR #302 (v0.1 dry-run), PR #290 (Phase B orchestrator).
**Branch:** `feat/phase-b-v02-synthesizer-stripping-2026-04-29`.
**Outputs (dry-run, NOT canonical filings/outgoing/):**
- `/tmp/phase-b-7il-v-knight-ndga-i/Attorney_Briefing_Package_*.md`
- Staged at `/mnt/fortress_nas/legal-briefs/7il-v-knight-ndga-i-v3-2026-04-29.md` (md5 `7d2b0c75cd3bc7922bc8839f3c03b0b6`)
- Outcome-b v3 preserved at `/mnt/fortress_nas/legal-briefs/7il-v-knight-ndga-i-v3-outcome-b-2026-04-29.md` (md5 `bce8484bec36c55095db5a86d8dfa037`)

## Implementation

**`backend/services/case_briefing_synthesizers.py`** — added `strip_reasoning_trace(text: str) -> str`. Single-pass strip + cleanup:

- `<think>...</think>` blocks: non-greedy multiline regex (`re.DOTALL`); anchors on the nearest `</think>`, never document end.
- Unclosed `<think>` (truncated trace): strip from `<think>` to next blank line OR end of text.
- Cleanup: collapse 3+ consecutive newlines to 2; trim leading/trailing whitespace.
- **Pass 2 (first-person planning prose) is intentionally NOT implemented** — deferred per brief; the strategy will likely target synthesizer system prompts upstream rather than post-hoc heuristic filtering.

Integration: `synthesize_synthesis_section()` is the single call site. Strip is applied immediately after streamed-response accumulation, before `_detect_grounding_citations()` and `SectionResult` build.

**8 unit tests** in `backend/tests/test_case_briefing_synthesizers.py` (`TestStripReasoningTrace`):

1. `test_strips_simple_think_block` — basic inline tag pair
2. `test_strips_multiline_think_block` — real PR #302 §2 fixture
3. `test_strips_multiple_think_blocks` — three blocks, three closures
4. `test_handles_unclosed_think_tag` — truncated trace, blank-line terminator
5. `test_preserves_substantive_body_prose` — clean input no-op
6. `test_collapses_excess_newlines` — 3+ → 2
7. `test_idempotent` — running twice equals running once
8. `test_preserves_first_person_outside_think` — pin Pass 2 not-implemented contract

All 8 pass.

## Execution

| Field | Value |
|---|---|
| Started | 2026-04-30T02:39:38Z |
| Finished | 2026-04-30T03:19:03Z |
| Total elapsed | **39 min 25 sec** |
| Sections produced | 10 / 10 |

## HARD PASS gate

| Check | Result |
|---|---|
| `<think>` count in new v3 | **0** ✓ |
| `</think>` count in new v3 | **0** ✓ |
| 10/10 sections produced | ✓ |
| §7 defense-counsel exclusion (Underwood, Podesta, FGP, Sanker, Argo, DRAlaw) | **0 hits** ✓ |
| FYEO marker | **absent** ✓ (Case I has 0 privileged chunks) |
| Cloud outbound during run (strict — `api.anthropic.com` / `api.openai.com` / `generativelanguage.googleapis.com` / `api.x.ai`) | **0** ✓ |
| Grounding citations ≥3 per synthesis section | **FAIL — §4 has only 2 citations** (below floor) |

**HARD PASS gate: FAIL.** §4 below ≥3 citation floor.

## Per-section citation counts (vs PR #302 outcome-b)

| Section | Type | v0.2 lines | v0.2 citations | Outcome-b raw | Outcome-b post-strip (body only) |
|---|---|---:|---:|---:|---:|
| 1 Case Summary | mechanical | 43 | 0 | 0 | 0 |
| 2 Critical Timeline | synthesis | 74 | **38** | 18 | 4 |
| 3 Parties & Counsel | mechanical | 18 | 0 | 0 | 0 |
| 4 Claims Analysis | synthesis | 24 | **2** ← FLOOR FAIL | 21 | 4 |
| 5 Key Defenses | synthesis | 38 | **8** | 18 | 7 |
| 6 Evidence Inventory | mechanical | 26 | 0 | 0 | 0 |
| 7 Email Intelligence | synthesis | 93 | **40** | 22 | 8 |
| 8 Financial Exposure | synthesis | 48 | **12** | 28 | 10 |
| 9 Recommended Strategy | placeholder | 10 | 0 | 0 | 0 |
| 10 Filing Checklist | mechanical | 23 | 0 | 0 | 0 |

**Critical insight from outcome-b post-strip column:** the apparent "21 citations" in PR #302 §4 was inflated by in-`<think>` reasoning ("Looking at [#13 Joint Preliminary Statement.pdf]..."). The body content of outcome-b §4 had only **4 citations** once `<think>` was stripped retroactively. v0.2's §4 produced only **2 body citations** — run-to-run variance plus mid-sentence truncation (BRAIN's `max_tokens=2000` was hit before §4 finished its second plaintiff count).

In other words: §4 was always thin in body content. v0.2 just makes it visible. The strip is not "eating" citations — citations weren't there.

## Measurement (no gate, report only)

| Metric | Outcome-b | v0.2 | Δ |
|---|---:|---:|---:|
| Lines | 557 | 384 | **-31%** |
| Bytes | 46,097 | 24,950 | **-46%** |
| Words | 6,683 | 3,532 | **-47%** |
| First-person planning prose hits (line-start `Let me / I should / I need to / I'll / Now, / Looking at`) | 22 | **6** | **-73%** |
| `<think>`/`</think>` tag pairs | 9 | **0** | **-100%** |

The 6 surviving first-person hits are all on body lines starting with "Looking at [filename.pdf]..." — the model's natural prose voice when introducing evidence. These are not pure planning ("Let me structure...") but evidence-introducing prose ("Looking at [X.pdf], there's a mention of..."). Pass 2 stripping would risk eating substantive analysis. Per brief, Pass 2 is deferred.

## Cloud egress, sovereignty, and §7 privilege filter

- Cloud egress during run window (22:39:00–23:20:00 EDT): **0 hits** for `api.anthropic.com` / `api.openai.com` / `generativelanguage.googleapis.com` / `api.x.ai`.
- §7 defense-counsel exclusion: **0 hits** for Underwood, Podesta, FGP, Sanker, Argo, DRAlaw — privilege filter holds.
- FYEO: correctly absent (Case I has 0 privileged chunks).

## Sample stripped sections (3 examples, trace removed, substantive content preserved)

### Example 1 — §2 Critical Timeline header

**Outcome-b (lines 33-38):**

```
## 2. Critical Timeline

<think>
Okay, let's tackle this. The user wants a chronological timeline of dated events for the case, using only the provided evidence. I need to go through each of the CASE EVIDENCE blocks and extract any dates mentioned, then organize them in order.

First, I'll start by scanning each document for dates. Let's go one by one.
```

**v0.2 (clean):**

```
## 2. Critical Timeline

| Date | Event | Source |
|---|---|---|
```

### Example 2 — §5 Key Defenses, between thinking and substantive prose

**Outcome-b (lines 247-252):**

```
_Grounding citations: 7_

<think>

So, compiling the list with citations and noting if any are thin. The main defenses are failure of condition precedent, plaintiff's breach, contract expiration, and unjust enrichment...
</think>
```

**v0.2 (clean — moves directly to substantive analysis):**

```
_Grounding citations: 7_

### Affirmative Defenses & Non-Affirmative Theories

#### **1. Failure of Condition Precedent**
```

### Example 3 — Citations preserved verbatim

Substantive prose with file-reference citations (`[#13 Joint Preliminary Statement.pdf]`, `[5464474_Exhibit_3_GaryKnight(23945080.1).pdf]`) is preserved exactly across both runs. The strip never touches `[*]` regions.

## Recommendation

**Outcome: Pass-1 strip works as specified, but reveals a body-density problem.** The strip itself is correct (8/8 tests pass; tag-only; deterministic). The problem is that BRAIN's `max_tokens=2000` budget was always being half-consumed by `<think>` reasoning, leaving the body short — and §4 of this run truncated mid-sentence (`- **`) before reaching the 3-citation floor.

**Recommended v0.3 scope (separate brief):** target the synthesizer system prompts and/or BRAIN call params:

1. **Reduce reasoning volume** — modify `_SYSTEM_PROMPT` in `case_briefing_synthesizers.py` (currently begins `"detailed thinking on\n\n"` per Nemotron contract) to either omit the trigger phrase or constrain reasoning to N tokens.
2. **Increase body budget** — bump `synthesize_synthesis_section`'s `max_tokens` from 2000 → 3500 (or split: budget reasoning separately from response).
3. **Tighten body-output instructions** — current prompt asks for "elements / defense theory / citations"; could be tightened to "MINIMUM 5 citations per count; one paragraph max per element" so the model spends body tokens efficiently.

**Whether to merge this PR:**
- The stripper is sound — gets shipped on its own merits (8/8 tests, deterministic, idempotent).
- Merging means accepting that the body-density issue is now visible (and §4 trips the ≥3 floor on this run).
- Operator decision: merge + iterate on v0.3, OR hold v0.2 until v0.3 lands (so a clean v3 brief is the merge gate).

## Outcome

**B (still issues — body density / max_tokens) → v0.3 prompt-fix recommended before Case II run.**

## Cross-references

- Brief: pasted v0.2 instructions (Pass 1 only) in this session
- v0.1 dry-run analysis: `docs/operational/phase-b-v0.1-dry-run-2026-04-29.md` (PR #302)
- Phase B orchestrator: `fortress-guest-platform/backend/services/case_briefing_compose.py` (PR #290)
- BRAIN model contract: `CLAUDE.md` DEFCON 3 / BRAIN tier ("All callers MUST supply a system prompt e.g. 'detailed thinking on'")
