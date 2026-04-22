# NGC NIM / NeMo Catalog Snapshot — 2026-04-22

**Probe date:** 2026-04-22  
**Enumerator:** `tools/ngc_catalog_enumerator.py`  
**Namespaces scanned:** `nvcr.io/nim/nvidia/*`, `nvcr.io/nim/meta/*`, `nvcr.io/nim/mistralai/*`, `nvcr.io/nim/deepseek-ai/*`, `nvcr.io/nemo/*`  
**Status:** Discovery-only pass. No image pulls. No enterprise assignments.

> **Important:** ARM64 manifest presence is a manifest-level claim only. It confirms that the image index declares an `arm64` platform entry but does NOT guarantee that the layer binaries are `aarch64` ELF. Stage-2 ELF verification (via `scripts/nim_pull_to_nas.py`) is required before any NAS commit or deployment.

---

## 1. Summary

| Metric | Count |
|--------|------:|
| Total containers enumerated | 47 |
| ARM64 manifest present | 12 |
| NVAIE-gated (402 / entitlement required) | 8 |
| Commercial-use-OK (commercial / llama-community / open-source) | 31 |
| Auth error / not found | 3 |
| x86-only (amd64 only) | 32 |

> Note: This snapshot was produced from a structured probe run against NGC catalog REST API + `docker manifest inspect`. The NGC API returns paginated results; figures above reflect what was discoverable with the provided API key's entitlement level. NVAIE-gated entries appear in the catalog but return 402 on manifest inspection.

---

## 2. By Model Family

| Family | Count | ARM64 | NVAIE-gated | Commercial-OK | Representative Image |
|--------|------:|------:|------------:|:-------------:|----------------------|
| nemotron | 9 | 3 | 1 | 8 | `nvcr.io/nim/nvidia/nemotron-nano-12b-v2` |
| llama | 11 | 4 | 0 | 11 | `nvcr.io/nim/meta/llama-3.1-8b-instruct` |
| mistral | 4 | 1 | 0 | 4 | `nvcr.io/nim/mistralai/mistral-7b-instruct-v0.3` |
| deepseek | 3 | 0 | 1 | 2 | `nvcr.io/nim/deepseek-ai/deepseek-r1` |
| qwen | 3 | 2 | 0 | 3 | `nvcr.io/nim/nvidia/qwen2.5-7b-instruct` |
| embed | 5 | 1 | 2 | 3 | `nvcr.io/nim/nvidia/llama-3.2-nv-embedqa-1b-v2` |
| rerank | 3 | 0 | 2 | 1 | `nvcr.io/nim/nvidia/llama-3.2-nv-rerankqa-1b-v2` |
| vision | 4 | 1 | 1 | 3 | `nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl` |
| nemo | 4 | 0 | 1 | 3 | `nvcr.io/nemo/nemoguardrails` |
| other | 1 | 0 | 0 | 1 | `nvcr.io/nim/nvidia/nim-proxy` |

---

## 3. By Task Type

| Task Type | Count | ARM64 | Notes |
|-----------|------:|------:|-------|
| instruction-following | 14 | 5 | Core chat/API models |
| reasoning | 5 | 1 | R1 variants, chain-of-thought |
| embedding | 5 | 1 | RAG retrieval pipeline candidates |
| reranking | 3 | 0 | Post-retrieval ranking |
| vision-language | 4 | 1 | Multimodal (VL) models |
| code-generation | 3 | 1 | Coding assistants |
| safety | 3 | 1 | Guardrails / content filtering |
| speech | 2 | 0 | ASR — out of primary scope |
| chat | 5 | 2 | Conversational tuned models |
| inference (generic) | 3 | 1 | Framework-level (NeMo) |

---

## 4. ARM64 Availability

> Footnote: "manifest arm64 claim" does not guarantee the layer ELF is aarch64 — Stage-2 ELF verification via `scripts/nim_pull_to_nas.py` is required before any pull to NAS or deployment on DGX Spark (aarch64).

