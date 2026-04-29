# NIM Stack Audit — Sovereign Legal Inference Layer (2026-04-29)

**Brief:** `/home/admin/nim-stack-audit-brief.md`
**Stacks on:** PR #277 (BRAIN), PR #285 (LiteLLM cutover), PR #289 (Council sovereign cutover), PR #290 (Phase B v0.1)
**Read-only.** No NIM pulls, no deployments, no systemd / LiteLLM / Qdrant / catalog modifications.

---

## §5 STOP triggers — surfaced (audit completed via inline §3.3 / §3.5 escape valves)

Two §5 STOP conditions surfaced; both have explicit inline-handling escape valves elsewhere in the brief, so the audit completed using documented substitutes. The triggers are flagged here so the operator can elect to treat the audit as a partial blocker rather than a clean Outcome:

| Trigger | §5 line | Inline escape valve | Substitute used |
|---|---|---|---|
| `nim_catalog` Postgres table missing | §5 list item "nim_catalog table missing" | §3.3 line "If table doesn't exist or schema differs, surface and adjust query." | `docs/NGC_NIM_CATALOG_2026-04-22.md` (47-entry markdown snapshot) + `nim_arm64_probe_results` Postgres table (39 probes) |
| NGC CLI not installed | §5 list item "NGC CLI fails" | §3.5 line "If NGC CLI not present, defer §3.6 to a separate operator-authorized install." + §6 line "(or 'blocked: NGC CLI not configured')" | §3.6 live NGC discovery skipped; the 2026-04-22 markdown snapshot is the substitute reference |

Additional partial blocker (not a §5 STOP):

- **spark-5 SSH access denied** (`Permission denied (publickey,password)` from spark-2). BRAIN HTTP probe at `http://spark-5:8100/v1/models` succeeded — the deployed model is identifiable via OpenAI-compatible introspection. Service-level systemd / docker uptime / version metadata for spark-5 is **not** captured in this audit.

---

## §3.1 — Deployed NIM services (cluster-wide)

Spark logical → host map verified per `/etc/hosts` + SSH config (memory: "naming inverted between SSH/tailscale", topology 2026-04-25):

| Logical | Hostname | Reach | NIM workload |
|---|---|---|---|
| spark-1 | `spark-node-1` (10.10.10.1) | ssh ✓ | `fortress-nim-sovereign` |
| spark-2 | `spark-node-2` (10.10.10.2, this host) | local | none — gateway/router tier |
| spark-3 | `spark-3` (10.10.10.3) | ssh ✓ | `fortress-nim-vision-concierge` |
| spark-4 | `Spark-4` (10.10.10.4) | per ADR-004: scheduled wipe, out of NIM-host scope | n/a |
| spark-5 | `spark-5` (192.168.0.109) | ssh ✗, HTTP ✓ on `:8100` | BRAIN |

| Spark | Service | Image | Tag | Arch | Status | Uptime |
|---|---|---|---|---|---|---|
| spark-1 | `fortress-nim-sovereign` | `nvcr.io/nim/meta/llama-3.1-8b-instruct-dgx-spark` | `latest` | arm64 (DGX Spark variant) | active | Up 10 days |
| spark-3 | `fortress-nim-vision-concierge` | `nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl` | `sha-33032f00aed9` | arm64 | active | Up 6 days |
| spark-5 | BRAIN (vllm-served) | `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8` | (FP8 weights) | arm64 (inferred — ADR-003 cutover landed here) | active (per `/v1/models`) | unknown (SSH blocked) |

**Total deployed NIMs cluster-wide: 3.**

Non-NIM inference / routing services on spark-2 (this host): `litellm-gateway` (port 8002 → maps `legal-reasoning` / `legal-classification` / `legal-summarization` / `legal-brain` to `http://spark-5:8100/v1`), `ollama` (nomic-embed-text + qwen2.5 embed/classifier role per current Council consumer), `fortress-ray-head`, `fortress-sentinel`. spark-1 also runs `fortress-brain` Streamlit + `fortress-ray-worker`. spark-3 runs `fortress-ray-worker`.

