# Wave 3 v2 — Partial Deployment Final Report

**Date:** 2026-05-01
**Operator:** Gary Knight
**Executor:** Claude Code on spark-5 (deviation from brief which targeted spark-2/CAPTAIN — note in §0)
**Branch:** `feat/wave-3-retrieval-stack-deployment-2026-05-01`
**Brief:** `docs/operational/wave-3-reranker-extraction-deployment-brief-v2.md` (PR #342, commit 596bb0c)
**Outcome:** PARTIAL — Components A (Reranker) and B (Extraction NIMs) deferred to Wave 3.5; Components C (EMBED verify), D (Vision attempt), F (Qdrant inspection), G (truncated e2e smoke) executed.

---

## 0. Execution context

Brief specified "Target: Claude Code on spark-2". Operator invoked execution from spark-5 instead. SSH-out pattern (CAPTAIN as hub for spark-3 commands, spark-5-local for spark-5 commands) preserved correctness. No functional impact.

Pre-flight discovered the local repo checkout was 155 commits behind `origin/main`; fast-forwarded and branched from `origin/main` (HEAD `596bb0c`).

---

## 1. Pre-flight summary

| Check | Result |
|---|---|
| Soak (phase-9-soak/2026-04-30.log) | Active; recent ticks before run all `endpoint_health=ready` |
| Frontier health (http://10.10.10.3:8000/health) | 200 throughout (12.5 min monitor window logged at `wave3-frontier-heartbeat.log`) |
| Frontier models | `nemotron-3-super` listed |
| NGC auth (CAPTAIN) | OK (`ngc config current` returns valid apikey; `ngc registry image info` works against accessible repos) |
| spark-5 GPU | NVIDIA GB10, BRAIN service inactive (Phase 9 retirement confirmed); disk 3.4 TB free; no fortress containers running |
| spark-3 services | EMBED active (port 8102, llama-nemotron-embed-1b-v2); Vision (vision-concierge) inactive at start |
| spark-3 GPU headroom | Only ~16.18 GiB free of 121.69 GiB (frontier dominates) — relevant for Component D |
| EMBED branch (§5.6) | Path EMBED-A — service already running with `llama-nemotron-embed-1b-v2:latest` (the NEWER, working model). HF_TOKEN not needed. |

---

## 2. Component A — Reranker (`llama-3.2-nv-rerankqa-1b-v2:1.8.0`) — DEFERRED to Wave 3.5

### What worked
- Pull via `sudo -E python3 scripts/nim_pull_to_nas.py llama-3.2-nv-rerankqa-1b-v2 --tag 1.8.0` — clean, 2.47 GB tar saved to `/mnt/fortress_nas/nim-cache/nim/llama-3.2-nv-rerankqa-1b-v2/1.8.0/image.tar`.
- ARM64 verification gates — both PASS:
  - Stage 1 (manifest): arm64 platform present (digest `sha256:f382372ac3065ac179f80cf57e6be70754fcfcf27eab785a731d3d9fa802b99f`).
  - Stage 2 (ELF): probe binary `ELF 64-bit LSB pie executable, ARM aarch64`.
  - Verification record retained at `docs/operational/wave-3-reranker-arm64-verification.json`.
- `docker load` on spark-5 (image ID `3fee4fe4f2a3`, 4.23 GB on disk).
- `list-model-profiles` discovered the only GB10-compatible profile: `f7391ddbcb95b2406853526b8e489fedf20083a2420563ca3e65358ff417b10f` (backend:onnx | precision:fp16). 22 other profiles target H100/A100/B200/L40S/L4/A10G/compute-cap 8.6/8.9/9.0/10.0/12.0 — none for GB10 sm_121.
- systemd unit `fortress-nim-rerank.service` created at `/etc/systemd/system/`, mirroring embed-unit conventions (cluster-canonical `--env-file`, NAS tar load in ExecStartPre, pinned profile hash, `nim-weights-cache` mount). Unit retained for forensics at `deploy/systemd/spark-5/fortress-nim-rerank.service`.
- Service started successfully after fixing one permissions gotcha (`nim-weights-cache/` was created by sudo as root:root; container hit `Permission denied (os error 13)`. Fixed via `chown admin:admin && chmod 775` to match embed pattern. Documented in `cluster-nim-deployment-conventions.md` §2.).
- `/v1/health/ready` returns 200 within 30s.
- `/v1/models` returns `nvidia/llama-3.2-nv-rerankqa-1b-v2`.

### Why deferred

Inference fails immediately on the first ranking request:

```
2026-05-01 04:08:09.999976635 [E:onnxruntime:, sequential_executor.cc:572 ExecuteKernel]
Non-zero status code returned while running ReduceSum node.
Name:'/_model/ReduceSum_1'
Status Message: CUDA error cudaErrorSymbolNotFound: named symbol not found
```

This is the **same ONNX/CUDA failure family** that brief §2.2 documents for `llama-3.2-nv-embedqa-1b-v2:1.10.0` (cjeske, NVIDIA forums 354998). Brief §4.4 cited cjeske as evidence the reranker `:1.8.0` works on Spark — that premise does not reproduce here. NIM container also warns: `Detected NVIDIA GB10 GPU, which may not yet be supported in this version of the container`.

### Cannot retry-for-fix

- Only ONE GB10-compatible profile exists in the manifest. No alternative profile to fall back on.
- Newer rerank model (`llama-nemotron-rerank-1b-v2`) explicitly lacks Blackwell support per its model card (brief §6.1).
- Brief hard stop §3.8 (by spirit): "Do not retry" the cudaErrorSymbolNotFound failures on Spark.

### Disposition

- Service `systemctl stop` + `systemctl disable`. Status `failed`/`disabled`.
- Image tar + verification.json retained at `/mnt/fortress_nas/nim-cache/nim/llama-3.2-nv-rerankqa-1b-v2/1.8.0/` for forensics.
- Unit retained at `deploy/systemd/spark-5/fortress-nim-rerank.service` (header documents the disabled status).
- **Wave 3.5 gate:** NIM rebuild against Spark-compatible CUDA/ONNX runtime (forums thread 354998 fix family).

---

## 3. Component B — Extraction NIMs (page / graphic / table) — DEFERRED to Wave 3.5

### Discovery
All three NIMs return **403 DENIED** at both `ngc registry image info` AND `docker manifest inspect` for every tag tried (`:latest`, `:1.0`, `:latest-dgx-spark`):

- `nvcr.io/nim/nvidia/nv-yolox-page-elements-v2`
- `nvcr.io/nim/nvidia/nv-yolox-graphic-elements-v1`
- `nvcr.io/nim/nvidia/nv-yolox-table-structure-v1`

### Diagnosis
NGC auth itself works (reranker `:1.8.0` from same `nim/nvidia` namespace pulled fine; embed/vision/super-49b all already in cache). The 403 is **entitlement-side**, not auth-side: cluster's NGC subscription does not include the entitlement that ships YOLOX extraction NIMs (likely a NeMo Retriever or NIM-Microservices subscription separate from base `nv-ai-enterprise`).

### Disposition
- Nothing pulled, nothing deployed.
- **Wave 3.5 gate:** Cluster NGC subscription upgrade to obtain YOLOX entitlement. Distinct from technical-fix gate; this is billing/sub.

---

## 4. Component C — EMBED verify (Path EMBED-A) — PASS

- Service `fortress-nim-embed.service` already active on spark-3:8102 since 2026-04-29 19:34 (per unit comment).
- Image: `nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest` (the newer, Spark-validated model — Path EMBED-A).
- `/v1/health/ready` → **200**.
- `/v1/models` → `nvidia/llama-nemotron-embed-1b-v2`.
- Functional probe with `input_type=passage`, query `"easement law test passage"`:
  - `vector_dim = 2048`
  - usage: `prompt_tokens=9 total_tokens=9`
  - latency (sequential warm): ~28 ms
- HF_TOKEN not needed (Path EMBED-B did not fire).

---

## 5. Component D — Vision restart — DEFERRED on capacity

### Attempted

- `sudo systemctl start fortress-nim-vision-concierge.service` succeeded at process level (active/enabled).
- Container started (`fortress-nim-vision-concierge`, `nemotron-nano-12b-v2-vl:sha-33032f00aed9`, port 8101->8000).
- vLLM engine init proceeded through architecture resolution (`NemotronH_Nano_VL_V2`), scheduler config, mamba page-size padding…

### Failure

```
ValueError: Free memory on device (16.18/121.69 GiB) on startup is less than
desired GPU memory utilization (0.55, 66.93 GiB).
Decrease GPU memory utilization or reduce GPU memory used by other processes.
```

Vision NIM requested 0.55 × 121.69 = 66.93 GiB. spark-3 GPU has only ~16 GiB free with TP=2 frontier as the dominant co-tenant (matches brief §5.5 caution: "If frontier is the only spark-3 tenant and is consuming ~115 GB, headroom is tight").

`Restart=always` looped 6 times before being stopped. Frontier 200 throughout (heartbeat log).

### Cannot retry-for-fix

Brief constraint forbids modifying Vision NIM configuration:
> §5.6 unit comment: "operator chose 8102 to avoid colliding with Vision NIM and honor §8 hard constraint forbidding Vision NIM modification"

So reducing Vision's `gpu_memory_utilization` is off-limits from this PR.

### Disposition
- Service `systemctl stop`. Status `failed`/`enabled` (operator can `reset-failed && start` when capacity allows).
- **Wave 3.5 gate:** spark-3 capacity headroom restored — either (a) frontier relocation off spark-3, (b) frontier KV cache reduction, or (c) explicit brief authorizing Vision config change.

---

## 6. Component E — LiteLLM aliases — SKIPPED per operator direction

Per partial-scope direction: rerank/extract aliases would point at non-existent services; embed alias already exists. No `litellm_config.yaml` mutation.

---

## 7. Component F — Qdrant `legal_ediscovery` reindex — VERIFIED, not executed

### Inspection

| Property | Value |
|---|---|
| Collection | `legal_ediscovery` |
| Vector dim | **768** |
| Distance | Cosine |
| Points | 738,918 |
| Status | green / indexed |
| Aliases on cluster | none (`legal_ediscovery_active` does not exist) |
| Existing `*_v2` collections at 2048-dim | `legal_caselaw_v2` (2,711 pts), `legal_caselaw_federal_v2` (0 pts), `legal_privileged_communications_v2` (241,167 pts), `legal_library_v2` (3 pts), `legal_headhunter_memory_v2` (0 pts) |

### Mismatch

Current EMBED dim is 2048 (§4). `legal_ediscovery` is 768. The collection was indexed against a different / older embed model. Cluster-wide pattern: a strangler-fig migration is in progress (`*_v2` collections at 2048 alongside legacy 768 collections; `legal_privileged_communications` and `legal_privileged_communications_v2` both at 241,167 points confirm the parallel-build pattern).

### Decision per operator direction
> "If `legal_ediscovery` vector dim already matches current EMBED, this becomes a no-op verification pass — document and move on, do not force a reindex."

The dim does NOT match. The reindex of 738,918 points against 2048-dim EMBED would be a non-trivial multi-hour operation needing: source-of-truth re-discovery, embed throughput planning, atomic alias swap (qdrant#7584). That is properly its own brief.

Reindex helper exists at `src/reindex_legal_qdrant_to_legal_embed.py` (different path from brief's `python3 -m fortress.indexing.reindex_legal_ediscovery`). Not exercised in this run.

### Disposition
- No collection mutated.
- No alias created.
- **Follow-up:** separate brief to plan + execute `legal_ediscovery → legal_ediscovery_v2` reindex against current EMBED, atomic alias swap, application caller migration to `legal_ediscovery_active` alias.

---

## 8. Component G — End-to-end retrieval smoke — PARTIAL PASS (truncated to embed→qdrant)

Per operator direction: rerank step skipped (Component A deferred). Used `legal_privileged_communications_v2` (2048-dim, 241,167 points) since it matches current EMBED dim.

### Result

```
=== Wave 3 partial e2e smoke ===
query:      warranty deed easement title transfer dispute
collection: legal_privileged_communications_v2
embed_ms:   28.0
qdrant_ms:  7.6
wall_ms:    63.8

=== top-5 hits ===
#1 score=0.4559  src=f29b5c5a-8c36-414e-a68c-11da32d7d478
   text: '…the Warranty Deed recorded at Deed Book 1079, Pages 751-752 …
          You also believe that there is an easement in favor…'
#2 score=0.4411  src=f29b5c5a-8c36-414e-a68c-11da32d7d478
   text: '…you - as owner with Lizabeth Knight of Lot 33 in Staurolite Mountain…'
#3 score=0.4238  src=4e638eb0-1a77-43d8-bc5f-dde16d68f480
   text: '…I pray you might take a look at what I think might be the additional
          information needed… The closing…'
#4 score=0.4230  src=9ab6a55e-1029-4cca-bd27-4a631cea01cf
   text: '…Circuit COA says it's not. We'd have to appeal to get that back.
          Also as I read this easement agreement…'
#5 score=0.4188  src=3be2a46d-1ac7-4b63-b9e6-85f6031bc579
   text: '…wrote: > Good morning, That is interesting. I think it is helpful…'
```

Top-5 are all relevant to the easement/warranty-deed query (mention Knight, Lot 33 Staurolite Mountain, Warranty Deed at Deed Book 1079). EMBED→Qdrant pipeline functional. Wall ~64 ms warm (qdrant cold at 268 ms on first run, dropped to 7.6 ms warm).

### What this does NOT prove
- Whether reranking would meaningfully improve top-5 ordering (Component A deferred — cannot test).
- Whether retrieval against `legal_ediscovery` works (dim mismatch; reindex is a separate brief).

---

## 9. Hard stops fired

Zero brief-defined hard stops fired (per §3 conditions):
1. NGC auth — passed (entitlement-side 403s on YOLOX are NOT auth-side per `cluster-nim-deployment-conventions.md` §5).
2. ARM64 verification — reranker PASS (manifest+ELF). No NIM failed verify.
3. Frontier health — 200 throughout (heartbeat at `wave3-frontier-heartbeat.log`); zero >60s sustained non-200.
4. Soak halt event — none.
5. Disk full — no, NAS 54 TB free, root 3.4 TB free.
6. OOM kill / nvidia-smi unresponsive — nope (Vision rejection was a vLLM engine init pre-allocation check, not OOM).
7. Qdrant collection corruption — no Qdrant mutation occurred.
8. EMBED-image cudaErrorSymbolNotFound — EMBED is on the working `llama-nemotron-embed-1b-v2`, not the broken v1.10.0; §3.8 condition not met.

What did fire (deviations, NOT hard stops):
- Reranker hit cudaErrorSymbolNotFound — same family as §3.8 EMBED case, but on a different NIM. Treated as deferred-deploy per partial-pass guidance.
- Vision rejected on capacity ceiling (not OOM kill — engine init pre-check).
- Extraction NIMs entitlement-blocked at registry.

---

## 10. Soak impact

- Frontier health 200 throughout monitored window (24/25 ticks definite-200; tick 1 had empty value attributable to SSH-handshake race in probe script — not a frontier event, evidenced by EMBED on same host responding fine in same window).
- No memory peaks on spark-3 attributable to Wave 3 (Vision came up briefly then was rejected before completing weight load).
- spark-5 GPU was used briefly by reranker (clean idle now).
- Soak clock unaffected — active to 2026-05-14 per brief context.

---

## 11. Files committed

- `docs/operational/cluster-nim-deployment-conventions.md` — primary durable artifact from this run; covers NIM_MODEL_PROFILE pinning, NAS cache layout, systemd unit pattern, ARM64 tooling, ngc CLI syntax, weight pull workflow, spark-3 capacity ceiling, anti-patterns
- `docs/operational/wave-3-final-report.md` — this file
- `docs/operational/wave-3-reranker-arm64-verification.json` — reranker ARM64 gate evidence
- `docs/operational/wave3-frontier-heartbeat.log` — frontier health probe log throughout deployment window
- `deploy/systemd/spark-5/fortress-nim-rerank.service` — disabled-but-staged unit for forensics + zero-touch re-enable
- `docs/operational/MASTER-PLAN.md` — Wave 3.5 watchlist additions (§6.2 amendments)

---

## 12. Recommended operator next actions

1. **Open separate brief** for `legal_ediscovery` reindex against 2048-dim EMBED — 738,918-point operation worth its own scoping (source pipeline, throughput plan, atomic alias swap pattern, caller migration to `legal_ediscovery_active` alias).
2. **File NGC ticket** for YOLOX entitlement on cluster's subscription (or decide nv-ingest + per-component extraction is not a Fortress-Prime requirement and remove from MASTER-PLAN watchlist entirely).
3. **Monitor NVIDIA forums thread 354998** (and any successor) for cudaErrorSymbolNotFound fix in NIM containers; when fixed, the staged `fortress-nim-rerank.service` unit + cached image become re-enablable with one `systemctl reset-failed && enable && start`.
4. **Decide spark-3 capacity strategy** for Vision: (a) move frontier off spark-3, (b) reduce frontier KV cache, (c) authorize Vision `gpu_memory_utilization` reduction in a follow-up brief.
5. **Promote this draft PR to ready** after reviewing the conventions doc + this report.
