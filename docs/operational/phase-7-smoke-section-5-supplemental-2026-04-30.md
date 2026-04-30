# Phase 7 round 2 — Section 5 smoke (supplemental to nemotron-3-super-tp2-deployment.md)

**Date:** 2026-04-30 12:43–12:45 EDT
**Endpoint:** `http://10.10.10.3:8000/v1/chat/completions` (live, same TP=2 instance as Section 2 smoke)
**Driver:** Operator request — Section 2 (chronological extraction) cleared all 4 criteria. Section 5 (defenses / legal argument) is a structurally different task; Nano-9B v0.3.5 cleared it with 20 cites. Surface whether Nemotron-Super matches the structural floor on a non-chronology section before declaring lock-ready.

**Status:** **Mixed signal — 2/4 criteria pass, 2/4 fail.** Format compliance held; volume metrics (output tokens, citation count) below floor. Soak clock continues per operator directive.

---

## Run parameters

Same as Section 2 smoke:
- Prompt source: v0.3.5 case_briefing pipeline, `case_slug=7il-v-knight-ndga-i`, `section_id=section_05_key_defenses_identified`
- Captured via `/tmp/capture_section5_prompt.py` (same approach as Section 2)
- 30 work-product chunks, 0 privileged chunks (identical retrieval to §2; only the instruction template differs)
- User prompt: 24,795 chars; system prompt: 403 chars
- Endpoint: TP=2 nemotron-3-super at `http://10.10.10.3:8000/v1`
- Temperature 0.6, max_tokens 8192, stream=False

Section-5 instruction template (from `case_briefing_synthesizers.py`):
> "List the affirmative defenses + non-affirmative defense theories supported by the evidence. For each: cite the supporting chunks by bracketed filename. Flag any defense where the evidence is thin or contradicted."

## Acceptance criteria

| # | Criterion | Section 2 | Section 5 | Status |
|---|---|---|---|---|
| 1 | output_tokens ≥ 3000 | 5,560 | **2,771** | ❌ FAIL |
| 2 | citation count ≥ 18 (Nano-9B baseline 20) | 18 | **7** (3 unique sources) | ❌ FAIL |
| 3 | no first-person planning prose in `content` | 0 matches | **0 matches** | ✅ PASS |
| 4 | no `<think>` blocks in `content` | 0 | **0** | ✅ PASS |

## Metrics

