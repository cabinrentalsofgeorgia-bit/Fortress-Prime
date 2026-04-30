# Track A v3 Case I Full Re-Run — Phase 3

**Branch:** `feat/synthesizer-per-section-reasoning-routing-2026-04-30` (stacked on PR #331)
**Date:** 2026-04-30
**Stacks on:** PR #326 (BrainClient TP=2 Path X), PR #327 (synthesizer cap 8000), PR #329 (Track A v3 analysis baseline), PR #330 (Phase 1 reasoning-control probes), PR #331 (Phase 2 BrainClient wiring + §4 stress test).
**Frontier load consumed:** ~16 minutes wall across two full Track A runs + one §5 isolation probe. Frontier health 200 throughout. No soak halts.

This is Phase 3 of the [4-phase TP=2 stabilization plan](../../nemotron-3-super-tp2-stabilization-4-phase-plan-v2-2026-04-30.md). Applies per-section reasoning policies through the BrainClient surgery shipped in PR #331. Closes Issue #328 with empirically-validated mechanism.

---

## 1. Per-section policy (post-Phase 3 §5 isolation)

| Section | Mode | enable_thinking | low_effort | max_tokens | Rationale |
|---|---|---|---|---:|---|
| §1 Case Summary | mechanical | — | — | — | deterministic, no LLM |
| §2 Critical Timeline | synthesis (recovered) | False | — | 4000 | categorization; reasoning suppression recovers content |
| §3 Parties & Counsel | mechanical | — | — | — | deterministic |
| §4 Claims Analysis | synthesis | True | True | 8000 | doctrinal; low_effort drives 97.6% reasoning reduction without quality loss |
| §5 Key Defenses | synthesis | True | **False** | 8000 | doctrinal; low_effort drops the non-affirmative denial subsection — see §3 below |
| §6 Evidence Inventory | mechanical | — | — | — | deterministic |
| §7 Email Intelligence | synthesis (recovered) | False | — | 4000 | categorization |
| §8 Financial Exposure | synthesis | True | True | 4000 | light reasoning |
| §9 Strategy (augmented) | LiteLLM passthrough | True | True | 8000 | doctrinal; via post-run §9 augmentation in runner |
| §10 Filing Checklist | mechanical | — | — | — | deterministic |

**The §5 deviation from the original plan table** is the single empirical finding from Phase 3 — see §3.

---

## 2. Per-section results vs PR #329 19:45Z baseline

| Section | Baseline content | New content | Δ% | Baseline reasoning | New reasoning | Baseline wall | New wall | Baseline grounding | New grounding | finish |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| §1 mechanical | 511 | 511 | 0% | 0 | 0 | n/a | n/a | 0 | 0 | n/a |
| **§2** synthesis | **0** | **4,659** | **recovered** | 71,294 | **0** | 840s | **73s** | 0 | **19** | length → **stop** |
| §3 mechanical | 509 | 509 | 0% | 0 | 0 | n/a | n/a | 0 | 0 | n/a |
| §4 claims | 7,818 | 10,074 | +28.86% | 21,656 | 527 | 306s | 126s | 4 | 4 | stop |
| **§5** defenses | 6,271 | 6,271 | **0%** | 19,090 | **19,090** | 269s | **270s** | 5 | **5** | stop |
| §6 mechanical | 1,376 | 1,376 | 0% | 0 | 0 | n/a | n/a | 0 | 0 | n/a |
| **§7** intel | **0** | **3,395** | **recovered** | 73,407 | **0** | 835s | **58s** | 0 | **17** | length → **stop** |
| §8 financial | 3,565 | 4,082 | +14.51% | 7,488 | 1,162 | 126s | 63s | 4 | 2 | stop |
| §9 augmented | 5,312 | 6,563 | +23.55% | 0 | 208 | 108s | 71s | n/a | n/a | stop |
| §10 mechanical | 611 | 611 | 0% | 0 | 0 | n/a | n/a | 0 | 0 | n/a |

**Total wall: 589.68s (9.83 min) vs baseline 2,377s (39.6 min). −75.2% reduction.**

**Format compliance:** all 11 emitted slots `format_compliant=true`. Zero first-person bleed. Zero `<think>` leakage. Issue #328 fully resolved.

---

## 3. The §5 isolation probe and per-section policy split

### What happened on the first Phase 3 run

The original plan table specified `enable_thinking=True, low_effort=True` for all four "doctrinal" sections (§4, §5, §8, §9). On the first full Track A run, §5 came back at:

- content_chars: 4,157 (vs baseline 6,271 — **−33.74%**)
- reasoning_chars: 260 (vs baseline 19,090 — −98.6%)
- wall: 44s (vs baseline 269s)
- grounding citations: 3 (vs baseline 5)

Hard stop §5 of the plan ("§4/§5/§8 regression — content_chars drops >10% from baseline") tripped on §5. Reading the §5 markdown side-by-side with baseline showed the cause: `low_effort=True` made the model **consolidate overlapping affirmative defenses and drop the entire "Non-affirmative defense theories (denials)" subsection** (4 explicit denial entries: denial of specific performance, denial of breach of warranty, denial of misrepresentation, denial of damages).

This is content the brief is supposed to deliver. Defense lawyers enumerate denials on the record because they have to; quietly dropping the denial table ships a structurally incomplete brief.

### The probe

Re-routed §5 only with `enable_thinking=True, low_effort=False`. Single 270s probe against the same prompt:

| Metric | Phase 3 run 1 (low_effort=True) | Probe (low_effort=False) | 19:45Z baseline |
|---|---:|---:|---:|
| content_chars | 4,157 | **6,271** | 6,271 |
| reasoning_chars | 260 | **19,090** | 19,090 |
| wall_seconds | 44 | **270.2** | 268.93 |
| Affirmative defenses | merged 7 rows | **7 rows** | 7 rows |
| Non-affirmative denials | **DROPPED** | **4 rows present** | 4 rows |
| Unique citations | 1 | **4** | 4-5 |
| finish | stop | stop | stop |

Probe result: **byte-identical to PR #329 baseline.** §5 has its own policy entry now: `enable_thinking=True, low_effort=False`. §4/§8/§9 stay on `low_effort=True`.

### Why §5 differs from §4 mechanically

PR #331's three-run §4 isolation showed `low_effort=True` produced *more* content with *better* organization on §4 (5 explicit causes, ASCII brackets replacing CJK quirk). On §5, the same knob produced *less* content and *dropped a structural subsection*. The shared mechanism: under low-effort thinking, the model compresses overlapping themes. On §4 (claims), distinct causes of action have minimal overlap, so compression doesn't hurt. On §5 (defenses), several affirmative defenses share underlying facts (encroachment caused all of "lapse", "impossibility", "plaintiff refused to close") — compression collapses them. And the non-affirmative-denial framework is a separate structural section that the compressed-thinking pass apparently doesn't deem worth the second table.

This is real Wave 4 prompt-tuning input: **`low_effort=True` is appropriate for sections where the prompt itself enumerates distinct categories. It's contraindicated where the prompt expects multiple structural subsections that the model could decide to merge.** §5's prompt asks for "affirmative AND non-affirmative" — the latter is the subsection at risk.

A future prompt-tuning pass could rewrite §5's prompt to split into two LLM calls (one per subsection), each with `low_effort=True`. That would recover the wall savings and keep coverage. Out of scope for this PR.

---

## 4. Wave 4 prompt-tuning observations

Three empirical findings worth capturing for future tuning work:

1. **The +29% content delta on §4 is chat-template engagement, not regression.** PR #331 attributed it to `low_effort=True` engaging the chat template. The model produces more thorough enumeration (5 explicit causes vs baseline's narrative coverage) with idiomatic ASCII brackets `[...]` replacing the baseline's CJK fullwidth `【...】` quirk. The CJK bracket flip suggests the unbounded reasoning trace was leaking non-English typographic conventions into the output — a sign that 5,414 reasoning tokens were drifting the model's formatting style. With reasoning bounded to ~132 tokens, formatting snaps back to standard English legal conventions.

2. **`low_effort=True` compresses overlapping themes (§5 finding).** Sections whose prompt asks for distinct categories work fine; sections whose prompt expects multiple structural subsections risk losing the secondary subsection. §5 vs §4 is the natural experiment: same model, same `low_effort=True`, opposite content shape because the underlying task structure differs.

3. **§9 augmentation now captures reasoning_content via LiteLLM.** Phase 2 BrainClient added dual response-shape parsing. Phase 3 updated the runner's §9 augmentation payload to include `chat_template_kwargs={enable_thinking: True, low_effort: True}` and to read `message.reasoning_content` first. Result: §9 produces +23.55% content (6,563 vs baseline 5,312) with 208 chars of reasoning captured for the first time. Previously the augmentation reported reasoning_chars=0 because the field was missed entirely.

---

## 5. Hard-stop check

| Hard stop from plan Phase 3 | Status | Note |
|---|---|---|
| §1 — `case_briefing_synthesizers.py` dispatch surface not located | PASS | dispatch via `SECTION_REASONING_POLICY` lookup in `stage_2_synthesize` |
| §2 — frontier `/health` non-200 sustained >60s | PASS | 200 throughout |
| §3 — soak halt event | PASS | not observed |
| §4 — §2 OR §7 still 0 content_chars with `enable_thinking=False` | PASS | §2 = 4,659 chars; §7 = 3,395 chars |
| §5 — §4/§5/§8 regression (content drops >10% from baseline OR finish flips to length) | PASS (after §5 re-route) | §4 +28.86%, §5 0.0% (post-fix), §8 +14.51%; all finish=stop |
| §6 — disk full | PASS | 1.3T avail |

§5's first-run drop tripped the hard stop letter. Surfaced to operator. Three options weighed (accept as Wave 4 future-fix; halt entirely; isolate §5 with no low_effort). Operator chose isolation. Probe took ~5 min frontier wall and gave a clean answer: §5 needs its own policy entry. Per-section table grew by one row. This is the Phase 3 working pattern — empirical isolation when an aggregate result trips, not blanket policy adjustment.

---

## 6. Frontier health log

```
Phase 3 run 1 pre:    200 (2026-04-30T22:26:59Z)
Phase 3 run 1 post:   200 (after 365s wall)
§5 probe pre:         200
§5 probe post:        200 (after 270s wall)
Phase 3 final pre:    200 (2026-04-30T22:44:03Z)
Phase 3 final post:   200 (after 590s wall)
```

No soak halt events. KV cache pressure not tripped (`--max-num-seqs 10` not saturated at single-call cadence).

---

## 7. v3 brief on NAS

**Path:** `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_I_v3_20260430T224403Z.md`
**Size:** 40,170 bytes (vs 19:45Z baseline 28,011 bytes — +43%).

This is the first 10/10-section v3 brief — §2 and §7 finally populated with content for the first time since Issue #328 was filed.

The brief is NOT in the repo (per Track A convention — briefs land on NAS, code+report+metrics in repo).

---

## 8. Issue #328 resolution

PR #329 reframed §2/§7 from "missing source data" (the original #328 framing) to "runaway reasoning" failure mode. PR #330 (Phase 1) confirmed `enable_thinking=False` was the empirical fix. PR #331 (Phase 2) wired the kwarg into BrainClient. This PR (Phase 3) applies it per-section.

Result: §2 (Critical Timeline) and §7 (Email Intelligence) both produce structured tabular content with 19 and 17 grounding citations respectively, finish=stop, ≤73s wall. Failure mode was never source data, never alias routing — it was the absence of a control mechanism for thinking depth on the Nemotron-3-Super chat template.

**Closes #328.**

---

## 9. What changed (code surface)

- `fortress-guest-platform/backend/services/case_briefing_synthesizers.py`
  - Added `SECTION_REASONING_POLICY: dict[str, dict]` mapping per-section reasoning kwargs.
  - `synthesize_synthesis_section` now accepts `enable_thinking` and `low_effort` parameters (and passes them through to `brain_client.chat`).
- `fortress-guest-platform/backend/services/case_briefing_compose.py`
  - `stage_2_synthesize` looks up `SECTION_REASONING_POLICY[section_id]` and passes the policy as kwargs to the synthesizer.
- `fortress-guest-platform/backend/scripts/track_a_case_i_runner.py`
  - `MetricCapturingBrainClient.chat` accepts the Phase 2 reasoning kwargs and passes them through to `super().chat`.
  - Captures `reasoning_chars`, `finish_reason`, `enable_thinking`, `low_effort`, `thinking_token_budget` in `metrics_log`.
  - `post_run_section_9_augmentation` payload upgraded with `chat_template_kwargs={enable_thinking:True, low_effort:True}` + `max_tokens` raised 5000 → 8000. Reasoning extraction now prefers `message.reasoning_content` (LiteLLM shape) before `message.reasoning` (direct vLLM shape).

No changes to BrainClient (correct as of Phase 2). No changes to LiteLLM, frontier, or any service.

---

## 10. References

- PR #326 — BrainClient TP=2 Path X (Defect 3 reasoning_effort/thinking now deprecated per Phase 2)
- PR #327 — synthesizer cap 8000 (unchanged)
- PR #329 — Track A v3 analysis (baseline; superseded as canonical baseline by this run)
- PR #330 — Phase 1 reasoning-control probes (decision matrix)
- PR #331 — Phase 2 BrainClient wiring (top-level chat_template_kwargs, deprecation, dual response-shape parsing, §4 stress test)
- vLLM bugs [#39103](https://github.com/vllm-project/vllm/issues/39103), [#39573](https://github.com/vllm-project/vllm/issues/39573), [#25714](https://github.com/vllm-project/vllm/issues/25714) — confirmed not exposed on this build (PR #330 inventory)

**Resolves #328.**
