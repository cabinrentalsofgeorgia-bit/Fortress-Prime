# Nemotron-3-Super-120B-A12B-NVFP4 — Throughput & Quality Optimization Deep Research

**Date:** 2026-05-01
**Author:** Claude (planning)
**Operator:** Gary Knight, Fortress-Prime
**Scope:** Throughput, latency, quality, and long-context optimization for the TP=2 NVFP4 frontier on spark-3 + spark-4. Companion to `nemotron-3-super-deep-research-2026-04-30.md` (model-correctness focused). This doc is operations-focused.
**Frontier under analysis:** vLLM 0.20.1rc1, NVFP4, TP=2 over spark-3 (rank-0) + spark-4 (rank-1), `--gpu-memory-utilization 0.85`, `--max-model-len 256k`, no `--reasoning-config`, no MTP, no expert parallelism. Wave 4 §5 prompt tightening active. Wave 2 schema discipline ratified (top-level `chat_template_kwargs`, per-alias differentiation wire-effective).
**Status:** Wave 2 closed. This research is the gating document for any optimization PR sequence.

---

## §0 Mission

Identify every lever that affects Super-120B-NVFP4 inference throughput, latency, or quality on a dual-Spark TP=2 deployment. For each lever: expected gain, risk, prerequisite, test method, and Fortress-Prime-specific evaluation. Conclude with a ranked optimization PR sequence.

This research turns over the rocks the Wave 2 deep research did not: every flag, every env var, every kernel backend, every quality/throughput tradeoff. Where empirical numbers exist they are cited; where they don't, they are flagged as "needs measurement."

---

## §1 Empirical Throughput Reference Points (from the field)

The throughput numbers reported in NVIDIA forums and community benchmarks against Super-120B-NVFP4 on DGX Spark, sorted by configuration:

### §1.1 Single Spark (TP=1) Reference

From NVIDIA Developer Forum thread `nvidia-nemotron-3-super-120b-a12b-nvfp4/363175` (March 2026), `giraudremi92` ran `llama-benchy` against single-Spark with vLLM + Marlin backend. **Single-prompt decode throughput:**

| Context Depth | tg128 t/s (c=1) | tg128 t/s (c=2 aggregate) | per-request t/s (c=2) |
|---|---|---|---|
| 0 (cold) | 14.94 | 24.03 | 12.31 |
| 4,096 | 14.65 | 19.74 | 11.22 |
| 8,192 | 15.55 | 17.74 | 11.30 |
| 16,384 | 14.95 | 13.09 | 9.59 |

**Prefill throughput (pp2048 token/s):**

| Context Depth | pp2048 t/s (c=1) | pp2048 t/s (c=2) |
|---|---|---|
| 0 | 1622 | 1597 |
| 4,096 | 587 | 594 |
| 8,192 | 365 | 371 |
| 16,384 | 198 | 196 |

**Single-Spark observations:**
- Decode is roughly flat with context (12–15 tok/s) — Mamba-2 hybrid amortizing the attention cost
- Prefill collapses with context (1622 → 198 as context grows 0→16k)
- Concurrency-2 doubles aggregate at low context but converges back to single-stream at deep context
- `adi-sonusflow` reported ~16.6 tok/s on single-Spark Marlin path — consistent with the 14-15 tok/s decode baseline

### §1.2 Dual Spark (TP=2) Reference