| Metric | Value |
|---|---|
| Wall time | **117.07 s** (less than half of Section 2's 278.37s) |
| First byte | 117.07 s (stream=False) |
| Output tok/s | **23.68 tok/s** (faster than Section 2's 19.97 tok/s; closer to NVIDIA's 24 tok/s claim) |
| `prompt_tokens` | 9,610 |
| `completion_tokens` | 2,771 |
| `total_tokens` | 12,381 |
| `finish_reason` | **`stop`** (model voluntarily terminated; NOT max_tokens hit) |
| Content chars | 4,305 |
| Reasoning chars | 7,994 |

## Citation diagnostic — reasoning vs content

The model **considered 6 sources in reasoning but cited 3 in content**:

| Source | In reasoning | In content |
|---|---|---|
| `[#13 Joint Preliminary Statement.pdf]` | yes | **cited** |
| `[#5464474_Exhibit_3_GaryKnight(23945080.1).pdf]` | yes | **cited** |
| `[#64-6 Knight's Resp. to Roggs.pdf]` | yes | **cited** |
| `[#12 Defendant's Initial Disclosures.pdf]` | yes | **omitted** |
| `[#2022.01.04 Pl's Initial Disclosures.pdf]` | yes | **omitted** |
| `[#65-1 7IL's BIS MSJ.pdf]` | yes | **omitted** |

The 3 omitted sources weren't filtered by retrieval — they were considered, then **deliberately not cited** in the defense theories. This is a precision filter, not a recall failure of the retrieval pipeline.

## Output content (5 distinct defense theories, clean format)

The output is a markdown table + bullet recap. Defense theories identified:

1. **Defendant is entitled to damages under both agreements** (counter-claim) — sourced to `#13`
2. **Defendant is entitled to attorney's fees and costs** — flagged as **thin** ("evidence merely identifies this as a contested issue; no factual basis shown")
3. **No breach by Defendant** — Plaintiff's refusal to close due to encumbrance excuses performance — sourced to `#5464474`
4. **Failure of condition precedent** — access easements not prepared by licensed Georgia attorney — sourced to `#13` + `#64-6`; flagged as **thin** ("does not show whether the easements were in fact prepared")
5. **Agreement lapsed because the condition precedent was never satisfied** — sourced to `#5464474`

Output explicitly satisfies the prompt instruction "Flag any defense where the evidence is thin or contradicted" — the model called out theories #2 and #4 as evidentially weak.

## First 500 chars of content

```
**Affirmative defenses / non‑affirmative defense theories supported by the case evidence**

| Defense theory | How the evidence supports it | Supporting citations (bracketed filename) |
|----------------|-----------------------------|-------------------------------------------|
| **Defendant is entitled to damages under the 253 River Heights Road and 92 Fish Trap Road Agreements** (counter‑claim for damages) | The Joint Preliminary Statement lists this as a disputed issue that the defendant raises – i.e., the defendant contends it is owed damages under those agreements.
```

## Last 500 chars of content (clean ending)

```
…the lack of affirmative proof weakens the defense.

All other defenses listed above are directly grounded in factual assertions found in the evidence chunks.
```

## `usage` block (verbatim)

```json
{
  "prompt_tokens": 9610,
  "total_tokens": 12381,
  "completion_tokens": 2771,
  "prompt_tokens_details": null
}
```

## Three plausible interpretations (operator legal judgment required)

### (A) Nemotron-Super under-cites — needs prompt tuning

Defense memos benefit from broad citation density. The model is too aggressive in pruning sources from content. Fix: tune the Section-5 prompt template to demand "cite every chunk that even partially supports each theory" or similar. Lock NOT advisable until prompt-tuning sweep + retest.

### (B) Nano-9B over-cited; 7 is correct precision

Nano-9B's 20 cites included noise (citing chunks tangential to each theory). Nemotron-Super's 7 well-targeted cites are higher precision. The "≥18" floor was a Nano-9B-era heuristic; the right floor for a precision-targeting model may be 5–10. Lock IS advisable; floor should be revised, not the model.

### (C) Section 5 is structurally harder than chronology

Section 5 (analytical synthesis of defense theories) is a different cognitive task than Section 2 (chronological extraction of dated events). Volume metrics that work for §2 don't generalize. Lock advisable; smoke metrics should be section-type-specific.

## Operator decision needed

- (A) → halt lock + tune prompt + re-smoke Section 5
- (B) or (C) → lock-readiness unchanged; soak proceeds; metrics floor revised in deployment doc

Recommendation surfaced for **operator legal judgment**: read the defense memo, decide whether 5 theories with 7 well-targeted cites is acceptable for the counsel-hire path, or whether the legal team specifically needs broader sourcing. Format compliance is unaffected; this is purely a citation-density question.

## Format compliance — still strong

- ✅ 0 first-person planning in `content` (3 in `reasoning` field where they belong)
- ✅ 0 `<think>` blocks in `content` (parser separating cleanly)
- ✅ `finish_reason: stop` (not max_tokens hit; model voluntarily decided it was done)
- ✅ Clean markdown table + bullet recap structure

The Nano-9B failure mode (first-person bleed-through, `<think>` block leakage) is **NOT recurring** on Section 5. The deployment-level architectural decision (ADR-007) is unaffected; this round 2 surfaces a citation-density question, not a format-compliance regression.

---

## Files / artifacts

- Captured prompt: `/tmp/smoke-prompt-section5.json` (saved to disk on spark-2)
- Response: `/tmp/nemotron-super-smoke-section5.json` (with curl timing footer) + `.body.json` (parsed)
- Capture script: `/tmp/capture_section5_prompt.py`
- This evidence file (PR #321 supplemental, do not amend the original commit)

---

End of Section 5 smoke supplemental.
