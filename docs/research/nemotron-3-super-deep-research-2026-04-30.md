# Nemotron-3-Super Deep Research — Field Reference

**Date:** 2026-04-30
**Scope:** Reasoning control internals, vLLM TP=2 serving on dual DGX Spark, prompt engineering for multi-block structural output, response shape, sampling calibration, known failure modes.
**Status:** Reference document. Sourced from NVIDIA official (technical report, advanced deployment guide, HF model card, chat template source, reasoning parser source) cross-referenced against community findings (NVIDIA Developer Forums, vLLM PRs, third-party deployment guides). Captured during Wave 4 §5 prompt tightening work to avoid re-deriving the mechanics next time we touch reasoning routing or frontier config.

**Repo location:** `docs/research/nemotron-3-super-deep-research-2026-04-30.md`
**Cross-reference:** PRs #330, #331, #332. Wave 4 §5 prompt tightening brief. Track A v3 baseline `Attorney_Briefing_Package_7IL_NDGA_I_v3_20260430T224403Z.md`.

---

## 1. The chat template is the source of truth

The three knobs are not three independent levers. The `chat_template.jinja` exposes only **two** variables: `enable_thinking` and `low_effort`. The third "knob" (`thinking_token_budget` / `reasoning_budget`) is **not a chat template variable** — it is a vLLM logits processor that runs server-side.

From the actual `chat_template.jinja` (Nemotron-3-Super-120B-A12B-NVFP4 commit `bd5a7df`):

```jinja
{%- set enable_thinking = enable_thinking if enable_thinking is defined else True %}
{%- set low_effort = low_effort if low_effort is defined else False %}
{%- set truncate_history_thinking = truncate_history_thinking if truncate_history_thinking is defined else True %}
```

Three operational implications:

**A. `enable_thinking` defaults to `True`.** Setting `enable_thinking=True` explicitly is literally a no-op vs. default — confirmed empirically by Phase 1 Probe E. The technical report calls full-reasoning "regular" mode and confirms it as the default for both SFT and RL stages.

**B. `low_effort=True` does exactly one thing.** It appends `\n\n{reasoning effort: low}` to the **last** user message:

```jinja
{%- if message.role == "user" and loop.index0 == ns.last_user_idx and low_effort %}
{{- content + '\n\n{reasoning effort: low}' }}
{%- endif %}
```

That is the entire mechanism. No system-level instruction, no special token, no header marker. The whole behavior of low-effort mode is conditioned on the model recognizing this trailing string from its 2% SFT distribution (math/STEM/instruction following) plus RL reinforcement.

**Why this collapses multi-block legal output:** The model sees `{reasoning effort: low}` appended to a 25KB legal prompt that looks nothing like its training distribution for that mode. The marker is interpreted as "single-pass plan," and any structural requirement that depends on multi-pass reasoning gets compressed.

**C. Hidden third variable — `truncate_history_thinking` (default `True`).** On multi-turn calls this strips `<think>` blocks from prior assistant turns to keep context lean. Single-turn synthesizer calls are unaffected.

---

## 2. `thinking_token_budget` is not what it appears to be

There are **three different mechanisms** named "budget" depending on backend, and they are not interchangeable:

| Backend | Parameter | Path | Mechanism |
|---|---|---|---|
| NIM (cloud) | `reasoning_budget` | `chat_template_kwargs` | `BudgetControlLogitsProcessor` — counts tokens between `<think>` and `</think>`, forces `</think>` once budget hit |
| NIM (cloud) | `max_thinking_tokens` | `nvext` block | Older alias, same processor |
| vLLM mainline | `thinking_token_budget` | top-level sampling param (NOT `chat_template_kwargs`, NOT `extra_body`) | Requires `--reasoning-config` on server defining `reasoning_start_str` / `reasoning_end_str` |
| Nano cookbook | `thinking_budget`, `thinking_budget_grace_period` | custom `BudgetLogitProcessor` plugin | end_think_id=13, prompt_think_ids=[12, 1010] |

**Why Phase 1 found `thinking_token_budget=2048` empirically inert on §4's 25KB prompt:**

1. Frontier started without `--reasoning-config` — no boundary configured for the logits processor to track. Without the config, the processor does not install.
2. Even if installed, on a 25KB prompt the model rarely produces 2048+ reasoning tokens before naturally emitting `</think>`. The budget caps a max it never hits.
3. NIM's `reasoning_budget` (the chat-template-kwargs path that worked at top-level in the probes) is a NIM-only feature upstreamed under a different name and integration path.

