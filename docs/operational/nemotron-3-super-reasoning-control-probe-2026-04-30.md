# Nemotron-3-Super Reasoning-Control Probe — 2026-04-30

**Branch:** `chore/nemotron-3-super-reasoning-control-probe-2026-04-30` (from `origin/main` 8d8c41b65)
**Mission:** Empirically determine which reasoning-control mechanisms the spark-3 vLLM frontier actually honors, before any BrainClient surgery.
**Frontier load consumed:** 7 probes, ~775 seconds of frontier wall, no soak halt events, frontier health 200 throughout.
**Production code touched:** zero.

---

## 1. Frontier inventory

| Field | Value |
|---|---|
| Endpoint | `http://10.10.10.3:8000` |
| Host (per ssh hostname) | spark-3 |
| Container | `vllm_node` |
| vLLM version | `0.20.1rc1.dev96+gefdc95674.d20260430.cu132` |
| Served model | `nemotron-3-super` |
| Model path | `/root/.cache/huggingface/nemotron-3-super-120b-nvfp4` |
| Quantization | NVFP4 |
| KV cache dtype | FP8 |
| MoE backend | cutlass |
| Attention backend | TRITON_ATTN |
| `--max-model-len` | 262,144 |
| `--max-num-seqs` | 10 |
| `--tensor-parallel-size` | 2 |
| `--distributed-executor-backend` | ray |
| `--reasoning-parser` | **nemotron_v3** |
| `--reasoning-config` | **NOT PRESENT** (good — avoids #39103) |
| `--speculative-config` / MTP | **NOT PRESENT** (good — avoids #39573) |
| `--tool-call-parser` | qwen3_coder |
| Accelerator | 2× GB10 (Grace Blackwell) |
| `--gpu-memory-utilization` | 0.7 |

### vLLM bug exposure on this build

| Bug | Triggered? | Why |
|---|---|---|
| [vllm-project/vllm#39103](https://github.com/vllm-project/vllm/issues/39103) — `--reasoning-config` bricks nemotron_v3 parser | **NO** | flag absent |
| [vllm-project/vllm#39573](https://github.com/vllm-project/vllm/issues/39573) — MTP silently disables `thinking_token_budget` | **NO** | speculative decoding disabled |
| [vllm-project/vllm#25714](https://github.com/vllm-project/vllm/issues/25714) — pre-0.18.0 builds don't honor budget parameter | **NO** | on 0.20.1rc1 |

The build is on the safe side of all three publicly-documented hazards. The control surface should be available; remaining question was schema (top-level vs nested in extra_body), which the probes settle.

---

## 2. Probe payload

Single representative §4-Claims-Analysis-shape prompt reused across all probes for fair comparison: ~2,900 chars total (306-char system prompt with the canonical `"detailed thinking on"` directive, 2,605-char user prompt with task + 4 abbreviated evidence chunks).

Original §4 production prompts at 19:45Z were ~25 KB; this probe prompt is intentionally shorter to keep frontier wall manageable across 7 probes. Reasoning depths therefore run ~25% of the production §4 depth (Probe A baseline: 1,939 reasoning tokens vs §4-19:45Z baseline: 5,414 reasoning tokens). **The reduced prompt does not stress the 2048-token budget** — see §6 open question.

All probes use `temperature=1.0`, `top_p=0.95` (Nemotron's published recommended sampling), `stream=false`, `max_tokens=20000` (or 4000 for `enable_thinking=False` which has nothing to think).

---

## 3. Probe results

### Direct-to-vLLM probes

| Probe | Knob | content_chars | reasoning_chars | reasoning tok | finish | wall_s |
|---|---|---:|---:|---:|---|---:|
| A | baseline (no controls) | 4,427 | 7,755 | ~1,939 | stop | 114.6 |
| B | `chat_template_kwargs.enable_thinking=False` (top-level), max_tokens=4000 | 7,122 | **0** | 0 | stop | 68.5 |
| C | `chat_template_kwargs.{enable_thinking:True, low_effort:True}` (top-level) | 7,038 | **93** | ~23 | stop | 70.8 |
| D | top-level `thinking_token_budget=2048` + `chat_template_kwargs.enable_thinking=True` | 5,156 | 4,778 | ~1,195 | stop | 94.5 |
| E | `extra_body: {thinking_token_budget: 2048, chat_template_kwargs: {enable_thinking: True}}` (wrapper form) | 5,263 | **10,215** | **~2,554** | stop | 144.1 |

### LiteLLM passthrough probes (model alias `legal-reasoning`)

| Probe | Knob | content_chars | reasoning_chars | reasoning tok | finish | wall_s | reasoning field |
|---|---|---:|---:|---:|---|---:|---|
| BL | same body as B, via LiteLLM | 5,070 | 0 | 0 | stop | 48.7 | _(none — message has no reasoning field)_ |
| DL | same body as D, via LiteLLM | 4,661 | 8,705 | ~2,176 | stop | 133.8 | `reasoning_content` |

### Response-shape variance

| Endpoint | Field name when reasoning is emitted | Field name when reasoning is suppressed |
|---|---|---|
| Direct vLLM | `message.reasoning` | absent |
| LiteLLM | `message.reasoning_content` | absent (only `content`, `role`, `provider_specific_fields`) |

Caller must read **both** keys (`reasoning_content` first, then `reasoning` as fallback) to be endpoint-agnostic.

---

## 4. Decision matrix

| # | Mechanism | vLLM direct | LiteLLM passthrough | Wire in BrainClient? |
|---|---|---|---|---|
| B | `chat_template_kwargs.enable_thinking=False` (top-level) | **PASS** — reasoning truly 0, content emits, wall ~70s | **PASS** — same shape, even faster | **YES** |
| C | `chat_template_kwargs.low_effort=True` (top-level) | **PASS** — reasoning ~0 (93 chars), content emits | not tested | YES (optional; likely OK by symmetry with B) |
| D | top-level `thinking_token_budget=N` + `chat_template_kwargs.enable_thinking=True` | **ACCEPTED** — no error, reasoning bounded near cap | **ACCEPTED** — same | **YES** (with caveat — see §6) |
| E | `thinking_token_budget` / `chat_template_kwargs` nested **inside** `extra_body` | **NOT HONORED** — reasoning ran 2,554 tok, exceeded 2,048 budget | not tested | **NO** — wrapper silently ignored |

The smoking gun for #E is the comparison to #D: same fields, same values, wrapped vs unwrapped — wrapped form ran **114% over budget** and behaved identically to baseline. vLLM's OpenAI-compat server does not introspect `extra_body`. Caller must put fields at top level.

---

## 5. Recommended Phase 2 BrainClient wiring

Based on the empirical results:

1. **Add per-call kwargs** `enable_thinking: bool | None = None`, `thinking_token_budget: int | None = None`, `low_effort: bool | None = None`.
2. **Inject at TOP LEVEL** of the request body (NOT inside `extra_body`):
   ```python
   if enable_thinking is not None or low_effort is not None:
       payload["chat_template_kwargs"] = {}
       if enable_thinking is not None:
           payload["chat_template_kwargs"]["enable_thinking"] = enable_thinking
       if low_effort is not None:
           payload["chat_template_kwargs"]["low_effort"] = low_effort
   if thinking_token_budget is not None:
       payload["thinking_token_budget"] = thinking_token_budget
   ```
3. **Response handling**: read `message.reasoning_content` first, fall back to `message.reasoning`. Both should land on `self.last_reasoning`.
4. **Deprecate** the existing `reasoning_effort` constructor/per-call kwargs added in PR #326 Defect 3. The probes did not directly test it (open question §6) but the brief's premise — that LiteLLM's `drop_params: true` silently drops the OpenAI-style `reasoning_effort` — is consistent with what we know about LiteLLM. Mark the kwarg deprecated, log a one-shot warning if used, do not inject it into the request body. Keep the param signature for backward compatibility.
5. **Per-section synthesizer routing** — the eventual fix for §2/§7:
   - §2 (Critical Timeline) — `enable_thinking=False`, `max_tokens=4000`
   - §7 (Email Intelligence) — `enable_thinking=False`, `max_tokens=4000`
   - §4/§5/§8 (productive synthesis) — `enable_thinking=True`, `thinking_token_budget=2048` (after stress test in §6 confirms enforcement)
   - §9 (post-run augmentation) — same as §4/§5/§8

Synthesizer max_tokens cap stays at 8000 (PR #327). The earlier cap=20000 work is moot once reasoning is bounded by budget.

---

## 6. Open questions / Phase 2 follow-ups

1. **Stress-test `thinking_token_budget=2048` enforcement.** My probe prompt was too short to naturally exceed the 2048-token budget — Probe D's reasoning naturally landed at ~1,195 tokens, well under cap, and Probe DL's at ~2,176 tokens (right at cap, ambiguous between "honored" and "natural stop"). The §4 production prompt at 25 KB drove ~5,414 reasoning tokens at 19:45Z. A re-run with the actual §4 prompt and budget=2048 will be conclusive: if reasoning halts cleanly near 2,048 and content still emits, the budget is enforced; if reasoning runs past 5,000 unchanged from baseline, this build doesn't honor the budget despite accepting the field. **Do this stress test before committing to budget-based routing in production.**
2. **Confirm `reasoning_effort` is inert.** Brief asserts LiteLLM drops it; my probes didn't include it. Quick follow-up probe (~1 min): `reasoning_effort: "high"` direct + via LiteLLM, compare reasoning depths to baseline. If identical to baseline, asserted inertness is empirical.
3. **Streaming response shape**. All probes used `stream=false` for cleaner response inspection. The synthesizer always streams. Verify that streamed `delta.reasoning` / `delta.reasoning_content` chunk emission still tracks per-token under each chat_template_kwargs setting (especially `enable_thinking=False` — does the model emit any reasoning deltas at all, or only content deltas?).
4. **Probe E follow-up — is `extra_body` ever read?** vLLM 0.20.1's request schema may have a forward-compatible `extra_body` field that the OpenAI Python client populates when callers use `client.chat.completions.create(..., extra_body=...)` — but our raw curl puts it as a literal JSON field. Worth verifying with a probe that uses the openai Python client directly.

---

## 7. Hard stop check

| Hard stop from brief | Status |
|---|---|
| Frontier `/health` non-200 sustained >60s | **PASS** — 200 throughout, all snapshots `/tmp/nemotron-probe-…/raw/health-snapshots.log` |
| Soak halt fires | not observed (read-only probes) |
| vLLM version unknown | **PASS** — captured |
| Probe A returned content=null with all tokens in reasoning (#39103 active) | **PASS** — content 4,427 chars, reasoning 7,755 chars, both populated |
| Disk full | **PASS** — 1.3T avail |

---

## 8. Issue #328 reframing

PR #329 reclassified §2/§7 from "missing source data" (the original #328 framing) to "runaway-reasoning failures." This probe confirms the next step:

> §2 and §7 don't need source data work. They need `chat_template_kwargs.enable_thinking=False` and a smaller `max_tokens`. The model produces clean tabular content directly when reasoning is suppressed; failure was the absence of a control mechanism, not absence of evidence.

Phase 2 (the BrainClient wiring PR) is the resolution. This PR (probe-only) is Phase 1 — empirical groundwork.

---

## 9. Artifacts

```
/tmp/nemotron-probe-20260430T212652Z/
├── inventory.json              # frontier serve-flag inventory
├── run-probe.py                # direct-vLLM probe runner
├── run-litellm-probe.py        # LiteLLM passthrough runner
├── requests/
│   ├── _prompt-base.json       # the §4-shape prompt reused across probes
│   ├── probe-{A,B,C,D,E}-body.json
│   └── probe-{BL,DL}-body.json
├── responses/
│   ├── probe-{A,B,C,D,E}-response.json     # full HTTP responses
│   ├── probe-{A,B,C,D,E}-metrics.json      # extracted metrics
│   ├── probe-{BL,DL}-response.json
│   └── probe-{BL,DL}-metrics.json
└── raw/
    └── health-snapshots.log
```

The probe artifacts live on `/tmp` (per brief) and are not in the repo. Probe runner + report (this file) are committed.

---

## 10. References

- vLLM bugs: [#39103](https://github.com/vllm-project/vllm/issues/39103), [#39573](https://github.com/vllm-project/vllm/issues/39573), [#25714](https://github.com/vllm-project/vllm/issues/25714)
- PR #326 — BrainClient TP=2 frontier compatibility (introduced now-deprecated `reasoning_effort`)
- PR #327 — synthesizer max_tokens 2000→8000 (cap stays at 8000 post-budget-control)
- PR #329 — Track A v3 analysis harvest, reclassified §2/§7 as runaway-reasoning
- Issue #328 — §2/§7 gap; this probe is Phase 1 of the resolution
