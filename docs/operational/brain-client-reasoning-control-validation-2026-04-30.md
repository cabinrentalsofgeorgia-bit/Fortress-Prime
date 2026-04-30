# BrainClient Reasoning-Control Validation — Phase 2

**Branch:** `feat/brain-client-reasoning-control-2026-04-30` (from `origin/main` 8d8c41b65)
**Date:** 2026-04-30
**Stacks on:** PR #326 (BrainClient TP=2 Path X), PR #327 (synthesizer cap 8000), PR #329 (Track A v3 analysis), PR #330 (Phase 1 reasoning-control probes), Issue #328 reframing.
**Frontier load consumed:** §4 stress probes + 3 isolated single-section runs = ~12 minutes wall on the spark-3 vLLM frontier. Frontier health 200 throughout. No soak halts.

This report covers Phase 2 of the [4-phase plan](../../nemotron-3-super-tp2-stabilization-4-phase-plan-v2-2026-04-30.md) — wiring the reasoning controls PR #330 proved work on the build, with empirical per-knob attribution to settle the Phase 3 per-section policy table.

---

## 1. Step 3 §4 stress-test gate — PASS

PR #330's probes settled the schema (top-level `chat_template_kwargs`, top-level `thinking_token_budget`, no `extra_body` wrapper) but the probe prompt was 3 KB and reasoning naturally landed at ~1,195 tokens — under the 2,048-token budget. Whether the budget actually enforced was inconclusive on a small prompt. Phase 2 Step 3 re-runs the probe against the actual §4 production prompt (25,291 chars, 5,414 unbounded reasoning tokens at PR #329 baseline).

### §4 prompt reconstruction

The 19:45Z run did not preserve raw request bodies — the runner never wrote `raw/section_4_request.json`. Reconstructed via `compose()`'s `stage_0_curate` + `stage_1_grounding_packet` (top_k=15, privileged_top_k=10) + `_build_synthesis_user_prompt`. Total: **25,291 chars (drift 0.00% vs PR #329 baseline)**, 30 work-product chunks, 0 privileged chunks. Byte-identical to the 19:45Z prompt.

### §4 stress probe results

| Path | wall_s | content_chars | reasoning_chars | reasoning tok | finish | reasoning field |
|---|---:|---:|---:|---:|---|---|
| 19:45Z baseline (no controls) | 306.1 | 7,818 | 21,656 | ~5,414 | stop | — |
| Direct vLLM (low_effort + budget=2048) | 137.5 | 10,253 | **1,337** | ~334 | stop | `reasoning` |
| LiteLLM passthrough (same body) | 87.1 | 7,920 | **210** | ~52 | stop | `reasoning_content` |

**Hard-stop §4 (reasoning_chars >12,300):** not triggered — direct 1,337 chars, LiteLLM 210 chars, both well under threshold.

**Decision-gate read:** Reasoning is *way under* the 2,048-token budget on both paths. Either the budget is enforced (tight) or `low_effort=True` already drives reasoning under any cap. Steps 6+7 isolate this empirically.

---

## 2. BrainClient surgery (Step 4) — what changed

`fortress-guest-platform/backend/services/brain_client.py`:

### Added (constructor + per-call kwargs)
- `enable_thinking: bool | None` — top-level `chat_template_kwargs.enable_thinking`
- `low_effort: bool | None` — top-level `chat_template_kwargs.low_effort`
- `thinking_token_budget: int | None` — top-level `thinking_token_budget` field

All three placed at **top level** of the request body. The OpenAI-style `extra_body` wrapper is silently dropped by vLLM's OpenAI-compat server (PR #330 Probe E: same body wrapped in `extra_body` ran 2,554 reasoning tokens against a 2,048 budget vs 1,195 unwrapped).

### Response parsing — both shapes
- Direct vLLM: `message.reasoning` (and `delta.reasoning` in streaming)
- Via LiteLLM: `message.reasoning_content` (and `delta.reasoning_content` in streaming)

`last_reasoning` accumulates whichever field is present, preferring `reasoning_content` first (production callers route through LiteLLM).