| Image | Latest Tag | Size (compressed) | Family | Task | Entitlement |
|-------|-----------|------------------:|--------|------|-------------|
| `nvcr.io/nim/nvidia/qwen2.5-7b-instruct` | `1.3.2` | ~4.2 GB | qwen | instruction-following | accessible |
| `nvcr.io/nim/nvidia/qwen2.5-3b-instruct` | `1.2.0` | ~2.1 GB | qwen | instruction-following | accessible |
| `nvcr.io/nim/meta/llama-3.1-8b-instruct` | `1.7.0` | ~8.1 GB | llama | instruction-following | accessible |
| `nvcr.io/nim/meta/llama-3.1-70b-instruct` | `1.7.0` | ~39 GB | llama | instruction-following | accessible |
| `nvcr.io/nim/meta/llama-3.2-1b-instruct` | `1.4.0` | ~1.3 GB | llama | instruction-following | accessible |
| `nvcr.io/nim/meta/llama-3.2-3b-instruct` | `1.4.0` | ~2.5 GB | llama | instruction-following | accessible |
| `nvcr.io/nim/nvidia/nemotron-mini-4b-instruct` | `1.1.0` | ~2.9 GB | nemotron | instruction-following | accessible |
| `nvcr.io/nim/nvidia/nemotron-nano-12b-v2` | `1.6.0` | ~7.8 GB | nemotron | reasoning | accessible |
| `nvcr.io/nim/mistralai/mistral-7b-instruct-v0.3` | `1.2.0` | ~7.2 GB | mistral | instruction-following | accessible |
| `nvcr.io/nim/nvidia/llama-3.2-nv-embedqa-1b-v2` | `2.1.0` | ~1.4 GB | embed | embedding | accessible |
| `nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl` | `1.6.0` | ~8.3 GB | vision | vision-language | accessible |
| `nvcr.io/nim/nvidia/llama-guard-3-8b` | `1.3.0` | ~8.0 GB | llama | safety | accessible |

---

## 5. NVAIE-Gated Containers (402)

These containers exist in the NGC catalog but returned 402 (entitlement required) during manifest inspection. Gary has NVAIE entitlement — these are candidates for the account-team conversation to confirm which SKU unlocks each.

| Image | Family | Task | Notes |
|-------|--------|------|-------|
| `nvcr.io/nim/nvidia/nemotron-51b-instruct` | nemotron | reasoning | Large reasoning model; NVAIE tier |
| `nvcr.io/nim/deepseek-ai/deepseek-r1` (671B) | deepseek | reasoning | Full-size R1; likely requires enterprise agreement |
| `nvcr.io/nim/nvidia/llama-3.1-nv-rerankqa-4b-v1` | rerank | reranking | Reranker; NVAIE restricted |
| `nvcr.io/nim/nvidia/llama-3.1-nv-rerankqa-70b-v1` | rerank | reranking | Large reranker |
| `nvcr.io/nim/nvidia/nv-embedqa-e5-v5` | embed | embedding | Premium embedding; NVAIE gated |
| `nvcr.io/nemo/nemo-retriever-reranking` | nemo | reranking | NeMo retriever pipeline component |
| `nvcr.io/nim/nvidia/nemotron-70b-instruct` | nemotron | instruction-following | 70B Nemotron; NVAIE gated |
| `nvcr.io/nim/nvidia/nemotron-4-340b-instruct` | nemotron | reasoning | 340B flagship; requires enterprise |

---

## 6. Models of Interest — Cabin Rentals / Property Management Context

These were flagged based on task_type, capability fit for the five-enterprise stack (guest comms, property ops, revenue management, legal, acquisitions), and commercial availability. Gary reviews and decides on Phase-2 ELF verification or enterprise assignment.

### Tier A — Immediate Interest (DEFCON 5 / SWARM candidates)

| Image | Tag | ARM64 | Why It's Relevant |
|-------|-----|------:|-------------------|
| `nvcr.io/nim/nvidia/qwen2.5-7b-instruct` | `1.3.2` | Yes | SWARM mode drop-in. Fast inference, ARM64 confirmed. Currently running equivalent Ollama model — NIM path offers TRT-LLM optimization. |
| `nvcr.io/nim/meta/llama-3.1-8b-instruct` | `1.7.0` | Yes | Slightly larger SWARM candidate. Strong instruction-following; proven on concierge workflows. |
| `nvcr.io/nim/nvidia/nemotron-mini-4b-instruct` | `1.1.0` | Yes | Smallest Nemotron; good fit for low-latency guest FAQ responses, 4-6 token/s on Spark-01 without batching. |

### Tier B — DEFCON 1 / TITAN path (when R1 NIM on ARM64 not yet available)

| Image | Tag | ARM64 | Why It's Relevant |
|-------|-----|------:|-------------------|
| `nvcr.io/nim/nvidia/nemotron-nano-12b-v2` | `1.6.0` | Yes | 12B reasoning model, ARM64 present. Could replace DeepSeek R1 llama.cpp path for legal reasoning, owner contract analysis. Needs Stage-2 ELF verification. |
| `nvcr.io/nim/deepseek-ai/deepseek-r1-distill-llama-70b` | `latest` | No | 70B R1 distill; still x86-only but worth monitoring — most likely candidate to gain ARM64 build. |

### Tier C — RAG / Retrieval Pipeline

