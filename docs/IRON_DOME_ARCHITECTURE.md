# Iron Dome — Fortress-Prime Sovereign AI Defense System

**Version:** 5.0
**Date:** April 18, 2026
**Author:** Gary Knight (with Claude)
**Supersedes:** v4 (commit 7b7cefeba)

## Why v5

v4 documented the cluster as two businesses with dedicated nodes
and domain-isolated RAG. v5 adds what was missing from every prior
version: the frontier tier that sits above sovereign, and the
mechanism by which sovereign learns from it.

v4 treated frontier API calls as "fallback when sovereign fails."
That framing is wrong. Frontier models aren't a fallback — they're
teachers. Sovereign models aren't a primary path — they're students.
The architecture is teacher-student distillation, and every
capture-write site is a training opportunity.

v5 makes that explicit.

## The three-tier architecture

┌─────────────────────────────────────────────────────┐
 │                   GODHEAD TIER                      │
 │    Frontier APIs, specialized per task type         │
 │                                                     │
 │  Claude (Anthropic)     │ Legal reasoning, brief    │
 │                         │ drafting, summarization   │
 │  GPT (OpenAI)           │ Code generation, general  │
 │                         │ reasoning                 │
 │  Gemini (Google)        │ Vision, multimodal        │
 │  Grok (xAI)             │ Real-time, current events │
 │  DeepSeek-R1 (cloud)    │ Heavy logic, math         │
 └─────────────────────────┬───────────────────────────┘
                           │
                           │ escalated when sovereign uncertain
                           │ captured as teacher signal
                           │
 ┌─────────────────────────▼───────────────────────────┐
 │                 SOVEREIGN TIER                       │
 │           Spark cluster, domain-dedicated            │
 │                                                      │
 │  spark-1  Fortress Legal                             │
 │  spark-4  CROG-VRS                                   │
 │  spark-2  Orchestration + fast tier + embeddings     │
 │  spark-3  Vision                                     │
 │                                                      │
 │  Models: deepseek-r1:70b, qwen2.5:32b,               │
 │          qwen2.5:7b, llama3.2-vision:90b             │
 └─────────────────────────┬───────────────────────────┘
                           │
                           │ every response evaluated
                           │
 ┌─────────────────────────▼───────────────────────────┐
 │                    JUDGE TIER                        │
 │       Task-type specialized classifier LLMs          │
 │                                                      │
 │  legal_reasoning_judge   on spark-1                  │
 │  brief_drafting_judge    on spark-1                  │
 │  vrs_concierge_judge     on spark-4                  │
 │  market_research_judge   on spark-4                  │
 │  pricing_math_judge      on spark-4                  │
 │  code_generation_judge   on spark-2                  │
 │  vision_analysis_judge   on spark-3                  │
 │  real_time_judge         on spark-2                  │
 │                                                      │
 │  Decision: confident | uncertain | escalate          │
 │  Output: decision + reasoning for audit              │
 └──────────────────────────────────────────────────────┘

Three tiers. Judge decides escalation. Sovereign serves when confident.
Godhead teaches when escalated. Every exchange captured as training
data for the next iteration of sovereign.

## Task specialization — Godhead mapping

Each frontier model is the authoritative teacher for specific task
types. ai_router routes to the right teacher when escalation happens.
Fallback: if the specialized teacher is rate-limited or unavailable,
route to the next-best teacher per this priority table.

| Task type | Primary | Fallback 1 | Fallback 2 |
|-----------|---------|------------|------------|
| Legal reasoning | Claude | GPT | DeepSeek-R1 |
| Brief drafting | Claude | GPT | DeepSeek-R1 |
| Legal citations | Claude | GPT | — |
| Contract analysis | Claude | GPT | — |
| Code generation | GPT | Claude | — |
| Code refactoring | Claude | GPT | — |
| Code debugging | GPT | Claude | — |
| Vision (damage, photos) | Gemini | Claude (with image) | — |
| OCR | Gemini | Claude (with image) | — |
| Real-time facts | Grok | Gemini (if web) | — |
| Current market conditions | Grok | Claude | — |
| Math reasoning | DeepSeek-R1 | Claude | GPT |
| Complex logic chains | DeepSeek-R1 | Claude | GPT |
| Summarization (long context) | Claude | Gemini | GPT |
| Summarization (news) | Grok | Claude | — |
| Concierge replies | Claude | GPT | — |
| OTA responses | Claude | GPT | — |
| Competitive intelligence | Claude | Gemini | — |
| Pricing strategy | Claude | GPT | DeepSeek-R1 |
| Acquisitions analysis | Claude | GPT | — |

