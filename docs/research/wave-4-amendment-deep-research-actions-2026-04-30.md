# Wave 4 Amendment — Three Actions from Nemotron-3-Super Deep Research

**Date:** 2026-04-30
**Scope:** Additive amendment to Wave 4 §5 prompt tightening brief.
**Status:** Folds three deep-research findings into Wave 4 execution. Does not modify the prompt edit (Block A/B/C/D append) or the three-run validation matrix. Adds parallel changes to BrainClient kwargs, the §5 reasoning policy entry, and pre-Run-1 sampling verification.
**Reference:** `docs/research/nemotron-3-super-deep-research-2026-04-30.md`

---

## Action 1 — Add `force_nonempty_content=True` to §5 chat_template_kwargs

**Mechanism:** `super_v3_reasoning_parser.py` documents `force_nonempty_content` as the safety valve for the rare case where reasoning runs to `max_tokens` without emitting `</think>`. Without it, the buffer is stranded in `reasoning_content` and `content` returns empty. With it, the parser falls back to placing the buffer in `content`.

**Cost:** Zero on success path. The kwarg only changes parser behavior in the failure case.

**Where to wire it:**

1. `SECTION_REASONING_POLICY["section_05_key_defenses_identified"]` in `case_briefing_synthesizers.py`:

   ```python
   "section_05_key_defenses_identified": {
       "enable_thinking": True,
       "low_effort": False,  # Wave 4 deviation per PR #332 — multi-pass planning required
       "force_nonempty_content": True,  # Wave 4: parser safety valve, see super_v3_reasoning_parser.py
       "max_tokens": 8000,
   },
   ```

   When validation passes and §5 routes back to `low_effort=True`, the `force_nonempty_content` line stays. The comment updates:

   ```python
   "low_effort": True,  # Wave 4: tightened prompt removes structural-completeness dependency on reasoning depth
   "force_nonempty_content": True,  # Wave 4: parser safety valve, see super_v3_reasoning_parser.py
   ```

2. **BrainClient passthrough verification.** If BrainClient has an allow-list filtering kwargs into `chat_template_kwargs`, add `force_nonempty_content` to the allow-list. If it passes the policy dict through unfiltered, no BrainClient change needed. **Verify which before Run 1.** Grep for `chat_template_kwargs` construction in `BrainClient` and check whether unknown keys are passed or dropped.

3. **Test the safety valve actually fires.** Add one assertion to the §5 isolation harness: in the three-run matrix, confirm that all runs return non-empty `content` from BrainClient response parsing. If any run shows empty content alongside non-empty reasoning, the kwarg is not being passed through correctly.

---

## Action 2 — Drop `thinking_token_budget=2048` from §5 calls

**Mechanism:** Phase 1 found `thinking_token_budget=2048` empirically inert on §4's 25KB prompt class. Deep research confirms two mechanistic reasons:

1. The Fortress-Prime frontier is started without `--reasoning-config`. vLLM's mainline `thinking_token_budget` requires the server to define `reasoning_start_str` and `reasoning_end_str` before the logits processor will install. Without `--reasoning-config`, the parameter is ignored at the engine layer.
2. Even with `--reasoning-config` enabled, on a 25KB legal prompt the model rarely produces 2048+ reasoning tokens before naturally emitting `</think>`. The cap is above the typical reasoning length.

**Action:**

1. Remove `thinking_token_budget` from `SECTION_REASONING_POLICY["section_05_key_defenses_identified"]` if currently present.
2. Remove `thinking_token_budget` from BrainClient's per-section kwarg construction for §5.
3. Audit all 10 sections in `SECTION_REASONING_POLICY` for any `thinking_token_budget` entries — none should remain after this PR. If any other section has it, remove there too. Single PR, full cleanup.
4. Add a comment in BrainClient near the section policy lookup documenting why the parameter was removed:

   ```python
   # thinking_token_budget removed Wave 4 — vLLM mainline requires --reasoning-config
   # on the frontier (not currently set). NIM's reasoning_budget is a separate path.
   # See docs/research/nemotron-3-super-deep-research-2026-04-30.md §2.
   ```

**Re-engagement path:** If budget control is ever needed, redeploy frontier with `--reasoning-config '{"reasoning_start_str": "<think>", "reasoning_end_str": "</think>"}'` and pass `thinking_token_budget` as a top-level sampling parameter (NOT inside `chat_template_kwargs`, NOT inside `extra_body` wrapper). Out of scope for Wave 4.

---

## Action 3 — Verify temperature=1.0, top_p=0.95 in BrainClient defaults before Run 1

