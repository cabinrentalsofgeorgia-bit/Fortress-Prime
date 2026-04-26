# Shared: Council — Deliberation

Spark allocation:
- **Current:** Spark 2 (tenant of the monorepo)
- **Target:** **Spark 4** (per ADR-002 LOCKED 2026-04-26 — Spark 4 hosts Council + Acquisitions + Wealth as a "shared services + intermittent divisions" multi-purpose node). Migration is staged after Spark 4 is provisioned: warm-spare → parallel verification week → command-center cutover → 7-day soak → Spark 2 instance retires.

Inference plane (per [ADR-003](../cross-division/_architectural-decisions.md) LOCKED 2026-04-26):
- Council deliberation **logic** stays on Spark 4 (per ADR-002).
- Council deliberation **inference workload** routes through the LiteLLM proxy on Spark 2 — Council dispatches to whichever spark's LLM endpoint LiteLLM selects.
- Multi-persona deliberation can use different endpoints for different personas in parallel (ADR-003 Phase 3).
- Direct endpoint calls from Council are deprecated in favor of LiteLLM-routed calls.

Last updated: 2026-04-26

## Technical overview

Council is Fortress's multi-persona deliberation engine. For a given case (or general legal question), it freezes context from Qdrant, runs a panel of LLM personas with case-aware prompts, and produces a `consensus_summary` plus a structured `frozen_context` artifact.

Post-PR G (#214), Council is **privilege-aware**: deliberations that retrieve any privileged chunk emit a `contains_privileged: true` SSE event and append a fixed-text FOR YOUR EYES ONLY warning to the consensus output.

## Privilege classifier

Inside `process_vault_upload()` (used by both live ingest and backfill):

- Local Qwen2.5 inference via Ollama-routed swarm
- Confidence ≥ 0.7 + `is_privileged=true` → `processing_status='locked_privileged'`
- Otherwise → falls through to the work-product track
- Decision is logged to `legal.privilege_log` with snippet, confidence, model, latency

The classifier's prompt is `legal_ediscovery.PRIVILEGE_SYSTEM_PROMPT`. See [`../../runbooks/legal-privilege-architecture.md`](../../runbooks/legal-privilege-architecture.md) §1 for the full policy.

## Retrieval — two collections

| Collection | When | Function |
|---|---|---|
| `legal_ediscovery` | Always | `freeze_context(case_brief, top_k, case_slug)` |
| `legal_privileged_communications` | When `COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL` env var truthy (default true) | `freeze_privileged_context(case_brief, top_k, case_slug)` |

Privileged chunks come back with a `[PRIVILEGED · counsel-domain · role]` prefix tag preserved in every downstream pipeline (PDF, copy/paste, deliberation prompt, persona output).

## Cross-matter expansion

When `COUNCIL_INCLUDE_RELATED_MATTERS` env var truthy (default true): retrieval expands to every slug in the case's `legal.cases.related_matters` JSONB. One-hop only (no transitive expansion).

## FYEO warning contract

Two surfaces:

1. **Structured flag** — every SSE event carries `contains_privileged: bool`; UI shows the FYEO Card the moment a privileged chunk lands in the frozen context
2. **In-band text** — `FOR_YOUR_EYES_ONLY_WARNING` constant appended to `consensus_summary` so PDF exports and copy-paste pipelines preserve it

Wording is fixed (canonical at `legal_council.FOR_YOUR_EYES_ONLY_WARNING`). Do not paraphrase — court filings would expose any drift.

## Consumers

- `apps/command-center/src/app/(dashboard)/legal/council/page.tsx` — UI that streams deliberation events
- `apps/command-center/src/lib/use-council-stream.ts` — SSE event reducer + state
- `backend/api/legal_counsel_dispatch.py` — REST + SSE entry points
- Other divisions (acquisitions, master-accounting, etc.) — TBD whether they consume Council, or each runs its own deliberation surface

## Contract / API surface

- `POST /api/internal/legal/cases/{slug}/deliberate` — kicks off a deliberation; SSE response stream
- Each SSE event includes: `frozen_context` snapshot, persona vote/reasoning chunks, `contains_privileged` flag, optional `privileged_warning` text
- Final `result` event: `consensus_summary` (with FYEO warning appended if applicable), `vector_ids` for traceability

## Env vars (deliberation-time, no restart needed to flip)

- `COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL` — default `true`. Set to `false`/`0`/`no`/`off`/empty for emergency containment.
- `COUNCIL_INCLUDE_RELATED_MATTERS` — default `true`. Disable to suppress cross-matter retrieval.

## Where to read the code

- `backend/services/legal_council.py:1113` — `LEGAL_COLLECTION` constant
- `backend/services/legal_council.py:_council_retrieval_flags()` — env-var reader
- `backend/services/legal_council.py:freeze_context()` — work-product retrieval
- `backend/services/legal_council.py:freeze_privileged_context()` — privileged retrieval (PR G)
- `backend/services/legal_council.py:_resolve_related_matters_slugs()` — related-matters lookup
- `backend/services/legal_council.py:run_council_deliberation()` — orchestrator

## Cross-references

- Privilege runbook: [`../../runbooks/legal-privilege-architecture.md`](../../runbooks/legal-privilege-architecture.md)
- [`qdrant-collections.md`](qdrant-collections.md) — collection inventory
- Cross-division flow: [`../cross-division/council-retrieval.md`](../cross-division/council-retrieval.md)

Last updated: 2026-04-26