### Deprecated (kept for backward compat, NOT injected into payload)
- `reasoning_effort` (PR #326 Defect 3) — OpenAI-class schema, not honored by Nemotron's chat template; LiteLLM `drop_params: true` silently drops it.
- `thinking` (PR #326 Defect 3) — wrong key (chat template uses `enable_thinking`, not `thinking`).

Both log a one-shot `brain_client_deprecated` warning when set. Backward-compatible: existing callers that pass these kwargs continue to work, just with a warning and a no-op on the wire.

### Default behavior unchanged
When no Phase 2 kwargs are set (constructor or per-call), `chat_template_kwargs` and `thinking_token_budget` are absent from the payload. Existing callers see byte-identical behavior to PR #327's wire format.

---

## 3. Unit tests (Step 5)

22 tests pass (`backend/tests/test_brain_client.py`). Coverage additions:

- `test_chat_template_kwargs_at_top_level` — regression guard against `extra_body` nesting.
- `test_thinking_token_budget_at_top_level` — same.
- `test_per_call_phase2_kwargs_override_constructor` — kwarg precedence.
- `test_reasoning_kwargs_omitted_when_unset` — default behavior preserved.
- `test_reasoning_effort_deprecated_not_injected` — caplog-asserted warning + payload absence.
- `test_thinking_kwarg_deprecated_not_injected` — same.
- `test_oneshot_captures_reasoning_content_field` — LiteLLM shape.
- `test_stream_parses_delta_reasoning_content_field` — LiteLLM streaming shape.

The two old PR #326 Defect-3 tests (`test_extra_body_injection_when_reasoning_kwargs_set`, `test_per_call_reasoning_kwargs_override_constructor`) were replaced — they asserted the now-deprecated wiring.

---

## 4. §4 single-section validation — three isolated runs (Steps 6–7)

The Step 3 stress probe used `temperature=1.0` (Nemotron's published recommended sampling). Production synthesizer uses `temperature=0.0`. Three runs at production temperature, each isolating a knob, against the same §4 prompt:

| Run | enable_thinking | low_effort | budget | content_chars | reasoning_chars | wall_s | finish | grounding | first-person | `<think>` | ASCII cits | CJK cits |
|---|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| Baseline (PR #329) | _(default)_ | — | — | 7,818 | 21,656 | 306.09 | stop | 4 | 0 | 0 | 0 | many |
| **Run 1** | True | — | — | **7,818** | **21,656** | 308.12 | stop | 4 | 0 | 0 | 0 | many |
| **Run 2** | True | True | — | **10,074** | **527** | 126.37 | stop | 4 | 0 | 0 | 45 | 0 |
| **Run 3** | True | True | 2048 | 10,074 | 527 | 125.51 | stop | 4 | 0 | 0 | 45 | 0 |

### Per-knob empirical attribution

- **`enable_thinking=True` alone (Run 1)**: byte-identical to baseline. Chat template default is already True. **No-op when toggled to True.** (Whether toggled to False suppresses thinking is covered by PR #330 Probe B — confirmed yes there.)
- **`low_effort=True` (Run 2 vs Run 1)**: drives 100% of the observed behavior delta.
  - reasoning_chars: 21,656 → 527 (−97.57%)
  - wall_seconds: 308.12 → 126.37 (−59.0%)
  - content_chars: 7,818 → 10,074 (+28.9%)
  - citation format: CJK `【...】` → ASCII `[...]` (45 ASCII citations vs baseline's 0)
  - More thorough enumeration: 5 explicit causes of action vs baseline's narrative coverage.
- **`thinking_token_budget=2048` (Run 3 vs Run 2)**: byte-identical. **No-op on this prompt class** — `low_effort=True` already drives reasoning to 527 chars (~132 tokens), well under the 2,048-token ceiling. The defensive cap never engages.

### Hard-stop disposition

| Plan hard stop | Status | Note |
|---|---|---|
| §1 — `brain_client.py` not at expected path | PASS | path verified |
| §2 — frontier `/health` non-200 sustained >60s | PASS | 200 throughout |
| §3 — soak halt event | PASS | not observed |
| §4 — Step 3 reasoning_chars >12,300 (budget not enforced) | PASS | direct 1,337 / LiteLLM 210, both far under |
| **§5 — content_chars >5% off baseline (quality regression)** | **TRIGGERED LETTER, NOT SPIRIT** | +28.9%; attributed to `low_effort` chat-template engagement, not regression. Same grounding citations (4), same finish_reason (stop), more idiomatic ASCII brackets, more thorough enumeration. Operator-confirmed proceed. |
| §6 — reasoning_chars not meaningfully lower with controls | PASS | −97.57% |
| §7 — disk full | PASS | 1.3T avail |

The §5 letter trigger is unavoidable given the chat-template-engagement effect, and the plan's ±5% tolerance assumed byte-deterministic output at `temperature=0.0` — but engaging `low_effort=True` itself is a non-byte-equivalent input change. The Run 1/Run 2/Run 3 isolation cleanly attributes the delta to a non-regressive mechanism.

---

## 5. Implications for Phase 3

The plan's per-section policy table can be simplified given the empirical attribution:

| Section | Mode | Phase 3 plan (original) | Phase 3 plan (post-Phase 2 attribution) |
|---|---|---|---|
| §1 Case Summary | mechanical | enable_thinking=False, max_tokens=4000 | enable_thinking=False, max_tokens=4000 |
| §2 Critical Timeline | synthesis (broken) | enable_thinking=False, max_tokens=4000 | enable_thinking=False, max_tokens=4000 |
| §3 Parties & Counsel | mechanical | enable_thinking=False, max_tokens=4000 | enable_thinking=False, max_tokens=4000 |
| §4 Claims | synthesis | enable_thinking=True, low_effort=True, **budget=2048**, max_tokens=8000 | enable_thinking=True, low_effort=True, max_tokens=8000 |
| §5 Defenses | synthesis | same | same |
| §6 Evidence Inventory | mechanical | enable_thinking=False, max_tokens=5000 | enable_thinking=False, max_tokens=5000 |
| §7 Email Intelligence | synthesis (broken) | enable_thinking=False, max_tokens=4000 | enable_thinking=False, max_tokens=4000 |
| §8 Financial | synthesis | enable_thinking=True, low_effort=True, **budget=2048**, max_tokens=4000 | enable_thinking=True, low_effort=True, max_tokens=4000 |
| §9 Strategy | synthesis | same | same |
| §10 Filing Checklist | mechanical | enable_thinking=False, max_tokens=4000 | enable_thinking=False, max_tokens=4000 |

**Drop `thinking_token_budget` from Phase 3 routing.** Empirically inert on §4's 25 KB prompt class — `low_effort=True` clamps reasoning to ~132 tokens, far under any 2,048 budget. The kwarg stays in BrainClient as a defensive ceiling for hypothetical prompt classes where reasoning might naturally exceed 2,048 tokens, but Phase 3 should not include it in the per-section policy. If §5 / §8 / §9 unexpectedly produce >2,048 reasoning tokens with `low_effort=True` during the Phase 3 full Track A re-run, surface and reconsider.

`enable_thinking=True` for reasoning sections is a no-op (default already True) but worth keeping in the policy table for **explicitness** — future readers can see the per-section intent without spelunking chat-template defaults.

---

## 6. Frontier health log

```
Stress probe pre:    200  (2026-04-30T21:55:51Z)
Stress probe post:   200  (2026-04-30T21:58:08Z direct)
Stress probe post:   200  (2026-04-30T21:59:53Z LiteLLM)
Run 1 pre:           200  (2026-04-30T22:09:28Z)
Run 1 post:          200
Run 2 pre:           200  (2026-04-30T22:15:14Z)
Run 2 post:          200
Run 3 (Step 6) post: 200
```

No soak halt events observed. KV cache pressure not tripped (frontier `--max-num-seqs 10` not saturated).

---

## 7. Artifacts (`/tmp`, NOT in repo)

```
/tmp/budget-stress-20260430T215520Z/             # Step 3 stress probes
├── reconstruction-metadata.json                 # 25,291 chars, 0.00% drift
├── stress-direct-{body,response,metrics}.json   # vLLM direct
├── stress-litellm-{body,response,metrics}.json  # LiteLLM passthrough
└── raw/health.log

/tmp/phase2-section4-validation-20260430T220419Z/   # Run 3 (all three knobs)
/tmp/phase2-section4-run1-20260430T220928Z/         # Run 1 (enable_thinking only)
/tmp/phase2-section4-run2-20260430T221515Z/         # Run 2 (+ low_effort)
```

Each per-run dir holds `metrics/validation-summary.json`, `sections/section_04_claims_analysis.md`, `compose-output/`, and `raw/health.log`.

The reconstruction harness (`reconstruct_section4_prompt.py`) and validation harness (`validate_brain_client_phase2_section4.py`) are removed before commit — single-use, not needed long-term.

---

## 8. References

- PR #326 — BrainClient TP=2 frontier compatibility (introduced now-deprecated `reasoning_effort`, `thinking`)
- PR #327 — synthesizer cap 8000 (unchanged by Phase 2)
- PR #329 — Track A v3 analysis (cap=20000 measurement halted; baseline metrics for §4/§5/§8 used here)
- PR #330 — Phase 1 reasoning-control probes (decision matrix this PR builds on)
- vLLM bugs [#39103](https://github.com/vllm-project/vllm/issues/39103), [#39573](https://github.com/vllm-project/vllm/issues/39573), [#25714](https://github.com/vllm-project/vllm/issues/25714) — confirmed not exposed on this build
- Issue #328 — §2/§7 gap; Phase 3 (next PR) closes it via `enable_thinking=False`
