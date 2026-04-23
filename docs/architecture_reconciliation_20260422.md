# Architecture Reconciliation — NeMo + Nemotron + NIM Migration Decision
_Date: 2026-04-22 | Phase 0 output | GATE — Gary must ack before Phase 1 proceeds_

---

## Canon Documents Read (in precedence order)

| Doc | Path | mtime | Role |
|-----|------|-------|------|
| Iron Dome v6.1 | `docs/IRON_DOME_ARCHITECTURE.md` | 2026-04-21 | **Primary architecture doc** |
| NGC NIM Catalog Snapshot | `docs/NGC_NIM_CATALOG_2026-04-22.md` | 2026-04-22 | NIM/NeMo availability truth |
| NIM 9B Cleanup Record | `docs/NIM_9B_CLEANUP_2026-04-22.md` | 2026-04-22 | ARM64 ELF verification history |
| NIM Nemotron Deployment Brief | `/home/admin/nim-nemotron-deployment-brief.md` | 2026-04-21 | Mission context (superseded by current prompt) |
| ARM64 Audit Discovery Brief | `/home/admin/arm64-audit-discovery-brief.md` | 2026-04-22 | Track 1/2 audit context |

---

## A — Target State (per Iron Dome v6.1)

### Training stack
- Not explicitly specified in v6.1. Phase 4d training section references HF + PEFT LoRA (implicit from context).
- v6.1 Principle 1: "vendor-optimized inference first" — does not mandate NeMo training; applies primarily to inference workloads.

### Inference stack
- **Principle 1 (canon):** For any workload where NVIDIA ships a tuned NIM or Nemotron variant, NIM is the **default choice**. Ollama is the fallback, not the default.
- spark-1: Fortress Legal — NIM `meta/llama-3.1-8b-instruct-dgx-spark` (per v5 Phase 5b, now live)
- spark-4: CROG-VRS — `qwen2.5:7b` (Ollama, pending NIM upgrade via nim-nemotron-deployment-brief.md Deployment A)
- spark-3: Vision — NIM `nemotron-nano-12b-v2-vl` planned (Deployment C from deployment brief, ELF verified as ARM64, 35GB cached)

### Base models (target)
- Fortress Legal sovereign: Llama 3.1 8B Instruct via NIM (currently deployed)
- CROG-VRS concierge: Nemotron-Nano-9B-v2 via NIM (Deployment A — **BLOCKED, see Current State**)
- Deliberation seats 4, 6, 9: Nemotron-3-Nano-30B-A3B (Deployment B — status TBD)
- Embed/rerank pipeline: llama-nemotron-embed-1b-v2 (cached, ARM64 verified), rerank not yet determined

### Node assignments (v6.1)
| Node | IP | Primary | Secondary |
|------|----|---------|-----------|
| spark-1 | 192.168.0.104 | Fortress Legal + NIM | Legal vector store |
| spark-2 | 192.168.0.100 | Orchestration + training | Accounting + Acquisitions |
| spark-3 | 192.168.0.105 | Vision | Financial GPU (on-demand) |
| spark-4 | 192.168.0.106 | CROG-VRS + Qdrant | — |

### Headroom constraint
- Hard limit: ≤60% per node steady-state
- Exception: `legal_train` on spark-2 may temporarily exceed 60% during training epochs

### Sovereignty
- No sovereign data (financials, legal, PII) leaves DGX cluster hardware
- No cross-domain retrieval across enterprise boundaries (Legal ↔ VRS prohibited)
- No cloud model for inference paths that handle sovereign data

---

## B — Current State (as of 2026-04-22 inspection)

### spark-1 (192.168.0.104) — Fortress Legal
- **NIM running:** `nvcr.io/nim/meta/llama-3.1-8b-instruct-dgx-spark:latest` (Up 3 days)
- systemd unit: `fortress-nim-sovereign.service` (active, running)
- Legal LoRA adapter: `/mnt/fortress_nas/models/legal-instruct-production/` → `legal-instruct-20260421-e3_1` (Qwen 7B bf16 LoRA, e3.1)
- **Discrepancy noted (see Section D):** Prod NIM serves Llama 3.1 8B; prod adapter symlink points to Qwen 7B LoRA. These are two different model families — adapter cannot be loaded into mismatched base.

### spark-2 (192.168.0.100) — Training host / control plane
- Training workload: `legal_train` not currently running (confirmed by GPU check)
- HF + PEFT training stack functional (e3.1 trained here, completed 2026-04-22)
- Hardened eval harness live: PR #132 merged

### spark-3 — Vision
- NIM pending (Deployment C from deployment brief)
- `nemotron-nano-12b-v2-vl` container (35GB): cached on NAS, ELF verified ARM64

### spark-4 (192.168.0.106) — CROG-VRS
- Previous NIM deployment (`nemotron-nano-9b-v2`): **cleaned up** — confirmed x86-only via ELF check, removed from both NAS cache and spark-4 Docker daemon
- VRS concierge systemd unit disabled and removed
- Current state: no NIM running on spark-4; VRS concierge route falls to spark-2/spark-1 Ollama

### NIM cache on NAS (`/mnt/fortress_nas/nim-cache/nim/`)
| Directory | Size | ARM64 Status |
|-----------|------|-------------|
| `llama-nemotron-embed-1b-v2/` | 2.5 GB | MATCH (ELF verified, keep) |
| `llama-nemotron-embed-vl-1b-v2/` | 0 (empty) | Not pulled |
| `nemotron-3-nano-30b-a3b/` | 0 (empty) | Not pulled |
| `nemotron-nano-12b-v2-vl/` | 35 GB | MATCH (ELF verified, keep) |