**Operational consequence:** the parameter is dead weight in BrainClient and the policy table on this stack. Drop it. To engage budget control on vLLM, the frontier would need to be redeployed with `--reasoning-config '{"reasoning_start_str": "<think>", "reasoning_end_str": "</think>"}'` and the parameter passed at top level (not in chat_template_kwargs).

---

## 3. The `super_v3_reasoning_parser.py` reveals why response shape diverged

Full source (1.88 KB), inheriting from DeepSeekR1:

```python
@ReasoningParserManager.register_module("super_v3")
class SuperV3ReasoningParser(DeepSeekR1ReasoningParser):
    def extract_reasoning(self, model_output, request):
        reasoning_content, final_content = super().extract_reasoning(
            model_output, request
        )
        if (
            hasattr(request, "chat_template_kwargs")
            and request.chat_template_kwargs
            and (
                request.chat_template_kwargs.get("enable_thinking") is False
                or request.chat_template_kwargs.get("force_nonempty_content") is True
            )
            and final_content is None
        ):
            # Put all nonempty content into the content,
            # rather than return content
            reasoning_content, final_content = None, reasoning_content
        return reasoning_content, final_content
```

Three operational implications:

**A. Direct vLLM returns `message.reasoning_content` (DeepSeek-R1 convention).** LiteLLM gateway re-wraps this differently across versions — `message.reasoning` in some, `message.reasoning_content` in others. Phase 2 dual-parsing was correct. Standardize on `reasoning_content` server-side and let LiteLLM map it; do not try to fix LiteLLM, just dual-parse permanently.

**B. There is a fourth chat-template-kwarg: `force_nonempty_content=True`.** Documented safety valve for when reasoning runs to max_tokens and `</think>` never emits — the parser falls back to placing the buffer in `content` instead of leaving it stranded in `reasoning_content`. **Production guidance: enable on any synthesizer that has structural-completeness requirements.** Cheap insurance, no behavioral cost on success path.

**C. TRT-LLM requires building from `main` (PR-12061 cherry-pick) for `force_nonempty_content` support.** vLLM has it natively. Stack runs vLLM, so it is available.

---

## 4. Why `low_effort=True` collapses multi-block structural output — the mechanism

Cross-referenced from technical report §3.1, NeMo cookbook, and chat-template behavior.

The technical report explicitly calls out a regression they engineered around: *"a single-stage SFT led to a marked degradation on long-input-short-output scenarios."* They added Stage 2 SFT with per-conversation normalization to fix it for **regular mode only**. Low-effort mode is a separate 2% SFT slice (math/STEM/instruction-following) that never went through the long-input-short-output recovery.

Under low-effort:
- Long input (25KB §5 retrieval packet) → reasoning compresses aggressively
- Multi-block output requirement → not in low-effort SFT distribution
- Model collapses to single-pass plan → structural subsections drop

**The "instruction following" slice of low-effort SFT is the lever.** That is the only one of the three trained low-effort domains accessible from the prompt itself. Wave 4's named-block prompt structure (Block A/B/C/D with explicit minimums) is exactly the right intervention — substituting explicit instruction-following structure for the multi-pass reasoning the model was implicitly using as a checklist.

**Practical guardrails:**
- `{reasoning effort: low}` semantics work better with **numbered, named, bounded** structural requirements than with prose paragraphs.
- Keep `max_tokens=8000` — even though low_effort suppresses reasoning, the structural-completeness requirement under instruction-following will still emit content of normal length. Lowering the ceiling does not help.

---

## 5. The three documented modes — only two are operationally distinct

| Mode | enable_thinking | low_effort | Behavior |
|---|---|---|---|
| Reasoning OFF | `False` | (ignored) | `<think></think>` empty pair appended; no CoT |
| Regular reasoning | `True` (default) | `False` (default) | Full CoT, multi-pass planning, structural completeness |
| Low-effort reasoning | `True` | `True` | Trailing `{reasoning effort: low}` marker, single-pass plan, multi-block output drops |

Phase 3 `low_effort=False` deviation for §5 is **regular reasoning mode** (because `low_effort` defaults to `False`). Setting `enable_thinking=True` explicitly is the no-op. Empirical attribution stands: `low_effort` is the only knob that does anything for §5.

**For Wave 4 routing decision after validation:** §5 becomes `enable_thinking=True, low_effort=True`. The explicit `enable_thinking=True` is redundant but documents intent.

---

## 6. TP=2 on dual DGX Spark — production reference

NVIDIA's official advanced deployment guide pretends DGX Spark only does TP=1. The validated dual-Spark TP=2 NVFP4 path exists in the field, documented on NVIDIA Developer Forums.