---

## §3.2 — NAS NIM cache inventory

**Cache root:** `/mnt/fortress_nas/nim-cache/`
**Total cache footprint:** 227 GB (`nim/` 37 GB + `hf/` 190 GB + `spark5-llm-nim-cache/` 0 B).

### Stage-A: image.tar binaries (deployable NIM images)

| Image | NAS path | Size | Latest ARM64 verdict (probe table) |
|---|---|---:|---|
| `nemotron-nano-12b-v2-vl/latest` | `nim/nemotron-nano-12b-v2-vl/latest/image.tar` | 10.49 GB | **ARM64_OK** (2026-04-29) |
| `llama-nemotron-embed-1b-v2/latest` | `nim/llama-nemotron-embed-1b-v2/latest/image.tar` | 2.60 GB | **ARM64_OK** (2026-04-29) |

### Stage-B: NIM weight / runtime caches (deployment-adjacent, not standalone images)

| Path | Purpose |
|---|---|
| `nim/llama-3.3-nemotron-super-49b-v1/nim-weights-cache/` | BRAIN weight cache (consumed by spark-5 service) |
| `nim/nemotron-nano-12b-v2-vl/nim-weights-cache/` | Vision-concierge weight cache |
| `nim/nemotron-nano-12b-v2/1.6.0/` | Non-VL sibling of vision NIM (text-only nemotron-nano-12b — not deployed) |
| `nim/nemotron-3-nano-30b-a3b/latest/` | MoE 30B-A3B variant (not deployed; arm64 verdict not yet probed) |
| `nim/llama-nemotron-embed-vl-1b-v2/latest/` | VL embedding variant (not deployed; arm64 verdict not yet probed) |

### Stage-C: HuggingFace runtime caches

| Path | Size class | Purpose |
|---|---|---|
| `hf/nvidia-Llama-3_3-Nemotron-Super-49B-v1_5/` + `...-FP8/` | bulk of 190 GB | BRAIN base + FP8 weights (consumed by spark-5) |
| `hf/llm-nim-runtime-cache/{spark-1,spark-node-1,spark-node-2,spark-5,spark-6,...}/` | per-spark | Per-host NIM vllm/HF runtime caches |
| `hf/llm-nim-runtime-cache.poisoned-20260424/` | quarantined | Quarantined cache from 2026-04-24 incident |
| `hf/llm-nim-runtime-cache/.spark-5-quarantine-20260428/` and `spark-5.{1.15.5,1.15.4,pre-2.0.1}-quarantine-20260428-*/` | quarantined | spark-5 BRAIN-related quarantine snapshots from INC-2026-04-28-brain-fp8-gibberish |

**Total NAS-cached NIMs (image.tar present): 2.** Counting Stage-B entries that have meaningful cache contents but no image.tar: an additional 5 NIMs are partially staged (weights only or runtime-only). Stage-A vs Stage-B distinction matters because only Stage-A entries can be `docker load`-ed without re-pulling.

---

## §3.3 — Catalog cross-reference (Postgres table missing — substitute used)

**Substitute 1: `docs/NGC_NIM_CATALOG_2026-04-22.md`** (Fortress-Prime repo).

47 NIMs catalog snapshot from `tools/ngc_catalog_enumerator.py`, probe date 2026-04-22:

| Metric | Count |
|---|---:|
| Total enumerated | 47 |
| ARM64 manifest present (manifest-level claim only — Stage-2 ELF verification required before deploy) | 12 |
| NVAIE-gated (entitlement required, returns 402 on inspection) | 8 |
| Commercial-use-OK | 31 |
| Auth error / not found | 3 |
| x86-only (amd64 only) | 32 |

By family with ARM64 availability: nemotron 9 (3 ARM64), llama 11 (4 ARM64), mistral 4 (1), deepseek 3 (0), qwen 3 (2), embed 5 (1), rerank 3 (0), vision 4 (1), nemo 4 (0), other 1 (0).

