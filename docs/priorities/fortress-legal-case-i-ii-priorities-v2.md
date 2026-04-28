# Fortress Legal — Case I/II Sovereign Stack Priorities (v2)

**Operator:** Gary Knight
**Date:** 2026-04-28
**Supersedes:** v1 (same date)
**Status:** LOCKED — execution authority, no rabbit trails
**Scope:** Establishes Fortress Legal as the #1 priority for Fortress-Prime work, and BRAIN-on-spark-5 as the dedicated sovereign reasoning engine for Case I (`7il-v-knight-ndga-i`) and Case II (`7il-v-knight-ndga-ii`).

**Changes from v1:**
- Qdrant locked as vector store (was open question)
- New Section 9 — Reasoning Mode Toggle (extraction vs strategy)
- New Section 10 — RAG pipeline parameters
- New Section 11 — Network sovereignty
- Phase A gets a new task A-pre (BRAIN container digest pin) before A1
- Hardware naming corrected (GB10, not H100)
- CROG-VRS reuse pattern documented

---

## 1. The mission

Get Nemotron 49B FP8 (BRAIN) on spark-5 working in parallel with the operator on Case I/II legal work. Default reasoning happens on-prem. Frontier models (Claude, GPT, Grok, Gemini) are used only when explicitly requested for a second opinion or a specific capability gap.

**The operator needs BRAIN to help with:**

