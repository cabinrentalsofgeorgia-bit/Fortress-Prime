# Iron Dome Phase 4 — NVIDIA AI Enterprise integration

**Status:** Plan locked, no deployment PRs yet authorized to write against this.
**Date:** 2026-04-24
**Addendum to:** [`IRON_DOME_ARCHITECTURE.md`](IRON_DOME_ARCHITECTURE.md), [`phase-3-flywheel-activation.md`](phase-3-flywheel-activation.md)

This document fixes the Phase 4 contract before any code lands. Every
deployment PR listed in §10 must conform to the boundaries set here.
Departures require an addendum to this addendum, not an unannounced
implementation choice.

---

## 1. Context & scope

**What Phase 4 adds.** Three new capabilities, in this order:

- Sovereign legal inference — a frontier-class model running on the
  DGX Spark cluster with no external API calls.
- Programmable guardrails — a policy layer that constrains generation
  to retrieved context, a fixed set of jurisdictions, and validated
  citations.
- Grounded legal retrieval — RAG over the existing Qdrant collections
  (`legal_caselaw`, `legal_ediscovery`) with `legal_hive_mind_memory`
  as a tertiary source.

**What Phase 4 does NOT change.**

- Privilege filter (Iron Dome Phase 2, PR #47, plus the multi-mailbox
  extension landed in PRs #157 / #158). Public contract of
  `classify_for_capture()` is stable.
- Captain multi-mailbox intake (`captain_multi_mailbox`,
  `captain_junk_filter`). Captain is upstream of inference; Phase 4
  is downstream.
- Qdrant remains the **only** vector store. No pgvector, no
  alternatives in evaluation.
- `nomic-embed-text` at 768 dimensions remains the **only** embedding
  model used at write time across every collection.

**Prerequisite.** CourtListener corpus ingested into the
`legal_caselaw` Qdrant collection (PR #162, in flight as of this
doc). No deployment PR in §10 may merge until the ingest run has
completed and `points_count > 0` is verified end-to-end.

---

## 2. Inference stack decision

**Primary legal drafting model.** `nvcr.io/nim/nvidia/llama-3.3-nemotron-super-49b-v1.5`,
served through NIM with TensorRT-LLM on the DGX Spark cluster.

**Why not the existing Qwen2.5-7B legal adapter today.** The most
recent eval at `/mnt/fortress_nas/models/legal-instruct-20260421-e3_1`
showed:

- 38–88% hallucination rates across domains A–E.
- `topic_f1 = 0.054` on domain B.
- Training cut short at step 105 with eval loss still descending —
  the model was never given a chance to plateau.

The model is not production-ready for court filings, even with
Guardrails on top. Path to promotion (out of scope for Phase 4):

1. Rebuild the training corpus using CourtListener-grounded
   prompt/response pairs (the corpus this Phase 4 effort makes
   queryable).
2. Retrain to eval-loss plateau, not to a fixed step count.
3. Target hallucination < 10% across all domains; < 5% for citations
   (domain C).
4. Re-evaluate against the same `metrics_v2.json` harness so deltas
   are comparable.

Until those targets are hit, Nemotron Super 49B carries every legal
draft.

**Llama 3.1 8B fp8** (already cached under `/mnt/fortress_nas/nim_cache/`)
is reserved for Captain-class agent workflows: email classification,
tool selection, and other low-stakes structured output. It is **not**
on the legal drafting path.

**External APIs.** No OpenAI, no Anthropic, no other external LLM
calls from any Fortress legal inference path. Sovereign-only. The
existing LiteLLM gateway fallback in `legal_email_intake.py` is
explicitly retired for legal generation in §6.

---

## 3. Embedding standard

`nomic-embed-text` at **768 dimensions**, across every Qdrant
collection. Non-negotiable for the lifetime of Phase 4.

**What this rules out.**

- **Nemotron-Embed-1B** (already pulled into the NIM cache): not
  adopted. Different output dimensions would create model drift
  across the 22 existing Qdrant collections (10.5M points in
  `fortress_knowledge` alone). The recent fortress audit flagged
  the *absence* of embedding drift as a structural strength — Phase 4
  preserves it.
- **Any other NVIDIA embedding NIM**: same reasoning. The cost of
  re-embedding 10M+ points is real, the benefit (small accuracy
  delta on legal-specific text) is not justified at this stage.

**NeMo Retriever, if deployed.** Used only for its reranking layer
on top of nomic-embedded vectors. The retriever's own default
embedding model is bypassed; Qdrant-with-nomic remains the source
of truth for vector search. If rerankers prove valuable they sit
*after* a nomic-embedded ANN search, not in place of it.

---

## 4. Guardrails architecture

NeMo Guardrails runs as a **programmable proxy** between the FastAPI
backend and the NIM inference endpoint. The backend never speaks to
NIM directly for legal generation; every request and response routes
through the Guardrails process.

Colang policies enforce the following constraints. Each is testable
in isolation and each maps to a specific failure mode the eval data
flagged.

### 4.a Retrieval-first generation

Every legal response must cite from retrieved context drawn from
`legal_caselaw` or `legal_ediscovery`. No retrieval, no generation.
A request that arrives with an empty retrieval bundle is rejected
before the model is invoked.

### 4.b Circuit scope

Citations are limited to:

- 11th Circuit
- Northern District of Georgia (NDGA)
- Georgia Supreme Court
- Georgia Court of Appeals
- Fannin County Superior Court

Extra-circuit citations are rejected at generation time. The
guardrails layer detects them (citation parser → court taxonomy
lookup) and forces regeneration with a reduced retrieval bundle.

### 4.c Citation validation

Every citation in the output is cross-checked against the
`filtered/georgia_insurance_opinions.jsonl` index (1,880 known-real
citations) before the response is returned to the caller.
Unverifiable citations cause the response to be rejected and
regenerated with the offending citation excluded from the next pass.

If the validator's hit rate drops below an as-yet-unset floor across
a moving window, the policy promotes to a hard refusal — better to
return "no draft" than a draft full of phantom citations.

### 4.d No "general advice"

Output is constrained to FRCP-compliant framing. Colloquial
qualifiers ("generally", "in most cases", "you might consider") are
stripped or rejected. The model is producing motion drafts, not
casual counsel.

### 4.e No invented facts

- Sampling temperature capped (exact value to be set in PR B; start
  at 0.0–0.2).
- Output validated against retrieved-context embeddings via cosine
  similarity floor. Output spans whose nearest retrieved-context
  vector falls below the floor are flagged as uncited and force
  regeneration.

### Policy file location

`fortress-guest-platform/backend/guardrails/legal.co` — to be
created in PR B (§10), not in this doc.

---

## 5. Retrieval layer contract

Collections consumed by legal inference, in priority order:

1. **`legal_caselaw`** — CourtListener opinions, 11th Circuit /
   Georgia. 768-dim, populated by PR #162. Authoritative for case-law
   citations.
2. **`legal_ediscovery`** — case files, depositions, vault uploads.
   768-dim. Authoritative for fact-pattern grounding.
3. **`legal_hive_mind_memory`** — accumulated Captain captures and
   prior reasoning artifacts. 768-dim. Tertiary; never the sole
   source for a citation.

**`legal_headhunter_memory`.** Role ambiguous as of this doc. To be
clarified in PR C (§10) before it is wired into the retrieval
pipeline. Default during Phase 4: not consulted.

**`restricted_captures`.** **Never** consulted at inference time.
Audit-only. This is enforced in retrieval *service code*, not just
in policy — the retrieval client refuses to open a connection that
lists `restricted_captures` in its collection set, regardless of who
calls it.

---

## 6. Deployment topology

- **NIM containers** run on DGX Spark nodes via Docker. K3s is
  optional; Phase 4 does not require it. Initial deployment targets
  spark-1 (Nemotron Super 49B). Llama 3.1 8B fp8 may run on a
  separate Spark node for the agent path.
- **NeMo Guardrails** runs as a Python process on **spark-2**,
  alongside the FastAPI backend, so the proxy hop is local.
- **Qdrant** stays where it is: spark-2 `localhost:6333`. No move,
  no replication change, no schema change.
- **No LoadBalancer or Ingress changes** required for Phase 4. All
  Phase 4 traffic stays inside the Cloudflare-Tunnel-protected
  internal mesh.
- **LiteLLM gateway** is retired *for legal inference*. NIM is
  called directly through Guardrails. LiteLLM may remain for
  non-legal, non-sovereign workflows that already use it; nothing
  in Phase 4 forces its removal from those paths.

---

## 7. Rollback plan

A single feature flag, `IRON_DOME_PHASE_4_ENABLED` (default
**false**), gates all legal generation through the new
NIM + Guardrails path.

- **Flag false** (the default after merge of every Phase 4 PR):
  legal generation falls back to the current Ollama / LiteLLM path.
  No behaviour change relative to today.
- **Flag true**: requests routed through Guardrails → NIM. Failures
  in Guardrails or NIM bubble up as 5xx; the fallback path is **not**
  silently re-engaged. Phase 4 is opt-in and observable.

The flag is reversible with no data migration required:

- No vector store changes (collections are already in place).
- No SQL schema changes.
- No retraining required to roll back.

A flip back to false strands no data and discards no work.

---

## 8. Out of scope for Phase 4

- **Qwen legal adapter v2 training.** Separate phase. Prerequisite
  is the CourtListener-grounded training corpus produced as a
  by-product of the work in §2 above.
- **Deposition video ASR.** Separate phase.
- **OCR sweep of the NAS legal corpus.** Separate phase, and a
  prerequisite for completing `legal_ediscovery` coverage. Phase 4
  works with whatever is already vectorized.
- **NeMo Retriever embedding.** Deferred indefinitely unless Qdrant
  is replaced — and Qdrant is not planned for replacement.
- **pgvector.** Not adopted. Qdrant is sufficient for the load and
  introducing a second vector store invites the drift problem §3
  exists to prevent.

---

## 9. Success criteria

Phase 4 is considered complete when:

1. A motion draft can be produced end-to-end for a real Generali
   fact pattern.
2. **100%** of citations in the output resolve to a real
   CourtListener `opinion_id`.
3. **Zero** extra-circuit citations across 100 sample generations.
4. Hallucination rate (measured the same way
   `legal-instruct-20260421-e3_1/metrics_v2.json` measures)
   - **< 10%** per domain
   - **< 5%** for citations (domain C)
5. Attorney review pass rate **≥ 90%** on a random sample of 20
   drafts.

The attorney review measurement protocol (rubric, blinding,
reviewer pool, conflict-of-interest handling) is to be defined
**before first real use** of any Phase 4 output. Without that
protocol the 90% number is unmeasurable.

---

## 10. Sequence of deployment PRs

The following PRs implement Phase 4 against this contract. They
must merge in order; later PRs assume earlier ones are live.

| PR | Title | What it lands |
|----|-------|---------------|
| A | NIM container orchestration on DGX Sparks | `docker compose` for Nemotron Super 49B, health probes, systemd unit, NIM cache wiring. No FastAPI changes. |
| B | NeMo Guardrails skeleton + Colang policy | `backend/guardrails/legal.co` implementing §4.a–§4.e, plus the proxy service and unit tests for each policy in isolation. |
| C | Retrieval service | Reads `legal_caselaw` + `legal_ediscovery` (+ `legal_hive_mind_memory` tertiary). Resolves the `legal_headhunter_memory` ambiguity. Hard-blocks `restricted_captures` at the connection layer. |
| D | Citation validator | Index-backed validator against `filtered/georgia_insurance_opinions.jsonl`. Used by the §4.c policy. |
| E | First end-to-end generation endpoint | Behind `IRON_DOME_PHASE_4_ENABLED`. Glue: FastAPI route → Retrieval → Guardrails → NIM → Validator → response. |
| F | Evaluation harness | Runs the §9 success criteria over a holdout set on demand and on a schedule. Output is the gate for flipping the flag in production. |

PRs A–F are documentation-only constraints in this doc; the doc does
not authorize any of them to merge. Each requires its own review
against the boundaries set here.

---

## Provenance

- Iron Dome Phases 1–3: see `IRON_DOME_ARCHITECTURE.md` and
  `phase-3-flywheel-activation.md`.
- Captain pipeline (Phase 2 ingest path that feeds the flywheel):
  PRs #157, #158, #159, #160, #161 — in `backend/services/captain_*`.
- Privilege filter (Phase 2 boundary): PR #47, extended in #157,
  preserved unchanged here.
- CourtListener ingest (Phase 4 prerequisite): PR #162.
- Eval data referenced in §2:
  `/mnt/fortress_nas/models/legal-instruct-20260421-e3_1/metrics_v2.json`.
- Citation index referenced in §4.c:
  `/mnt/fortress_nas/legal-corpus/courtlistener/filtered/georgia_insurance_opinions.jsonl`.
