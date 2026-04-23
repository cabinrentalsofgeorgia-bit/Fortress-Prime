# Nemotron NIM Bake-off — Escalation Memo
_Date: 2026-04-22 | STOP — Three independent blockers require Gary's decision_

## Summary

Three independent blockers halted Phase 1 execution before any production config was
changed. No spark-1 NIM was touched. No prod routing was modified. All findings are
pre-deployment discovery.

---

## Blocker 1 — Nemotron-H requires trust_remote_code (training)

**Phase affected:** Phase 2 Step 4 (HF+PEFT training on Nemotron base)

**Finding:** `nvidia/NVIDIA-Nemotron-Nano-12B-v2` uses model_type `nemotron_h`
(Mamba-Attention hybrid), which ships custom Python files:
- `configuration_nemotron_h.py`
- `modeling_nemotron_h.py`

HuggingFace requires `trust_remote_code=True` to load this model. The mission
constraint is explicit: **"No trust_remote_code."**

**Evidence:**
```
HF repo: nvidia/NVIDIA-Nemotron-Nano-12B-v2
model_type: nemotron_h
Custom files present: configuration_nemotron_h.py, modeling_nemotron_h.py
license: other (NVIDIA Open Model License)
```

**Verification command (reproducible):**
```bash
curl -s https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-12B-v2/raw/main/config.json \
  | python3 -c "import sys,json; c=json.load(sys.stdin); print(c.get('model_type'))"
# Output: nemotron_h
```

**Impact:** Cannot train a legal LoRA adapter on Nemotron-nano base using
the existing HF+PEFT pipeline. Phase 2 Step 4 cannot be executed as specified.

**What this does NOT block:** NIM inference. NIM containers package
their own model runtime internally — trust_remote_code is irrelevant for
deploying the pre-built NIM image.

---

## Blocker 2 — NGC auth scope: only DGX-Spark paths accessible

**Phase affected:** Phase 1 Step 1 (pulling nemotron-nano-12b-v2 for ELF verify)

**Finding:** Current docker credentials for `nvcr.io` only grant access to
DGX Spark-specific container paths and the cached VL model. General NIM catalog
models return "Access Denied."

**Evidence — manifest inspect results:**

| Image | Result |
|-------|--------|
| `nvcr.io/nim/meta/llama-3.1-8b-instruct-dgx-spark:latest` | ✅ Accessible |
| `nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl:1.6.0` | ✅ Accessible (cached) |
| `nvcr.io/nim/nvidia/nemotron-nano-12b-v2:1.6.0` | ❌ Access Denied |
| `nvcr.io/nim/nvidia/nemotron-mini-4b-instruct:1.1.0` | ❌ Access Denied |
| `nvcr.io/nim/nvidia/llama-guard-3-8b:1.3.0` | ❌ Access Denied |
| `nvcr.io/nim/nvidia/qwen2.5-7b-instruct:1.3.2` | ❌ Access Denied |
| `nvcr.io/nim/mistralai/mistral-7b-instruct-v0.3:1.2.0` | ❌ No such manifest |

NGC REST API returns HTTP 403 FORBIDDEN for all API key queries against non-accessible models.

**Root cause hypothesis:** The NGC API key in `/etc/fortress/nim.env` is scoped to
DGX Spark entitlements only, not the general NIM catalog. Gary's NGC account may need
to be linked to the NIM catalog subscription, or a new API key with broader scope needs
to be generated.

**What this does NOT block:** Inference using the two accessible images
(`llama-3.1-8b-instruct-dgx-spark`, `nemotron-nano-12b-v2-vl`).

---

## Blocker 3 — spark-1 memory constraint (60% rule)

**Phase affected:** Phase 1 Step 2 (deploy Nemotron NIM on spark-1)

**Finding:** spark-1 is currently at 55.9% memory utilization. Adding a second
NIM for nemotron-nano-12b-v2-vl (~24 GiB bf16) would push to ~75%.

**Evidence:**
```
spark-1 memory (2026-04-22 inspection):
  Total:     121.7 GiB
  Used:       68.0 GiB (55.9%)
  Available:  52.0 GiB
  Threshold:  76.8 GiB (60%)
  Headroom:   +8.8 GiB before limit

Nemotron 12B VL estimated footprint:
  Model weights (bf16): 12B × 2 bytes = ~24 GiB
  KV cache + activations: ~4-6 GiB additional
  Total estimated: ~28-30 GiB

Projected after deployment:
  68 + 28 = 96 GiB = 78.9% → EXCEEDS 60% RULE BY 18.9%
```

**Architecture doc constraint (Iron Dome v6.1 Principle 2, canon):**
> "Target per-node memory utilization ≤ 60% under steady-state workload."
> "If a model allocation would push a node over 60%, the allocation gets
> revisited — re-host to a different node, use a smaller model, or defer."