The table is authoritative; changes require an architectural decision
logged here.

## Task type classifier

Before routing, ai_router classifies the incoming request into one
of the task types above. Classifier lives at the top of the request
path — lightweight, deterministic where possible.

Three-tier classification:

1. **Source module hint (deterministic).** If the request comes from
   `legal_council`, the task_type defaults to the legal category
   that module specifies. No inference needed.

2. **Keyword patterns (deterministic).** If the prompt contains
   structured markers like "brief:", "draft:", "analyze contract",
   "calculate pricing for", deterministic rules assign task_type.

3. **Small LLM classifier (fallback).** When neither module hint
   nor keyword pattern resolves, a small classifier (qwen2.5:0.5b
   on spark-2) assigns task_type from prompt content. Fast, under
   100ms.

Classification result is logged on every capture in the `task_type`
field. Analytics and audits can filter by task.

## The Judge tier

### Purpose

Every sovereign response passes through a judge before being returned
to the user. Judge decides whether sovereign's response is good
enough to serve, or whether the query should be escalated to the
task-specialized Godhead teacher.

### Architecture — specialized judges per task type

Eight judges, one per primary task category. Each is a small
instruction-tuned LLM (qwen2.5:1.5b or qwen2.5:3b) fine-tuned on
labeled examples from its task domain.

**spark-1 (Fortress Legal):**
- `legal_reasoning_judge` — evaluates legal analysis, statutory application, precedent usage
- `brief_drafting_judge` — evaluates argument structure, persuasive writing, citation integrity

**spark-4 (CROG-VRS):**
- `vrs_concierge_judge` — evaluates tone, factual accuracy about properties, brand voice
- `market_research_judge` — evaluates analytical depth, data citation, currency of info
- `pricing_math_judge` — evaluates mathematical correctness, pricing rationale

**spark-2 (Orchestrator):**
- `code_generation_judge` — evaluates correctness, style, security
- `real_time_judge` — evaluates recency of information, source credibility

**spark-3 (Vision):**
- `vision_analysis_judge` — evaluates image description accuracy, damage identification correctness

### Judge output format

Each judge returns a structured decision:

```json
{
  "decision": "confident | uncertain | escalate",
  "reasoning": "One sentence explaining the decision.",
  "confidence_score": 0.0-1.0
}
```

Decision definitions:

`confident` — return sovereign response to user as-is, capture for potential training
`uncertain` — return sovereign response but tag for human review
`escalate` — discard sovereign response, route to Godhead teacher, return teacher response to user, capture full exchange as high-value training signal

### Judge training — labeling hybrid

Training data for judges comes from a hybrid pipeline:

**Phase A: Godhead-as-labeler at scale.**
For the first 30-60 days, every sovereign response is evaluated by
the specialized Godhead teacher: "was this response acceptable? Why
or why not?" Godhead's judgment becomes the judge's training label.
This produces thousands of labels per task type quickly but imprints
Godhead's biases.

**Phase B: Human QC on samples.**
You (Gary) review a 10% random sample of Godhead labels per week.
Corrections become higher-weight training signal. This keeps judges
from drifting into whatever Godhead happens to think is good.

**Phase C: Judge-self-improvement (later).**
Once judges are running in production, their decisions are logged.
When judge says "confident" but later evidence shows the response
was bad (user complaint, manual correction, downstream error), that
becomes a retraining signal.

### Judge deployment

Each judge runs as an inline call inside `ai_router` after sovereign
responds but before user sees the response.

Latency budget: judge inference must complete in under 200ms p95.
This constrains judge model size and prompt length. Small fast
judges are the design choice, not big accurate judges.

## Escalation flow

End-to-end request lifecycle:

## The capture format — what every row needs

