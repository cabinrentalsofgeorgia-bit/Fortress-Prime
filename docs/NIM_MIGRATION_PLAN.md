# NVIDIA NIM Migration Roadmap (ARM64 / GB10 Grace Blackwell)

**Status:** Pending — awaiting NVIDIA ARM64 NIM container release
**Last Reviewed:** 2026-02-28
**Owner:** Lead Sovereign Systems Architect

---

## Current State

The DGX Spark cluster (Captain, Muscle, Ocular, Sovereign) operates on ARM64 GB10
Grace Blackwell architecture with 128 GB unified memory per node. NVIDIA NIM does
not currently provide native ARM64 LLM container images (`nvcr.io/nim/`). The
Fortress utilizes **Ollama** (backed by `llama.cpp`) as the production inference
runtime for SWARM and HYDRA modes.

This deviation from Rule 001 (Titan Protocol — NIM Mandate) is acknowledged and
tracked. Ollama is treated as the sanctioned interim runtime until NIM ARM64 images
ship. All Ollama versions are pinned in deployment scripts and `switch_defcon.sh`.

### Active Inference Topology

| DEFCON Mode | Runtime | Model | Nodes | Port |
|---|---|---|---|---|
| SWARM (5) | Ollama | qwen2.5:7b | All 4 via Nginx LB | 11434 |
| HYDRA (3) | Ollama | deepseek-r1:70b | Muscle, Ocular, Sovereign | 11434 |
| TITAN (1) | Ollama / llama.cpp RPC | deepseek-r1:671b | All 4 pooled | 11434 |

---

## Migration Triggers

This migration protocol initiates within **72 hours** of NVIDIA releasing ARM64
`nvcr.io/nim/` images that meet ALL of the following criteria:

1. Target platform `linux/arm64` with CUDA 12.x+ support
2. Include TensorRT-LLM optimization for GB10 Grace Blackwell unified memory
3. Support OpenAI-compatible `/v1/chat/completions` API endpoint
4. Available for models in the 7B-70B parameter range (SWARM and HYDRA tiers)

**Monitoring:** Check `nvcr.io` catalog monthly. Subscribe to NVIDIA NIM release
notes at https://docs.nvidia.com/nim/.

---

## Phase 1: Side-by-Side Deployment

**Objective:** Validate NIM containers without disrupting production Ollama.

- [ ] Pull ARM64 NIM images to `/mnt/fortress_nas/nim_cache`
- [ ] Add NIM service definitions to `docker-compose.yml` on non-conflicting ports (e.g., 8000-8003)
- [ ] Pin NIM images by digest (Rule 010 Section V)
- [ ] Set `platform: linux/arm64` on all NIM services
- [ ] Configure NAS model weight cache mount: `/mnt/fortress_nas/nim_cache:/opt/nim/.cache`
- [ ] Validate NVMe-oF model weight loading speeds (target: < 30s cold start)
- [ ] Run golden prompt suite against NIM endpoints and compare output quality to Ollama
- [ ] Verify GPU memory budget: ~40 GB model + ~40 GB KV cache per HYDRA head

**Exit Criteria:** NIM serves identical API responses to Ollama with p95 latency
within 20% of Ollama baseline across the golden prompt suite.

---

## Phase 2: SWARM Cutover

**Objective:** Route production SWARM traffic (qwen2.5:7b or equivalent) through NIM.

- [ ] Update `config.py:get_inference_client("SWARM")` to point to NIM endpoint
- [ ] Update Nginx `wolfpack_ai.conf` upstream pool to target NIM ports instead of Ollama
- [ ] Run 24-hour parallel observation: NIM serves live traffic, Ollama runs shadow
- [ ] Monitor throughput via Grafana (target: >= 5,000 tasks/min)
- [ ] Monitor latency via Prometheus (target: p95 <= 2.5s per Rule 010 Section VI)
- [ ] If SLO regression > 25% on p95 latency: immediate rollback to Ollama upstream

**Exit Criteria:** 48 hours of clean production serving with SLOs met.

---

## Phase 3: HYDRA / TITAN Cutover

**Objective:** Transition deep reasoning models (R1-70B, R1-671B) to NIM.

- [ ] Deploy NIM R1-70B on Muscle, Ocular, and Sovereign nodes
- [ ] Update `config.py:get_inference_client("HYDRA")` to NIM endpoint
- [ ] Update Nginx `wolfpack_ai.conf` HYDRA upstream to NIM ports
- [ ] Exclude Captain from HYDRA upstream (VRAM reserved for SWARM + embeddings)
- [ ] Execute `Modules/CF-01_GuardianOps/test_vision_engine.py` for LLaVA API compat
- [ ] Run legal drafter regression test: generate 10 damage claim drafts, compare quality
- [ ] For TITAN (671B): evaluate NIM multi-node deployment via Kubernetes/Helm when available
- [ ] If NIM multi-node 671B is not available: retain llama.cpp RPC as TITAN fallback

**Exit Criteria:** HYDRA serves R1-70B via NIM with p95 <= 20s. TITAN path documented.

---

## Phase 4: Ollama Decommission

**Objective:** Remove legacy runtime and simplify the stack.

- [ ] Stop all Ollama processes across the cluster
- [ ] Update `switch_defcon.sh` to orchestrate NIM containers exclusively
- [ ] Remove Ollama entries from Nginx upstream configs
- [ ] Remove `get_ollama_endpoints()` helper from `config.py`
- [ ] Purge Ollama binaries and model cache from all nodes
- [ ] Update Rule 001 (Titan Protocol) to reflect NIM-only production state
- [ ] Update `docker-compose.yml` to include NIM services as primary inference
- [ ] Final golden prompt suite validation across all three DEFCON modes

**Exit Criteria:** Zero Ollama processes running. `switch_defcon.sh` manages NIM only.
All DEFCON modes operational via NIM with SLOs met for 7 consecutive days.

---

## Rollback Protocol

At any phase, if NIM exhibits:
- p95 latency regression > 25% vs Ollama baseline
- Error rate > 2% sustained over 15 minutes
- Correctness drift on golden prompt suite (manual review)
- GPU thermal exceedance (> 85C sustained)

**Action:** Revert Nginx upstream and `config.py` to Ollama endpoints within 10
minutes. NIM containers remain deployed but idle for debugging. File issue with
NVIDIA via NGC support portal.
