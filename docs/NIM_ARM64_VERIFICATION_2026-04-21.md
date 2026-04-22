# NIM / Nemotron ARM64 Verification — 2026-04-21

**Purpose:** Phase 0 gate check before any NIM pulls to the DGX Spark cluster.
**Method:** docker manifest inspect (authenticated via nvapi key), NVIDIA Build API catalog.
**Cluster:** 4× DGX Spark GB10 Grace Blackwell — ARM64 aarch64, 128GB unified memory each.

---

## Name resolution (brief intel vs actual NGC catalog)

| Brief name | Actual NGC catalog ID | Match? |
|---|---|---|
| Nemotron-3-Nano-30B-A3B | `nvidia/nemotron-3-nano-30b-a3b` AND `nvidia/nemotron-nano-3-30b-a3b` | Two variants — Gary confirms which |
| Nemotron-Nano-9B-v2-NIM | `nvidia/nvidia-nemotron-nano-9b-v2` | **Name differs** — double "nvidia" prefix |
| Nemotron-Nano-12B-v2-VL-NIM | `nvidia/nemotron-nano-12b-v2-vl` | Exact match |
| llama-nemotron-embed-1b-v2 | `nvidia/llama-nemotron-embed-1b-v2` | Exact match |
| llama-nemotron-rerank-1b-v2 | **NOT FOUND** | No rerank-1b model in NGC catalog |

**Rerank note:** NGC catalog has `nvidia/llama-3.2-nemoretriever-1b-vlm-embed-v1` and
`nvidia/llama-3.2-nemoretriever-300m-embed-v1` (embed models). No dedicated rerank-1b
model exists under this name. NeMo Retriever reranking may be provided via a different
container not currently in the Build API, or the brief's name is incorrect.
Closest candidate to confirm with Gary: `nvidia/llama-3.2-nemoretriever-1b-vlm-embed-v1`.

---

## ARM64 verification table

Manifest inspected via: `docker manifest inspect nvcr.io/nim/nvidia/<model>:latest`
Auth: `docker login nvcr.io -u '$oauthtoken' -p <nvapi-key>`

| # | Model (actual NGC ID) | ARM64? | Method | Notes |
|---|---|---|---|---|
| 1 | nvidia/nvidia-nemotron-nano-9b-v2 | ✅ YES | manifest | architectures: [amd64, arm64] |
| 2 | nvidia/nemotron-nano-12b-v2-vl | ✅ YES | manifest | architectures: [arm64, amd64] |
| 3 | nvidia/llama-nemotron-embed-1b-v2 | ✅ YES | manifest | architectures: [arm64, amd64] |
| 4 | nvidia/nemotron-3-nano-30b-a3b | ❓ UNVERIFIABLE | manifest denied | NIM container requires elevated NGC entitlement; registry returns ACCESS DENIED even with nvapi key. Cannot confirm ARM64 without NVAIE subscription or explicit NIM access grant. |
| 5 | llama-nemotron-rerank-1b-v2 | ❌ NOT FOUND | catalog search | Model does not exist in NGC catalog under this name. Cannot verify. |

---

## License assessment

Nemotron models released under the **NVIDIA Open Model License Agreement** (NOMLA).
NOMLA permits commercial use by entities with revenue < $1B/year or < 700M monthly active users.
CROG/Fortress Prime is a small business — comfortably within NOMLA commercial use thresholds.

**Exception:** NIM containers require a valid NGC account and may require NVAIE (NVIDIA AI
Enterprise) subscription for production deployment. Development use is permitted under
standard NGC terms. Confirm with Gary whether NVAIE is active or needed before production pull.

---

## Memory budget — 60% headroom rule

DGX Spark GB10 unified memory: **128GB per node**
60% cap: **76.8GB** | 40% reserve floor: **51.2GB**

### Current load (from /api/ps, live):

| Node | IP | Current VRAM active | On-disk models |
|---|---|---|---|
| spark-2 | 192.168.0.100 | ~0GB (qwen2.5:7b idle) | 5.4GB |
| spark-1 | 192.168.0.104 | 0.6GB (nomic-embed) | 131GB |
| spark-3 | 192.168.0.105 | 0GB | 62.7GB |
| spark-4 | 192.168.0.106 | 8.2GB (qwen2.5:7b) | 76.4GB |

