# Synthesizer max_tokens cap cascade — validation 2026-04-30

**Branch:** `fix/synthesizer-max-tokens-cap-2026-04-30` (cut from `origin/main`)
**Cascade from:** PR #326 (BrainClient `default_max_tokens=8000`)
**Edit:** `fortress-guest-platform/backend/services/case_briefing_synthesizers.py:205`
`max_tokens: int = 2000,` → `max_tokens: int = 8000,`

## Pre-fix baseline (PR #323, Track A v1)

All 5 synthesis sections (§2, §4, §5, §7, §8): `content_chars=0`, `finish_reason=length`.
Root cause: nemotron_v3 reasoning trace (~2000+ tokens) consumed the full 2000-token budget; vLLM
emitted only `delta.reasoning` chunks; pre-Path-X BrainClient ignored reasoning chunks; content
never emitted.

## Post-fix Track A re-run (this branch)

Run stamp: `20260430T185147Z` · wall: 1376.03s (~23m) · endpoint:
`http://10.10.10.3:8000` (spark-3 vLLM TP=2, served `nemotron-3-super`).

| Section | Mode | content_chars | citations (orchestrator) | wall (s) | Result |
|---|---|---:|---:|---:|---|
| §2 Critical Timeline | synthesis | **0** | 0 | 335.06 | ❌ STILL EMPTY |
| §4 Claims Analysis | synthesis | 7818 | 4 | 308.10 | ✅ PASS |
| §5 Key Defenses Identified | synthesis | 6271 | 5 | 270.46 | ✅ PASS |
| §7 Email Intelligence Report | synthesis | **0** | 0 | 335.69 | ❌ STILL EMPTY |
| §8 Financial Exposure Analysis | synthesis | 3565 | 4 | 126.12 | ✅ PASS |

**Net: 3/5 synthesis sections recovered; 2/5 still empty.**

Quality on the 3 passing sections:
- 0 first-person bleed across all sections
- 0 `<think>` block leakage across all sections
- `format_compliant: true` across all sections
- Citation density consistent with pre-Wave-4 baseline (4-5 grounding citations per section)

§9 augmentation (post-orchestrator legal-reasoning call): content_chars=6259, finish_reason=stop,
completion_tokens=4760 — confirms LiteLLM augmentation path unaffected.

## Why §2 and §7 still empty

§2 (Critical Timeline) and §7 (Email Intelligence Report) ran the full 335s wall — same shape as
the pre-fix Track A failures: long quiet stream then end. Pattern is consistent with reasoning
trace exceeding 8000 tokens on these prompts (timeline reconstruction and email-graph analysis are
the heaviest reasoning loads in the brief).

The pre-Path-X BrainClient on this branch (`backend/services/brain_client.py` from `origin/main`)
yields only `delta.content` chunks. If reasoning consumes the entire `max_tokens` budget on a
given prompt, vLLM hits `finish_reason=length` mid-reasoning and never emits content — the client
returns 0 content chars. Raising the cap to 8000 lifted 3 prompts out of that regime; it did not
lift §2 or §7.

## Tests

`backend/tests/test_brain_client.py` — 7/7 passing (pre-Path-X baseline; this branch does not
include PR #326's 10 new tests because PR #326 has not yet merged).

No dedicated synthesizer test exists. The synthesizer's `max_tokens` is a default parameter; its
only effect is the value passed through to `BrainClient.chat(max_tokens=...)`, which the existing
brain-client tests already cover for both pass-through and stream behavior.

Pytest collection of the broader test tree errors on 4 pre-existing DB-fixture issues
(`test_acquisition_area6`, `test_nim_migration`, `test_parity_monitor`,
`test_vault_documents_integrity`) — unrelated to this change.

## Acceptance vs the brief

The brief's success bar was "all 5 synthesis sections content > 1000 chars; finish_reason=stop;
0 first-person bleed; 0 `<think>` leakage."

- 3/5 sections (§4, §5, §8): all four conditions met ✅
- 2/5 sections (§2, §7): content_chars=0, conditions not met ❌

This PR ships as **draft** — it is a strict improvement over the pre-fix baseline (5/5 empty
→ 2/5 empty) but does not fully meet the brief's bar. Two follow-up paths to close the gap:

1. **Path X merge (PR #326).** With `delta.reasoning` properly captured by BrainClient, §2 and §7
   would still hit `finish_reason=length` if reasoning exceeds 8000 budget — but the operator
   would gain visibility (`client.last_reasoning`, `client.last_finish_reason`) to confirm it
   and decide on a higher cap.
2. **Further cap raise (e.g. 12000–16000) for §2 and §7 specifically.** Could be done either as a
   per-section override in the synthesizer call sites, or as a global cap raise once Path X is
   in place to confirm 8000 is in fact the binding constraint and not some other failure mode.

Either path is out of scope for this one-line cascade PR.

## Per-section call metrics (BrainClient)

```
section_02_critical_timeline      max_tokens=8000  prompt=25196  content=0     wall=335.06s
section_04_claims_analysis        max_tokens=8000  prompt=25291  content=7818  wall=308.10s
section_05_key_defenses_identified max_tokens=8000 prompt=25198  content=6271  wall=270.46s
section_07_email_intelligence_report max_tokens=8000 prompt=25284 content=0    wall=335.69s
section_08_financial_exposure_analysis max_tokens=8000 prompt=25193 content=3565 wall=126.12s
```

Run summary JSON: `docs/operational/synthesizer-cap-cascade-validation-2026-04-30.json`
Sections artifacts: `/tmp/track-a-case-i-v3-20260430T185147Z/sections/`