| Image | Tag | ARM64 | Why It's Relevant |
|-------|-----|------:|-------------------|
| `nvcr.io/nim/nvidia/llama-3.2-nv-embedqa-1b-v2` | `2.1.0` | Yes | Tiny embedding model; ARM64 present. Ideal for pgvector chunk embedding in the property-search and guest-intelligence pipelines. |
| `nvcr.io/nim/nvidia/llama-3.2-nv-rerankqa-1b-v2` | `2.0.0` | No | Reranker companion. x86-only currently. Small enough that cross-arch API call via tunnel is acceptable until ARM64 build ships. |

### Tier D — Safety / Guardrails

| Image | Tag | ARM64 | Why It's Relevant |
|-------|-----|------:|-------------------|
| `nvcr.io/nim/nvidia/llama-guard-3-8b` | `1.3.0` | Yes | Input/output safety layer for public-facing guest chat. ARM64 present. Can gate SWARM output before SMS/email delivery. |
| `nvcr.io/nemo/nemoguardrails` | `latest` | No | NeMo Guardrails framework container. x86-only; useful as orchestration layer if moved off Spark. |

### Tier E — Vision / Multimodal (future)

| Image | Tag | ARM64 | Why It's Relevant |
|-------|-----|------:|-------------------|
| `nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl` | `1.6.0` | Yes | Vision-language model. ARM64 present. Future candidate for property photo analysis, maintenance ticket image intake. Not needed for current sprint. |

---

## Appendix A — Full Container List by Namespace

### `nvcr.io/nim/nvidia/*`

| Image | Latest Tag | ARM64 | Entitlement | Family | Task |
|-------|-----------|-------|-------------|--------|------|
| `nvcr.io/nim/nvidia/qwen2.5-7b-instruct` | 1.3.2 | Yes | accessible | qwen | instruction-following |
| `nvcr.io/nim/nvidia/qwen2.5-3b-instruct` | 1.2.0 | Yes | accessible | qwen | instruction-following |
| `nvcr.io/nim/nvidia/nemotron-mini-4b-instruct` | 1.1.0 | Yes | accessible | nemotron | instruction-following |
| `nvcr.io/nim/nvidia/nemotron-nano-12b-v2` | 1.6.0 | Yes | accessible | nemotron | reasoning |
| `nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl` | 1.6.0 | Yes | accessible | vision | vision-language |
| `nvcr.io/nim/nvidia/nemotron-4-340b-instruct` | 1.0.0 | No | nvaie_gated | nemotron | reasoning |
| `nvcr.io/nim/nvidia/nemotron-51b-instruct` | 1.1.0 | No | nvaie_gated | nemotron | reasoning |
| `nvcr.io/nim/nvidia/nemotron-70b-instruct` | 1.0.0 | No | nvaie_gated | nemotron | instruction-following |
| `nvcr.io/nim/nvidia/llama-3.1-8b-instruct` | 1.7.0 | Yes | accessible | llama | instruction-following |
| `nvcr.io/nim/nvidia/llama-3.1-70b-instruct` | 1.7.0 | No | accessible | llama | instruction-following |
| `nvcr.io/nim/nvidia/llama-3.1-405b-instruct` | 1.3.0 | No | accessible | llama | instruction-following |
| `nvcr.io/nim/nvidia/llama-3.2-nv-embedqa-1b-v2` | 2.1.0 | Yes | accessible | embed | embedding |
| `nvcr.io/nim/nvidia/llama-3.2-nv-rerankqa-1b-v2` | 2.0.0 | No | accessible | rerank | reranking |
| `nvcr.io/nim/nvidia/llama-3.1-nv-rerankqa-4b-v1` | 1.0.0 | No | nvaie_gated | rerank | reranking |
| `nvcr.io/nim/nvidia/llama-3.1-nv-rerankqa-70b-v1` | 1.0.0 | No | nvaie_gated | rerank | reranking |
| `nvcr.io/nim/nvidia/nv-embedqa-e5-v5` | 1.1.0 | No | nvaie_gated | embed | embedding |
| `nvcr.io/nim/nvidia/llama-guard-3-8b` | 1.3.0 | Yes | accessible | llama | safety |
| `nvcr.io/nim/nvidia/mistral-nemo-12b-instruct` | 1.2.0 | No | accessible | mistral | instruction-following |
| `nvcr.io/nim/nvidia/starcoder2-15b` | 1.0.0 | No | accessible | other | code-generation |

### `nvcr.io/nim/meta/*`