**Mechanism:** NVIDIA's official guidance, repeated across model card, NeMo cookbook, and advanced deployment guide, locks sampling at `temperature=1.0, top_p=0.95` for **all modes — reasoning, tool-calling, and general chat alike.** The model is calibrated against this distribution. Lower temperatures shift it off-distribution rather than improving determinism.

**Risk:** If BrainClient currently runs anything other than these values, the Wave 4 three-run validation matrix has a sampling-distribution confound on top of the reasoning-control attribution. Run 1 vs Run 3 (legacy prompt sanity) needs to differ only in the prompt, not in sampling.

**Action — pre-Run-1 verification:**

1. Grep BrainClient for `temperature` and `top_p` defaults.
2. Trace the §5 code path: `case_briefing_synthesizers.py` → BrainClient call → frontier request body. Capture the actual outgoing JSON for one §5 invocation (one-shot, throwaway log line, not committed).
3. Confirm `temperature=1.0, top_p=0.95` are what the frontier sees. If a global default has been set lower elsewhere (e.g., 0.6, 0.7), document it.

**If BrainClient defaults match NVIDIA guidance:**
- No code change. Note the verification in the Wave 4 PR body under "Sampling verification."

**If BrainClient defaults diverge from NVIDIA guidance:**
- Two paths, decide before Run 1:
  - **Path A — align with NVIDIA.** Set `temperature=1.0, top_p=0.95` for §5 (or globally) before Run 1. Cleaner attribution. Risk: behavioral change vs every prior Track A run.
  - **Path B — keep current defaults.** Document the deviation explicitly in the Wave 4 PR body. Risk: any future cross-reference against NVIDIA-recommended runs requires a re-baseline.
- **Recommended: Path A for §5 only**, scoped via the SECTION_REASONING_POLICY dict if it supports per-section sampling overrides. If it doesn't, extend it to support `temperature` and `top_p` keys, default to NVIDIA values, and route §5 explicitly. This preserves other sections' current behavior while bringing §5 into NVIDIA-recommended sampling for clean Wave 4 attribution.

**Either path:** add a section to the Wave 4 PR body:

```
## Sampling verification

Pre-Run-1 audit: BrainClient §5 outgoing temperature=<X>, top_p=<Y>.
NVIDIA-recommended: temperature=1.0, top_p=0.95.
Path taken: <A | B>.
[If Path A: code change in <file>:<line>.]
[If Path B: deviation noted, no code change. Risk acknowledged.]
```

---

## Order of operations

Insert between Wave 4 brief Steps 5 and 6 (after prompt edit, before three-run isolation):

**Step 5a — BrainClient kwarg passthrough audit.**
- Grep BrainClient for chat_template_kwargs construction
- Confirm `force_nonempty_content` will pass through (allow-list extension if needed)
- Confirm `thinking_token_budget` is removed from §5 path
- Document findings inline before continuing

**Step 5b — §5 SECTION_REASONING_POLICY edit.**
- Add `force_nonempty_content: True`
- Remove `thinking_token_budget` if present
- Audit all 10 sections for stray `thinking_token_budget` entries

**Step 5c — Sampling verification.**
- Capture outgoing JSON for one §5 BrainClient invocation
- Confirm or correct temperature/top_p
- Decide Path A or Path B before Run 1

**Then proceed to Step 6 — three-run isolation per original brief.**

---

## What this amendment does NOT change

- Prompt edit (Block A/B/C/D append) — unchanged
- Three-run validation matrix — unchanged (tightened+low_true / tightened+low_false / legacy+low_true)
- Hard-stop conditions — unchanged
- Pass / soft-pass / hard-fail thresholds — unchanged
- Path 2 fallback (split §5 into two synthesizer calls) — unchanged
- 14-day soak precedence — unchanged
- Out-of-scope sections (§4 verbosity, §8 verbosity, §9 augmentation) — unchanged

---

## PR body addition

Append to PR body skeleton from Wave 4 brief §6:

```
## Deep research integration (this PR)

Three additive changes from Nemotron-3-Super deep research
(see docs/research/nemotron-3-super-deep-research-2026-04-30.md):

1. Added `force_nonempty_content=True` to §5 chat_template_kwargs.
   Safety valve documented in super_v3_reasoning_parser.py for
   reasoning-runs-to-max_tokens edge case. Zero cost on success path.

2. Removed `thinking_token_budget` from §5 (and audited remaining 9
   sections — confirmed clean). vLLM mainline requires --reasoning-config
   on the frontier (not currently set) before the logits processor
   installs. Parameter was empirically inert per Phase 1 Probe E and is
   now mechanistically explained.

3. Verified BrainClient §5 sampling defaults against NVIDIA-recommended
   temperature=1.0, top_p=0.95.
   [Path A: aligned with NVIDIA / Path B: deviation documented]
```

---

End of Wave 4 amendment.