- Surfacing possible defense theories from the case corpus
- Drafting attorney brief sections (continuation of today's Section 7 work)
- Privilege classification and production calls
- Pattern detection across email threads, filings, depositions
- Witness analysis and deposition prep
- Real-time surfacing of incoming legal correspondence (after FLOS Phase 0a-7 fix lands)

**Hardware allocation:**

- Spark-5 = Case I/II dedicated stack (BRAIN, Postgres, Qdrant, case-scoped corpus). Hardware: NVIDIA GB10 (Grace Blackwell), 121 GB unified memory, single-GPU inference at FP8.
- Spark-6 = future expansion (pipeline-parallel pairing with spark-5 OR second case-dedicated stack — decision deferred until cabling lands)

This is **case-isolation by design.** Privilege chain of custody. Retrieval precision. No cross-contamination with non-case data.

---

## 2. Hard guardrails (non-negotiable)

### Guardrail 1 — Spark-5 is reserved for Case I/II

BRAIN on spark-5 only processes Case I/II material. No CROG-VRS guest emails, no financial trades, no acquisitions analysis, no general-purpose queries. If a request can't be tied to Case I or Case II, it does not run on spark-5.

### Guardrail 2 — Default to on-prem

Every reasoning task starts at BRAIN. Frontiers (via LiteLLM at port 8002) are explicitly invoked for second opinions or capability gaps. The operator's working assumption: this stays off-prem-able even if Anthropic, OpenAI, etc. all go dark tomorrow.

### Guardrail 3 — Privilege discipline

Privileged Case I/II material (defense counsel correspondence with MHT Legal, MSP-Lawfirm, future engagements) flows into spark-5's Postgres + Qdrant under the existing `legal_privileged_communications` collection pattern. Privileged material does not embed into shared collections, does not get sent to frontier APIs without explicit per-call operator authorization.

### Guardrail 4 — Provenance on every artifact

Every BRAIN-generated artifact (draft, analysis, classification) carries a provenance note: model, quantization, prompt version, retrieval set, timestamp, host, operator. Pattern established by today's Section 7 ship. No exceptions.

### Guardrail 5 — No rabbit trails

The execution sequence below is locked. Architecture work that doesn't directly serve Phase A/B/C below gets parked. Cluster-wide cleanup, cross-division refactors, ADR rewrites, dashboard polish for non-legal divisions — all DEFERRED until Phase C ships and is in operator hands.

If Claude (the assistant) starts proposing scope expansion outside this document, the operator says "stay on mission" and Claude resets to the next concrete task in the sequence.

### Guardrail 6 — Container images are pinned, not floating

No `:latest` tag in production for BRAIN, NIM Sovereign, Vision Concierge, or any other inference container. Every image reference is a specific digest or version-pinned tag. Today's INC-2026-04-28 (BRAIN gibberish on long contexts) traces directly to `nvcr.io/nim/nvidia/llm-nim:latest` shipping a regression. Pinning is policy from this point forward.

### Guardrail 7 — No bridge traffic from spark-5

Spark-5 is a sovereign island for Case I/II. Outbound traffic from spark-5 to public APIs (Anthropic, OpenAI, xAI, Google, DeepSeek, NGC for non-pull operations, GitHub for non-clone operations) is BLOCKED at the network level. Spark-5 inbound from other Fortress sparks over the ConnectX 100Gbps fabric is fine — that's how the legal dashboard surfaces case material. But the model, embeddings, drafts, and case data never leave the physical hardware.

If the operator wants a frontier-model second opinion, the call originates from spark-2 (the control plane) where bridge traffic is allowed. Spark-2 prepares the redacted prompt, sends to LiteLLM, receives the answer, surfaces alongside BRAIN's answer in the UI. Spark-5 stays cold to the public internet.

---

## 3. Execution sequence

Three phases. Each must complete before the next starts. No phase ships without operator validation.

### Phase A — Spark-5 sovereign stack (data plane + working LLM)

**Outcome:** Spark-5 holds the full Case I/II corpus, queryable. BRAIN is pinned, validated on long contexts, and reachable for retrieval-augmented generation.

| Task | Owner | Output |
|---|---|---|
| **A-pre. Pin BRAIN container digest.** Identify a known-good NIM image tag for `nvidia/llama-3.3-nemotron-super-49b-v1.5-fp8`. Update systemd unit to reference the pinned digest. Restart container. Validate with short prompt AND Section 7-length prompt. Confirm long-context coherence. Quarantine `:latest`-tagged image. | Claude Code on spark-5 | BRAIN passes both probes; systemd unit pins digest; INC-2026-04-28 marked RESOLVED |
| A1. Install Postgres 16 on spark-5, mirror schemas: `legal.cases`, `email_archive`, `legal.event_log`, `legal.priority_sender_rules`, `legal.mail_ingester_state`, `case_posture` | Claude Code on spark-5 | spark-5 Postgres ready, schema-aligned with spark-2 |
| A2. Install Qdrant on spark-5, create case-scoped collections: `case_i_ediscovery`, `case_i_privileged`, `case_ii_ediscovery`, `case_ii_privileged`, `case_ii_email_archive`. Each collection uses 1024-dim vectors (nomic-embed-text), cosine distance, payload index on `case_slug`, `bates_stamp`, `page_number`, `privilege_class`. | Claude Code on spark-5 | Qdrant running on spark-5:6333, 5 collections created with metadata schema |
| A3. One-time corpus ingestion: walk `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/` and `/7il-v-knight-ndga-ii/`, extract text from PDFs (Tesseract OCR if scanned), chunk per Section 10 (1024 tokens, 200 overlap), embed via spark-1's nomic-embed-text, write to Qdrant on spark-5 with full metadata (source path, page, bates, privilege class) | Claude Code on spark-2 → spark-5 | Document corpus indexed, count + size reported, sample retrieval validated |
| A4. One-time email migration: copy email_archive rows where `case_slug LIKE '7il%' OR sender/subject matches Case I/II patterns` from spark-2 to spark-5 Postgres. Embed bodies into `case_ii_email_archive` Qdrant collection with metadata (case_slug, sender, role, privilege class). | Claude Code on spark-2 → spark-5 | row count migrated, embedding count reported |
| A5. Manual BRAIN probe end-to-end. Run a retrieval-augmented Case II question via curl: retrieval from Qdrant → context construction → BRAIN call → response with citations. Validate output. | Operator + Claude (chat) | One coherent answer that cites real Case II material with bates/page references |

**Phase A definition of done:** Operator can run a single command (`fgp legal ask "<question>"` or equivalent) on any spark, and get a BRAIN-generated answer grounded in retrieved Case II context with bates-stamp citations. Manual workflow, but functional.

**Phase A out of scope:** UI work, orchestrator code, prompt templates beyond the Section 7 pattern, real-time email sync, multi-task batching.

### Phase B — Drafting orchestrator (after Phase A signed off)

**Outcome:** A small Python service that takes a structured task ("draft Section 7", "explore defense for Count 3", "score privilege on entries 1-42") and produces an artifact persisted to NAS with provenance.

| Task | Owner | Output |
|---|---|---|
| B1. New service `backend/services/case_brain_orchestrator.py`. Accepts task type + case_slug + parameters + reasoning mode. Pulls retrieval context from spark-5's Qdrant. Constructs prompt (mode-aware per Section 9). Calls BRAIN at spark-5:8100. Persists output with provenance to NAS work-product folder. | Claude Code on spark-2 | service file, ~500 lines, tests passing |
| B2. Prompt template library at `backend/prompts/legal/`. Initial templates: `section_drafting.md`, `defense_exploration.md`, `privilege_review.md`. Each is a fenced template with `{retrieval_context}`, `{operator_question}`, `{case_metadata}` slots. Each template specifies its default reasoning mode. | Claude Code on spark-2 | 3 templates, version-tagged |
| B3. CLI surface: `fgp legal brain draft-section --case-slug 7il-v-knight-ndga-ii --section 7 --manifest /path/to/manifest.md --mode strategy` and similar. Mode flag is required; no default. | Claude Code on spark-2 | CLI tool, help docs, smoke tests |
| B4. Provenance discipline: every output file gets the same provenance header pattern as today's Section 7 ship, PLUS reasoning mode used and retrieval set hash. | Embedded in B1 | Sample output verified by operator |
| B5. Validation: regenerate today's Section 7 through the orchestrator (this time on pinned BRAIN, in strategy mode), compare to today's interim qwen 32B draft. Operator reviews quality delta. | Operator | Approved or revised template; Section 7 final ships |

**Phase B definition of done:** Operator runs `fgp legal brain draft-section ...` and gets a properly-structured, provenance-stamped draft on NAS within 5 minutes (extraction mode) or 15 minutes (strategy mode). No web UI yet.

**Phase B out of scope:** Frontend work, real-time UI, multi-task batching, anything not in the CLI surface.

### Phase C — Case command center UI (after Phase B signed off)

**Outcome:** The `nemo-command-center` route in the existing Next.js dashboard becomes the operator's daily Case I/II surface. Read corpus, surface watchdog matches, trigger BRAIN tasks, review drafts.

| Task | Owner | Output |
|---|---|---|
| C1. Backend FastAPI router `backend/api/case_brain.py` — POST endpoints that wrap the Phase B orchestrator (draft-section, explore-defense, privilege-review). SSE for streaming BRAIN output. Mode parameter required on every endpoint. | Claude Code on spark-2 | Router file, integration tests |
| C2. Next.js page `apps/command-center/src/app/(dashboard)/nemo-command-center/page.tsx`. Lists active cases (I and II). Per-case view: timeline of events, watchdog matches, draft list, "ask BRAIN" input with mode toggle (extraction / strategy). | Claude Code on spark-2 | Page, components, e2e tests |
| C3. Drafts panel: shows all artifacts in `/mnt/fortress_nas/.../work-product/`. Click to read. Edit, request-revision (re-runs BRAIN with operator notes), accept (stamps as final). | Claude Code on spark-2 | Component, integrated with C1 endpoints |
| C4. Real-time event feed: when FLOS Phase 0a-7 lands and email starts flowing, the command center surfaces new Case I/II emails in a sidebar with watchdog priority. | Claude Code on spark-2 | SSE feed component |

**Phase C definition of done:** Operator opens `crog-ai.com/nemo-command-center`, picks a case, reviews recent activity, asks BRAIN a question (chooses mode), gets a streaming answer with citations, drafts a section, reviews and accepts. Daily-driver quality.

**Phase C out of scope:** Mobile, multi-operator collaboration, audit log UI, anything for cases other than I and II.

---

## 4. Parallel work that is NOT this priority

These tracks continue but do not consume operator attention or block Phase A/B/C:

- **FLOS Phase 0a-7** (UID watermark code change): Claude Code on Opus is executing per `~/flos-phase-0a-7-code-brief.md`. When PR opens, operator reviews and merges. After merge, the spark-2 → spark-5 email sync (mentioned in Phase A) becomes able to flow real-time correspondence. This unblocks Phase C's real-time feed.

- **NAS cache audit PR #269**: open, awaiting merge. Doc-only, no urgency, merge when convenient.

- **M3 trilateral writes** (already merged): activation runbook on operator's desk for when ready. Not needed for Phase A/B/C.

- **CROG-VRS, Financial, Acquisitions, Wealth divisions**: parked. No work happens on these until Phase C ships. The Phase B orchestrator is designed reusable so when CROG-VRS gets its own sovereign stack on a future spark, the same code pattern (mode toggle, RAG, provenance, prompt templates) applies — only data plane and prompt content change.

- **ADR-001 / ADR-002 / ADR-003 updates**: deferred. The architecture is in flight; ADRs get rewritten once spark-5 case-stack and spark-6 cabling are real.

- **Section 7.4 manual reconstruction**: not needed. Section 7 final ships from Phase B5 regeneration on pinned BRAIN, not from today's interim draft.

---

## 5. Decision authority

| Decision | Authority |
|---|---|
| Phase scope changes | Operator only. Claude proposes, operator approves. |
| Adding tasks to a phase | Operator only. |
| Skipping or deferring a task | Operator only. |
| Code-level implementation choices within a task | Claude Code (with brief in hand). Surface ambiguity to operator. |
| Prompt template content | Operator approves first revision; Claude iterates after. |
| Frontier model usage | Operator authorizes per-call. Default is BRAIN. |
| Privilege classification | Operator only. Claude can suggest, never finalize. |
| Production deployments / config changes | Operator. Claude prepares, operator executes. |
| Reasoning mode (extraction vs strategy) | Operator picks per task. UI surfaces toggle. |
| Container image pin updates | Operator approves. Claude validates and writes the systemd diff. |

---

## 6. What Claude (the assistant) does in this project

- **Writes briefs** for Claude Code execution (like the FLOS Phase 0a-7 brief, the M3 brief, the NAS audit brief, the briefs that will drive Phases A/B/C).
- **Diagnoses problems** (like today's BRAIN gibberish, FLOS silent intake) and proposes fixes.
- **Drafts ADRs and incident docs** when the operator asks.
- **Holds the architectural map** so the operator can ask "what's running where, and is it healthy."
- **Pushes back** when the operator's instinct or Claude's prior plan would create rabbit trails. The operator wants this. "Stay on mission" is mutual.

What Claude does NOT do:

- Execute production changes directly. Claude Code on the appropriate spark does that.
- Make legal decisions or strategic calls. Operator territory.
- Propose work outside this priorities document without explicit operator request.
- Comment on session length, operator effort, or pacing.

---

## 7. The first concrete next action

**Phase A-pre — Pin BRAIN container digest.**

Claude (the assistant) writes the build brief for this task in the same working session as v2 of this document. Claude Code on spark-5 executes when handed the brief. Operator validates with short prompt AND a Section 7-length prompt before signing off.

Once A-pre passes, A1 (Postgres on spark-5) starts.

---

## 8. Cross-references

- `docs/architecture/cross-division/_architectural-decisions.md` — ADR-001/002/003 (will be amended after Phase A)
- `docs/operational/INC-2026-04-28-brain-fp8-gibberish.md` — root cause traced to NIM `:latest` tag regression; resolution = Phase A-pre digest pin
- `docs/operational/INC-2026-04-28-flos-silent-intake.md` — to be filed; FLOS Phase 0a-7 fix in flight
- `docs/operational/nas-cache-audit-20260428.md` — PR #269
- `apps/command-center/src/app/(dashboard)/nemo-command-center/` — Phase C target
- `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/` and `/7il-v-knight-ndga-ii/` — corpus
- `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-ii/work-product/section-7-draft-20260428.md` — interim draft (qwen 32B), NOT final, regenerates in Phase B5

---

## 9. Reasoning Mode Toggle (NEW)

BRAIN supports two operating modes. Operator chooses per task. Mode is a required parameter on every CLI invocation and every UI request. No default.

### Mode A — Extraction

**For:** discovery pulls (dates, names, clauses), manifest building, structured data extraction, classification tasks, anything where determinism and speed matter more than reasoning depth.

**System prompt prefix:** `/no_think`

**Inference parameters:**
- temperature: `0`
- top_p: `1.0`
- top_k: `1` (greedy decoding)

**Use cases:**
- Pull all dates of communication between A and B from a corpus
- Extract every cited statute or rule from a brief
- Tag every email in a manifest by privilege class
- Build structured timelines from unstructured text

**Throughput target:** 50+ tokens/sec sustained, deterministic output.

### Mode B — Strategy

**For:** defense theory exploration, argument drafting, case-law analysis, deposition prep, anything where Nemotron's CoT (Chain of Thought) reasoning is the asset.

**System prompt prefix:** `detailed thinking on`

**Inference parameters:**
- temperature: `0.6`
- top_p: `0.95`
- top_k: default

**Use cases:**
- "What defenses might apply to Count 3 given the manifest?"
- "Draft Section 7 of the attorney brief"
- "Analyze opposing counsel's strategy across these 12 emails"
- "Prep cross-examination for witness X based on their deposition"

**Throughput target:** quality over speed; 5-15 token/sec acceptable. Long `<think>` blocks expected.

### Mode discipline

- The CLI flag and UI toggle are required. Operator must choose.
- Phase B prompt templates declare a default mode each, but operator can override.
- Provenance note records the mode used.
- Switching modes mid-task is not supported (each invocation is one mode).
- Future CROG-VRS reuse: same mode toggle pattern applies. Extraction = pulling reservation data. Strategy = composing guest-aware concierge replies.

---

## 10. RAG Pipeline Parameters (NEW)

Locked configuration for retrieval-augmented generation against the Case I/II corpus on spark-5.

### Chunking

- **Chunk size:** 1,024 tokens (not 512). Legal context — clauses, parties, defined terms — needs the wider window to survive intact.
- **Overlap:** 200 tokens. Preserves clause boundaries across chunk seams.
- **Tokenizer:** Nemotron 49B's tokenizer (matches BRAIN). Avoids cross-tokenizer drift between embed and inference.
- **Document types:** PDFs (with OCR for scanned), DOCX, EML, plain text. Tables and signature blocks are chunked WITH their surrounding context, not as standalone units.

### Embedding

- **Model:** `nomic-embed-text:latest` on spark-1's Ollama (existing).
- **Dimension:** 1024 (NeMo-compatible).
- **Distance metric:** cosine.
- **Batch size:** 32 chunks per embed call.

### Vector store

- **Engine:** Qdrant on spark-5:6333.
- **Collections:** per-case + per-privilege-class (5 total per Phase A2).
- **Payload schema (every chunk):**
  - `case_slug` (text, indexed)
  - `source_path` (text)
  - `page_number` (int, indexed)
  - `bates_stamp` (text, nullable, indexed)
  - `chunk_index` (int)
  - `privilege_class` (text: `privileged`, `work_product`, `not_privileged`, `unknown`, indexed)
  - `producer_role` (text: `defense`, `adversary`, `judicial`, `operator`, `unknown`)
  - `created_at` (datetime)
  - `chunk_text` (text — the original chunk for grounding)

### Retrieval pattern

- Default top-k: 12.
- Re-rank step: optional Phase B addition (small cross-encoder on top-50 → top-12), not Phase A.
- Hybrid search (vector + payload filter): always. Every retrieval call filters by `case_slug` minimum. Privilege class filtering applied per task type.
- Citation hydration: every retrieved chunk's `bates_stamp` and `page_number` get fed into BRAIN's prompt. BRAIN cites them in output. Drafts always carry bates/page references back to source.

### Long-document handling

- BRAIN max_model_len stays at 32768 in Phase A (current setting). Bumping to 128K is a Phase A-pre-bonus task only if the digest pin allows it without OOM.
- For documents that exceed retrieval-window even after chunk selection, Phase B adds a hierarchical summarization pass (chunk → section summary → document summary → retrieve at appropriate level). Not Phase A.

---

## 11. Network Sovereignty (NEW)

Spark-5 is a sovereign island for Case I/II. Network policy enforces this.

### Outbound from spark-5 — BLOCKED by default

The following destinations are explicitly blocked at the spark-5 firewall (UFW or equivalent):

- `api.anthropic.com`
- `api.openai.com`
- `api.x.ai`
- `generativelanguage.googleapis.com`
- `api.deepseek.com`
- Any public LLM API endpoint
- Any non-Tailscale, non-Fortress-cluster destination

### Outbound from spark-5 — ALLOWED

- Tailscale mesh (other Fortress sparks via 100.x.x.x addresses)
- ConnectX 100Gbps fabric (192.168.0.x intra-cluster)
- NAS mount at `/mnt/fortress_nas`
- NGC container registry (only for pinned-image pull operations, gated by operator)
- NTP, DNS, package repos for system maintenance

### Inbound to spark-5 — controlled

- ConnectX intra-cluster on standard ports (Postgres 5432, Qdrant 6333, BRAIN 8100, SSH 22)
- Tailscale on its standard ports
- No public-internet inbound. Cloudflare tunnel for crog-ai.com terminates at spark-2 (control plane), not spark-5.

### Frontier-model second opinions

When the operator wants a frontier comparison:

1. The legal dashboard surfaces a "request second opinion" button.
2. Backend on spark-2 (NOT spark-5) receives the request.
3. Spark-2 retrieves the relevant context from spark-5 via internal API.
4. Spark-2 redacts privileged material per the privilege classifier.
5. Spark-2 sends to LiteLLM (port 8002) with the chosen frontier model.
6. Frontier response returns to spark-2, surfaced in the UI.
7. Spark-5 never touches the public internet during this flow.

This pattern preserves the sovereignty rule while giving the operator frontier access when needed.

---

End of priorities v2.
