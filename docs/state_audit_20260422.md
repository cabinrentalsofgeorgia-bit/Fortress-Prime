# Fortress-Prime ML Infrastructure State Audit
_Date: 2026-04-22 | Role: Read-only audit | No production state modified_

---

## Executive Summary

**Five direct answers:**

1. **e3.1 base model:** `Qwen/Qwen2.5-7B-Instruct` — confirmed across adapter_config.json, README.md, and training_manifest.json for every adapter. Gary's recollection of "Nemotron 9B" is incorrect. Nemotron-9B was a failed VRS concierge NIM deployment (x86 mislabeled), not the legal adapter base.

2. **e3.1 production serving:** **NOT currently served.** spark-2 GPU has zero running processes. No systemd unit, Docker container, or Ollama instance loads the e3.1 Qwen LoRA adapter. The `legal-instruct-production` symlink exists on NAS but nothing reads it for live inference. The vLLM bridge on spark-2 (port 18001) targets a dead container (`vllm-70b-captain`) that does not exist.

3. **spark-1 state:** `fortress-nim-sovereign` (`meta/llama-3.1-8b-instruct-dgx-spark`) running on port 8000, confirmed healthy via `/v1/models` API. Nemotron VL image (`nemotron-nano-12b-v2-vl:latest`, created 2026-01-27) is present in Docker image store but **not running as a container**.

4. **spark-1 memory (55.9%):** Reconciled and explained. The 57.2 GiB (58,542 MiB) is the NIM container's vLLM KV cache pre-allocation on GB10 unified memory — this is normal vLLM behavior. Remaining ~11 GiB: OS/system + Ollama (713 MiB, only `nomic-embed-text` loaded).