From `leon-gibat` thread (`nemotron-3-super-nvfp4-via-vllm-tp-2-on-2x-dgx-spark-24-tok-s`), March 2026:
- **24 tok/s decode** on dual-Spark NVFP4 TP=2 via vLLM with eugr/spark-vllm-docker recipe
- 262K context window (1M native if `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1`)
- ConnectX-7 direct-connect 200Gbps (matches Fortress topology)
- Tested via the `nemotron-3-super-nvfp4` recipe with cu132 wheel fix `.dev176`
- vLLM 0.18.1rc1.dev121+gcd7643015.d20260325.cu132 (newer than Fortress's 0.20.1rc1 — wait, actually older — version numbering doesn't sort the way you'd think; need to verify)
- Author's note: "NVFP4 quality noticeably better than Q4_K_M GGUF" — relevant for legal reasoning quality

**Dual-Spark vs single-Spark gain: 24/15 ≈ 1.6×** at single-prompt decode. Below the 2× theoretical maximum because TP collective overhead eats some of the gain.

### §1.3 Other Reference Configurations

- **B200 8× DEP8 throughput-optimized** (NVIDIA Advanced Deployment Guide Config B): `max_batch_size: 256`, `enable_attention_dp: true`, target is enterprise scale not Fortress scale
- **B200 2× TEP2 latency-optimized** (Config A): `max_batch_size: 16`, `tp_size 2 / ep_size 2`, MTP `num_nextn_predict_layers: 3` — closest analog to Fortress topology, but B200 not GB10
- **DGX Spark TRT-LLM Config C** (Advanced Guide, single-Spark CUTLASS): `max_batch_size: 4`, `cuda_graph max_batch_size: 32`, vendor-recommended for deterministic latency
- **DGX Spark Single-Spark vLLM** (NVIDIA single-Spark deployment guide, full config): `cu130-nightly` image, `--gpu-memory-utilization 0.90`, `--max-num-seqs 4`, `--max-model-len 1000000`, `--moe-backend marlin`, MTP `num_speculative_tokens: 3`, mamba_ssm_cache_dtype float32
- **HF model card vLLM serve** (newer): `vllm/vllm-openai:v0.20.0` image, `--gpu-memory-utilization 0.9`, `--max-model-len 262144`, `--max-cudagraph-capture-size 128`, `--mamba-ssm-cache-dtype float16`, `--swap-space 0`

### §1.4 Fortress Frontier — Empirically Unmeasured

We have NOT measured Fortress's frontier in tok/s. PR #335 measured wall time (83s for §5 with low_effort=True), not tok/s decomposition. **This is the single biggest gap in the optimization roadmap** — without a baseline, any optimization PR has no measurable gain claim.

**Predicted Fortress baseline from configuration:**
- TP=2 over CX7-100Gbps direct-connect (similar to leon-gibat's 200Gbps)
- vLLM 0.20.1rc1 (newer than leon-gibat's 0.18.1rc1)
- Marlin backend (per Wave 2 deep research)
- gpu-memory-utilization 0.85 (vs leon-gibat's likely 0.7-0.85)
- No MTP, no `--reasoning-config`, default chunked-prefill

Predicted decode: **18-24 tok/s single-prompt** at low context. Drops at high context per single-Spark pattern but Mamba-2 keeps decode mostly flat. **Concurrency-2 should land 25-35 tok/s aggregate** based on the single-Spark scaling curve.

§7.1 (below) prescribes the empirical baseline measurement plan that resolves this gap.

---

## §2 Architecture Refresher — Why Levers Behave The Way They Do

Three properties of Super-120B that determine every optimization decision:

### §2.1 LatentMoE

Expert computation in compressed latent dimension `d=4096 → ℓ=1024`. All-to-all routing traffic reduced ~4× vs standard MoE. **Implication for Fortress:**

- Expert parallelism (`--enable-expert-parallel` / `--ep`) is **strongly preferred over pure TP** per NVIDIA Advanced Deployment Guide. We are NOT using EP.
- The 4× routing reduction is *especially* valuable across NVLink-class interconnect. Across CX7-100Gbps it may help less because the link is slower — measurement needed.
- The Advanced Deployment Guide's TRT-LLM Config A (2×B200) explicitly uses `tp_size 2 / ep_size 2` (TEP2), describing this as "full EP across both GPUs."
- vLLM's Advanced Guide baseline (4× GB200) uses `--enable-expert-parallel` plus TP=4. The vLLM single-Spark deployment guide explicitly says "On a single-GPU system like DGX Spark, expert parallelism is not applicable."
- **For dual-Spark TP=2:** enabling EP=2 alongside TP=2 (TEP2) is the architecturally correct configuration per the LatentMoE design. Fortress is currently leaving this unrealized.

### §2.2 MTP (Multi-Token Prediction)

One MTP layer baked into checkpoint. Functions as a tail-augmented draft model for speculative decoding. **The single most material throughput lever Fortress has not pulled.**

- MTP layer is built-in; no external draft model needed; minimal additional KV cache or latency overhead.
- NVIDIA single-Spark guide enables MTP via `--speculative_config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'`.
- Advanced guide enables MTP via `--speculative-config '{"method": "nemotron_h_mtp", "num_speculative_tokens": 5}'`.
- TRT-LLM Config A uses `decoding_type: MTP, num_nextn_predict_layers: 3, allow_advanced_sampling: true`.
- TRT-LLM throughput mode (Config B 8×B200) uses MTP with average draft acceptance length of 3.45 on SPEED-Bench at draft length 7.
- **Speedup expectation: 2-3× wall-clock for structured generation.** Legal reasoning is structured (named output blocks per Wave 4 §5 work), so MTP should benefit material.
- **Risk:** MTP interacts with the reasoning parser. The `super_v3` parser must accept multi-token-prediction output correctly. NVIDIA's recipes use MTP with super_v3 parser, so the path exists, but Fortress hasn't validated it.
- **Quality risk:** MTP draft acceptance can fall on hard tokens; the model verifies and rejects, falling back to single-token decode. No quality regression expected, but verification needed.

### §2.3 Mamba-2 Hybrid

SSM state cache (`mamba_ssm_cache`) is distinct from the KV cache. Major implications:

- **`mamba_ssm_cache_dtype`:** float32 mandated for all checkpoint precisions per Advanced Guide. NVIDIA single-Spark guide: float32. HF model card: float16. eugr recipe: implicitly float32 per Marlin path. **TRT-LLM throughput config (Config B) supports stochastic-rounded float16** with `mamba_ssm_stochastic_rounding: true, mamba_ssm_philox_rounds: 5` — measurable memory savings for negligible quality cost.
- **`enable_block_reuse: false`** is the correct setting in TRT-LLM. Mamba recurrent state is NOT prefix-cacheable. **This means standard prefix caching does NOT help Super-120B's Mamba layers.** It does help the attention layers (interleaved). Council deliberation prefix caching gain is therefore lower than for pure attention models — but not zero.
- Decode is roughly flat with context length on single-Spark (per §1.1 data). This is the Mamba-2 amortizing attention's quadratic cost. Long context (256k → 1M) is therefore *viable in principle*, throughput should not collapse at depth.

---

## §3 Optimization Lever Inventory — Full Sweep

For each lever: name, current Fortress state, NVIDIA-recommended state, expected gain, risk, prerequisite. Sorted by category.

### §3.1 Speculative Decoding

| Lever | Current | Recommended | Gain | Risk |
|---|---|---|---|---|
| MTP via `--speculative_config` | OFF | `'{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'` | 2-3× decode wall | Parser interaction, draft acceptance rate variance |
| `num_speculative_tokens` value | N/A | 3 (single-Spark guide) or 5 (advanced guide) | Higher = more draft attempts; diminishing returns and quality risk | 5 is aggressive; 3 is safer |
| `moe_backend: triton` (in spec config) | N/A | `triton` per NVIDIA single-Spark guide | Required for MTP path | None — vendor-mandated value |

**Rationale:** MTP is the highest-leverage single optimization Fortress has available. Built into checkpoint, vendor-validated, 2-3× expected gain. Should be Wave 8 §1.

### §3.2 Parallelism Strategy

| Lever | Current | Recommended | Gain | Risk |
|---|---|---|---|---|
| `--tensor-parallel-size` | 2 | 2 (no change for dual-Spark) | Locked architecture | None |
| `--enable-expert-parallel` | OFF | ON for LatentMoE per NVIDIA Advanced Guide | 5-15% latency improvement on routing-heavy generation | EP across CX7 may have higher overhead than NVLink; measurement required |
| `--pipeline-parallel-size` | 1 | 1 (no change) | Pipeline parallelism increases TTFT; not appropriate for latency-sensitive serving | None |
| `--data-parallel-size` | 1 | 1 (no change for dual-Spark TP=2) | Would require additional Sparks | N/A |

**Rationale:** EP on CX7-class interconnect is empirically untested for Super-120B specifically. Forum reports cover NVLink (B200) and single-Spark, not dual-Spark CX7. EP gain is real but Fortress-specific magnitude unknown. Should be Wave 8 §3.

### §3.3 KV Cache & Memory

| Lever | Current | Recommended | Gain | Risk |
|---|---|---|---|---|
| `--kv-cache-dtype` | fp8 | fp8 (matches all guides) | None to capture; already optimized | None |
| `--gpu-memory-utilization` | 0.85 | 0.85-0.90 (NVIDIA guides use 0.90 single-Spark, 0.85 dual-Spark via TRT-LLM) | 5% more KV cache headroom = larger batch capacity | OOM risk if other services co-tenant on spark-3 |
| `--swap-space` | default | 0 per HF model card | Removes disk-swap latency surface | None — strictly better |
| `--mamba-ssm-cache-dtype` | float32 | float32 (NVFP4 mandate) | Already correct | Quality regression if changed to float16 without stochastic rounding |
| `mamba_ssm_stochastic_rounding` (TRT-LLM only) | N/A | true with float16 mamba cache for memory savings | 3-5GB SSM cache memory freed for KV cache | Quality risk; vendor says "negligible" |
| `--enable-chunked-prefill` | unknown — likely default ON in 0.20.1rc1 | ON (vendor-mandated) | Reduces prefill TTFT for long prompts | None on 0.20.x |
| `--max-num-seqs` | unknown | 4 (single-Spark guide) or scale up if Council 7-seat parallelism | Higher = better aggregate throughput, but limited by KV cache headroom | OOM if too high |
| `--max-cudagraph-capture-size` | default 512 | 128 (HF model card) or 512 (Advanced Guide). 256 mentioned in optional flags | Reduce CUDA graph memory footprint to free KV cache | None at 128; no upside above 512 |
| `--max-model-len` | 256k | 256k (current); 1M with `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1` | Long-context viability for legal vault retrieval | KV cache memory pressure at long context; prefill cost |

**Rationale:** Most of these are minor (5-15% gains each). The `--gpu-memory-utilization 0.85 → 0.90` bump is the easiest free gain. `swap-space 0` is strictly correct.

### §3.4 Reasoning & Sampling

| Lever | Current | Recommended | Gain | Risk |
|---|---|---|---|---|
| `--reasoning-config` | NOT SET | Set to engage `thinking_token_budget` mechanism | Reasoning cap = controlled latency for legal-* aliases | Quality regression on hard prompts if budget too low |
| `thinking_token_budget` (in reasoning config) | N/A | TBD per alias (e.g., 4096 for legal-summarization, 16384 for legal-reasoning) | Bounded latency = predictable serving | Insufficient budget cuts mid-thought; degraded quality |
| `--reasoning-parser-plugin` | super_v3_reasoning_parser.py | Same | Required for thinking block extraction | None |
| `--reasoning-parser` | super_v3 | super_v3 | Required | None |
| Sampling temperature | t=0.3 (drafting), 0.5 (reasoning), 0.4 (summarization) | t=1.0 per NVIDIA spec; top_p=0.95 | Vendor's quality-validated path uses t=1.0 | Higher temperature = more variance; need eval before/after |
| Sampling top_p | unknown | 0.95 per NVIDIA spec | Vendor-validated | None |
| `force_nonempty_content` (per-alias kwarg) | TRUE per Wave 2 schema fix | TRUE | Prevents empty content blocks | None — Wave 2 ratified |
| `enable_thinking` (per-alias kwarg) | varies per alias | varies | Per-alias differentiation wire-effective per PR #338 | None — Wave 2 ratified |
| `low_effort` (per-alias kwarg) | TRUE for some legal-* aliases | per-alias | Reasoning depth control | None — Wave 2 ratified |
| `--enable-auto-tool-choice` | UNKNOWN | ON (vendor recipe) | Tool calling support for agentic workloads | None |
| `--tool-call-parser` | UNKNOWN | qwen3_coder (vendor recipe) | Vendor-validated parser | None |

**Rationale:** Engaging `--reasoning-config` is the second-highest-leverage lever after MTP. It moves reasoning depth from "always full" (current state, was the schema-defect symptom Wave 2 corrected, now schema-correct but unbounded for some aliases) to "bounded per-alias." For legal-summarization, this turns a 19090-char reasoning prefix into a configured budget — direct latency lever.

### §3.5 Quantization & Numerics

| Lever | Current | Recommended | Gain | Risk |
|---|---|---|---|---|
| `--quantization` | fp4 | fp4 | Already optimized (NVFP4 native) | None |
| `--moe-backend` | marlin | marlin (single-Spark guide) or CUTLASS (dual-GPU) | Marlin verified working on Spark; CUTLASS faster on Blackwell multi-GPU | CUTLASS may not work on dual-Spark CX7 |
| `VLLM_NVFP4_GEMM_BACKEND` | marlin | marlin | NVIDIA single-Spark guide mandates marlin on GB10 | None |
| `VLLM_USE_FLASHINFER_MOE_FP4` | 0 | 0 single-Spark; 1 multi-GPU latency mode | "FlashInfer FP4 MoE kernels are Blackwell multi-GPU only" per NVIDIA single-Spark guide | If 1 enabled wrongly on Spark, causes failures |
| `VLLM_USE_FLASHINFER_MOE_FP8` | OFF | ON if running FP8 path; OFF for NVFP4 | N/A for NVFP4 | None |
| `VLLM_FLASHINFER_MOE_BACKEND` | N/A or unset | `latency` (online serving) or `throughput` (offline batch) | Vendor-mandated for online | None |
| `VLLM_FLASHINFER_ALLREDUCE_BACKEND` | trtllm | trtllm | Required for AllReduce on this topology | Fixed upstream in vllm#35793 |
| `VLLM_ALLOW_LONG_MAX_MODEL_LEN` | 1 (per Wave 2) | 1 (required for max_model_len > checkpoint native) | Required for long-context | None |
| `VLLM_MOE_PADDING_SIZE` | UNKNOWN | 512 mentioned in HF discussion thread for single-Spark | Possibly relevant for single-Spark; uncertain for dual | Untested on dual-Spark |

**Rationale:** Quantization stack is largely correct on Fortress. The main question is `VLLM_FLASHINFER_MOE_BACKEND=latency` — vendor-recommended for online serving — which Fortress may or may not have set.

### §3.6 Prefix Caching

| Lever | Current | Recommended | Gain | Risk |
|---|---|---|---|---|
| `--enable-prefix-caching` | UNKNOWN | Enable for Council 7-seat deliberation pattern | 2-5× latency reduction on cache-hit prefixes | Memory cost; cache-miss path same as no caching |
| `enable_block_reuse` (TRT-LLM) | N/A | `false` for Mamba layers (vendor mandate) | N/A — vLLM uses different mechanism | If enabled, may break Mamba recurrent state |
| NVIDIA Dynamo | NOT DEPLOYED | Could deploy as inference orchestration layer | Dynamo claims 2-5× latency on repeated prefixes via KV-aware routing | Major architectural change; deferred |

**Rationale:** Council deliberation reuses substantial case context across the 7 seats. Prefix caching gain is real but partially blunted by Mamba-2 architecture (Mamba state not cacheable). Attention layers benefit; SSM layers don't. Net gain is harder to predict than for pure-attention models. Should be measured before deploying Dynamo.

### §3.7 Loading & Container

| Lever | Current | Recommended | Gain | Risk |
|---|---|---|---|---|
| Container image | likely cu130-nightly or vllm/vllm-openai:v0.20.1rc1 | `vllm/vllm-openai:v0.20.0` (HF model card, current stable) or `cu130-nightly` (NVIDIA single-Spark guide) or `nvcr.io/nvidia/vllm:26.03.post1-py3` (NGC, newest mentioned) | Newer = more bug fixes; older = more validated | Stability cliff with each version bump |
| `--load-format fastsafetensors` | UNKNOWN | ON (eugr recipe) — uses multi-threaded loading | 2-5× model load time reduction (cold start) | Not for >0.85 RAM utilization; OOM risk |
| `--load-format instanttensor` | N/A | EXPERIMENTAL per eugr 2026-04-14 changelog | Faster loading than fastsafetensors | Experimental |
| `--async-scheduling` | UNKNOWN | ON (NVIDIA single-Spark guide) | Improved single-GPU throughput | None |
| `--distributed-executor-backend` | likely ray for TP=2 | ray (Wave 1 baseline) or pytorch (`--no-ray` per eugr) | `--no-ray` ~1 t/s improvement, less memory | Different orchestration semantics |

**Rationale:** Container image choice is non-trivial. NVIDIA's published guides recommend cu130-nightly OR vllm/vllm-openai:v0.20.0. Fortress is on 0.20.1rc1. Either upgrade or downgrade is a deliberate decision; need to validate Fortress's specific frontier behavior against the recommended images.

### §3.8 GB10-Specific Considerations

From the embed deep research §2 plus this research's findings:

- **Driver:** 580.x recommended per eugr 2026-03-12 changelog. **590.x has CUDAGraph capture deadlock on GB10 unified memory.** Verify Fortress driver version before any optimization PR.
- **GPU clock frequency:** eugr recommends `nvidia-smi -lgc 200,2150` for stability under sustained heavy inference (some firmware causes sudden shutdown at 2411 MHz default on GB10). Doesn't survive reboot. Operational discipline issue.
- **GPU architecture flag:** `12.1a` (default) or `12.0f` if rebuilding. Fortress likely on 12.1a.
- **Unified memory specifics:** GB10 reports "memory.free" via nvidia-smi but the value is misleading on unified memory architecture. Use `docker stats` for container-level memory accounting (per embed deep research §7A — already adopted).
- **CUDAGraph:** `--max-cudagraph-capture-size` controls memory footprint for graph capture. Fortress is at default. NVIDIA single-Spark guide implicitly uses default; HF model card uses 128.
- **Mamba state stochastic rounding** is GB10-compatible (Philox-based, runs on unified memory).

---

## §4 Throughput Stack — Ranked by Expected Gain × Risk

| Rank | Lever | Expected Gain | Risk | Prerequisite | Effort |
|---|---|---|---|---|---|
| 1 | **MTP speculative decoding** | 2-3× decode wall-clock | Parser interaction validation | Reasoning parser handles MTP output (NVIDIA recipes do this) | Add `--speculative_config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'`; benchmark before/after |
| 2 | **`--reasoning-config` engagement** | Variable; bounded latency for legal-summarization, no gain for legal-reasoning at default depth | Quality regression on undersized budgets | Per-alias budget calibration | Add to frontier serve flags; per-alias `thinking_token_budget` |
| 3 | **`--enable-expert-parallel` (TEP2)** | 5-15% routing-heavy gain | Untested on CX7 dual-Spark; may regress | Empirical test on Fortress topology | Add `--enable-expert-parallel` to frontier serve flags; benchmark |
| 4 | **`--enable-prefix-caching`** for Council deliberation | 1.5-3× on Council 7-seat with shared context | Memory cost, cache-miss path same as no caching | Measure Council prefix cache hit rate first | Add flag; capacity planning for cache memory |
| 5 | **`--gpu-memory-utilization 0.85 → 0.90`** | 5% larger KV cache = better at high concurrency | Headroom for spark-3 co-tenancy with EMBED | Spark-3 EMBED memory profile | One-flag change |
| 6 | **`--moe-backend marlin → cutlass`** (if vLLM 0.20.1rc1 supports CUTLASS on Spark dual-node) | Possibly faster on Blackwell multi-GPU | CUTLASS path may not work on CX7 | Test in staging first | Flag change; staging validation |
| 7 | **`--max-num-seqs` increase from default to 8 or 16** | Council 7-seat parallel throughput | OOM risk | KV cache headroom (depends on lever 5) | Flag change; benchmark |
| 8 | **`--load-format fastsafetensors`** | 2-5× model cold-start reduction | Not for >85% RAM | Verify load-time RAM headroom | Flag change |
| 9 | **NVIDIA Dynamo prefix caching** | 2-5× on repeated prefixes | Major architectural change | Deferred — significant infrastructure work | Wave 9+ |
| 10 | **vLLM image upgrade** to `vllm/vllm-openai:v0.20.0` (HF) or `cu130-nightly` (NVIDIA) | Stability + bug fixes; possibly throughput | Each version has stability cliff | Stage on spark-5 (freed) before frontier rotate | Container image change with rollback plan |

**Effort grouping:**

- **One-line changes** (highest ROI): MTP, reasoning-config, gpu-memory-utilization, max-num-seqs, fastsafetensors, swap-space=0
- **Multi-flag changes**: TEP2, prefix-caching, container image
- **Infrastructure work**: Dynamo

**Risk grouping:**

- **Low risk** (vendor-validated, easy rollback): MTP, reasoning-config, swap-space, max-cudagraph-capture-size, fastsafetensors
- **Medium risk** (Fortress-specific testing needed): TEP2, prefix-caching, gpu-memory-utilization, max-num-seqs
- **High risk** (architectural): container image, Dynamo, mamba_ssm float16+stochastic rounding

---

## §5 Quality vs Throughput Tradeoff Matrix

Some optimizations are pure throughput; others trade quality. The matrix:

| Lever | Throughput | Quality |
|---|---|---|
| MTP | + | neutral (model verifies and rejects bad drafts) |
| `--reasoning-config` (well-calibrated budget) | + | neutral |
| `--reasoning-config` (under-calibrated budget) | + | – (cuts mid-thought) |
| TEP2 | + | neutral |
| Prefix caching | + | neutral (deterministic decode unchanged) |
| `--gpu-memory-utilization 0.90` | + | neutral |
| `--max-num-seqs` increase | + | neutral (per-request latency may regress slightly) |
| Sampling temperature t=0.4 → t=1.0 | neutral | + (vendor-validated path) but more variance |
| Mamba SSM float16+stochastic | + | – (negligible per vendor; needs Fortress eval) |
| Fastsafetensors loading | + cold-start | neutral runtime |

**Sampling discipline.** Wave 2 deep research §0.3 explicitly documented Fortress sampling deviation from NVIDIA spec (t=0.3/0.5/0.4 vs spec t=1.0/top_p=0.95). The deviation was operational discipline (lower variance for legal output) but it's an empirical question whether NVIDIA's t=1.0 actually produces better legal reasoning. For Case II, an A/B with v3 Case I brief baseline is the right test.

---

## §6 Long-Context Viability — 256k → 1M

Currently Fortress runs at `--max-model-len 256k`. Native model context is 1M tokens.

### §6.1 What 1M Context Gets You

- Whole legal vault retrieval in single context (no chunking, no retrieval pipeline as Phase B prerequisite)
- Multi-document legal reasoning without RAG architecture
- Full deposition + relevant case law + brief structure in single prompt

### §6.2 Throughput Viability

From single-Spark §1.1 data, decode is roughly flat with context (12-15 tok/s @ 16k vs 14-15 @ 0). If this scaling holds at 256k+ (Mamba-2 is theoretically O(n) for sequence length, vs O(n²) for attention), 1M context decode should be on the order of 8-12 tok/s. **Empirically untested at 256k+ for Super-120B.**

Prefill is the cost: 1622 → 198 tok/s as context grows 0 → 16k. At 1M context, prefill could be ~2-5 tok/s. **A 1M token prefill at 5 tok/s is ~2.3 days of compute.** Not viable for interactive use; viable for long-running offline analysis.

### §6.3 Memory Viability

KV cache at fp8 dtype scales linearly with context. At 1M context with TP=2 split:

- KV cache size ≈ ~80GB at fp8 for Super-120B with full context (estimated; requires confirmation)
- Mamba SSM state is sequence-independent, ~3-5GB
- Model weights at NVFP4: ~70GB total, ~35GB per Spark with TP=2
- Total per Spark at 1M context: 35 + 5 + 40 = ~80GB; under 128GB unified

**Memory feasibility: yes** for 1M context with TP=2 fp8 KV. But the 80GB number needs empirical validation — Fortress at 256k currently doesn't stress this.

### §6.4 Recommendation

Long-context unlock is **a separate research direction, not a Wave 8 optimization PR**. Prerequisite: Wave 3 retrieval stack first (the architectural answer to long-context is retrieval-augmented, not single-prompt 1M). Once retrieval lands, long-context becomes a quality lever for specific cases (e.g., whole-deposition analysis), not a default mode.

For Wave 8 optimization, hold at 256k. Revisit 1M after retrieval stack lands.

---

## §7 Empirical Baseline Plan

The single biggest gap in this research is that we don't have Fortress baseline numbers. Wave 8 optimization PRs without a baseline have no measurable claim. Plan:

### §7.1 Baseline Measurement (prerequisite to all optimization PRs)

Use `vllm bench serve` per NVIDIA's Nemotron-3-Nano benchmark recipe:

```bash
vllm bench serve \
  --host 10.10.10.3 \
  --port 8000 \
  --model nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4 \
  --trust-remote-code \
  --dataset-name random \
  --random-input-len 1024 \
  --random-output-len 1024 \
  --num-warmups 20 \
  --max-concurrency 1 \
  --num-prompts 16 \
  --save-result --result-filename baseline-c1-i1024-o1024.json
```

Repeat at concurrency 2, 4, 7 (Council seat count), 8.

Plus context-depth sweep at concurrency 1: input lengths 0, 4096, 8192, 16384, 32768, 65536. Decode 1024.

Plus legal-workload simulation: actual Wave 4 §5 prompts at concurrency 1, 7. Measure §5 wall time, decode tok/s, prefill tok/s, time to first token (TTFT), time per output token (TPOT), inter-token latency (ITL).

### §7.2 Baseline Deliverables

- `tests/benchmarks/super-120b-baseline-2026-MM-DD.json` — vllm bench raw output
- `docs/operational/super-120b-baseline-2026-MM-DD.md` — interpreted findings table
- Comparison vs §1.2 leon-gibat 24 tok/s reference
- Identification of Fortress-specific bottlenecks (e.g., if decode is ~12 tok/s vs leon-gibat's 24, investigate before optimizing)

### §7.3 Baseline → Optimization PR Sequence

After baseline lands:
- Each optimization PR includes a re-run against the same benchmark suite
- Gain claim is empirical: "MTP enabled: decode tok/s 14 → 38, +171%"
- Failures to replicate vendor-claimed gains surface a Fortress-specific issue worth investigating

---

## §8 Council-Specific Tuning

Fortress runs Council 7-seat parallel deliberation pattern. This is a workload optimization problem.

### §8.1 7-Seat Concurrency Profile

If 7 seats run in parallel against the frontier:
- `--max-num-seqs` must be ≥ 7
- KV cache headroom must accommodate 7 simultaneous reasoning prefixes
- Per-seat decode tok/s = aggregate / 7 (assuming equal load)
- From single-Spark c=2 data: per-request t/s drops ~50% at c=2; at c=7 expect heavier per-seat regression

### §8.2 Prefix Cache Hit Rate for Council

Council seats share substantial context: case file, retrieved precedents, brief structure. Per-seat prompts diverge in the synthesis instruction. If prefix caching lands:
- Shared-prefix hits → 70-85% of input tokens cached
- Each seat's prefill cost drops from full-context to instruction-only
- Wall-clock for Council deliberation could halve

This is the **largest single throughput gain available** for Council workload specifically. Higher than MTP for this pattern.

### §8.3 Recommendation

Two prerequisites before Council-pattern optimization:
1. Empirical Council deliberation profile — what does the cache-hit rate actually look like?
2. Prefix caching enabled

Council-specific tuning is a Wave 9 (or later) workstream after generic Wave 8 optimization lands.

---

## §9 Production Reference Comparison

Side-by-side table of Fortress current vs canonical references:

| Flag/Env | Fortress Current | NVIDIA Single-Spark | NVIDIA Advanced (Config A 2×B200) | HF Model Card | eugr Community | Recommendation for Fortress |
|---|---|---|---|---|---|---|
| Image | vllm/vllm-openai:v0.20.1rc1 | vllm/vllm-openai:cu130-nightly | (vLLM 0.17.1 baseline) | vllm/vllm-openai:v0.20.0 | eugr custom build | Stay on 0.20.1rc1; revisit if optimization PRs reveal version-specific bugs |
| --tensor-parallel-size | 2 | 1 | 2 (with EP=2) | varies | 2 | 2 (locked) |
| --enable-expert-parallel | OFF | N/A (single-Spark) | ON | N/A | varies | **Test ON for Fortress dual-Spark** |
| --speculative_config | N/A (off) | mtp 3 / triton | mtp 3 (TRT-LLM) | not in HF cmd | varies | **Enable MTP** |
| --reasoning-config | NOT SET | not in cmd | N/A | not in HF cmd | not in recipe | **Set per-alias** |
| --kv-cache-dtype | fp8 | fp8 | fp8 | fp8 | fp8 | fp8 (correct) |
| --gpu-memory-utilization | 0.85 | 0.90 | 0.80 (free_gpu_mem fraction) | 0.9 | 0.7-0.85 | **Bump to 0.90 if spark-3 co-tenancy headroom permits** |
| --mamba_ssm_cache_dtype | float32 | float32 | float32 | float16 | float32 | float32 (correct for NVFP4) |
| --moe-backend | marlin | marlin | TRTLLM (TRT-LLM only) | not in HF cmd | marlin | marlin (correct) |
| --enable-chunked-prefill | likely on | ON | ON | ON | varies | ON (correct) |
| --max-num-seqs | unknown | 4 | N/A (max_batch_size 16 in TRT) | not in HF cmd | varies | **Test 8 or 16 for Council pattern** |
| --max-model-len | 262144 | 1000000 | 262144 | 262144 | varies | 262144 (correct for current Phase B; revisit for long-context) |
| --max-cudagraph-capture-size | default 512 | default | N/A | 128 | varies | 128 (HF cmd) for memory savings |
| --reasoning-parser | super_v3 | super_v3 | nano-v3 (TRT-LLM) | super_v3 | super_v3 | super_v3 (correct) |
| --tool-call-parser | UNKNOWN | qwen3_coder | qwen3_coder | qwen3_coder | varies | **Verify qwen3_coder set** |
| --enable-auto-tool-choice | UNKNOWN | ON | ON | ON | varies | **Verify ON** |
| --load-format | likely mmap default | not specified | N/A | not specified | fastsafetensors | **Test fastsafetensors** |
| --swap-space | default | not specified | N/A | 0 | not specified | **0** |
| --async-scheduling | UNKNOWN | ON | N/A | not specified | varies | **Verify ON** |
| VLLM_NVFP4_GEMM_BACKEND | marlin | marlin | N/A | marlin | marlin | marlin (correct) |
| VLLM_USE_FLASHINFER_MOE_FP4 | 0 | 0 | 1 | 0 | 1 | 0 single-Spark; **test 1 for dual-Spark** |
| VLLM_FLASHINFER_MOE_BACKEND | UNKNOWN | not set (single-Spark uses marlin) | latency | not set | varies | **latency for online serving** |
| VLLM_FLASHINFER_ALLREDUCE_BACKEND | trtllm | trtllm | trtllm | trtllm | varies | trtllm (correct) |
| VLLM_ALLOW_LONG_MAX_MODEL_LEN | 1 | 1 | N/A | 1 | varies | 1 (correct) |

**Unknowns to resolve in baseline measurement:**

- `--max-num-seqs` actual value
- `--enable-chunked-prefill` actual state
- `--enable-auto-tool-choice` actual state
- `--tool-call-parser` actual state
- `--load-format` actual state
- `--swap-space` actual state
- `--async-scheduling` actual state
- `VLLM_FLASHINFER_MOE_BACKEND` actual state

These should be captured in the baseline pass via inspection of the active vLLM frontier service unit + env file.

---

## §10 Recommended Optimization PR Sequence — Wave 8

Sequenced PRs for the optimization rollout. Each PR includes empirical before/after benchmark.

### §10.1 PR-1: Baseline Measurement (no optimization, just measure)

- Capture full Fortress frontier serve flag inventory (resolve unknowns above)
- Run vllm bench serve at concurrency 1, 2, 4, 7 with input/output length sweeps
- Run Wave 4 §5 prompt against current config, capture decode/prefill tok/s
- Document baseline table
- Single-file PR: `docs/operational/super-120b-baseline-2026-MM-DD.md`

**Gates:** none (read-only).

### §10.2 PR-2: Low-Risk One-Flag Optimizations (free wins)

- Add `--swap-space 0` (HF model card)
- Set `--max-cudagraph-capture-size 128` (HF model card)
- Verify `--async-scheduling` enabled
- Verify `--enable-auto-tool-choice` and `--tool-call-parser qwen3_coder` for tool-calling correctness
- Re-run bench, document gain
- PR includes baseline diff + new bench

**Gates:** halt if any benchmark regresses.

### §10.3 PR-3: GPU Memory Utilization Bump

- `--gpu-memory-utilization 0.85 → 0.90`
- Verify spark-3 EMBED co-tenancy headroom holds
- Re-run bench at high concurrency (where KV cache pressure shows)
- Co-residency monitor (per Wave 3 amendment §0.4) active during bench

**Gates:** halt if EMBED degrades or frontier OOM.

### §10.4 PR-4: MTP Speculative Decoding (highest-leverage single change)

- Add `--speculative_config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}'`
- Validate super_v3 parser handles MTP output correctly
- Validate quality on v3 Case I brief reproduction (no quality regression vs baseline)
- Re-run bench; expected 2-3× decode wall-clock gain

**Gates:** halt if quality regresses on Case I brief reproduction; halt if parser errors emerge.

### §10.5 PR-5: Reasoning Config Engagement

- Add `--reasoning-config` to frontier serve flags
- Per-alias `thinking_token_budget` calibration:
  - legal-summarization: 4096 (was 19090 char prefix → bounded)
  - legal-reasoning: 32768 (preserve depth)
  - legal-drafting: 16384
  - legal-analysis: 24576
  - legal-research: 16384
- LiteLLM alias config update with top-level chat_template_kwargs (Wave 2 schema)
- Re-run bench + Wave 4 §5 prompt
- Validate quality on v3 Case I brief

**Gates:** halt on quality regression; halt on schema violation per PR #338 discipline.

### §10.6 PR-6: Expert Parallelism Test (TEP2)

- Add `--enable-expert-parallel` to frontier serve flags
- Re-run bench; compare against PR-2 baseline
- Watch for CX7-specific regressions on EP all-to-all traffic
- Decision gate: if gain < 5% or regression, revert
- If gain holds, retain for production

**Gates:** halt on regression; halt on NCCL collective timeout.

### §10.7 PR-7: Prefix Caching for Council Workload

- Add `--enable-prefix-caching` to frontier serve flags
- Add Council prefix-cache hit-rate telemetry
- Re-run Council 7-seat deliberation profile
- Memory pressure check (cache memory vs KV cache headroom)
- If hit-rate < 50% on Council pattern, decision gate: keep for general workload, accept lower-than-claimed gain

**Gates:** halt on memory pressure causing OOM.

### §10.8 PR-8: Concurrency Tuning

- `--max-num-seqs` bump to value determined by PR-3 + PR-7 KV cache headroom
- Council 7-seat parallel deliberation as primary test
- Document aggregate vs per-seat throughput
- Calibrate against operator UX expectations

**Gates:** halt if per-seat tok/s drops below 5 tok/s (UX threshold).

### §10.9 Future PRs (scoped out of Wave 8)

- PR-9+: NVIDIA Dynamo prefix-cache routing (architectural; significant work)
- PR-10+: Long-context unlock to 1M (post-Wave 3 retrieval landing)
- PR-11+: Container image upgrade evaluation (cu130-nightly or v0.20.0)
- PR-12+: Mamba SSM stochastic-rounded float16 (TRT-LLM only; Fortress is vLLM)

---

## §11 Schema Discipline Carry-Forward (Wave 2 → Wave 8)

PR #338 ratified that all chat_template_kwargs MUST be top-level on the request body, never `extra_body`-wrapped. This applies to optimization PRs that touch alias configs:

- PR-5 (reasoning-config) carries `thinking_token_budget` per-alias as **top-level chat_template_kwargs**, not extra_body
- Any new alias added (e.g., for MTP testing) follows the same discipline
- LiteLLM gateway must be re-verified after each alias config change to confirm wire-effective differentiation

Schema discipline is non-negotiable; optimization PRs that violate it require revert.

---

## §12 Sampling Specification Discipline

Wave 2 deep research §0.3 documented Fortress sampling deviation from NVIDIA spec:
- Fortress: t=0.3 (drafting), 0.5 (reasoning), 0.4 (summarization)
- NVIDIA spec: t=1.0, top_p=0.95

This deviation was a deliberate operator decision for legal output discipline. Optimization PRs do NOT change sampling parameters unless the optimization specifically targets sampling (none in this Wave 8 plan).

A separate research direction (out of Wave 8 scope): A/B test NVIDIA spec t=1.0 against Fortress t=0.3-0.5 for legal reasoning quality. Resolve via Case I brief reproduction at both temperatures, judged by operator. This is not throughput work, it's quality calibration.

---

## §13 Failure Modes & Rollback

Each optimization lever has a known failure mode. Documented for runbook completeness:

| Lever | Failure Mode | Symptom | Rollback |
|---|---|---|---|
| MTP | Parser doesn't handle multi-token output | Reasoning blocks malformed; super_v3 parser errors | Remove --speculative_config; restart |
| reasoning-config | Budget too low | Truncated reasoning; mid-thought cutoffs in legal output | Increase budget; restart |
| TEP2 | CX7 collective timeout | NCCL collective errors in vLLM logs; frontier hangs | Remove --enable-expert-parallel; restart |
| Prefix caching | Cache memory pressure | OOM or KV cache eviction storms | Remove --enable-prefix-caching; restart |
| GPU memory util 0.90 | EMBED on spark-3 OOM | EMBED HTTP 500; spark-3 docker stats RSS approaching limit | Revert to 0.85; restart frontier |
| Container image change | API incompatibility | Service won't start or crashes on first request | Revert image; restart |
| Driver 590.x | CUDAGraph capture deadlock | Frontier hangs at startup; never enters serving state | Downgrade driver to 580.x |
| Mamba float16+stochastic | Quality regression | Legal output quality drops on hard prompts | Revert to float32; restart |

---

## §14 Open Questions (NOT resolved in this research)

The following are gaps that this research surfaces but cannot answer:

1. **Does CUTLASS MoE backend work on dual-Spark CX7?** vLLM 0.20.1rc1 may have improved this since Wave 2. Test in PR-2 staging.
2. **Council prefix-cache hit rate.** Empirical question; resolved by PR-7 telemetry.
3. **Optimal `thinking_token_budget` per legal-* alias.** Empirical; PR-5 calibration phase.
4. **Fortress baseline tok/s.** Empirical; PR-1 result.
5. **Dynamo deployment cost-benefit.** Architectural question; deferred to Wave 9+.
6. **NVFP4 vs FP8 quality on legal reasoning.** Sampling experiment; out of Wave 8 scope.
7. **Long-context tail throughput at 256k+.** Empirical; PR-1 context-depth sweep gives initial data, full validation requires 256k+ specific test.
8. **NVIDIA Dynamo specifics for prefix routing.** Not researched in detail in this pass; needs separate research before PR-9.
9. **Council 7-seat concurrency vs latency tradeoff.** PR-8 calibration phase.

---

## §15 Sources

**NVIDIA official documentation:**
- Single-Spark Deployment Guide: https://docs.nvidia.com/nemotron/nightly/usage-cookbook/Nemotron-3-Super/SparkDeploymentGuide/README.html
- Advanced Deployment Guide: https://docs.nvidia.com/nemotron/nightly/usage-cookbook/Nemotron-3-Super/AdvancedDeploymentGuide/README.html
- vLLM Recipes — Nano benchmark methodology: https://docs.vllm.ai/projects/recipes/en/latest/NVIDIA/Nemotron-3-Nano-30B-A3B.html
- NeMo GitHub canonical configs: https://github.com/NVIDIA-NeMo/Nemotron/tree/main/usage-cookbook/Nemotron-3-Super

**HuggingFace:**
- Model card with HF model serve command: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4
- Model card discussion thread (DGX Spark deployment field reports): https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4/discussions/14

**vLLM blog:**
- Run Highly Efficient Multi-Agent AI with Nemotron 3 Super: https://vllm.ai/blog/nemotron-3-super

**Community references:**
- eugr/spark-vllm-docker: https://github.com/eugr/spark-vllm-docker (1.1k stars; dual-Spark recipes; Nemotron-3-Super recipe at recipes/nemotron-3-super-nvfp4.yaml)
- Leon Gibat dual-Spark TP=2 24 tok/s: https://forums.developer.nvidia.com/t/nemotron-3-super-nvfp4-via-vllm-tp-2-on-2x-dgx-spark-24-tok-s-abi-fix-for-cu130-cu132-mismatch/364862
- Single-Spark benchmark thread (giraudremi92, llama-benchy data): https://forums.developer.nvidia.com/t/nvidia-nemotron-3-super-120b-a12b-nvfp4/363175
- Single-Spark Marlin path field report (adi-sonusflow 16.6 tok/s): same thread
- Nano "65+ tps" reference with technique transfer: https://forums.developer.nvidia.com/t/dgx-spark-nemotron3-and-nvfp4-getting-to-65-tps/355261

**Fortress-Prime artifacts:**
- `docs/research/nemotron-3-super-deep-research-2026-04-30.md` (Wave 2 schema-correctness companion)
- `docs/research/llama-nemotron-embed-1b-v2-deep-research-2026-04-30.md` (co-residency methodology adopted here)
- `docs/operational/phase-9-wave-2-alias-surgery-brief.md` §0 reconciliation pattern (Wave 2)
- `docs/architecture/cross-division/_architectural-decisions.md` ADR-007 LOCKED (TP=2 frontier)
- PR #335 Wave 4 §5 prompt tightening (operational baseline reference)
- PR #336 EMBED ratification (co-residency baseline on spark-3)
- PR #337-#340 Wave 2 ratification sequence (schema discipline + retirement runbook)

---

## §16 Conclusions

1. **MTP is the largest single throughput lever Fortress has not pulled.** 2-3× decode wall-clock expected. Built into the checkpoint. Vendor-validated. Wave 8 §1.

2. **Engaging `--reasoning-config` is the second-largest lever** for legal-* alias serving, especially legal-summarization which currently has unbounded reasoning depth post-Wave-2.

3. **Expert parallelism (TEP2) is the architecturally correct choice** for LatentMoE on dual-Spark, but CX7-specific gain is empirically untested. Wave 8 §3 with explicit revert path.

4. **Fortress baseline is unmeasured.** This is the single biggest gap. PR-1 fixes it. Without baseline, no optimization PR has a measurable claim.

5. **Long-context unlock to 1M is a separate research direction**, not a Wave 8 PR. Prerequisite: Wave 3 retrieval stack lands first.

6. **Schema discipline (PR #338) and sampling discipline (Wave 2 §0.3) carry forward** into all Wave 8 PRs unchanged.

7. **Council prefix-cache hit rate is an empirical question** that determines whether prefix caching is high-leverage or modest-gain for Fortress. Resolves via PR-7.

8. **Driver version (580.x vs 590.x)** must be verified before any optimization PR. 590.x has known CUDAGraph deadlock.

9. **Container image is currently 0.20.1rc1.** NVIDIA recommends cu130-nightly OR v0.20.0. Either upgrade or downgrade is a deliberate decision. Defer until other optimizations land or specific bug surfaces.

10. **Wave 8 PR sequence: baseline → low-risk wins → memory utilization → MTP → reasoning-config → TEP2 → prefix caching → concurrency tuning.** Each PR includes empirical before/after; halt on regression.

---

## §17 Recommended Next Action

Two paths:

**Path A — Wave 3 amendment first, then Wave 8 baseline.** Wave 3 retrieval is blocking Phase B Case II. Optimization can wait. This research stays as reference doc for Wave 8 when it kicks off.

**Path B — Wave 8 baseline (PR-1) interleaved with Wave 3.** PR-1 is read-only (no service mutation), can run in parallel with Wave 3 amendment doc-PR. Yields baseline for Wave 8 sequencing without blocking Wave 3.

Recommendation: **Path B.** PR-1 is small, doesn't deploy, doesn't conflict with Wave 3. Returns concrete numbers that ground all subsequent optimization decisions.

After PR-1 baseline lands and Wave 3 retrieval lands, Wave 8 §10.2 starts.

---

End of research.
