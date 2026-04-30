# BrainClient TP=2 Fix — Validation Report

**Date:** 2026-04-30
**Branch:** `fix/brain-client-tp2-frontier-compatibility-2026-04-30`
**Driver:** Path X fix for Track A (PR #323) BrainClient defects
**Brief:** `docs/operational/brain-client-tp2-frontier-fix-brief.md`

## Pre-fix BrainClient state

| Field | Value |
|---|---|
| File | `fortress-guest-platform/backend/services/brain_client.py` (162 lines) |
| Constructor | `BrainClient(base_url, timeout=600.0, model=…)` — no reasoning controls |
| `chat()` default | `max_tokens: int = 4000` (chat default; synthesizer overrides to 2000) |
| Module constant | none for max_tokens |
| `_stream()` parser | parses `delta.content` only; `delta.reasoning` silently discarded |
| Caller surface | 8 callers across orchestrator + scripts + tests (no behavior change in callers required) |
| Existing tests | 7 passing |

## Pre-fix repro (synthesis-style prompt against TP=2 frontier, default BrainClient)

Confirmed via Track A run 2026-04-30 (PR #323):

```
CONTENT_LEN: 0
REASONING_LEN: (not exposed by old BrainClient)
FINISH: length
```

5 of 5 synthesis sections empty; reasoning trace consumed full max_tokens=2000 budget; content emission never started.

## Edits applied

| File | Change |
|---|---|
| `fortress-guest-platform/backend/services/brain_client.py` | Surgical refactor (170 lines, +50 LOC): module constant `_DEFAULT_MAX_TOKENS = 8000`; constructor adds `default_max_tokens`, `reasoning_effort`, `thinking` kwargs; `chat()` resolves max_tokens via constructor default when None, accepts per-call `reasoning_effort`/`thinking` overrides, builds `extra_body` + `chat_template_kwargs`; `_stream()` parses both `delta.content` (yielded) AND `delta.reasoning` (accumulated to `client.last_reasoning`); `_oneshot()` extracts `message.reasoning` + `finish_reason` to `client.last_reasoning` / `client.last_finish_reason` |
| `fortress-guest-platform/backend/tests/test_brain_client.py` | +10 new tests covering all 3 defects (reasoning chunk parsing, max_tokens default, kwargs injection, per-call override, oneshot reasoning capture) |

Diff stats: 2 files changed, ~250 insertions, ~30 deletions (constructor + chat signature reshape).

## Post-fix unit test results

| | Pre-fix | Post-fix |
|---|---|---|
| Existing tests | 7 passing / 0 failing | 7 passing / 0 failing |
| New Path-X tests | n/a | **10 new** |
| Total | 7/7 | **17/17 PASS** |

No regression. All 7 prior tests continue to pass with the refactored signatures (`max_tokens=None` default + `chat()` resolves; per-call args still wire through correctly).

## Post-fix repro (BrainClient direct, synthesis-style prompt)

`/tmp/brain-client-repro.py` against live `http://10.10.10.3:8000` with `nemotron-3-super`:

| Run | content_chars | reasoning_chars | finish_reason |
|---|---|---|---|
| Default (no reasoning kwargs, default_max_tokens=8000) | **3,203** | **4,495** | **stop** ✅ |
| reasoning_effort=high, thinking=True | 3,203 | 4,495 | stop |
| reasoning_effort=low, thinking=False | 3,203 | 4,495 | stop |

**Defect 1 + 2 fix validated.** Pre-fix: 0 chars. Post-fix: 3,203 chars of clean affirmative-defenses table grounded in the bracketed-filename evidence. `finish_reason=stop` (not length).

## reasoning_effort behavior validation

| | reasoning_chars |
|---|---|
| reasoning_effort=high | 4,495 |
| reasoning_effort=low | 4,495 |
| **Δ** | **0** |

**Defect 3 wiring validated; vLLM activation deferred.** Per brief §7.4: "If they're equal: vLLM build may not honor `reasoning_effort` extra_body kwarg. Document the finding; the constructor wiring is still correct (frontier may need newer vLLM build to act on it). Don't halt — the kwarg infrastructure is in place; activation depends on vLLM features."

The kwargs are present in the request body (verified by unit test `test_extra_body_injection_when_reasoning_kwargs_set`); the live vLLM build (`0.20.1rc1.dev96+gefdc95674.d20260430`) does not differentiate the reasoning trace based on the flag. When upstream vLLM honors `reasoning_effort` for nemotron_v3, BrainClient is already wired to pass it through.

## §8 Track A re-run via real orchestrator

Re-ran `track_a_case_i_runner.py` end-to-end against case `7il-v-knight-ndga-i`. Wall: 421.5 s.

| § | Mode | Wall (s) | Content chars | finish_reason | Cites |
|---|---|---|---|---|---|
| 1 | mechanical (deterministic) | <1 | 511 | n/a | 0 |
| 2 | synthesis via BrainClient | 84.05 | **0** | (length per BrainClient `last_finish_reason`) | 0 |
| 3 | mechanical (deterministic) | <1 | 509 | n/a | 0 |
| 4 | synthesis via BrainClient | 84.33 | **0** | length | 0 |
| 5 | synthesis via BrainClient | 84.25 | **0** | length | 0 |
| 6 | mechanical (deterministic) | <1 | 1,376 | n/a | 0 |
| 7 | synthesis via BrainClient | 84.09 | **0** | length | 0 |
| 8 | synthesis via BrainClient | 84.16 | **0** | length | 0 |
| 9 (placeholder) | operator_written | <1 | 383 | n/a | 0 |
| **9 (augmented)** | **LiteLLM legal-reasoning, post-run** | 174.73 | **6,375** | **stop** | **14 (1 unique)** |
| 10 | mechanical (deterministic) | <1 | 611 | n/a | 0 |

**Result: 5 synthesis sections via the orchestrator pipeline still empty.** Section 9 augmentation (which uses LiteLLM directly, NOT BrainClient + synthesizer) produced 6,375 chars cleanly — up from 4,578 chars in the original Track A run.

### Why the synthesizer pipeline still fails (per brief §8 documented finding)

The BrainClient fix raised the **client-level** default `max_tokens` from 4,000 to 8,000 — but the synthesizer at `case_briefing_synthesizers.py:205` **hardcodes its own `max_tokens=2000`** parameter and passes it explicitly to `brain_client.chat(max_tokens=2000)`. The new BrainClient resolves `max_tokens=None` → 8,000, but `max_tokens=2000` (explicit) → 2,000.

Per brief §11 ("DO NOT touch: Synthesizer prompt logic / case_briefing_compose.py orchestrator"), the synthesizer was **not modified** in this PR.

This is a separate, narrowly-scoped follow-up: change one default at `case_briefing_synthesizers.py:205` from 2000 → 8000.

Per brief §8: "If any of the 5 still fail: Defect set wasn't complete. Surface, halt, do NOT modify further. File new issue."

**Halt honored.** Synthesizer not modified. Follow-up issue queued.

## Defect status

| Defect | Status | Validation |
|---|---|---|
| 1 — `_stream()` discards `delta.reasoning` | ✅ **FIXED** | Unit test `test_stream_parses_delta_reasoning_separately` PASS; live repro shows `reasoning_chars=4,495` in `client.last_reasoning` |
| 2 — default `max_tokens=2000` (synthesizer) / 4000 (chat) too low | ✅ **FIXED at BrainClient layer** | Unit test `test_default_max_tokens_is_8000` PASS; live repro with default produces 3,203 content chars + finish=stop. **Caveat:** synthesizer's own hardcoded `max_tokens=2000` overrides the BrainClient default; cascade requires synthesizer-side follow-up (out of Path X scope) |
| 3 — no `reasoning_effort` / `thinking` kwarg mechanism | ✅ **FIXED at BrainClient layer; vLLM activation deferred** | Unit tests `test_extra_body_injection_when_reasoning_kwargs_set` + `test_per_call_reasoning_kwargs_override_constructor` PASS; live behavior identical between high/low (vLLM build doesn't honor extra_body kwarg yet — wiring complete, awaiting vLLM upgrade) |

## Soak impact

- Frontier endpoint `/health` 200 throughout
- No soak halt triggers fired
- ~14 min total TP=2 endpoint load consumed by this PR's repro + Track A re-run (productive load; Section 9 augmentation produced 6,375 chars of usable content)
- Memory peak captured indirectly via next hourly soak collector tick

## Follow-up issue to file post-merge

| Title | Priority |
|---|---|
| **Phase B synthesizer `max_tokens` cap — raise from 2000 to 8000 (cascade BrainClient fix to orchestrator pipeline)** | **P1** |

Body draft:
> Track A re-run 2026-04-30 (BrainClient TP=2 fix PR) confirmed BrainClient defects closed at the client layer. However, `fortress-guest-platform/backend/services/case_briefing_synthesizers.py:205` hardcodes `max_tokens: int = 2000` in `synthesize_synthesis_section()`, which it passes explicitly to `brain_client.chat(max_tokens=2000)`. The new BrainClient resolves `max_tokens=None` → 8000, but explicit 2000 → 2000.
>
> All 5 LLM synthesis sections (2/4/5/7/8) still hit `finish_reason=length` on the orchestrator pipeline post-BrainClient-fix. Reasoning trace fills the 2000 budget; content emission never starts.
>
> **Fix scope:** change one default in `case_briefing_synthesizers.py:205` from `max_tokens: int = 2000` to `max_tokens: int = 8000`. Tiny PR. Test: re-run Track A; expect non-empty content with `finish_reason=stop` on all 5 sections.
>
> **Why not in the BrainClient fix PR:** brief §11 explicitly excluded synthesizer modifications. Path X = surgical BrainClient fix only.
>
> **Empirical evidence:** Track A re-run 2026-04-30 (this PR's `RUN_DIR=/tmp/track-a-case-i-v3-20260430T183436Z/`); section files for 2/4/5/7/8 are 0 bytes; per-section wall ~84 s with content_chars=0 and finish_reason=length. Section 9 augmentation (which uses LiteLLM directly with max_tokens=5000) produced 6,375 chars cleanly — proving the endpoint works when given enough budget.

## What this PR unblocks

- ✅ **Direct BrainClient consumers** (e.g., `brain_rag_probe.py`, future direct callers) can now produce content against the TP=2 frontier with default settings — Defect 1+2+3 closed at the BrainClient layer
- ✅ **The wiring for per-section reasoning depth control** is in place; activation lands when vLLM upgrade honors `reasoning_effort` extra_body
- ✅ **Track A's empirical evidence is closed at one layer** — the BrainClient defects identified are no longer the active bottleneck for direct callers

## What remains blocked (until follow-up issue lands)

- ❌ **Phase B v0.1 orchestrator synthesis sections** — still hit synthesizer's hardcoded 2000 cap. Track A full pipeline re-run still produces empty synthesis sections.
- ❌ **Case II briefing on the orchestrator pipeline** — same root cause as above; cannot complete until synthesizer-cap follow-up merges.

The Section 9 augmentation pattern (post-run LiteLLM call with `legal-reasoning` alias) **continues to work as a viable interim path** for any single-section synthesis use case until the synthesizer-cap fix lands.

## Path Y (Wave 6 NAT migration) status

Unchanged. Path Y (retire BrainClient, route synthesizers via LiteLLM aliases) remains the strategic endgame; not blocked, not urgent. Tracked under issue #325.

---

End of validation report.