**Reference deployment (Leon Gibat, NVIDIA Developer Forums, March 26 2026 — 24 tok/s on dual Spark):**

- Image: `vllm/vllm-openai:cu130-nightly` (`.dev176+` resolves cu130/cu132 ABI mismatch — clear wheel cache to pull fresh)
- Model: `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4` (~75 GB on disk, FP4 variant)
- Transport: ConnectX-7 direct connect 200 Gbps (Fortress-Prime: ConnectX 100 Gbps — should work, lower bandwidth headroom)
- TP=2 across both Sparks, NVFP4 with `--moe-backend cutlass` (CUTLASS, not Marlin, for LatentMoE on Spark)

**Required env vars for Spark:**

```
VLLM_NVFP4_GEMM_BACKEND=marlin
VLLM_ALLOW_LONG_MAX_MODEL_LEN=1
VLLM_FLASHINFER_ALLREDUCE_BACKEND=trtllm
VLLM_USE_FLASHINFER_MOE_FP4=0   # critical — FlashInfer MoE FP4 broken on Spark, see flashinfer issue #2884
```

**Key serve flags from NVFP4 model card multi-Spark recipe:**

```
--async-scheduling
--dtype auto
--kv-cache-dtype fp8
--max-model-len 262144              # cap to 256k unless 1M required
--swap-space 0
--trust-remote-code
--gpu-memory-utilization 0.85       # not 0.9 — 0.85 is what working forum config used
--max-cudagraph-capture-size 128
--enable-chunked-prefill
--mamba-ssm-cache-dtype float16     # NVFP4 only — float32 for BF16/FP8
--reasoning-parser-plugin /workspace/super_v3_reasoning_parser.py
--reasoning-parser super_v3
--enable-auto-tool-choice
--tool-call-parser qwen3_coder
--max-num-seqs 4                    # Spark conservative — raise to 8-16 only after stable
```

**Why TP=2 is suboptimal vs EP=2 on Nemotron-3-Super specifically:**

LatentMoE compresses expert computation to a 1024-dim latent (vs full 4096-dim model dim). All-to-all routing traffic over EP is ~4x lower than equivalent TP collective volume. NVIDIA's advanced guide is explicit: *"Expert parallelism (`--enable-expert-parallel` / `--ep`) is strongly preferred over pure TP for this architecture."*

**Caveat for Fortress-Prime stack:** `--enable-expert-parallel` over CX-100Gbps between two Sparks may not behave correctly on cu130-nightly. The validated 24 tok/s benchmark used pure TP=2. Test EP=2 only after TP=2 stable, with rollback path.

**Current Fortress-Prime frontier:** vLLM 0.20.1rc1 at `http://10.10.10.3:8000`, TP=2 over spark-3+spark-4, no MTP, no `--reasoning-config`. Two specific risks:

1. **MTP off is correct for now.** Advanced Deployment Guide warns `--speculative-config '{"method": "nemotron_h_mtp", ...}'` plus NVFP4 plus TP=2 combinations are bleeding-edge. Pinned `0.17.1` does not support MTP+NVFP4 on Spark — requires cu130-nightly. If/when MTP flips on, expect stability shakedown.
2. **`mamba-ssm-cache-dtype` mismatch.** Advanced guide says `float32` "for all checkpoint precisions." Spark NVFP4 recipe uses `float16`. Model weights themselves bake float16 SSM cache for FP4 quantizations. Use `float16` on NVFP4 weights, `float32` on BF16/FP8. Mismatch silently degrades quality.

---

## 7. Sampling parameters NVIDIA insists on

From every official source — model card, NeMo cookbook, advanced deployment guide:

```
temperature = 1.0
top_p = 0.95
```

**For all modes — reasoning, tool-calling, general chat.** No exceptions documented.

The recommended `temperature=1.0` is unusual (most production stacks default to 0.6–0.7 for legal/structured work) and is non-negotiable in NVIDIA's guidance. The model is calibrated against this sampling distribution; lower temperatures do not improve determinism the way they would with a non-Nemotron model — they shift the model off-distribution.

**Implication:** if BrainClient runs anything other than `temperature=1.0, top_p=0.95`, that is a confound on three-knob attribution. Verify before any reasoning-control validation run.

**Token IDs (stable across all family checkpoints):**
- `<think>` = token ID 12
- `</think>` = token ID 13

If a custom logits processor is ever needed (e.g., Path 3 fallback for a section that resists prompt tightening), these are the IDs to use.

---

## 8. Known failure modes