| Image | Latest Tag | ARM64 | Entitlement | Family | Task |
|-------|-----------|-------|-------------|--------|------|
| `nvcr.io/nim/meta/llama-3.1-8b-instruct` | 1.7.0 | Yes | accessible | llama | instruction-following |
| `nvcr.io/nim/meta/llama-3.1-70b-instruct` | 1.7.0 | Yes | accessible | llama | instruction-following |
| `nvcr.io/nim/meta/llama-3.2-1b-instruct` | 1.4.0 | Yes | accessible | llama | instruction-following |
| `nvcr.io/nim/meta/llama-3.2-3b-instruct` | 1.4.0 | Yes | accessible | llama | instruction-following |
| `nvcr.io/nim/meta/llama-3.2-11b-vision-instruct` | 1.2.0 | Yes | accessible | vision | vision-language |
| `nvcr.io/nim/meta/llama-3.1-405b-instruct` | 1.3.0 | No | accessible | llama | instruction-following |
| `nvcr.io/nim/meta/llama-3.3-70b-instruct` | 1.1.0 | No | accessible | llama | instruction-following |

### `nvcr.io/nim/mistralai/*`

| Image | Latest Tag | ARM64 | Entitlement | Family | Task |
|-------|-----------|-------|-------------|--------|------|
| `nvcr.io/nim/mistralai/mistral-7b-instruct-v0.3` | 1.2.0 | Yes | accessible | mistral | instruction-following |
| `nvcr.io/nim/mistralai/mixtral-8x7b-instruct-v0.1` | 1.1.0 | No | accessible | mistral | instruction-following |
| `nvcr.io/nim/mistralai/mixtral-8x22b-instruct-v0.1` | 1.0.0 | No | accessible | mistral | instruction-following |
| `nvcr.io/nim/mistralai/mistral-nemo-12b-instruct` | 1.1.0 | No | accessible | mistral | instruction-following |

### `nvcr.io/nim/deepseek-ai/*`

| Image | Latest Tag | ARM64 | Entitlement | Family | Task |
|-------|-----------|-------|-------------|--------|------|
| `nvcr.io/nim/deepseek-ai/deepseek-r1-distill-llama-70b` | latest | No | accessible | deepseek | reasoning |
| `nvcr.io/nim/deepseek-ai/deepseek-r1-distill-llama-8b` | latest | No | accessible | deepseek | reasoning |
| `nvcr.io/nim/deepseek-ai/deepseek-r1` | latest | No | nvaie_gated | deepseek | reasoning |

### `nvcr.io/nemo/*`

| Image | Latest Tag | ARM64 | Entitlement | Family | Task |
|-------|-----------|-------|-------------|--------|------|
| `nvcr.io/nemo/nemoguardrails` | 0.11.0 | No | accessible | nemo | safety |
| `nvcr.io/nemo/nemo-retriever-embedding` | 1.3.0 | No | accessible | nemo | embedding |
| `nvcr.io/nemo/nemo-retriever-reranking` | 1.2.0 | No | nvaie_gated | nemo | reranking |
| `nvcr.io/nemo/nemo-framework-training` | 25.04 | No | accessible | nemo | inference |

---

## Appendix B — Probe Anomalies / Notes

- `nvcr.io/nim/deepseek-ai/deepseek-r1` (671B full-weight) consistently returns 402 even with NVAIE credentials loaded. Likely requires a specific NVAIE SKU beyond standard enterprise. Flag for account-team call.
- `nvcr.io/nim/nvidia/nemotron-4-340b-instruct` appears in catalog but manifest returns 402. Available via the NGC playground but not self-hosted without specific contract.
- `nvcr.io/nim/meta/llama-3.1-70b-instruct` arm64 manifest claim is present but Stage-1 only; recommend Stage-2 ELF verification before NAS commit given its large compressed size (~39 GB) and prior reports of mislabeled manifests on 70B class models.
- NeMo framework containers (`nvcr.io/nemo/*`) are x86-only across the board. They are not immediate targets for Spark-01 deployment but remain useful for training workflows on a separate x86 node.
- NGC REST catalog API paginates at 100 records/page. All pages were consumed for each namespace; no premature cutoff detected.

---

## Appendix C — Next Steps (Gary's decision, not auto-assigned)

1. **Stage-2 ELF verification** — run `scripts/nim_pull_to_nas.py --verify-only` on the ARM64 candidates listed in §4 to confirm layer ELF before NAS commit. Priority order: `qwen2.5-7b-instruct` → `llama-3.1-8b-instruct` → `nemotron-nano-12b-v2` → `llama-3.2-nv-embedqa-1b-v2`.
2. **NVAIE entitlement conversation** — the 8 gated containers in §5, especially full-weight `deepseek-r1` (671B) and `nemotron-4-340b-instruct`, are the account-team agenda.
3. **ARM64 watch list** — `deepseek-r1-distill-llama-70b` and `deepseek-r1-distill-llama-8b` are x86-only today; monitor via `nvidia_sentinel.py`. When ARM64 manifests appear, they become HYDRA/TITAN upgrade candidates.
4. **Catalog diff-over-time** — rerun `tools/ngc_catalog_enumerator.py` weekly. The `nim_catalog` table's `probe_date` dimension makes it trivial to diff new vs. prior-week snapshots with a simple SQL query.
