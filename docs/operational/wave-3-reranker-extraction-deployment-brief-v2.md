# Wave 3 — Retrieval Stack Deployment Brief (v2 — rebuilt 2026-05-01)

**Target:** Claude Code on spark-2
**Branch:** `feat/wave-3-retrieval-stack-deployment-2026-05-01`
**Date:** 2026-05-01 (rebuild of 2026-04-30 v1 with current ARM64 reality)
**Operator:** Gary Knight
**Mode:** END-TO-END AUTONOMOUS — but with revised component scope. Hard stops only on real break conditions.
**Driver:** Track A v3 baseline (590s wall, 10/10 sections, finish=stop) validates the Nemotron-3-Super frontier. Wave 3 adds the retrieval pipeline that makes Case II briefing meaningfully better than the current state. **MAJOR REVISION FROM v1: NV-Ingest extraction stack is NOT yet ARM64-supported per NVIDIA staff confirmation (forums thread 360011, aniculescu, 2026-02-09). Component B reshaped to ARM64-native alternatives.**

**Stacks on:**
- PR #341 merged — three deep-research artifacts now on `main` under `docs/research/`
- PR #340 / Wave 2 closed
- PR #322 (Phase 9 alias surgery + BRAIN retirement; spark-5 freed)
- PR #321 (TP=2 deployment; soak active to 2026-05-14)
- Track A v3 Case I baseline (`Attorney_Briefing_Package_7IL_NDGA_I_v3_20260430T224403Z.md`)
- nemotron-super-stack-architecture-brief.md (Wave 3 spec)
- MASTER-PLAN v1.7 §6.2

**Resolves:** Wave 3 of the architecture brief, with ARM64-realistic component scope.

---

## 1. Mission

Deploy ARM64-validated retrieval pipeline components on spark-3 + spark-5. Wire LiteLLM aliases. Reindex `legal_ediscovery` Qdrant collection against the validated EMBED. End state: extraction → embedding → reranking → grounded synthesis on the TP=2 frontier, all running on what actually works on GB10 ARM64 today, with documented contingency for components that don't.

---

## 2. The ARM64 reality check (NEW — drives v2 component reshaping)

Field research 2026-05-01 confirms three landmines that v1 brief did not account for:

### 2.1 NV-Ingest has NO public ARM64 build
NVIDIA staff (aniculescu) confirmed on developer forums 2026-02-09 that nv-ingest images "have not been built for ARM platforms yet" with no ETA. April 2026 software update did not address this. **Component B in v1 brief is undeployable as written.**

### 2.2 Llama-3.2 NV Embedqa NIM broken on GB10 with `cudaErrorSymbolNotFound`
Reproducible failure on `nvcr.io/nim/nvidia/llama-3.2-nv-embedqa-1b-v2:1.10.0` on DGX Spark — released pre-Spark, ONNX runtime hits cudaErrorSymbolNotFound on ReduceSum node. NVIDIA's official recommendation for embed on Spark is **Qwen3-Embedding-4B via llama.cpp** (see multi-agent-chatbot playbook), not the broken NIM.

### 2.3 Most NIMs lack `-dgx-spark` tag
NIMs are now tagged `-dgx-spark` for ARM64+Blackwell compatibility. Models without that tag may surface as "amd64-only" → exec format error. **Every NIM pull in this brief verifies arm64 layers per PR #128 tooling before deployment.**

### 2.4 What we know works on Spark today
From cjeske's confirmed-working stack (forums thread 354998) on a different DGX Spark:
- `nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5:1.13.1` — works (older Super NIM)
- `nvcr.io/nim/nvidia/llama-3.2-nv-rerankqa-1b-v2:1.8.0` — **works on Spark**
- "NeMo Retriever page/graphic/table NIMs are also running fine" — works on Spark (per his report)
- `nvcr.io/nim/nvidia/llama-3.2-nv-embedqa-1b-v2:1.10.0` — **broken on Spark**

This is contradictory at first glance: cjeske says page/graphic/table work, NVIDIA staff say nv-ingest doesn't have ARM build. Resolution: page/graphic/table NIMs (the YOLOX detection components) appear to have ARM64 builds, but the **nv-ingest orchestrator** that wires them together does not. Without nv-ingest, you can run the per-component NIMs but lose the unified `/v1/extract` API.

### 2.5 The TP=2 frontier soak is continuing — protect it
Active NCCL all-reduce deadlock thread (forums 366127, 2026-04-09) reports TP=2 deadlocks across two DGX Sparks on multiple vLLM/TRT-LLM container versions and NCCL 2.27/2.28/2.29. Fortress-Prime's TP=2 frontier is currently stable; **nothing in this brief touches the spark-3+4 frontier endpoint**. Health-check it continuously throughout deployment.

---

## 3. Hard stops

Halt + surface ONLY for:

1. **NGC API auth fails persistently.** Two retries with cluster-canonical key + 30s sleep. Both fail → operator-side credential issue.
2. **ARM64 verification fails on any pulled NIM.** Per PR #128 tooling: manifest layers must be arm64 AND must actually contain arm64 binaries (not amd64 binaries under arm64 manifest — the Nemotron-Nano-9B incident).
3. **Frontier endpoint dies during deployment.** `curl http://10.10.10.3:8000/health` non-200 sustained >60s → halt and protect frontier. **This is non-negotiable: nothing about Wave 3 is worth breaking the TP=2 soak.**
4. **Soak halt event fires.** Phase 9 collector emits halt — cluster telling you to stop.
5. **Disk full** anywhere in the write path. <5GB free.
6. **OOM kill / nvidia-smi unresponsive / fabric link down on spark-3 or spark-5.**
7. **Qdrant reindex corrupts existing collection.** Use shadow-collection pattern. Note: alias silent-overwrite (qdrant#7584) — explicit `delete_alias + create_alias` in same atomic transaction, never bare `create_alias`.
8. **EMBED service fails to start with the same `cudaErrorSymbolNotFound` cjeske hit.** Documented broken on Spark; if you're trying to restart the v1.10.0 image, that's expected-broken. Do not retry.

Everything else proceeds. Defaults apply; deviations land in the final report.

---

## 4. Scope — REVISED FROM v1

**In scope:**

A. **Reranker NIM** on spark-5: `llama-3.2-nv-rerankqa-1b-v2:1.8.0` (the field-validated working version, NOT the newer `llama-nemotron-rerank-1b-v2` which lists Ampere/Hopper/Lovelace only — no Blackwell)
B. **Per-component extraction NIMs** on spark-5 — page-elements, graphic-elements, table-structure (validated-working per cjeske); skip nv-ingest orchestrator until ARM64 lands
C. **EMBED — DECISION GATE:** restart existing `legal-embed` service on spark-3:8102 IF the working version is `llama-nemotron-embed-1b-v2` (newer model). IF it's `llama-3.2-nv-embedqa-1b-v2:1.10.0`, switch to **Qwen3-Embedding-4B via llama.cpp** per NVIDIA Spark playbook recommendation
D. **Vision NIM** restart on spark-3:8101 (`nemotron-nano-12b-v2-vl`)
E. **LiteLLM alias additions** for new services (`legal-rerank`, `legal-extract-page`, `legal-extract-graphic`, `legal-extract-table`)
F. **Qdrant `legal_ediscovery` reindex** against new EMBED via shadow-collection pattern with explicit atomic alias swap
G. **End-to-end retrieval smoke** — query through per-component extraction → embed → rerank → top-k delivery
H. **Wave 3 deployment doc + reindex evidence pack**
I. **NV-Ingest ARM64 watchlist entry** in MASTER-PLAN — when ARM build lands, add unified extraction orchestrator as Wave 3.5

**Out of scope:**
- nv-ingest orchestrator (not ARM64-available; deferred to Wave 3.5 watchlist)
- Llama-3.2 NV Embedqa NIM (broken on Spark; replaced)
- Case II briefing work (Wave 7, separate brief)
- Wave 5 guardrails
- Wave 6 NAT migration
- NeMo Evaluator deployment
- Reprocessing the 14 Case II OCR'd PDFs through new extraction stack (separate Case II brief; happens after Wave 7 retrieval cutover)
- Sentinel content-aware classifier upgrade
- Frontier endpoint modifications

---

## 5. Pre-flight (autonomous)

### 5.1 State

```bash
git fetch origin
git checkout origin/main
git checkout -b feat/wave-3-retrieval-stack-deployment-2026-05-01
git status
git log origin/main..HEAD --oneline
```

### 5.2 Soak + frontier health

```bash
ssh admin@192.168.0.100 '
  tail -50 /mnt/fortress_nas/audits/phase-9-soak/$(date +%Y-%m-%d).log 2>/dev/null
  curl -fsS --max-time 10 http://10.10.10.3:8000/health
  curl -fsS http://10.10.10.3:8000/v1/models | jq ".data[].id"
'
```

Soak active + frontier 200 + nemotron-3-super listed → proceed. Otherwise hard stop §3.3 or §3.4.

### 5.3 NGC auth

```bash
ssh admin@192.168.0.100 '
  ngc config current
  ngc registry resource list --org cabin-rentals-of-georgia 2>&1 | head -10
'
```

If auth fails: try cluster-canonical key per MASTER-PLAN v1.7 §5.3. Both fail → hard stop §3.1.

### 5.4 spark-5 readiness (post-BRAIN retirement)

```bash
ssh admin@192.168.0.109 '
  hostname
  uptime
  df -h /
  nvidia-smi --query-gpu=name,memory.free,memory.total --format=csv
  systemctl is-active fortress-nim-brain.service 2>&1
  docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
'
```

Confirm:
- spark-5 GPU free ≥100 GB (BRAIN retired, ~128 GB available)
- spark-5 disk free ≥100 GB
- `fortress-nim-brain.service` inactive (Phase 9 retirement)

### 5.5 spark-3 capacity check (for restart of EMBED + Vision)

```bash
ssh admin@192.168.0.105 '
  hostname
  nvidia-smi --query-gpu=memory.free,memory.total --format=csv
  systemctl list-units --type=service --no-pager --state=active | grep fortress
  docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
'
```

Confirm spark-3 has ~14 GB GPU free (Vision ~12 GB + EMBED ~2 GB needed). If frontier is the only spark-3 tenant and is consuming ~115 GB, headroom is tight — proceed cautiously and monitor frontier health every 30s during co-tenant restart.

### 5.6 Identify which embed is currently deployed-inactive

```bash
ssh admin@192.168.0.105 '
  cat /etc/systemd/system/fortress-nim-embed.service 2>&1 | grep -i image
  ls -la /mnt/fortress_nas/nim-cache/nim/ | grep -i embed
'
```

Surface the image tag. Three branches:
- Image is `llama-nemotron-embed-1b-v2:*` → §6 path EMBED-A (restart in place)
- Image is `llama-3.2-nv-embedqa-1b-v2:1.10.0` → **§6 path EMBED-B (replace with Qwen3-Embedding-4B via llama.cpp)** — known broken on Spark per forums 354998
- Image is something else → log it and decide based on whether it's been tested on Spark

### 5.7 NIM catalog sanity check (record current state, not action)

```bash
ssh admin@192.168.0.100 '
  echo "=== Reranker (validated working on Spark per cjeske) ==="
  ngc registry resource info nim/nvidia/llama-3.2-nv-rerankqa-1b-v2 2>&1 | head -20

  echo "=== Extraction NIMs ==="
  for NIM in nv-yolox-page-elements-v2 nv-yolox-graphic-elements-v1 nv-yolox-table-structure-v1; do
    echo "--- $NIM ---"
    ngc registry resource list --query "$NIM" --org nvidia 2>&1 | head -5
  done

  echo "=== nv-ingest (expected: NO arm64 manifest) ==="
  ngc registry resource info nvidia/nv-ingest 2>&1 | head -20
'
```

Surface paths, sizes, dgx-spark tags. Document what's available to operator decision-making.

---

## 6. Component A — Reranker NIM on spark-5

### 6.1 Pull `llama-3.2-nv-rerankqa-1b-v2:1.8.0` (NOT the newer rerank-1b-v2)

**Why this version:** cjeske reports `:1.8.0` working healthy on DGX Spark in same thread that confirms newer embed broken. The newer `llama-nemotron-rerank-1b-v2` model card lists "Supported Hardware: Ampere, Hopper, Lovelace" — no Blackwell. Until NVIDIA publishes Blackwell support for the newer one, the 1.8.0 NIM is the validated path on Spark.

```bash
ssh admin@192.168.0.109 '
  cd /mnt/fortress_nas/nim-cache/nim/
  mkdir -p reranker-v2
  cd reranker-v2

  # Try cluster-side pull with timeout; F5 fallback if it fails
  timeout 600 ngc registry resource download-version "nim/nvidia/llama-3.2-nv-rerankqa-1b-v2:1.8.0" 2>&1 | tee /tmp/wave-3-reranker-pull.log
  PULL_RC=$?
  if [ $PULL_RC -ne 0 ]; then
    echo "Cluster-side pull failed (rc=$PULL_RC); fall back to W3 operator-side"
    rm -rf llama-3.2-nv-rerankqa-1b-v2_v1.8.0
  fi
  ls -la
'
```

If Path B (cluster) succeeds → §6.2. If fails → operator W3 pull on Mac, then scp to NAS, then §6.2.

### 6.2 ARM64 verification (HARD STOP §3.2)

```bash
ssh admin@192.168.0.109 '
  cd /mnt/fortress_nas/nim-cache/nim/reranker-v2/llama-3.2-nv-rerankqa-1b-v2_v1.8.0
  /home/admin/Fortress-Prime/backend/scripts/verify_nim_arm64.sh ./
  RC=$?
  if [ $RC -ne 0 ]; then
    echo "ARM64 VERIFICATION FAILED — HARD STOP §3.2"
    exit 1
  fi
'
```

### 6.3 HF-cache restructure (per MASTER-PLAN §5.4 step 4)

```bash
ssh admin@192.168.0.109 '
  /home/admin/Fortress-Prime/backend/scripts/nim_cache_restructure.sh \
    --source /mnt/fortress_nas/nim-cache/nim/reranker-v2/llama-3.2-nv-rerankqa-1b-v2_v1.8.0 \
    --target /mnt/fortress_nas/nim-cache/nim/reranker-v2/hf-cache
'
```

### 6.4 systemd unit + start

```bash
ssh admin@192.168.0.109 '
  sudo tee /etc/systemd/system/fortress-nim-rerank.service > /dev/null <<EOF
[Unit]
Description=Fortress NIM Rerank — llama-3.2-nv-rerankqa-1b-v2:1.8.0 on spark-5 (Tier 4 retrieval)
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=admin
EnvironmentFile=/etc/fortress/nim.env
ExecStartPre=-/usr/bin/docker stop fortress-nim-rerank
ExecStartPre=-/usr/bin/docker rm fortress-nim-rerank
ExecStart=/usr/bin/docker run --rm \\
  --name fortress-nim-rerank \\
  --gpus all \\
  --shm-size=8g \\
  -p 8103:8000 \\
  -v /mnt/fortress_nas/nim-cache/nim/reranker-v2/hf-cache:/opt/nim/.cache \\
  -e NGC_API_KEY=\${NGC_API_KEY} \\
  -e NIM_MODEL_PROFILE=auto \\
  nvcr.io/nim/nvidia/llama-3.2-nv-rerankqa-1b-v2:1.8.0
ExecStop=/usr/bin/docker stop fortress-nim-rerank
Restart=on-failure
RestartSec=30s

[Install]
WantedBy=multi-user.target
EOF

  sudo systemctl daemon-reload
  sudo systemctl enable fortress-nim-rerank.service
  sudo systemctl start fortress-nim-rerank.service
  sleep 60
  sudo systemctl status fortress-nim-rerank.service --no-pager | head -25
'
```

### 6.5 Health probe

```bash
ssh admin@192.168.0.109 '
  for i in 1 2 3 4 5 6; do
    sleep 30
    if curl -fsS --max-time 10 http://localhost:8103/v1/health/ready 2>/dev/null; then
      echo "Reranker ready after ${i}x30s"
      break
    fi
    echo "Reranker not ready (${i}/6)"
  done
  curl -fsS http://localhost:8103/v1/health/ready
  curl -fsS http://localhost:8103/v1/models | jq .
'
```

### 6.6 Functional smoke

```bash
ssh admin@192.168.0.109 '
  curl -fsS http://localhost:8103/v1/ranking \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"nvidia/llama-3.2-nv-rerankqa-1b-v2\",
      \"query\": {\"text\": \"easement on River Heights\"},
      \"passages\": [
        {\"text\": \"The plaintiff alleges Knight recorded an easement on River Heights in March 2025 burdening the property in favor of Thor James.\"},
        {\"text\": \"The Atlanta Hawks won the 1958 NBA Championship.\"},
        {\"text\": \"Knight argues the easement was within his rights as titleholder pre-closing.\"}
      ]
    }" | jq .
'
```

Expected: legal-text passages outrank basketball passage.

---

## 7. Component B — Per-component Extraction NIMs on spark-5

**SCOPE CHANGE FROM v1:** v1 brief specified `nv-ingest` as orchestrator. nv-ingest has no public ARM64 build per NVIDIA staff (forums 360011). v2 deploys the per-component YOLOX detection NIMs (which cjeske confirms work on Spark) and exposes them individually via LiteLLM. Unified extraction orchestrator deferred to Wave 3.5 watchlist.

### 7.1 Catalog enumeration

```bash
ssh admin@192.168.0.100 '
  for NIM in nv-yolox-page-elements-v2 nv-yolox-graphic-elements-v1 nv-yolox-table-structure-v1; do
    echo "=== $NIM ==="
    ngc registry resource info "nim/nvidia/${NIM}" 2>&1 | head -30
    echo
  done
'
```

Surface paths, sizes, dgx-spark tags per NIM. Each is small (~2-5 GB).

### 7.2 Per-NIM pull pattern (apply for each of the three)

For each of `nv-yolox-page-elements-v2`, `nv-yolox-graphic-elements-v1`, `nv-yolox-table-structure-v1`:

1. Cluster-side pull (timeout 10 min)
2. ARM64 verify (HARD STOP §3.2 per-NIM)
3. HF-cache restructure
4. systemd unit (port 8110/8111/8112 respectively)
5. Service start + health probe
6. If any one fails ARM64 verify → halt that NIM, continue with the others, document in final report

### 7.3 systemd unit template (apply per-NIM, swap NIM_NAME and PORT)

```ini
[Unit]
Description=Fortress NIM Extraction ${NIM_NAME} on spark-5 (Tier 4 retrieval)
After=docker.service
Requires=docker.service

[Service]
Type=simple
User=admin
EnvironmentFile=/etc/fortress/nim.env
ExecStartPre=-/usr/bin/docker stop fortress-nim-${NIM_NAME}
ExecStartPre=-/usr/bin/docker rm fortress-nim-${NIM_NAME}
ExecStart=/usr/bin/docker run --rm \
  --name fortress-nim-${NIM_NAME} \
  --gpus all \
  --shm-size=8g \
  -p ${PORT}:8000 \
  -v /mnt/fortress_nas/nim-cache/nim/${NIM_NAME}/hf-cache:/opt/nim/.cache \
  -e NGC_API_KEY=${NGC_API_KEY} \
  -e NIM_MODEL_PROFILE=auto \
  nvcr.io/nim/nvidia/${NIM_NAME}:latest-dgx-spark
ExecStop=/usr/bin/docker stop fortress-nim-${NIM_NAME}
Restart=on-failure
RestartSec=30s

[Install]
WantedBy=multi-user.target
```

**Critical:** Use `:latest-dgx-spark` tag if available (per DeepWiki: "containers tagged with `-dgx-spark` to indicate ARM64 and Blackwell GPU compatibility"). If only `:latest` is available, ARM64 verify must pass.

### 7.4 Per-NIM functional smoke

For each, send a sample PDF page and verify:
- page-elements → returns layout boxes (text/figure/table regions)
- graphic-elements → returns chart/figure metadata
- table-structure → returns table cell structure

Document per-NIM smoke output in final report.

---

## 8. Component C — EMBED restart or replace on spark-3

### 8.1 Path EMBED-A: existing service is `llama-nemotron-embed-1b-v2`

If §5.6 surfaces the newer embed:

```bash
ssh admin@192.168.0.105 '
  sudo systemctl start fortress-nim-embed.service
  sleep 60
  sudo systemctl status fortress-nim-embed.service --no-pager | head -25
  for i in 1 2 3 4 5; do
    sleep 30
    if curl -fsS --max-time 10 http://localhost:8102/v1/health/ready 2>/dev/null; then
      echo "EMBED ready after ${i}x30s"
      break
    fi
  done
  curl -fsS http://localhost:8102/v1/models | jq .
'
```

If EMBED comes up healthy → §8.3 functional smoke.

### 8.2 Path EMBED-B: existing service is broken `llama-3.2-nv-embedqa-1b-v2:1.10.0`

**Replace with Qwen3-Embedding-4B via llama.cpp** per NVIDIA's official multi-agent-chatbot playbook recommendation for Spark.

```bash
ssh admin@192.168.0.105 '
  sudo systemctl stop fortress-nim-embed.service
  sudo systemctl disable fortress-nim-embed.service

  # Download Qwen3-Embedding-4B GGUF
  cd /mnt/fortress_nas/models
  mkdir -p qwen3-embedding-4b
  hf download Qwen/Qwen3-Embedding-4B-GGUF \
    Qwen3-Embedding-4B-Q8_0.gguf \
    --local-dir ./qwen3-embedding-4b/

  # Build llama.cpp on spark-3 (one-time) if not already present
  if [ ! -f /home/admin/llama.cpp/build/bin/llama-server ]; then
    cd /home/admin
    git clone https://github.com/ggerganov/llama.cpp.git 2>/dev/null || (cd llama.cpp && git pull)
    cd llama.cpp
    mkdir -p build && cd build
    cmake .. -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="121" -DLLAMA_CURL=OFF
    make -j8
  fi
'
```

Then create systemd unit `fortress-embed-llamacpp.service` running `llama-server --embedding --port 8102 -m /mnt/fortress_nas/models/qwen3-embedding-4b/Qwen3-Embedding-4B-Q8_0.gguf -ngl 99 --host 0.0.0.0`.

**KNOWN CONSEQUENCE:** Vector dimensionality differs from old embed. `legal_ediscovery` MUST be reindexed (Component F). This is expected if Path EMBED-B taken.

### 8.3 EMBED functional smoke

```bash
ssh admin@192.168.0.105 '
  curl -fsS http://localhost:8102/v1/embeddings \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"<actual-model-name>\", \"input\": [\"This is a test passage about easement law.\"]}" | jq ".data[0].embedding | length"
'
```

Surface vector dimensionality. Locks the reindex schema in §10.

---

## 9. Component D — Vision NIM restart on spark-3

```bash
ssh admin@192.168.0.105 '
  sudo systemctl start fortress-nim-vision.service
  sleep 60
  curl -fsS http://localhost:8101/v1/health/ready
  curl -fsS http://localhost:8101/v1/models | jq .
'
```

Same restart pattern as v1 brief §7. Vision uses `nemotron-nano-12b-v2-vl` per nemotron-super-stack-architecture-brief.md Tier 5; that one is field-validated on Spark.

**Frontier health check after Vision restart** (spark-3 capacity is tight):

```bash
ssh admin@192.168.0.100 '
  curl -fsS --max-time 10 http://10.10.10.3:8000/health
  curl -fsS http://10.10.10.3:8000/v1/models | jq ".data[].id"
'
```

If frontier 200 → continue. If non-200 → HARD STOP §3.3.

---

## 10. Component E — LiteLLM aliases

### 10.1 Pre-mutation snapshot

```bash
ssh admin@192.168.0.100 '
  cp /home/admin/Fortress-Prime/litellm_config.yaml \
     /home/admin/Fortress-Prime/litellm_config.yaml.bak.wave-3-$(date +%Y%m%dT%H%M%SZ)
'
```

### 10.2 Add aliases

Add to `litellm_config.yaml`:

```yaml
- model_name: legal-rerank
  litellm_params:
    model: openai/nvidia/llama-3.2-nv-rerankqa-1b-v2
    api_base: http://192.168.0.109:8103/v1
    api_key: empty

- model_name: legal-extract-page
  litellm_params:
    model: openai/nvidia/nv-yolox-page-elements-v2
    api_base: http://192.168.0.109:8110/v1
    api_key: empty

- model_name: legal-extract-graphic
  litellm_params:
    model: openai/nvidia/nv-yolox-graphic-elements-v1
    api_base: http://192.168.0.109:8111/v1
    api_key: empty

- model_name: legal-extract-table
  litellm_params:
    model: openai/nvidia/nv-yolox-table-structure-v1
    api_base: http://192.168.0.109:8112/v1
    api_key: empty
```

If Path EMBED-B taken in §8.2, also update `legal-embed` alias to point at `http://192.168.0.105:8102/v1` with the Qwen3 model name.

### 10.3 LiteLLM reload + per-alias smoke

```bash
ssh admin@192.168.0.100 '
  sudo systemctl reload fortress-litellm.service || sudo systemctl restart fortress-litellm.service
  sleep 10
  curl -fsS http://localhost:4000/v1/models | jq ".data[].id" | grep -E "legal-rerank|legal-extract"
'
```

Document the four/five new aliases in final report.

---

## 11. Component F — Qdrant `legal_ediscovery` reindex

### 11.1 Shadow-collection pattern

```bash
ssh admin@192.168.0.100 '
  # Create new collection with current EMBED dim
  EMBED_DIM=$(curl -fsS http://192.168.0.105:8102/v1/embeddings -H "Content-Type: application/json" -d "{\"model\": \"<model-name>\", \"input\": [\"test\"]}" | jq ".data[0].embedding | length")
  echo "EMBED_DIM=${EMBED_DIM}"

  # Snapshot the old one first (qdrant#6754: alias data not in snapshot, but we want point data)
  curl -fsS -X POST "http://localhost:6333/collections/legal_ediscovery/snapshots"

  curl -fsS -X PUT "http://localhost:6333/collections/legal_ediscovery_v2" \
    -H "Content-Type: application/json" \
    -d "{
      \"vectors\": {
        \"size\": ${EMBED_DIM},
        \"distance\": \"Cosine\"
      }
    }"
'
```

### 11.2 Reindex from source (NOT from existing vectors — they're old embed)

Vectors must be regenerated against new EMBED. Re-run the original ingestion pipeline output (Sentinel-emitted document chunks) through new EMBED:

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  python3 -m fortress.indexing.reindex_legal_ediscovery \
    --source-collection legal_ediscovery \
    --target-collection legal_ediscovery_v2 \
    --embed-endpoint http://192.168.0.105:8102/v1 \
    --batch-size 64 \
    2>&1 | tee /mnt/fortress_nas/audits/wave-3-reindex-$(date +%Y%m%dT%H%M%SZ).log
'
```

If reindex script doesn't exist at that path: build minimal scratch script using the chunk metadata from `legal_ediscovery` payload (text + source path) → embed via new endpoint → upsert to v2. **Do not commit scratch script** — keep it ad-hoc for this brief; productionize in separate PR if needed.

### 11.3 Validation against shadow

```bash
ssh admin@192.168.0.100 '
  ORIG_COUNT=$(curl -fsS http://localhost:6333/collections/legal_ediscovery | jq ".result.points_count")
  NEW_COUNT=$(curl -fsS http://localhost:6333/collections/legal_ediscovery_v2 | jq ".result.points_count")
  echo "Original: $ORIG_COUNT, Shadow: $NEW_COUNT"

  # Must be within 1% — chunks may differ slightly if EMBED chunks differently
  if [ $(echo "scale=4; ($NEW_COUNT - $ORIG_COUNT) / $ORIG_COUNT" | bc -l | tr -d -) > 0.01 ]; then
    echo "Shadow point count >1% off — investigate before cutover"
    exit 1
  fi
'
```

### 11.4 Quality probe before cutover

Run 3 known-good queries against both collections:

```bash
QUERIES=(
  "easement on River Heights recorded by Knight"
  "section 8 financial breakdown Q3 2025"
  "Thor James grantor warranty deed"
)

for q in "${QUERIES[@]}"; do
  # Query both, compare top-5 source paths overlap
  ...
done
```

Document overlap percentage. If <60% top-5 overlap → flag for operator review before cutover; do not auto-cutover.

### 11.5 Atomic alias swap (CRITICAL — qdrant#7584)

```bash
ssh admin@192.168.0.100 '
  curl -fsS -X POST "http://localhost:6333/collections/aliases" \
    -H "Content-Type: application/json" \
    -d "{
      \"actions\": [
        {\"delete_alias\": {\"alias_name\": \"legal_ediscovery_active\"}},
        {\"create_alias\": {\"collection_name\": \"legal_ediscovery_v2\", \"alias_name\": \"legal_ediscovery_active\"}}
      ]
    }"
'
```

**Why explicit delete + create in same atomic transaction:** qdrant#7584 confirms `create_alias` silently overwrites without warning. The atomic delete+create pattern makes the swap intention explicit and survives rollback inspection.

If application code currently references `legal_ediscovery` directly (not the alias), update Phase B retrieval config to use `legal_ediscovery_active` alias instead. This is one config change in `fortress-guest-platform/backend/services/case_briefing_synthesizers.py` or wherever Qdrant client is initialized. Do not delete `legal_ediscovery` original — keep for 14-day rollback window.

---

## 12. Component G — End-to-end retrieval smoke

```bash
ssh admin@192.168.0.100 '
  # Real Case I retrieval query
  QUERY="What did Knight argue about the easement timing in his answer?"

  # 1. EMBED the query
  EMBEDDING=$(curl -fsS http://192.168.0.105:8102/v1/embeddings \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"<model>\", \"input\": [\"${QUERY}\"]}" | jq ".data[0].embedding")

  # 2. Search Qdrant via alias
  TOP_K=$(curl -fsS http://localhost:6333/collections/legal_ediscovery_active/points/search \
    -H "Content-Type: application/json" \
    -d "{\"vector\": ${EMBEDDING}, \"limit\": 20, \"with_payload\": true}" | jq ".result")

  # 3. Rerank top 20 to top 5
  RERANKED=$(curl -fsS http://192.168.0.109:8103/v1/ranking \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"nvidia/llama-3.2-nv-rerankqa-1b-v2\",
      \"query\": {\"text\": \"${QUERY}\"},
      \"passages\": [...top-20-text...]
    }")

  # 4. Document end-to-end latency + source paths surfaced
'
```

Expected: ≥3 of top-5 reranked passages cite Knight's answer document. Document end-to-end wall (target <5s).

---

## 13. PR

### 13.1 Files to commit

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime

  # Land THIS brief itself
  cp /home/admin/wave-3-reranker-extraction-deployment-brief-v2.md docs/operational/

  # systemd units
  mkdir -p deploy/systemd/spark-5 deploy/systemd/spark-3
  scp admin@192.168.0.109:/etc/systemd/system/fortress-nim-rerank.service deploy/systemd/spark-5/
  scp admin@192.168.0.109:/etc/systemd/system/fortress-nim-page-elements.service deploy/systemd/spark-5/
  scp admin@192.168.0.109:/etc/systemd/system/fortress-nim-graphic-elements.service deploy/systemd/spark-5/
  scp admin@192.168.0.109:/etc/systemd/system/fortress-nim-table-structure.service deploy/systemd/spark-5/

  # If Path EMBED-B taken, llama.cpp service unit
  scp admin@192.168.0.105:/etc/systemd/system/fortress-embed-llamacpp.service deploy/systemd/spark-3/ 2>/dev/null || true

  # LiteLLM diff
  diff -u /home/admin/Fortress-Prime/litellm_config.yaml.bak.wave-3-* /home/admin/Fortress-Prime/litellm_config.yaml > docs/operational/wave-3-litellm-config-diff.patch

  # Reindex evidence
  cp /mnt/fortress_nas/audits/wave-3-reindex-*.log docs/operational/

  # Final run report
  cat > docs/operational/wave-3-final-report.md <<EOF
# Wave 3 Final Report — $(date +%Y-%m-%d)
[populated at run end per §14]
EOF

  # Runbook
  cat > docs/operational/runbooks/wave-3-retrieval-stack.md <<EOF
# Wave 3 Retrieval Stack Runbook

## Services
- spark-5:8103 fortress-nim-rerank.service — llama-3.2-nv-rerankqa-1b-v2:1.8.0
- spark-5:8110 fortress-nim-page-elements.service
- spark-5:8111 fortress-nim-graphic-elements.service
- spark-5:8112 fortress-nim-table-structure.service
- spark-3:8102 fortress-nim-embed.service OR fortress-embed-llamacpp.service (Path EMBED-A or EMBED-B)
- spark-3:8101 fortress-nim-vision.service

## Critical health invariants
1. spark-3+4 frontier endpoint health (http://10.10.10.3:8000/health) MUST stay 200
2. Reranker only deployed via :1.8.0 — newer rerank-1b-v2 lacks Blackwell support
3. EMBED only deployed via Path EMBED-A (llama-nemotron-embed-1b-v2) or EMBED-B (Qwen3-Embedding-4B llama.cpp); v1.10.0 of llama-3.2-nv-embedqa is BROKEN on Spark

## Watchlist (deferred to Wave 3.5)
- nv-ingest unified extraction orchestrator — when ARM64 build lands per forums 360011
- llama-nemotron-rerank-1b-v2 (newer model) — when NVIDIA publishes Blackwell support

## Qdrant collections
- legal_ediscovery — original, archived for 14-day rollback
- legal_ediscovery_v2 — current production, target of legal_ediscovery_active alias
- legal_ediscovery_active — alias to v2, used by Phase B retrieval

## Rollback procedure
- Service rollback: systemctl stop new service; restart old image tag
- Qdrant rollback: atomic alias swap delete+create back to original collection
EOF

  git add docs/operational/wave-3-* docs/operational/runbooks/wave-3-* deploy/systemd/spark-5/ deploy/systemd/spark-3/
  git status
'
```

### 13.2 Commit + PR

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  git commit -m "feat(wave-3): retrieval stack deployment (Reranker + per-component Extraction + EMBED + Vision)

ARM64-validated component selection:
- Reranker NIM via field-tested llama-3.2-nv-rerankqa-1b-v2:1.8.0 (newer
  rerank-1b-v2 lists no Blackwell support)
- Per-component YOLOX extraction NIMs on spark-5 (page/graphic/table)
- nv-ingest orchestrator deferred to Wave 3.5 watchlist (no public ARM64
  build per NVIDIA forums thread 360011, 2026-02-09)
- EMBED via [Path EMBED-A or EMBED-B based on existing image] — broken
  llama-3.2-nv-embedqa-1b-v2:1.10.0 NOT used (forums 354998)
- Vision restored via nemotron-nano-12b-v2-vl
- LiteLLM aliases legal-rerank, legal-extract-page/graphic/table added
- legal_ediscovery reindexed to legal_ediscovery_v2; alias
  legal_ediscovery_active points at v2 via atomic delete+create swap (qdrant#7584)
- End-to-end retrieval pipeline smoke validated

Frontier endpoint untouched; soak clock unaffected (active to 2026-05-14).

Wave 3 of nemotron-super-stack-architecture-brief.md.
Stacks on PR #341 (deep-research artifacts).
"

  git push -u origin feat/wave-3-retrieval-stack-deployment-2026-05-01

  gh pr create \
    --title "Wave 3 — Retrieval stack: Reranker + per-component Extraction + EMBED/Vision (v2 ARM64-validated)" \
    --body-file docs/operational/wave-3-final-report.md \
    --draft
'
```

PR opens as draft. Operator promotes to ready after reviewing extraction smoke output, reindex log, and frontier health throughout deployment.

---

## 14. Final report (auto-surface at run end)

Surface to chat at run end:

1. **Pre-flight summary**
   - Soak status, frontier health throughout
   - NGC auth path (cluster vs W3 fallback)
   - spark-5 readiness, spark-3 headroom
   - EMBED branch identified (A or B)

2. **Component A — Reranker (`:1.8.0`)**
   - Pull path used (cluster vs W3)
   - ARM64 verification result
   - Service running on 8103, health 200
   - Functional smoke result (legal text vs basketball)

3. **Component B — Per-component Extraction**
   - Per-NIM pull status (3 NIMs)
   - Service stack on 8110/8111/8112
   - Per-NIM functional smoke
   - **Wave 3.5 watchlist note for nv-ingest orchestrator**

4. **Component C — EMBED**
   - Path used (EMBED-A restart or EMBED-B Qwen3 llama.cpp)
   - Vector dimensionality
   - Health probe result
   - Functional smoke

5. **Component D — Vision restart**
   - Service running on 8101
   - **Frontier health post-Vision-restart** (critical due to spark-3 co-tenancy)

6. **Component E — LiteLLM aliases**
   - Pre/post alias map
   - Per-alias smoke

7. **Component F — Qdrant reindex**
   - Original / shadow point counts
   - Quality probe top-5 overlap percentage
   - Atomic alias swap evidence

8. **Component G — End-to-end retrieval**
   - Pipeline pass/fail
   - End-to-end wall

9. **Halt triggers fired** (should be zero on clean run)

10. **Soak impact**
    - Frontier health throughout (any 30s+ non-200 windows)
    - Memory peaks on spark-3, spark-5
    - Any soak halt events

11. **PR**
    - Branch, PR number + URL
    - Files committed

12. **Recommended operator next action**
    - All pass: Wave 3 complete; Case II briefing (Wave 7) has retrieval stack
    - Partial pass: which components deferred + Wave 3.5 scope

---

## 15. Constraints

- Branches from `origin/main` only.
- Single Claude Code session at a time on cluster.
- Never `--admin`, never self-merge, never force-push main.
- **DO NOT modify the spark-3+4 frontier endpoint or its serve flags.** This is non-negotiable.
- DO NOT touch Track A artifacts (separate work).
- DO NOT modify Phase B v0.1 orchestrator code.
- DO NOT delete `legal_ediscovery` original collection — archive for 14-day rollback only.
- DO NOT halt for soft conditions; hard stops in §3 only.
- ARM64 verification on every NIM is non-negotiable (HARD STOP §3.2).
- Frontier health monitored continuously; if degrades, protect frontier (HARD STOP §3.3).
- DO NOT pull `nv-ingest` orchestrator (no ARM build; Wave 3.5).
- DO NOT pull `llama-nemotron-rerank-1b-v2` (lacks Blackwell support; use `llama-3.2-nv-rerankqa-1b-v2:1.8.0`).
- DO NOT restart `llama-3.2-nv-embedqa-1b-v2:1.10.0` (broken on Spark per forums 354998 — falls to Path EMBED-B).
- If ANY ARM64 verification fails, that component does NOT deploy; document and continue.

---

## 16. References

**NVIDIA official:**
- DGX Spark Software Updates 04/2026 announcement: https://forums.developer.nvidia.com/t/dgx-spark-software-updates-04-2026/368114
- Nemotron 3 Super Spark Deployment Guide: https://docs.nvidia.com/nemotron/nightly/usage-cookbook/Nemotron-3-Super/SparkDeploymentGuide/README.html
- Multi-Agent Chatbot playbook (Qwen3-Embedding-4B reference): https://build.nvidia.com/spark/multi-agent-chatbot
- DGX Spark Porting Guide: https://docs.nvidia.com/dgx/dgx-spark-porting-guide/dgx-spark-porting-guide.pdf
- DGX Spark Playbooks DeepWiki: https://deepwiki.com/NVIDIA/dgx-spark-playbooks

**Field reports — confirmed working / broken on Spark:**
- nv-ingest no ARM build (NVIDIA staff): https://forums.developer.nvidia.com/t/dgx-spark-arm64-nv-ingest-images-or-roadmap/360011
- Embed NIM cudaErrorSymbolNotFound (cjeske, NVIDIA reply): https://forums.developer.nvidia.com/t/dgx-spark-gb10-arm64-embedding-nim-llama-3-2-nv-embedqa-1b-v2-1-10-0-fails-with-cudaerrorsymbolnotfound-onnx-runtime/354998
- NIMs multiplatform request: https://forums.developer.nvidia.com/t/nims-should-be-built-multiplatform/348914
- NCCL all-reduce deadlock dual Spark: https://forums.developer.nvidia.com/t/nccl-all-reduce-deadlock-on-dual-dgx-spark-after-successful-channel-establishment-affects-both-vllm-and-trt-llm/366127
- Leon Gibat dual-Spark TP=2 NVFP4 24 tok/s: https://forums.developer.nvidia.com/t/nemotron-3-super-nvfp4-via-vllm-tp-2-on-2x-dgx-spark-24-tok-s-abi-fix-for-cu130-cu132-mismatch/364862

**Qdrant landmines:**
- Alias silent overwrite: https://github.com/qdrant/qdrant/issues/7584
- Alias data not in snapshot: https://github.com/qdrant/qdrant/issues/6754

**Project knowledge:**
- v1 brief: `wave-3-reranker-extraction-deployment-brief.md` (this is the source for procedures; v2 amends component scope)
- `nemotron-super-stack-architecture-brief.md` (Wave 3 spec, ADR-005)
- `MASTER-PLAN-v1.7.md` (Tier-1 NIM batch-pull, §6.2)
- `nemotron-3-super-deep-research-2026-04-30.md` (cited for chat template + reasoning control mechanics)

---

## 17. What changed from v1

| Section | v1 | v2 |
|---|---|---|
| Component B | nv-ingest orchestrator + 4 component NIMs | Per-component NIMs only; nv-ingest deferred to Wave 3.5 watchlist |
| Component A model | `llama-nemotron-rerank-1b-v2` (newer; no Blackwell) | `llama-3.2-nv-rerankqa-1b-v2:1.8.0` (field-validated on Spark) |
| Component C | Restart existing EMBED service | Decision gate: restart if `llama-nemotron-embed-1b-v2`; replace with Qwen3-Embedding-4B + llama.cpp if `llama-3.2-nv-embedqa-1b-v2:1.10.0` (broken) |
| Hard stops | 7 conditions | 8 conditions (added: EMBED known-broken signature) |
| Qdrant alias swap | Implicit `create_alias` | Explicit atomic `delete_alias` + `create_alias` per qdrant#7584 |
| Frontier protection | Stated as hard stop | Stated as hard stop + explicit reminder due to dual-Spark TP=2 instability reports |
| References | NVIDIA cookbook only | + 5 field-report threads documenting current ARM64 state |

---

End of Wave 3 v2 brief.