**A. cu130/cu132 ABI mismatch.** Rebuilding vLLM container from main may produce `_ZN3c1013MessageLoggerC1EPKciib` undefined symbol. Fix: `cu130 → cu132` for torch index URL on lines 48, 259 of the Dockerfile. Resolved upstream as of `.dev176+`.

**B. FlashInfer MoE FP4 unstable on Spark.** Flashinfer issue #2884 documents three CUDA errors (illegal instruction, misaligned address, generic SIGSEGV) when running NVFP4 + FlashInfer MoE on Spark. **Always set `VLLM_USE_FLASHINFER_MOE_FP4=0` on Spark.** Marlin backend is what works.

**C. `--enable-chunked-prefill` regression on vLLM ≤ 0.15.0.** Current 0.20.1rc1 is past that. If pinning downward, that flag silently corrupts long-context output. Add `--no-enable-chunked-prefill` if going to 0.15 or earlier.

**D. Mamba-2 state cache is NOT prefix-cacheable.** Setting `--enable-prefix-caching` produces nothing on this model — Mamba's recurrent state is not keyed the same way KV cache is. Do not waste config tuning on prefix cache for retrieval re-runs.

**E. Triton attention backend may be required.** vLLM upstream issue #35219 was Nemotron-3 attention regression on certain topologies. Fixed in mainline. If attention crashes appear, add `--attention-backend TRITON_ATTN`.

---

## 9. Quick-reference matrix — what to set where

| Goal | Where set | Value |
|---|---|---|
| Full reasoning, structural completeness | `chat_template_kwargs` | `{"enable_thinking": True, "low_effort": False}` |
| Fast reasoning, single-pass plan | `chat_template_kwargs` | `{"enable_thinking": True, "low_effort": True}` |
| No reasoning at all | `chat_template_kwargs` | `{"enable_thinking": False}` |
| Safety valve for max_tokens cutoff | `chat_template_kwargs` | `"force_nonempty_content": True` |
| Cap reasoning tokens (NIM only) | `chat_template_kwargs` | `"reasoning_budget": <int>` |
| Cap reasoning tokens (vLLM mainline) | top-level sampling param | `"thinking_token_budget": <int>` (requires `--reasoning-config` on server) |
| Sampling | top-level | `temperature=1.0, top_p=0.95` |
| Response field (direct vLLM) | response | `message.reasoning_content` |
| Response field (LiteLLM gateway) | response | `message.reasoning` OR `message.reasoning_content` — dual-parse |

---

## 10. Sources

**NVIDIA official:**
- Nemotron 3 Super Technical Report (arxiv:2512.20848): https://research.nvidia.com/labs/nemotron/files/NVIDIA-Nemotron-3-Super-Technical-Report.pdf
- Advanced Deployment Guide: https://docs.nvidia.com/nemotron/nightly/usage-cookbook/Nemotron-3-Super/AdvancedDeploymentGuide/README.html
- Spark Deployment Guide: https://docs.nvidia.com/nemotron/nightly/usage-cookbook/Nemotron-3-Super/SparkDeploymentGuide/README.html
- HF model card (NVFP4): https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4
- HF model card (BF16): https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16
- Chat template (raw): https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4/blob/main/chat_template.jinja
- Reasoning parser (raw): https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4/raw/main/super_v3_reasoning_parser.py
- NIM thinking-budget docs: https://docs.nvidia.com/nim/large-language-models/latest/thinking-budget-control.html
- vLLM blog: https://vllm.ai/blog/nemotron-3-super
- vLLM reasoning outputs docs: https://docs.vllm.ai/en/latest/features/reasoning_outputs/

**Community / field reports:**
- Leon Gibat dual-Spark TP=2 NVFP4 (24 tok/s, ABI fix): https://forums.developer.nvidia.com/t/nemotron-3-super-nvfp4-via-vllm-tp-2-on-2x-dgx-spark-24-tok-s-abi-fix-for-cu130-cu132-mismatch/364862
- FlashInfer Spark instability: https://github.com/flashinfer-ai/flashinfer/issues/2884
- vLLM reasoning_budget PR #37112: https://github.com/vllm-project/vllm/pull/37112
- vLLM serving issue (NVIDIA-NeMo/Nemotron #127): https://github.com/NVIDIA-NeMo/Nemotron/issues/127
- Spheron deployment guide: https://www.spheron.network/blog/nemotron-3-super-deployment-guide/
- Cobus Greyling controllable reasoning analysis: https://cobusgreyling.medium.com/nvidia-nemotron-3-super-833685b64723
- Greyling demo repo (CLI, batch benchmark, adaptive router): https://github.com/cobusgreyling/NVIDIA-Nemotron-3-Super

---

End of reference.