v5 schema (shipped in Phase 3 retag, PR #64):

- `id` — UUID
- `created_at` — timestamp
- `source_module` — which fortress module made the call
- `source_persona` — persona context (e.g., senior_litigator)
- `user_prompt` — the prompt
- `assistant_resp` — the final response returned to user
- `task_type` — classified task type
- `served_by_endpoint` — actual endpoint that served the response
- `served_vector_store` — which RAG store was consulted, if any
- `escalated_from` — sovereign endpoint that was bypassed (NULL if no escalation)
- `sovereign_attempt` — what sovereign said before escalation (NULL if no escalation)
- `teacher_endpoint` — Godhead endpoint URL if escalated (NULL otherwise)
- `teacher_model` — name of Godhead model used (NULL if not escalated)
- `judge_decision` — confident/uncertain/escalate
- `judge_reasoning` — judge's explanation
- `eval_holdout` — Phase 4b marker
- `status` — pending/exported
- `capture_metadata` — jsonb extras

## Domain-isolated RAG (from v4, unchanged)

v5 inherits v4's RAG architecture. Vector stores remain:
- Fortress Legal store on spark-1 only
- CROG-VRS store on spark-4 only
- Shared entities store on NAS
- Cross-domain retrieval prohibited at query layer

Judges see `served_vector_store` as context: a judge evaluating a
legal response knows the response was grounded in the legal store,
and can flag if sovereign hallucinated citations not in the retrieved
context.

## Phase plan v5

### Phase 1 — Plumbing deployed (DONE)
### Phase 2 — Privilege filter (DONE)
### Phase 2.5 — Model registry (DONE)
### Phase 3 — Flywheel capture with v5 tagging (DONE)
### Phase 4b — Eval harness (DONE)
### Phase 4c — Adapter routing scaffold (DONE, needs realignment)

### Phase 4e.1 — Labeling infrastructure (NEW, NEXT)
Godhead-as-labeler pipeline. Manual QC surface. Capture extension
for (prompt, sovereign_response, godhead_judgment, gary_correction).
Enables every downstream judge phase.

### Phase 4e.2 — Task type classifier (DONE)
Task classifier live. Three tiers: module hint → keyword pattern → qwen2.5:0.5b (500ms timeout). See backend/services/task_types.py for module→task and keyword→task mappings. task_type populated on every ai_router and legal_council capture.
Three-tier classifier: source hint → keyword → small LLM. Wires into
ai_router at top of request path. Populates task_type on every capture.

**Defect 3 fix (2026-04-19):** Tier 1 module hint can now be overridden by
content analysis when the prompt strongly contradicts the module's default
task type. Currently only fires for `pricing_math`: `quote_engine` is
multi-purpose — it handles both pricing calculations and property
description/marketing copy tasks. When a quote_engine prompt contains no
pricing signal (`_PRICING_PATTERNS`) but clear descriptive signal
(`_DESCRIPTIVE_PATTERNS`), `_detect_content_mismatch` returns `vrs_concierge`
instead. Pricing signal always wins if present; the override only fires on
zero pricing + positive descriptive. See `task_classifier.py`.

**Ambiguous multi-purpose modules:** `quote_engine` defers to keyword content.
`vrs_agent_dispatcher` stays `vrs_concierge` regardless of pricing keywords —
the override only fires when Tier 1 resolves to `pricing_math`, not when it
resolves to `vrs_concierge`. If a `vrs_agent_dispatcher` capture contains
substantive pricing discussion, that is within-scope for `vrs_concierge`
(staff pricing guidance is a concierge function). If pricing math becomes a
distinct vrs sub-task with sufficient volume, add `vrs_pricing` to `_TASK_TYPES`
and update `_MODULE_TO_TASK` in a separate architectural decision.

### Phase 4e.3 — Judge scaffolding (DONE, awaiting training data)
Highest-volume task type, lowest-risk errors, fastest iteration.
Proves the judge architecture end-to-end before replicating.

### Phase 4e.4 through 4e.10 — remaining judges
One per primary task type, sequenced by data volume and strategic
value. Legal reasoning judge ships early despite lower volume because
its value per correct decision is highest.

### Phase 4a — CROG-VRS distillation (ACTIVE — trainer retargeted 2026-04-19)
qwen2.5:7b → qwen2.5:7b-crog-vrs. Nightly fine-tune pipeline
(`src/nightly_finetune.py`) now targets Qwen2.5-7B-Instruct staged at
`/mnt/fortress_nas/models/Qwen2.5-7B-Instruct` (PR #70).

**Retarget rationale:** ai_router production inference runs on `qwen2.5:7b`
via NIM/vLLM. Training the same architecture closes the train/serve gap.
The previous Llama-3.3-70B-Instruct-FP4 target was never served to production
and required stopping NIM to free ~60 GB for training. Qwen2.5-7B QLoRA
peaks at ~15 GB, fits alongside NIM on the GB10 (120 GB unified memory)
without disruption. `NIGHTLY_FINETUNE_STOP_NIM` now defaults to `false`.

Adapter artifacts: `qwen2.5-7b-crog-vrs-<date>/` on NAS.
Previous Llama-3.3 adapter stubs (`llama-3.3-70b-crog-*`) are pipeline
development exercises and can be ignored — they contain only error files.

### Phase 4d — Fortress Legal distillation (NEW, later)
qwen2.5:32b → qwen2.5:32b-fortress-legal. Uses public legal corpus
PLUS captures where judge_decision = escalate on legal tasks (with
matter-level redaction). Ships after legal_reasoning_judge is mature.

### Phase 5a — RAG architecture migration (from v4)

**Part 1 — spark-4 VRS Qdrant LIVE (2026-04-19)**
- Qdrant `latest` running on spark-4 (192.168.0.106:6333) via Docker
- Data volume: `/mnt/fortress_nas/qdrant-vrs/` (NAS-backed)
- systemd unit: `fortress-qdrant-vrs.service` (enabled, starts on boot)
- Collection `fgp_vrs_knowledge` created: 768d Cosine, 4 payload indexes
  (`source_table`, `record_id`, `property_id`, `category`) — empty, migration deferred
- Smoke test passed: write → read → delete round-trip from both spark-4 and spark-2
- Full ingestion audit: `docs/RAG_INGESTION_AUDIT.md`

**Part 2 — Snapshot migration COMPLETE (2026-04-19)**
- 168 points migrated from spark-2 `fgp_knowledge` → spark-4 `fgp_vrs_knowledge`
- Tool: `src/rag/migrate_fgp_to_vrs.py` (scroll 3×64-batch + upsert wait=true)
- Verification: count parity 168==168 ✓, 10/10 sampled vectors byte-identical ✓
- Elapsed: 1.2s. Idempotent — safe to re-run with --force.
- spark-2 `fgp_knowledge` is **NOT modified** — remains source of truth for reads.
- spark-4 `fgp_vrs_knowledge` is a static snapshot. New writes still go to spark-2
  until Part 3 (ingestion cutover).

**Part 3 — Ingestion cutover + read flip (NEXT)**: add `QDRANT_VRS_URL` env var;
`VectorizerWorker` and `sync_knowledge_base_to_qdrant` write to both spark-2 and
spark-4 simultaneously. Once parity is confirmed stable, flip reads to spark-4.

**Part 3 — Read cutover (LATER)**: after spark-4 data matches spark-2 (168 points +
ongoing delta), flip `QDRANT_URL` → spark-4 and `QDRANT_COLLECTION_NAME` → `fgp_vrs_knowledge`.
Remove dual-write code.

Recommendation: Option A (dual-write) — not Option B (hard cutover) because
`_qdrant_search` is called on every guest concierge interaction (zero downtime tolerance).
See `docs/RAG_INGESTION_AUDIT.md` for full write/read site table and rationale.

Legal collections (`legal_library`, `legal_ediscovery`) stay on spark-2 permanently;
they are NOT in Phase 5a scope.

### Phase 5b — Node role migration (from v4)
Move NIM off spark-2. Unchanged from v4.

### Phase 6 — Multi-node observability (from v4)
Extended to surface judge decisions, escalation rates, teacher
distribution.

## Migration sequence

1. Phase 4e.1 — Labeling infrastructure (~3-5 days)
2. Phase 4e.2 — Task type classifier (~2-3 days)
3. Phase 4e.3 — First judge, vrs_concierge (~3-5 days)
4. Phase 5a part 1 — spark-4 VRS vector store (~2-3 hours)
5. Phase 4e.4 — vrs_market_research_judge (~3-5 days)
6. Phase 4a — CROG-VRS distillation (~2-3 hours of code, weeks of
   capture accumulation)
7. Phase 4e.5-4e.7 — Remaining VRS + orchestrator judges (~2 weeks total)
8. Phase 4e.8 — Legal reasoning judge (~1 week, needs clean data)
9. Phase 5a part 2 — spark-1 legal vector store (~multiple sessions)
10. Phase 4e.9-4e.10 — Remaining legal and vision judges
11. Phase 4d — Fortress Legal distillation (~multi-session)
12. Phase 5b — NIM migration off spark-2 (maintenance window)
13. Phase 6 — Observability extensions (ongoing)

Total realistic program: **6-12 weeks** for full judge tier across
all task types plus two distilled models plus RAG migration.

First working end-to-end loop (Phases 4e.1-4e.3 + 4a): **2-3 weeks**.

## Decision log (April 18, 2026 — v5 session)

1. Three-tier architecture. Godhead teaches, Sovereign serves,
   Judge decides. Not a two-tier fallback model.

2. Specialized Godhead per task type. Claude for legal, Gemini for
   vision, Grok for real-time, GPT for code, DeepSeek-R1 for math.
   Fallbacks defined per task.

3. Task type classifier at top of request path. Three-tier: source
   hint → keyword → small LLM. Deterministic where possible.

4. Judges specialized per task type. Eight judges minimum, one per
   primary task category. Small instruction-tuned LLMs, distributed
   across nodes with their domain.

5. Judge output is structured: decision, confidence, reasoning,
   escalation_category.

6. Labeling via hybrid pipeline. Godhead labels at scale, Gary
   QCs 10% samples per week, judge self-improvement later.

7. Escalation discards sovereign response, returns Godhead response
   to user. Sovereign's attempted response captured as training
   signal but not shown to user.

8. Capture schema v5 includes task_type, judge_decision, judge_reasoning,
   sovereign_attempt, teacher_endpoint, teacher_model, escalated_from —
   shipped in Phase 3 retag.

9. Judge-first implementation order. Full judge tier before distillation
   begins. "Build it right, even if slow."

10. First judge is vrs_concierge_judge. Highest volume, lowest risk
    per error, fastest iteration to prove architecture.

## Risks live after v5

R1-R8 from v2/v3 unchanged. R9-R12 from v4 unchanged.

**New risks from v5:**

R13 — Godhead-as-labeler bias. Judges trained on Godhead's judgments
inherit Godhead's blind spots. Mitigation: Gary's 10% QC sample is
not optional. Systematically under-weight label patterns that correlate
with known Godhead weaknesses (e.g., Claude's over-caution, GPT's
confident hallucination).

R14 — Judge latency in request path. 200ms p95 inline judge call
adds latency to every request. Mitigation: small judge models,
optimized prompts, parallel inference where possible, circuit-breaker
if judge unreachable (default to serving sovereign response with
judge_decision=unknown).

R15 — Escalation cost unboundedness. If judges escalate aggressively,
Godhead API costs scale with traffic. Mitigation: per-judge escalation
rate SLO (e.g., target <30% escalation rate). Retrain judges that
over-escalate. Hard cap on daily Godhead spend with alert.

R16 — Judge disagreement with reality. Judge says "confident" but
response was actually bad. Mitigation: downstream signal capture
(user complaints, manual corrections, error rates) feeds judge
retraining. Judge accuracy itself becomes a measurable KPI.

R17 — Task classifier cold start. Small LLM classifier on spark-2
has no training data initially — uses keyword rules and source
hints only. Mitigation: acceptable for first weeks. Classifier
trains on accumulated task_type labels (which the classifier itself
produced, creating circularity — but also self-correcting as
misclassifications get surfaced by judge escalation patterns).

## What this document does

Iron Dome v5 is the target architecture. Three tiers, specialized
teachers, specialized judges, domain-isolated infrastructure,
provenance-tagged captures.

Implementation is 6-12 weeks of work. First functional end-to-end
loop in 2-3 weeks. Every PR from here cites a Phase 4e sub-phase
or an earlier unfinished phase.

This replaces v4 as the single source of architectural truth.