### NeMo Framework Training
- `nvcr.io/nemo/nemo-framework-training:25.04` — **ARM64: No**
- Explicitly documented in `docs/NGC_NIM_CATALOG_2026-04-22.md` Appendix B:
  *"NeMo framework containers are x86-only across the board."*
- No arm64 variant exists in the enumerated NGC catalog (47 containers surveyed)

---

## C — Gaps Between Target and Current

| Gap | Severity | Blocks |
|-----|----------|--------|
| **NeMo training container: x86-only** | **CRITICAL** | Full NeMo + Nemotron migration |
| VRS concierge NIM (9B): x86-only, removed | HIGH | Deployment A from deployment brief |
| Nemotron-nano-12b-v2 (text-only): Stage-2 ELF unverified | MEDIUM | Nemotron text inference on spark-1 |
| Nemotron-3-Nano-30B-A3B: not pulled, ARM64 unverified | MEDIUM | Deployment B (deliberation seats) |
| Prod symlink (e3.1 Qwen LoRA) ≠ spark-1 NIM (Llama 3.1 8B) | HIGH | Understanding current inference path |
| Legal LoRA adapter serving path not documented | HIGH | Any LoRA adapter NIM integration |

---

## D — Constraints This Bake-off Must Honor

Per Iron Dome v6.1 and NGC catalog findings:

1. **ARM64 gate is absolute.** No container or binary without a verified ARM64 ELF deploys on DGX Spark. Manifest claims are not sufficient — Stage-2 ELF verification required (precedent: 9B mislabeled incident).

2. **60% memory rule is absolute.** spark-1 running Llama 3.1 8B NIM. Any additional NIM or training workload must leave ≥40% headroom.

3. **Do not disrupt spark-1 NIM.** `fortress-nim-sovereign.service` is live and serving Legal. No config changes until decision is made and Gary approves.

4. **NeMo training cannot run on this cluster today.** All four nodes are ARM64 Grace Blackwell. NeMo framework training container is x86-only. This is the decisive constraint for the NeMo + Nemotron full migration path.

5. **Sovereignty.** No model weights from a non-permissive license. No telemetry to NVIDIA (or any third party) that includes legal document content.

6. **NIM LoRA multi-tenancy path unconfirmed.** If the text-only `nemotron-nano-12b-v2` NIM supports LoRA adapter serving, it must be confirmed against actual NIM API docs before training anything.

---

## E — Critical Contradictions Flagged

### Contradiction 1: Prompt vs. actual spark-1 NIM
**Prompt says:** "prod adapter: e3.1 (Qwen 7B bf16 LoRA, trained via HF + PEFT)"  
**Actual spark-1 NIM serves:** `meta/llama-3.1-8b-instruct-dgx-spark`

These are different model families. A Qwen 7B LoRA adapter cannot be loaded into a Llama 3.1 8B NIM base. The current inference path for the legal LoRA adapter (e3.1) is **not through spark-1 NIM** — it must be served via a separate HF bf16 inference path on spark-2. The prod symlink exists but the routing mechanism is not documented. **Architecture doc is silent on this; it does not specify where the LoRA adapter is served from.**

*Resolution needed from Gary before any NIM LoRA integration work:* Is e3.1 served via direct HF inference on spark-2, or via some other path? The eval harness confirms it works, but the serving path is unresolved.

### Contradiction 2: Prompt assumes NeMo training is viable
**Prompt says:** "Verify NeMo Framework is installable on DGX Spark ARM64. ... Pull the NeMo training container on spark-2. Smoke test..."  
**NGC catalog says:** `nvcr.io/nemo/nemo-framework-training:25.04` has `ARM64: No`.

The architecture doc (canon) does not mandate NeMo training — it mandates vendor-optimized **inference** via NIM. The prompt's assumption that NeMo training is viable on this cluster is contradicted by the NGC catalog snapshot (also in the repo). **Architecture doc wins; Phase 2 NeMo smoke test cannot be executed as specified.** Flagged for Gary.

---

## Phase 0 Summary

The full NVIDIA-native migration (NeMo training + Nemotron base + NIM serving) is **not currently executable on this cluster.** The blocking constraint is the NeMo training container — it has no ARM64 build. NVIDIA has not published an ARM64 NeMo framework training container as of the 2026-04-22 catalog snapshot.

**Viable partial paths** (require Gary's direction):
1. **Inference-only Nemotron via NIM:** Use `nemotron-nano-12b-v2` (ARM64 claim present, Stage-2 ELF verification pending) as the inference base on spark-1. Keep HF + PEFT training on spark-2. This delivers Nemotron inference without NeMo training.
2. **Resume HF bake-off:** The killed bake-off (Qwen 14B, Mistral 7B, Phi-3-medium) is fully prepped (bakeoff_train.sh committed, bases dir clean). Gary re-engages by confirming which path to take.
3. **Wait for NVIDIA ARM64 NeMo container:** Monitor NGC for an ARM64 NeMo framework training build. NGC sentinel script (`nvidia_sentinel.py`) can watch for this. Not on a known timeline.

**GATE — awaiting Gary's direction before Phase 1 execution.**