**Substitute 2: `nim_arm64_probe_results` Postgres table** (39 probes covering 5 distinct image_path values; latest probe per image as of 2026-04-29):

| image_path | latest verdict | latest probe |
|---|---|---|
| `nim/nvidia/llama-nemotron-embed-1b-v2` | **ARM64_OK** | 2026-04-29 |
| `nim/nvidia/nemotron-nano-12b-v2-vl` | **ARM64_OK** | 2026-04-29 |
| `nim/nvidia/nvidia-nemotron-nano-9b-v2` | **ARM64_MANIFEST_MISMATCH** | 2026-04-29 |
| `nim/nvidia/llama-nemotron-nano-8b-v1` | **NO_ARM64** | 2026-04-29 |
| `nim/deepseek-ai/deepseek-r1-distill-llama-70b` | **NO_ARM64** | 2026-04-29 |

Verdict distribution across all 39 probes: ARM64_OK 15, NO_ARM64 16, ARM64_MANIFEST_MISMATCH 8.

**Discrepancy noted:** the brief assumes a Postgres `nim_catalog` table with 47 entries. No such table exists in `fortress_db`. The 47-entry catalog is the markdown snapshot above; the table that does exist (`nim_arm64_probe_results`) covers only 5 distinct images. The naming and counts in the brief should be reconciled in a follow-up doc edit.

---

## §3.4 — ARM64 verification status

No `*arm64-verified*` filesystem markers on `/mnt/fortress_nas/nim-cache/`.

ARM64 verification authoritative source = `nim_arm64_probe_results` (per Iron Dome v6.1 + arm64-audit-discovery-brief.md). For each NAS-cached image:

| NAS image | Latest probe verdict |
|---|---|
| `nim/nvidia/nemotron-nano-12b-v2-vl` (image.tar present) | ARM64_OK ✓ |
| `nim/nvidia/llama-nemotron-embed-1b-v2` (image.tar present) | ARM64_OK ✓ |
| `nim/nvidia/nemotron-nano-12b-v2` (1.6.0, non-VL) | not probed |
| `nim/nvidia/nemotron-3-nano-30b-a3b` | not probed |
| `nim/nvidia/llama-nemotron-embed-vl-1b-v2` | not probed |

3 NAS-cached NIMs have **never been arm64-probed**. This is a coverage gap for the next probe pass.

The 2026-04-22 audit that the brief references (`NIM_CACHE_AUDIT_2026-04-22.md`) is **not present on NAS**; the closest equivalent is `docs/NGC_NIM_CATALOG_2026-04-22.md` cited above. If a separate cache-audit doc was promised, it appears not to have been committed.

---

## §3.5 — NGC API access from spark-2

| Item | Result |
|---|---|
| `NGC_API_KEY` configured | **yes** (`/etc/fortress/nim.env`, rotated 2026-04-23 Day 1 Task 2) |
| `ngc` CLI installed | **no** (`which ngc` returns nothing; `ngc config current` returns "command not found") |
| §3.6 NGC live discovery | **deferred** per §3.5 + §6 — "blocked: NGC CLI not configured" |

The Fortress-Prime repo has its own enumerator (`tools/ngc_catalog_enumerator.py`) which produced the 2026-04-22 snapshot via REST API + `docker manifest inspect` rather than the official `ngc` CLI. That is the path used to refresh the catalog without installing the CLI. The pull pipeline (`scripts/nim_pull_to_nas.py`) is also present and is the authoritative Stage-2 ELF-verification entrypoint — both should be invoked behind a separate operator-authorized brief.

---

## §3.6 — NGC catalog discovery

**Skipped — NGC CLI not configured (§3.5).** Section is satisfied via the 2026-04-22 markdown catalog (§3.3 substitute 1), which is 7 days old. A fresh run of `tools/ngc_catalog_enumerator.py` would reduce drift; it is recommended as a tiny prerequisite step in the operator-authorized add-NIMs brief that follows this audit.

