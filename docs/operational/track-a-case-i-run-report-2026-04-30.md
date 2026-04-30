# Track A — Empirical Wave 4 build target identified

**Date:** 2026-04-30
**Branch:** `feat/track-a-phase-b-v01-case-i-dryrun-2026-04-30`
**Driver:** `docs/operational/track-a-phase-b-v01-case-i-dryrun-brief.md` — Phase B v0.1 dry-run on Case I (`7il-v-knight-ndga-i`)
**Stamp:** `20260430T174043Z`
**Wall:** 421.92 s (well under 60–80 min budget; halt-trigger fired early)

---

## Headline

**Frontier validated end-to-end.** Section 9 augmentation via LiteLLM `legal-reasoning` produced **4,578 chars of clean output, `finish_reason=stop`, format-compliant** — proving the spark-3 + spark-4 TP=2 endpoint serves Case I synthesis correctly when called with the right shape.

**Orchestrator-frontier integration gap surfaced and root-caused.** Phase B v0.1's `BrainClient` is structurally incompatible with the new TP=2 endpoint at three specific layers. All 5 LLM synthesis sections returned **0 bytes of content** with `finish_reason=length` — the §5.5 halt trigger fired.

**Run halted per brief §5.5; no auto-retry per operator decision (D).** This run *is* the deliverable: empirical Wave 4 build target.

---

## What worked

| § | Mode | Result |
|---|---|---|
| 1. Case Summary | mechanical (deterministic) | ✅ 511 B |
| 3. Parties & Counsel | mechanical (deterministic) | ✅ 509 B |
| 6. Evidence Inventory | mechanical (deterministic) | ✅ 1,376 B (783 docs across 7 clusters) |
| 9. Recommended Strategy (augmented) | LiteLLM `legal-reasoning` post-run | ✅ **4,578 B clean content; 4,663 B reasoning_effort=high; finish_reason=stop** |
| 10. Filing Checklist | mechanical (deterministic) | ✅ 611 B |

**Section 9 augmentation was the proof of frontier capability.** Same prompt shape as the orchestrator's synthesis sections, routed through LiteLLM with the `legal-reasoning` profile (reasoning_effort=high, max_tokens=5000, thinking=true): clean output, correctly-formatted recommendations with bracketed citations, no first-person bleed in content, no `<think>` leakage.

## What didn't work

| § | Mode | Result | finish_reason |
|---|---|---|---|
| 2. Critical Timeline | synthesis (LLM) via BrainClient | ❌ 0 B | length |
| 4. Claims Analysis | synthesis (LLM) via BrainClient | ❌ 0 B | length |
| 5. Key Defenses | synthesis (LLM) via BrainClient | ❌ 0 B | length |
| 7. Email Intelligence | synthesis (LLM) via BrainClient | ❌ 0 B | length |
| 8. Financial Exposure | synthesis (LLM) via BrainClient | ❌ 0 B | length |

5 of 5 synthesis sections via the orchestrator's BrainClient produced **no usable content**. The orchestrator's assembled file flagged each with `FAIL_GROUNDING: only 0 grounded citations; minimum required is 3`.

## Root cause — three structural defects in `BrainClient` vs `nemotron_v3`

### Defect 1: stream parser ignores `delta.reasoning` chunks

The vLLM endpoint with `--reasoning-parser nemotron_v3` emits stream chunks with a custom `reasoning` field, NOT the standard OpenAI `content` field, **for the entire reasoning trace until max_tokens is hit**. Sample chunks (verbatim from `evidence/vllm-stream-sample-delta-reasoning.txt`):

```
data: {..."choices":[{"delta":{"reasoning":"We"}}]}
data: {..."choices":[{"delta":{"reasoning":" need"}}]}
data: {..."choices":[{"delta":{"reasoning":" to"}}]}
data: {..."choices":[{"delta":{"reasoning":" output"}}]}
...
data: {..."choices":[{"delta":{"reasoning":"\n\n"},"finish_reason":"length"}]}
```

`BrainClient._stream()` parses only `delta.content` (standard OpenAI). The reasoning chunks are silently consumed and discarded.

**Consumer impact:** the synthesizer's `async for chunk in iterator: response += chunk` accumulates an empty string. Section content in `SectionResult.content` is `""`. Grounding-citation detector finds 0 citations. `FAIL_GROUNDING` warning fires.

### Defect 2: default `max_tokens=2000` exhausted by reasoning trace alone