5. **Contradictions:** One conversation claim confirmed wrong (Gary's "Nemotron 9B"). One claim confirmed mismatch with reality ("spark-2 serves e3.1 in production" — no active serving found).

---

## 1. Adapter Base Models

### 1a. Adapter Config — Verbatim Findings

| Adapter Dir | Symlink Target | `base_model_name_or_path` | Source File |
|-------------|---------------|--------------------------|-------------|
| `legal-instruct-20260420-e2` | (direct) | `/mnt/fortress_nas/models/Qwen2.5-7B-Instruct` | adapter_config.json |
| `legal-instruct-20260420-e3` | (direct) | `/mnt/fortress_nas/models/Qwen2.5-7B-Instruct` | adapter_config.json |
| `legal-instruct-20260421-e3_1` | (direct) | `/mnt/fortress_nas/models/Qwen2.5-7B-Instruct` | adapter_config.json |
| `legal-instruct-production` | **→ legal-instruct-20260421-e3_1** | `/mnt/fortress_nas/models/Qwen2.5-7B-Instruct` | adapter_config.json (via symlink) |

### 1b. LoRA Configuration (all adapters identical)

| Field | Value |
|-------|-------|
| `peft_type` | LORA |
| `r` (rank) | 16 |
| `lora_alpha` | 32 |
| `lora_dropout` | 0.05 |
| `target_modules` | `q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj` |

### 1c. Cross-Source Verification

Three independent sources all agree on Qwen 7B base:

| Source | File | Value |
|--------|------|-------|
| PEFT config | `adapter_config.json` | `/mnt/fortress_nas/models/Qwen2.5-7B-Instruct` |
| HuggingFace card | `README.md` | `base_model: /mnt/fortress_nas/models/Qwen2.5-7B-Instruct` |
| Training manifest | `training_manifest.json` | `base_model: qwen2.5:7b` |

**No Nemotron reference anywhere in any adapter directory.**

---

## 2. Base Model Weights on Disk

### 2a. NAS `/mnt/fortress_nas/models/` — Top-level Directories

| Directory | Type | Config `model_type` | `architectures` | Adapters Dependent |
|-----------|------|--------------------|-----------------|--------------------|
| `Qwen2.5-7B-Instruct/` | Base model weights | `qwen2` | `['Qwen2ForCausalLM']` | e2, e3, e3.1, production |
| `llama-3.1-70b-f16/` | GGUF weights (5 shards) | N/A (GGUF, no config.json) | Llama 3.1 70B | None (standalone GGUF) |
| `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` | GGUF file | N/A | Llama 3.1 8B Q4 | None |
| `nomic-embed-text-v1.5.f16.gguf` | GGUF file | N/A | Nomic embed | None |
| `legal-instruct-*` (4 dirs) | LoRA adapters | N/A | See §1 | — |
| `bakeoff_20260422/` | Selection memo + KILLED record | N/A | — | — |
| `bases/` | Empty directory | N/A | — | — |
| `lora_work/` | Work dir | Not inspected | — | — |
| `archive/` | Archived models | Not inspected | — | — |

### 2b. NAS `bases/` Directory

**Empty.** The partial downloads (Qwen 14B, Mistral 7B, Phi-3-medium) were cleaned up. No base model weights in this directory.

### 2c. HuggingFace Cache — spark-2 Local (`~/.cache/huggingface/hub/`)

| Cache Entry | `model_type` | Notes |
|-------------|--------------|-------|
| `models--Qwen--Qwen2.5-7B-Instruct` | qwen2 | Present, downloaded during HF bake-off prep |
| `models--Qwen--Qwen2.5-14B-Instruct` | qwen2 | Present (from bake-off download, killed) |
| `models--mistralai--Mistral-7B-Instruct-v0.3` | mistral | Present (from bake-off download, killed) |
| `models--microsoft--Phi-3-medium-128k-instruct` | phi3 | Present (from bake-off download, killed) |
| `models--sentence-transformers--all-MiniLM-L6-v2` | N/A | MiniLM embedder for eval harness |

**Note:** Qwen 14B, Mistral 7B, Phi-3-medium are in HF cache on spark-2 even though `/mnt/fortress_nas/models/bases/` was cleaned. The HF cache is on spark-2 local disk, not NAS. These were cached during the `huggingface-cli download` runs.

### 2d. Does `base_model_name_or_path` Resolve?

Adapters reference `/mnt/fortress_nas/models/Qwen2.5-7B-Instruct` (absolute NAS path).

`/mnt/fortress_nas/models/Qwen2.5-7B-Instruct/` **exists** and contains valid HF-format weights (config.json confirms `model_type: qwen2`, `hidden_size: 3584`, `num_hidden_layers: 28`). The base model path resolves correctly.

**No Nemotron-9B, Nemotron-nano, or any Nemotron model exists on NAS as HF-format weights.**

---

## 3. Spark-1 Live State

### 3a. Running Containers

| Container Name | Image | Status | Ports |
|----------------|-------|--------|-------|
| `fortress-nim-sovereign` | `nvcr.io/nim/meta/llama-3.1-8b-instruct-dgx-spark:latest` | **Up 3 days** | `0.0.0.0:8000->8000/tcp` |
| `fortress_portainer-agent.*` | `portainer/agent:lts` | Up 6 days | — |

### 3b. Docker Images Present (not running)

| Image | Disk | Notes |
|-------|------|-------|
| `nvcr.io/nim/meta/llama-3.1-8b-instruct-dgx-spark:latest` | 21.6 GB | Running as fortress-nim-sovereign |
| `nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl:latest` | 19.9 GB | **Not running**. Created 2026-01-27 — pre-existed before this audit session. Stage-2 ELF: **PASS** (aarch64). |

### 3c. GPU Processes (nvidia-smi)

| PID | Process | GPU Memory |
|-----|---------|-----------|
| 355813 | `VLLM::EngineCore` | **58,542 MiB (57.2 GiB)** |
| 539160 | `/usr/local/bin/ollama` | 713 MiB |
| 10112 | Firefox | 263 MiB |
| 8054 | Xorg | 91 MiB |
| 8489 | gnome-shell | 71 MiB |

### 3d. Memory Reconciliation

| Component | GiB | Source |
|-----------|-----|--------|
| vLLM KV-cache + model weights (llama-3.1-8b NIM) | 57.2 | nvidia-smi PID 355813 |
| Ollama daemon (nomic-embed-text loaded) | 0.6 | nvidia-smi PID 539160 + api/ps |
| Firefox + X11 + GNOME | 0.4 | nvidia-smi |
| OS/kernel/buffers/system/other | ~9.8 | `free -h` residual |
| **Total used** | **68.0** | `free -h` |
| **Total available** | **121.7** | `free -h` |
| **Utilization** | **55.9%** | |

**Reconciliation: fully accounted.** The 57.2 GiB for vLLM is not anomalous — on GB10 unified memory, vLLM pre-allocates a large KV cache (model weights: ~16 GiB bf16; remaining ~41 GiB: KV cache for max_model_len=8192 with generous batch allocation). This is standard vLLM behavior on high-memory systems.

### 3e. Listening Ports (spark-1)

| Port | Process | Purpose |
|------|---------|---------|
| 8000 | Docker/NIM (vLLM) | Fortress Legal NIM — `meta/llama-3.1-8b-instruct` |
| 8501 | `streamlit` (fortress-brain.service) | Dashboard UI |
| 11434 | Ollama | Local Ollama API |
| 46333, 52365, 40157, 38627, 35697, 37931 | Ray (raylet, DashboardA, RuntimeEnv) | Ray distributed compute |
| 22 | sshd | SSH |
| Various loopback | k3s, system | Kubernetes agent, internal |

### 3f. NIM Health Probe

`GET http://192.168.0.104:8000/v1/models` returns:
```json
{"object":"list","data":[{"id":"meta/llama-3.1-8b-instruct","owned_by":"vllm","max_model_len":8192}]}
```
**NIM is healthy and serving** `meta/llama-3.1-8b-instruct`. No inference request sent.

### 3g. Ollama Models on spark-1 (not all loaded in GPU)

| Model | Size | GPU-loaded |
|-------|------|-----------|
| `deepseek-r1:70b` | 42.5 GB | No |
| `llama3.2-vision:90b` | 54.6 GB | No |
| `qwen2.5:32b` | 19.9 GB | No |
| `qwen2.5:7b` | 4.7 GB | No |
| `llava:latest` | 4.7 GB | No |
| `mistral:latest` | 4.4 GB | No |
| `nomic-embed-text:latest` | 0.3 GB | **YES** — 595 MiB |

Only `nomic-embed-text` is currently resident in GPU memory on spark-1's Ollama. The 70B/90B models are available but not loaded.

**Notable:** `llama3.2-vision:90b` (54.6 GB) and `deepseek-r1:70b` (42.5 GB) are present on spark-1 Ollama but not loaded. If either were loaded, it would push spark-1 far past the 60% memory rule (currently 55.9%). This is a latent risk — any Ollama call to these models would load them.

---

## 4. Spark-2 Serving Path

### 4a. GPU State

**No GPU processes.** `nvidia-smi` shows zero running GPU processes on spark-2. The GPU is completely idle. Temperature: 65°C (warm from prior training run, now cooling).

### 4b. Docker Containers on spark-2

| Container | Image | Status | Ports | Notes |
|-----------|-------|--------|-------|-------|
| `nim-embed` | `vllm/vllm-openai:latest` | **Exited (1) 12 days ago** | — | Dead |
| `fortress-hermes` | `fortress-hermes:cuda13` | **Exited (137) 2 weeks ago** | — | Dead |
| `fortress-event-broker` | redpanda | **Exited (137) 10 days ago** | — | Dead |
| `fortress_portainer.1.*` | portainer | Up 2 weeks | 8888 | Running |
| `fortress_portainer-agent.*` | portainer/agent | Up 2 weeks | — | Running |
| `fortress-event-console` | redpanda/console | Up ~1 min | 127.0.0.1:18080 | Running |
| `fortress-rag-retriever` | yzy-retriever | Up 12 days (healthy) | 8010 | Running |
| `fortress-chromadb` | chromadb | Up 2 weeks | 127.0.0.1:8004 | Running |
| `fortress-qdrant` | qdrant | Up 2 weeks | 6333-6334 | Running |
| `fortress_mission_control` | open-webui | Up 12 days (healthy) | — | Running |
| `fortress-chroma` | chromadb:latest | Up 2 weeks | 8020 | Running |

### 4c. Inference Serving on spark-2

**Comprehensive search for e3.1 serving:**

| Check | Result |
|-------|--------|
| GPU processes | **None** |
| vLLM processes (grep) | `vllm_http_proxy.py` only — this is a proxy, not a server |
| vLLM bridge target (`vllm-70b-captain`) | Container **does not exist** |
| LiteLLM config (`litellm_config.yaml`) | Only cloud APIs (Claude, GPT, Grok, Gemini, DeepSeek). No local adapter references |
| Systemd units loading e3.1 path | **None found** |
| Ollama models on spark-2 | `qwen2.5:7b` (4.7 GB), `qwen2.5:0.5b`, `nomic-embed-text` — all loaded in memory. **No e3.1 LoRA adapter** |

**The `fortress-vllm-bridge.service` is running (PID 710186) but its target is dead:**
- Bridge listens on `127.0.0.1:18001`
- Proxies to container `vllm-70b-captain` at `http://127.0.0.1:8000`
- Container `vllm-70b-captain` **does not exist** in `docker ps -a`
- This bridge is currently a dead-end — any request to port 18001 will fail

**Conclusion on spark-2 e3.1 serving:** The e3.1 Qwen LoRA adapter is **not served anywhere in the cluster**. The `legal-instruct-production` symlink is a reference artifact. Inference serving for Fortress Legal currently routes to spark-1's `meta/llama-3.1-8b-instruct` NIM (no LoRA adapter) and cloud Godhead (Claude via LiteLLM).

### 4d. Active spark-2 Services

| Service | Port | Purpose |
|---------|------|---------|
| `fortress-backend.service` | 8000 | FastAPI main backend (`run.py`) |
| `litellm-gateway.service` | 127.0.0.1:8002 | Cloud model router (Claude, GPT, Grok, Gemini, DeepSeek) |
| `ollama.service` (3 instances) | 127.0.0.1:36909, 40683, 43377 | Serving qwen2.5:7b, qwen2.5:0.5b, nomic-embed-text |
| `fortress-ray-head.service` | various | Ray cluster head |
| `fortress-vllm-bridge.service` | 127.0.0.1:18001 | **Dead bridge to non-existent container** |
| `fortress-sentinel.service` | — | NAS document indexing |
| PostgreSQL | 5432 | Application database |
| Qdrant | 6333-6334 | Vector store |
| ChromaDB (×2) | 8004, 8020 | Vector store |

---

## 5. Contradictions Table

| Claim in Conversation | Evidence from Audit | Verdict |
|----------------------|---------------------|---------|
| "e3.1 is Qwen 7B LoRA" | `adapter_config.json`: `base_model_name_or_path: /mnt/fortress_nas/models/Qwen2.5-7B-Instruct`; `training_manifest.json`: `base_model: qwen2.5:7b` — three independent sources agree | **MATCH** |
| "spark-2 serves e3.1 in production" | spark-2 GPU: zero processes. No systemd unit, no Docker container, no Ollama instance loads e3.1 adapter. LiteLLM config has no local model entry. vLLM bridge targets dead container. | **MISMATCH** — e3.1 is not served anywhere |
| "spark-1 serves llama-3.1-8b NIM" | `docker ps`: `fortress-nim-sovereign` running. `/v1/models` health check: `{"id":"meta/llama-3.1-8b-instruct"}`. vLLM EngineCore running on GPU. | **MATCH** |
| "spark-1 at 55.9% memory" | `free -h`: 68 GiB / 121.7 GiB = 55.9%. Fully reconciled: 57.2 GiB vLLM + 0.6 GiB Ollama + 0.4 GiB X11 + ~9.8 GiB OS. | **MATCH** — and now explained |
| "base is actually Nemotron 9B" (Gary) | Zero Nemotron references in any adapter config, README, or training manifest. No Nemotron HF-format weights on NAS. The Nemotron-9B image (`nvidia-nemotron-nano-9b-v2`) was a failed VRS concierge NIM deployment (confirmed x86 mislabeled, cleaned up), not a legal adapter base. | **MISMATCH** — Gary's recollection is incorrect |

---

## 6. Open Questions

Items that could not be resolved without making changes:

1. **How does Fortress Legal actually serve inference today?** Given e3.1 is not served, legal queries presumably route through LiteLLM (Claude) or the spark-1 llama-3.1-8b NIM. Which path does the application use? A read of `backend/services/legal_reasoning_judge.py` or equivalent would answer this without state changes — not done in this audit to keep scope contained.

2. **What loaded `nemotron-nano-12b-v2-vl:latest` onto spark-1?** The image was created 2026-01-27 and is in Docker image store. It was not started during this session (load was killed, and the image predates the session). Reviewing Docker daemon logs or spark-1 history would clarify when and why it was pulled.

3. **What is `vllm-70b-captain`?** The bridge references a container that no longer exists. The NAS has `llama-3.1-70b-f16` GGUF weights — this may have been a DeepSeek-R1-70B or Llama-70B server that was shut down. It is dead and the bridge is a stale artifact.

4. **Three Ollama instances on spark-2 (PIDs 2154877, 2846183, 3461430) — why three?** Each is an `ollama runner` serving a different model on different loopback ports. This is Ollama's normal behavior for concurrent model serving, but three simultaneous instances is worth understanding in context of the memory budget.

5. **spark-1 Ollama model list includes 90B vision + 70B DeepSeek models.** Neither is GPU-loaded now, but loading either would push spark-1 past 60% (current: 55.9%). No active safeguard prevents an Ollama call from loading them. This is a latent memory overflow risk.

---

_Audit complete. No production state was modified. All data is read-only observation._