**Image state:** The NIM image was NOT loaded to spark-1 Docker daemon.
The `docker load` command was killed before completion. spark-1 Docker image
store: no Nemotron image present. **spark-1 is unchanged.**

---

## Stage-2 ELF Verify Results (completed, not blocked)

The ELF verify was completed on the one accessible candidate before the NGC
auth issue was discovered:

| Image | Stage 1 | Stage 2 ELF | Verdict | Build |
|-------|---------|-------------|---------|-------|
| `nemotron-nano-12b-v2-vl:1.6.0` (NAS tar) | PASS | PASS | **PASS** | `ELF 64-bit LSB pie executable, ARM aarch64` |
| `llama-nemotron-embed-1b-v2` (NAS tar) | PASS | PASS | **PASS** | `ELF 64-bit LSB pie executable, ARM aarch64` |
| `nemotron-nano-12b-v2` (text, from NGC) | N/A | N/A | **ACCESS DENIED** | Cannot pull |

The VL model (`nemotron-nano-12b-v2-vl`) is the only Nemotron NIM candidate
confirmed ARM64 and accessible. Stage-2 ELF gate result for Phase 1 Step 1:

> **PASS on nemotron-nano-12b-v2-vl. BLOCKED on nemotron-nano-12b-v2 (cannot pull).**

---

## Options for Gary

### Option 1: Fix NGC auth, proceed with text-only Nemotron on spark-2

**What's needed:**
- Gary re-generates NGC API key with NIM catalog entitlement (not just DGX Spark scope)
- Target: `nemotron-nano-12b-v2:1.6.0` becomes pullable
- Deploy Nemotron NIM on spark-2 (currently idle, 128 GiB with no NIM resident) instead of spark-1

**Remaining training blocker:** Nemotron-H still requires trust_remote_code for HF+PEFT. Deploying the text-only NIM for inference-only comparison (base Nemotron vs adapted Qwen) is possible. Training a legal adapter on Nemotron base is not.

**Inference-only comparison remains useful:** If base Nemotron-nano-12B-v2 beats adapted Qwen-7B-e3.1 on the hardened harness, that's a strong signal to invest in solving the trust_remote_code problem (PEFT has experimental Mamba LoRA support via the `mamba_proj` layer).

### Option 2: Use nemotron-nano-12b-v2-vl on spark-2 (inference-only)

**What's needed:**
- Gary confirms spark-2 as target node (currently idle after legal_train completed)
- spark-2 memory: 128 GiB total, low current utilization (no NIM running)
- Deploy VL NIM on spark-2 port 8001
- Run hardened eval: base Nemotron-12B-VL vs e3.1-Qwen on spark-2 HF inference

**Benefit:** No new NGC auth needed. VL model is cached and Stage-2 verified.
**Limitation:** Base model comparison only (no legal adapter on Nemotron). Answers
"is Nemotron-12B better out of the box than adapted Qwen-7B?" — a valid question.

### Option 3: Resume HF bake-off (killed in PR #136)

If the NVIDIA stack constraints are too restrictive, the HF bake-off is fully prepped:
- `src/legal/bakeoff_train.sh` committed (dc43e6517)
- Candidates: Qwen 14B (Apache 2.0), Mistral 7B v0.3 (Apache 2.0), Phi-3-medium (MIT)
- Download time: ~4 hours. Train time: ~3-4x e3.1 wall-clock each.
- All three support standard HF loading without trust_remote_code.
- LoRA target modules confirmed compatible for Qwen and Mistral; Phi-3 uses `qkv_proj` override (configured in bakeoff_train.sh).

### Option 4: Wait for PEFT Mamba LoRA + NGC auth fix

PEFT has experimental SSM/Mamba LoRA support as of version 0.13+ via
`target_modules=["mamba_proj", "in_proj", "out_proj"]`. If:
- Gary fixes NGC auth to pull the text-only Nemotron model
- PEFT version in the venv supports Mamba LoRA (needs verification)

Then full NeMo-equivalent training is possible via HF+PEFT on the Nemotron-H base.
This is the cleanest path to the intended outcome but requires Gary to unblock auth first.

---

## Current State (all safe)

- spark-1: Unchanged. `fortress-nim-sovereign` running on port 8000 (llama-3.1-8b-dgx-spark). No Nemotron image loaded.
- spark-2: Idle. legal_train not running. HF eval harness available.
- NAS cache: `nemotron-nano-12b-v2-vl` (35 GiB, Stage-2 ELF PASS), `llama-nemotron-embed-1b-v2` (2.5 GiB, Stage-2 ELF PASS). No changes.
- Prod symlink: `/mnt/fortress_nas/models/legal-instruct-production` → e3.1. Unchanged.
- Prod routing: unchanged. All Fortress Legal traffic continues on existing path.

**GATE: Gary decides Option 1, 2, 3, or 4 before any further execution.**