Synthesis prompts on Case I are ~9,600 input tokens (30 retrieval chunks). Reasoning traces on similar prompts measured ~2,000 tokens (per Phase 7 Section 5 smoke: `reasoning_chars=7,994` ≈ 2,000 tokens). With reasoning alone matching the cap, **content emission never starts** — the model is still emitting reasoning chunks when `finish_reason=length` truncates the response.

Synthesizer default at `case_briefing_synthesizers.py:205`: `max_tokens: int = 2000`.

### Defect 3: no mechanism to set `reasoning_effort` or `thinking` flags

BrainClient's `chat()` accepts `messages`, `max_tokens`, `temperature`, `stream`. There's no `reasoning_effort` parameter, no `chat_template_kwargs`, no `extra_body`. Consumers cannot route reasoning depth per section. The model's reasoning behavior is entirely server-side defaults.

LiteLLM's per-alias `extra_body.reasoning_effort` configs (Phase 9 Wave 2) are bypassed because BrainClient calls the vLLM endpoint directly, not through the gateway.

---

## Section 9 v3 vs v0.3.5 — the only valid synthesis comparison

The operator brief asked for "Section 9 v3 vs v0.3.5: the one valid synthesis comparison."

| | v0.3.5 baseline | v3 (Track A) |
|---|---|---|
| Generation method | orchestrator `operator_written` placeholder | orchestrator placeholder + LiteLLM `legal-reasoning` augmentation |
| Content | "[TO BE WRITTEN BY OPERATOR]" placeholder only | **4,578 chars of structured strategy recommendations** |
| Output tokens | 0 (placeholder) | ~1,150 (5,000 max_tokens budget; finish_reason=stop) |
| Recommendations | 0 (none generated) | 5 numbered recommendations with action / why-now / supporting-evidence / blocking-dependencies structure per recommendation |
| Citations in content | 0 | 3+ (bracketed-filename: `5464474_Exhibit_3_GaryKnight…`, `#64-6 Knight's Resp. to Roggs.pdf`, plus Case metadata reference) |
| Format compliance | n/a (placeholder) | ✅ no first-person bleed in content; no `<think>` leakage; `finish_reason=stop` |

**Verdict:** v3 Section 9 is **purely additive** — v0.3.5 had no Section 9 LLM output at all. There is no head-to-head; this is a new capability. Operator legal judgment determines whether the 5 recommendations meet counsel-hire quality.

The augmentation pattern (post-run LiteLLM call against `legal-reasoning` alias) is **the validated path** for Section 9 going forward, until BrainClient is fixed (P1 follow-up).

---

## Mechanical sections 1 / 3 / 6 / 10 — structural-only comparison

The orchestrator's `mechanical` mode runs deterministic Python (no LLM call) for these 4 sections. v0.3.5 also runs them through the same deterministic path. **v3 and v0.3.5 produce byte-identical output for mechanical sections** because the input data (case metadata, vault inventory, deadlines table) is unchanged between runs.

This is structural-comparison only. Not quality evidence about Super-120B vs Nano-9B.

---

## Citation density curve / synthesis quality probe — NOT GENERATED

Brief §6.3 + §6.4 expected per-section citation density curves and synthesis quality probes for sections 4 / 5 / 9. With 5 of 5 LLM synthesis sections returning empty content (due to Defect 1+2 above), there is no v3 data to plot against the v0.3.5 baseline.

The single exception: Section 9 augmentation, which has citation density data (3+ unique sources cited in 4,578 B; ~0.65 cites/1000 tokens). That's a single data point, not a curve.

The empirical curve the brief expected to produce is replaced by a more concrete Wave 4 finding: **fix BrainClient first, then the empirical curve becomes possible.**

---

## Soak impact

- Frontier endpoint health: 200 OK on `/health` immediately after run; subsequent hourly soak collector tick will confirm continued stability.
- TP=2 endpoint consumed ~7 min of Track A load (5 × 84 s synthesis sections + Section 9 augmentation 210 s). Each synthesis section consumed GPU time on reasoning chains that hit `max_tokens` — productive load (real usage) but produced no content.
- No soak halt triggers fired during run.
- Memory peak captured indirectly via next hourly soak entry; no OOM observed.

---

## Files / artifacts

### Committed in this PR