### Proposed deployments + memory math:

**Deployment A — spark-4 (VRS)**

| Component | Size | Running total | % of 128GB |
|---|---|---|---|
| Existing qwen2.5:7b (cold standby) | 4.7GB | 12.9GB | 10% |
| nemotron-nano-9b-v2 NIM | ~18GB | 30.9GB | 24% |
| llama-nemotron-embed-1b-v2 | ~2GB | 32.9GB | 26% |
| RERANK (unresolved) | TBD | TBD | TBD |

**Verdict: WITHIN 60%** assuming no reranker size surprise.
spark-4 has 76.4GB on disk but only 8.2GB active — plenty of headroom.

**Deployment B — spark-1 (deliberation seats)**

| Component | Size | Running total | % of 128GB |
|---|---|---|---|
| Existing nomic-embed | 0.6GB | 0.6GB | 0.5% |
| deepseek-r1:70b (loaded on demand) | 42.5GB | 43.1GB | 34% |
| nemotron-3-nano-30b-a3b fp16 | ~60GB | 103.1GB | 81% |

**Verdict: BLOCKED** — 30B fp16 + deepseek-r1:70b together would push spark-1 to ~81%,
exceeding the 60% cap. Options: (a) use INT4/INT8 quantized NIM build (~15-20GB,
would bring total to ~63GB = 49%), or (b) confirm 30B model is MoE where active weight
footprint is ~8-10GB (not full 60GB). The brief says "3.5B active params" — this needs
to be confirmed against actual NIM container memory requirements.

**Deployment C — spark-3 (Vision)**

| Component | Size | Running total | % of 128GB |
|---|---|---|---|
| llama3.2-vision:90b (on disk, cold) | 54.6GB | 8GB active | 6% |
| nemotron-nano-12b-v2-vl NIM | ~24GB | 32GB | 25% |

**Verdict: WITHIN 60%** provided vision jobs are gated (which they are via vision_guard.sh).

---

## Stop conditions that fire in Phase 0

**STOP #4 (name mismatch × 2):**
1. Brief says "Nemotron-Nano-9B-v2-NIM" → actual NGC ID is `nvidia/nvidia-nemotron-nano-9b-v2` (double nvidia prefix). Confirm this is the intended model before pull.
2. Brief says "llama-nemotron-rerank-1b-v2" → does not exist in NGC catalog. Confirm intended rerank model.

**STOP #1 (ARM64 unverifiable × 1):**
- `nemotron-3-nano-30b-a3b` NIM container requires elevated NGC entitlement to inspect manifest. Cannot confirm ARM64 without NVAIE or explicit NIM access grant. This is the largest and most expensive model in the deployment plan.

**STOP #3 (memory 60% violation × 1):**
- Deployment B as spec'd (30B fp16 on spark-1 with deepseek-r1:70b co-resident) would reach ~81%. Requires either quantized NIM build confirmation or MoE active-weight clarification before proceeding.

---

## Deployment verdicts

| Deployment | Description | Verdict |
|---|---|---|
| A | VRS: nemotron-nano-9b-v2 + embed-1b on spark-4 | **GO** (ARM64 confirmed, memory OK) — rerank needs name resolution |
| B | Deliberation seats: 30B MoE on spark-1 | **DEFER** — ARM64 unverifiable + memory concern at fp16 size |
| C | Vision-language: nemotron-nano-12b-v2-vl on spark-3 | **GO** (ARM64 confirmed, memory OK under gating) |

---

## Recommended next actions (for Gary)

1. **Confirm "nvidia-nemotron-nano-9b-v2" is the intended 9B model** (double nvidia prefix in actual NGC ID).
2. **Confirm rerank model name** — `llama-nemotron-rerank-1b-v2` doesn't exist. Closest: `llama-3.2-nemoretriever-1b-vlm-embed-v1`.
3. **Grant NIM entitlement** for `nemotron-3-nano-30b-a3b` or confirm NVAIE subscription is active. Without it, ARM64 verification for Deployment B is blocked.
4. **Confirm 30B memory footprint** — brief says 3.5B active params (MoE); if NIM loads only active weights (~8GB), spark-1 memory budget is fine. If full weights must be resident, quantized build required.
5. **Greenlight A/B/C individually** — A and C can proceed; B needs resolution of items 3 and 4 above.