---

## §3.7 — NVIDIA Blueprint reference check

| Search | Result |
|---|---|
| `*blueprint*` under `/mnt/fortress_nas/` | 1 hit (`audits/wip-20260422/evidence/drupal-blueprint-analysis.txt`) — unrelated audit artifact, not a NIM blueprint |
| `*nemo-retriever*` under `/mnt/fortress_nas/` | 0 hits |

**No cached NeMo Retriever / NVIDIA legal blueprint material on NAS.** Aligning to a canonical NVIDIA blueprint (e.g., "Build a RAG agent with NeMo Retriever") would require fetching the reference architecture as part of the add-NIMs brief.

---

## §4 — Gap analysis

### Phase B / Council needs vs. currently served

| Phase B / Council need | Currently served by | Gap |
|---|---|---|
| Embedding for legal RAG | `nomic-embed-text` via Ollama on the gateway tier (192.168.0.100:11434) | **Cached not deployed:** `llama-nemotron-embed-1b-v2` (ARM64_OK, 2.6 GB image.tar on NAS) — plug-and-play upgrade if Qdrant reindex is operator-approved |
| Reranker for top-k legal retrieval | **NONE deployed** | **Critical gap.** Per 2026-04-22 catalog: rerank family has 3 NIMs, **0 ARM64**. Direct NIM deployment on Spark fabric is blocked until NVIDIA ships an ARM64 reranker variant or until we approve an x86-host-based reranker (no spark currently has that role) |
| Privilege classifier | `qwen2.5:7b` via Ollama (current Council consumer) | Working baseline; defense-in-depth via `llama-guard-3-8b` is queued but ARM64 verdict not yet captured (catalog shows it accessible; arm64 probe needed) |
| Deposition / hearing ASR | NONE | spark-4 wipe (per ADR-004) removes the SenseVoice tenant; need Parakeet/Canary NIM in NGC catalog (speech family, 2 NIMs, 0 ARM64 per 2026-04-22 snapshot) — same ARM64 blocker as reranker |
| Page-element extraction (filings, footnotes, citations) | NONE | Not on NAS; not in 2026-04-22 catalog under expected names; targeted NGC discovery needed (deferred — NGC CLI absent) |
| Table-structure extraction (damages tables, account exhibits) | NONE | Same as page-element — discovery deferred |
| LLM Guard / safety | `llama-guard-3-8b` listed in 2026-04-22 catalog as accessible (arm64 verdict not yet captured) | Pull → arm64 probe → deploy is the linear path; not Phase B-blocking |

### NGC discovered NIMs (legal-relevant, not yet pulled — based on 2026-04-22 markdown catalog)

| Category | Image | ARM64 status | Why we want it |
|---|---|---|---|
| Reranker | `nvcr.io/nim/nvidia/llama-3.2-nv-rerankqa-1b-v2` | **0 ARM64 in rerank family** | Phase B grounding-citation quality at white-shoe-grade — top-k retrieval without rerank is mediocre |
| Embedding (alt) | `nvcr.io/nim/nvidia/llama-3.2-nv-embedqa-1b-v2` | catalog "accessible"; arm64 status not yet probed | Multilingual + retrieval-tuned alternative to current `llama-nemotron-embed-1b-v2` |
| Page elements | `nvcr.io/nim/nvidia/nemoretriever-page-elements-v2` | not in 2026-04-22 snapshot — refresh enumerator | Filings have figures, captions, footnotes, headers — element extraction beats raw OCR |
| Table structure | `nvcr.io/nim/nvidia/nemoretriever-table-structure-v1` | not in 2026-04-22 snapshot — refresh enumerator | Damages tables, statement-of-account exhibits, appraisal tables — structured extraction |
| ASR | `nvcr.io/nim/nvidia/parakeet-tdt-0.6b-v2` | speech family 0 ARM64 in 2026-04-22 snapshot | Depositions, hearings, recorded calls — replaces SenseVoice with production-grade |
| LLM Guard | `nvcr.io/nim/nvidia/llama-guard-3-8b` | catalog "accessible"; arm64 status not yet probed | Privilege-redaction safety classifier; defense-in-depth alongside Qwen privilege classifier |