| Path | Purpose |
|---|---|
| `fortress-guest-platform/backend/scripts/track_a_case_i_runner.py` | Wrapper script that performed the run (compose() injection + Section 9 augmentation + metric capture) |
| `docs/operational/track-a-case-i-run-report-2026-04-30.md` | This report |
| `docs/operational/track-a-evidence-2026-04-30/run-summary.json` | Per-section scores + BrainClient call metrics + section modes |
| `docs/operational/track-a-evidence-2026-04-30/vllm-stream-sample-delta-reasoning.txt` | Raw vLLM stream chunks — proves Defect 1 (`delta.reasoning` not `delta.content`) |
| `docs/operational/track-a-evidence-2026-04-30/section-09-v3-augmented.md` | The one good v3 synthesis output |
| `docs/operational/track-a-evidence-2026-04-30/section-09-v0.3.5-baseline.md` | v0.3.5 placeholder for comparison |
| `docs/operational/track-a-evidence-2026-04-30/compose-output-with-fail-grounding.md` | Orchestrator's assembled file with `FAIL_GROUNDING` warnings preserved as honest documentation |

### On NAS (referenced, not committed)

- `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_I_v3_20260430T174043Z.md` — the assembled v3 brief (mostly mechanical + Section 9 augmentation; 5 sections empty as documented)

### On spark-2 RUN_DIR (preserved 30+ days, not committed)

- `/tmp/track-a-case-i-v3-20260430T174043Z/` — full run dir
- `/tmp/track-a-runner.log` — runner stdout/stderr

---

## Wave 4 build target

Two follow-up issues to file post-merge:

### Follow-up 1 — P1: Phase B BrainClient TP=2 frontier compatibility

| Field | Value |
|---|---|
| Title | Phase B BrainClient — TP=2 frontier compatibility (Wave 4 prerequisite) |
| Priority | **P1** (blocks Case II briefing on current orchestrator) |
| File touched | `fortress-guest-platform/backend/services/brain_client.py` |

Three structural defects (verbatim from this report):
1. `_stream()` parses `delta.content` only; `nemotron_v3` emits `delta.reasoning` chunks; reasoning silently discarded.
2. Default `max_tokens=2000` below reasoning-trace floor (~2,000 tokens reasoning alone; content needs more on top).
3. No `reasoning_effort` / `chat_template_kwargs.thinking` mechanism; per-section reasoning depth not routable.

Proposed fix scope:
- Modify `_stream()` to handle `delta.reasoning` chunks (separate accumulator, expose via response object alongside content)
- Bump default `max_tokens` to 8000 for synthesis calls
- Add `reasoning_effort` + `thinking` kwargs to BrainClient constructor and per-call override
- OR retire BrainClient entirely; have synthesizers route via LiteLLM aliases (Wave 6 endgame)

Test: existing Phase 7 smoke prompts on the new BrainClient should produce nonzero content with `finish_reason=stop`.

Empirical evidence: `docs/operational/track-a-evidence-2026-04-30/` (this PR).

### Follow-up 2 — P2: Phase B v0.1 → v0.4 frontier migration plan

| Field | Value |
|---|---|
| Title | Phase B v0.1 → v0.4 frontier migration plan |
| Priority | **P2** |

Track A finding: orchestrator's BrainClient is the integration gap, not the synthesizer prompts. Two paths:

**Path X — fix BrainClient (the issue above), keep v0.1 architecture, tune prompts incrementally.**
Faster to a working Case II brief on existing orchestrator. Tech debt: orchestrator still bypasses LiteLLM, no per-section alias differentiation.

**Path Y — retire BrainClient, route synthesizers via LiteLLM aliases.**
Aligns with Wave 6 NAT migration endgame. Slower; more code change. Cleaner architecture.

Operator decision required before Wave 4 spec finalizes.

---

## Halt triggers fired (per §5.5)

- `finish_reason=length` on **5 sections** (2, 4, 5, 7, 8) — halt fired immediately on first observation; Section 9 augmentation proceeded as compensating mechanism per D1 from operator pre-flight decisions; Run halted before any retry attempt per operator option (D).

No retry. No auto-fix. No orchestrator code touched.

---

## Operator decision points after review

- Lock the two follow-up issue titles + priorities (P1, P2 as drafted above)
- Pick Path X or Path Y (drives Wave 4 spec scope)
- Confirm Section 9 augmentation pattern is the interim path until BrainClient ships
- Decide whether to re-run Track A on Case I after BrainClient fix (or skip directly to Case II)

---

End of report.