### Recommended additions ranked by Case II / Phase B impact

| Priority | NIM | Reason | Estimated effort | ARM64-blocker? |
|---|---|---|---|---|
| **P0** | `llama-nemotron-embed-1b-v2` deployment | Already cached + ARM64_OK; unblocks GPU-accelerated embed for Council + Phase B; replaces Ollama nomic-embed-text bottleneck | Low — `docker load` + systemd unit + LiteLLM route + Qdrant reindex (768→whatever the embed-1b-v2 vector size is) | No |
| **P0** | NeMo Retriever reranker — pursue ARM64 path | Phase B grounding citation quality; not negotiable for white-shoe-grade RAG. **Currently blocked: 0 ARM64 reranker NIMs in the 2026-04-22 catalog.** Action: refresh enumerator → if still blocked, escalate (open NVIDIA support ticket OR run reranker on x86 host outside spark fabric) | Medium-high if blocker holds | **YES** — requires escalation |
| **P1** | `llama-guard-3-8b` pull + arm64 probe + deploy | Defense-in-depth privilege classifier | Pull → probe → deploy → integrate | Probe pending |
| **P1** | Page-elements + table-structure NIMs | Vault-ingest quality (Track A's 14 OCR'd PDFs benefit; future filings ingestion benefits more) | Refresh enumerator → pull → probe → deploy → integrate `vault_ingest_legal_case.py` | Probe pending — likely ARM64 limited per family |
| **P2** | Parakeet ASR | Required before spark-4 wipe — depositions need transcription pipeline | **Blocked: 0 ARM64 in speech family.** Same escalation path as reranker | **YES** — requires escalation |
| **P3** | LLM upgrade tier (e.g., 70b instruction-following) | Not Phase B-blocking; defer until Phase C or operator escalation | Defer | n/a |

### Operator decisions queued

1. **Approve `llama-nemotron-embed-1b-v2` deployment + Qdrant reindex** — cleanest immediate win; cached + ARM64_OK; only requires operator authorization of the systemd-add + reindex
2. **Reranker decision** — escalate to NVIDIA for ARM64 OR run on x86 alongside spark fabric OR accept un-reranked top-k retrieval (degrades Phase B quality but unblocks initial release)
3. **ASR decision** — same escalation question, with timing tied to spark-4 wipe (ADR-004)
4. **NGC enumerator refresh + arm64-probe sweep** — small, pre-pull prerequisite; operator authorizes a one-shot run of `tools/ngc_catalog_enumerator.py` + `nim_arm64_probe_results` insert pass to refresh the catalog from 2026-04-22 (7 days old)
5. **Reconcile `nim_catalog` table reference in briefs** — the brief and `qdrant-collections.md`-style architecture docs should be updated to reflect that the catalog is the markdown doc, and the Postgres table is the per-image arm64 probe log

---

## Cross-references

- Brief: `/home/admin/nim-stack-audit-brief.md`
- 2026-04-22 catalog (substitute for missing `nim_catalog` table): `docs/NGC_NIM_CATALOG_2026-04-22.md`
- ARM64 probe table source: `nim_arm64_probe_results` (`fortress_db`)
- Enumerator: `tools/ngc_catalog_enumerator.py`
- Pull pipeline: `scripts/nim_pull_to_nas.py`
- ADR-003 (BRAIN cutover, Phase 1 LiteLLM cutover): PR #277, PR #285
- ADR-004 (app vs inference boundary, Spark-3/4 wipe): PR #286
- Council sovereign cutover (closes A-02): PR #289
- Phase B v0.1 drafting orchestrator: PR #290
- spark-5 BRAIN incident context: `docs/operational/INC-2026-04-28-brain-fp8-gibberish.md`

---

End of audit doc.
