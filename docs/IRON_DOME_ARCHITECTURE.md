# Iron Dome — Fortress-Prime Sovereign AI Defense System

**Version:** 6.1
**Date:** April 21, 2026
**Author:** Gary Knight (with Claude)
**Supersedes:** v5 (April 18, 2026)

---

## Why v6

v5 established the three-tier architecture (Godhead / Sovereign / Judge)
and assigned two enterprises to nodes — Fortress Legal on spark-1,
CROG-VRS on spark-4. v6 corrects two realities that surfaced after
v5 was written:

1. **v5 on paper was not v5 in production.** The atlas / model_registry
   never listed `qwen2.5:7b` on spark-4. `tier_routing.fast` was
   `["spark-2", "spark-1"]` only. Every `task_type=vrs_concierge` call
   routed to spark-2 (training-loaded) or spark-1 (also under load),
   then cascaded to cloud fallback. The "spark-4 is CROG-VRS" story
   was an architectural aspiration, not a deployment. v6 makes it
   real via the atlas fix (feat/atlas-vrs-spark4-routing, PR
   forthcoming).

2. **v5 had no home for non-VRS, non-Legal enterprises.** Master
   Accounting, Acquisitions, and the Financial / Trading / Wealth
   enterprise were implicitly piled onto spark-2 by default. This
   perpetuated the crowding problem v5 was designed to avoid and
   caused the sovereignty break documented above. v6 explicitly
   assigns homes for the remaining enterprises.

---

## Operating Principles (v6.1)

### Principle 1 — Vendor-optimized inference first

For any workload where Nvidia ships a tuned NIM or Nemotron variant
(concierge, reasoning, customer service, high-throughput inference), that is
the **default choice**. Generic Ollama pulls are the fallback when no
NIM/Nemotron fits the workload, not the default.

This applies because this cluster is 4× DGX Spark (GB10 Grace Blackwell,
unified memory) — built specifically for the NIM ecosystem. Using commodity
models when vendor-optimized variants exist leaves performance and safety on
the table.

### Principle 2 — Headroom discipline

- Target per-node memory utilization **≤ 60%** under steady-state workload.
- Reserve ≥ 40% for: training collisions, on-demand bursts (Financial,
  Vision), concurrent guest traffic, emergency failover capacity.
- No node operates with zero slack. If a model allocation would push a node
  over 60%, the allocation gets revisited — re-host to a different node,
  use a smaller model, or defer the decision.
- **Exception:** `legal_train` during active epochs may push spark-2 beyond
  60% temporarily. Other nodes compensate via health-probe failover per the
  3-phase probe introduced in PR #105. This exception is time-bounded to the
  epoch duration and does not set a precedent for steady-state overcommit.

---

## Enterprise → node assignments (v6, amended 2026-04-29 by ADR-003 Phase 1)

| Node    | IP              | Primary Role                        | Secondary Role                         |
|---------|-----------------|-------------------------------------|----------------------------------------|
| spark-1 | 192.168.0.104   | Fortress Legal app (vault, ingestion, privilege)    | Legal vector store host (no inference) |
| spark-2 | 192.168.0.100   | Orchestration + backend + control + LiteLLM gateway | Captain / Council / Sentinel permanent (per ADR-002 amended) |
| spark-3 | 192.168.0.105   | Financial + Acquisitions + Wealth co-tenants (planned, until Spark-7+) | — |
| spark-4 | 192.168.0.106   | Inference cluster member (Phase 3) | — (was CROG-VRS host; CROG-VRS data moves with Phase 3 plan) |
| spark-5 | 192.168.0.109   | **BRAIN inference (NIM Llama-3.3-Nemotron-49B-FP8)**, Ray head | Inference cluster head |
| spark-6 | 192.168.0.115   | Inference cluster worker (Phase 2 — cable pending) | — |

**Changes from prior v6:**
- ADR-003 Phase 1 (LOCKED 2026-04-29) moves BRAIN inference off spark-1 onto the dedicated **spark-5 NIM** at `http://spark-5:8100`. spark-1 is now app-tier only — no NIM, no TITAN, no inference tenancy.
- LiteLLM gateway on spark-2 now routes the legal tier (`legal-reasoning` / `legal-classification` / `legal-summarization` / `legal-brain` model names) to spark-5. **Audit finding A-02 (cloud legal inference) — RESOLVED 2026-04-29 at the routing layer.** Production seat-level cutover (`legal_council.py` `SEAT_ROUTING`) ships in a follow-up Phase B PR; sovereign route is **available** but not yet **traffic-cutover** at the consumer layer.
- Council moves from the planned Spark-4 Option B host back to spark-2 control plane (Option A across the board) per ADR-002 amended 2026-04-29.

**Sovereignty claim (post-cutover):** Legal-tier inference terminates on sovereign hardware (spark-5 NIM). The previous v6 statement that legal inference was sovereign was inaccurate at the routing layer until 2026-04-29; it is now accurate at the routing layer. Operator must complete the Phase B `SEAT_ROUTING` migration before this is true at the consumer layer.

---

## The five enterprises

### Fortress Legal
- Sovereign model: NIM `meta/llama-3.1-8b-instruct-dgx-spark`
  (migrated to spark-1 per v5 Phase 5b)
- Judge: `legal_reasoning_judge`, `brief_drafting_judge` (qwen2.5:32b, 1000ms
  latency, is_active=False pending training data per Phase 4e.3)
- Godhead: Claude primary, GPT fallback (legal reasoning / brief drafting)
- Vector store: `legal_library`, `legal_ediscovery` — stays on spark-2 Qdrant
  (NOT in Phase 5a migration scope)
- Privilege boundary: no cross-domain retrieval into VRS stores

### CROG-VRS (Cabin Rentals of Georgia)
- Sovereign model: `qwen2.5:7b` served from spark-4
- Distilled target: `qwen2.5:7b-crog-vrs` (Phase 4a, nightly finetune active)
- Judge: `vrs_concierge_judge`, `market_research_judge`, `pricing_math_judge`
  (qwen2.5:7b, 200ms latency)
- 9-seat concierge deliberation: `crog_concierge_engine.run_guest_triage` /
  `run_email_triage` (Seats 1–9 per the concierge architecture; seats 4, 7
  hit spark-3/spark-4 local, seat flagship via LiteLLM gateway)
- Godhead: Claude primary for guest concierge, GPT fallback
- Vector store: `fgp_vrs_knowledge` on spark-4 Qdrant (Phase 5a complete,
  read cutover live)
- Email pipeline: `email_messages` / `email_inquirers` tables + `/api/email/outbound-drafts`
  (PR #104)

### Financial / Trading / Wealth (NEW in v6)
- Current mode: **research-only**. `/mnt/fortress_nas/wealth/LIVE_DISABLED`
  marker enforces no live broker endpoints. Every wealth script checks
  this file at startup and refuses to run if missing.
- GPU: spark-3, on-demand, gated via marker file (see Shared GPU Gating
  section below). No scheduled jobs — operator triggers backtests.
- Sovereign model: NOT YET ALLOCATED. Research uses Godhead (Claude for
  thesis analysis, GPT for data munging, DeepSeek-R1 for math).
  Distilled sovereign model decision deferred until Financial proves
  out workload patterns — spec'd after 60+ days of real research usage.
- Judge: not yet scaffolded. Blocked on sovereign model allocation.
- Godhead routing (per task):
    - Math reasoning / complex logic: DeepSeek-R1 primary
    - Strategy / thesis: Claude primary
    - Real-time market conditions: Grok primary
    - Code generation (backtest frameworks): GPT primary
- Vector store: `wealth_research` (to be created on NAS), NOT shared
  with VRS or Legal — cross-domain retrieval prohibited by design.
  Ingestion sources: market data, FRED, filings, research papers.

### Master Accounting
- Compute: spark-2 (lightweight). Books, ledger, statement workflows,
  Stripe reconciliation — all transactional, CPU-sufficient.
- Writes: only from accounting lane (per lane architecture). Other
  lanes emit to `/mnt/fortress_nas/accounting/inbox/` for batch drain.
- Sovereign model: none needed. Reports and analysis via Godhead
  (Claude for narrative statements, GPT for SQL generation).

### Acquisitions Pipeline
- Compute: spark-2 (lightweight). Deal flow, diligence notes, research.
- Capital requests to Wealth via `/mnt/fortress_nas/wealth/capital_requests/`
  (one-way, never the reverse).
- Sovereign model: none needed. Cloud Godhead for analysis.

---

## Shared GPU gating (spark-3)

spark-3 serves two masters: vision (primary) and Financial GPU (secondary,
on-demand). Since Financial is operator-triggered and vision is sporadic,
a scheduler is overkill. v6 uses a marker-file gate:

**Mechanism:**
- `/mnt/fortress_nas/spark3/VISION_BUSY` — written by vision jobs at start,
  removed at end (trap-handler on exit)
- Financial GPU scripts check for this file at startup:
    - File exists → Financial script logs "vision busy, deferring" and exits
      (operator re-runs manually)
    - File absent → Financial writes `/mnt/fortress_nas/spark3/FINANCIAL_BUSY`
      and proceeds
- Vision scripts similarly check for `FINANCIAL_BUSY` and defer if present

**Rules:**
- No automatic retry / queue. Operator sees the defer message and re-runs
  when the other workload clears.
- Marker files include PID + start timestamp so stale markers (from a
  crashed script) can be identified and cleared.
- A daily cron at 4am scans for markers older than 12h and logs a
  warning — prevents silent deadlock if a script crashes before cleanup.

**Why this is enough for now:**
- Financial is on-demand (operator-triggered), not scheduled
- Vision bursts are mostly predictable (check-in/out windows)
- Worst case: operator sees "deferring" and triggers 30 min later
- Scheduler layer (proper priority queue) can ship later if contention
  becomes frequent. Marker files are cheap to replace.

---

## Model routing (v6 atlas)

`tier_routing` defines which nodes serve which tier per task_type:

```yaml
# Excerpt — see backend/services/model_registry.py for authoritative source

fast_tier (qwen2.5:7b, <500ms target):
  vrs_concierge:        [spark-4, spark-2, spark-1]   # v6 change
  pricing_math:         [spark-4, spark-2, spark-1]
  concierge_replies:    [spark-4, spark-2, spark-1]
  code_generation:      [spark-2, spark-1]
  real_time:            [spark-2, spark-1]
  generic:              [spark-2, spark-1, spark-4]

deep_tier (qwen2.5:32b, 500-1500ms target):
  legal_reasoning:      [spark-1]
  brief_drafting:       [spark-1]
  contract_analysis:    [spark-1]
  legal_citations:      [spark-1]

vision_tier (llama3.2-vision:90b, latency tolerant):
  vision_analysis:      [spark-3]
  vision_photo:         [spark-3]
```

**Key change from v5:** `vrs_concierge` lists spark-4 first. spark-2 and
spark-1 retained as fallback overflow but deprioritized. Non-VRS fast-tier
traffic continues to use spark-2/spark-1 primarily — spark-4's GPU stays
free for CROG-VRS.

**Health probe upgrade (v6):** `model_registry` probe now checks
`/api/chat` with a minimal inference (1 token, short prompt, 3s timeout)
instead of only `/api/tags` existence. An Ollama process that has the
model listed but can't actually serve inference (GPU under load, OOM,
etc.) is now correctly marked unhealthy. This prevents the failure mode
v5 suffered: router picked a GPU-starved node because it passed the
tags check.

---

## Godhead tier (frontier teachers, unchanged from v5)

Task → primary teacher mapping is the v5 table, unchanged:

| Task type            | Primary    | Fallback 1 | Fallback 2 |
|---------------------|-----------|-----------|-----------|
| Legal reasoning     | Claude    | GPT       | DeepSeek-R1 |
| Brief drafting      | Claude    | GPT       | DeepSeek-R1 |
| Concierge replies   | Claude    | GPT       | —         |
| Pricing strategy    | Claude    | GPT       | DeepSeek-R1 |
| Vision (damage)     | Gemini    | Claude    | —         |
| Real-time facts     | Grok      | Gemini    | —         |
| Math reasoning      | DeepSeek-R1 | Claude  | GPT       |
| Code generation     | GPT       | Claude    | —         |

All frontier calls route through LiteLLM gateway at `127.0.0.1:4000`
on spark-2. When sovereign fails or the judge escalates, the specialized
teacher responds.

---

## Judge tier (per-task specialized, status unchanged from v5)

All judges scaffolded per v5 Phase 4e.3, `is_active=False` pending
accumulation of training data. No changes in v6 — the judge plan
stands as-is.

---

## Risks (new in v6)

**R18 — spark-3 GPU deadlock via marker files.**
A crashed vision or Financial script could leave a marker file behind,
blocking the other workload indefinitely. Mitigation: the 4am stale-marker
janitor plus PID + timestamp in every marker. Operator can manually
`rm` a stale marker with confidence.

**R19 — Financial on spark-3 contends with vision during damage-claim surges.**
If a cabin has a big damage event and 50 photos need vision analysis,
a Financial backtest triggered at the wrong moment will be deferred.
Acceptable for research-mode. If Financial goes live with production
inference, contention becomes a real problem and spark-5 procurement
is back on the table.

**R20 — v6 atlas change affects non-VRS traffic indirectly.**
Adding spark-4 to fast-tier routing for vrs_concierge doesn't remove
spark-2/spark-1 from other fast-tier tasks. But the health probe upgrade
(checking /api/chat) may mark spark-2 unhealthy during training-heavy
periods, pushing ALL fast-tier traffic to spark-1. Mitigation: monitor
post-merge for spark-1 saturation. If spark-1 starts failing its own
probe, we have a real capacity gap the architecture was hiding.

---

## Migration from v5 to v6

Ordered work items:

1. **Atlas fix (in progress as of this writing):** atlas registers
   qwen2.5:7b on spark-4, tier_routing.fast vrs_concierge routes to
   spark-4 first. Health probe upgraded from /api/tags to /api/chat.
   Branch: feat/atlas-vrs-spark4-routing (Claude Code, Part 2).

2. **Merge PR #104 (feat/email-pipeline-parallel)** — email pipeline
   for CROG-VRS guest inquiries. Parallel tables to SMS. Already tested
   end-to-end.

3. **Create `/mnt/fortress_nas/spark3/` directory** for marker files.
   Write the stale-marker janitor script. Schedule 4am cron on spark-2.

4. **Financial spark-3 GPU access:** wealth lane scripts updated to
   SSH to spark-3 for GPU work. `nrun` helper in wealth lane .lane-env
   adjusted.

5. **v6 doc (this doc) merged as single source of architectural truth,
   superseding v5.**

6. **Deferred (not v6 scope, tracked for later):**
    - Financial sovereign model allocation (after 60 days of research usage)
    - spark-5 procurement decision (if Financial goes live)
    - Judge activation (when training data accumulates per Phase 4e)
    - `reservations_draft_queue` deprecation (after email pipeline stable 48h+)

---

## Decision log (April 21, 2026 — v6 session)

1. Financial enterprise exists and needs a home. spark-3 chosen as
   shared node (vision primary, Financial secondary via marker-file gating).
   spark-5 procurement deferred until Financial proves out.

2. v5 routing was never deployed to the atlas. v6 makes it real.
   qwen2.5:7b added to spark-4's atlas entry, vrs_concierge fast-tier
   prioritizes spark-4.

3. Health probe upgraded from /api/tags to /api/chat. A node that has
   the model listed but cannot actually inference is now correctly
   marked unhealthy. This was the silent bug in v5 that caused
   training-loaded spark-2 to be picked for vrs_concierge traffic.

4. Marker-file GPU gating preferred over scheduler for v6. Simplest
   possible mechanism. Upgrade to proper scheduler only if contention
   becomes frequent in practice.

5. Financial stays research-only via LIVE_DISABLED marker. No sovereign
   model allocation until operational pattern is proven.

6. Master Accounting and Acquisitions explicitly named as spark-2
   co-tenants (were implicit in v5).

---

## What this document does

Iron Dome v6 corrects the v5 deployment gap (atlas never matched doc),
adds an explicit home for Financial as the fifth enterprise, and
establishes shared-GPU gating for spark-3. It preserves v5's three-tier
architecture, all task-type mappings, and the judge scaffolding plan.

This replaces v5 as the single source of architectural truth.

---

## Changes from v6.0

**v6.1 (April 21, 2026):** Added two Operating Principles — Vendor-optimized
inference first (NIM/Nemotron preferred on GB10 hardware) and Headroom
discipline (≤ 60% per-node steady-state, ≥ 40% reserve). These formalize
architecture decisions implied by the DGX Spark hardware choice and the
legal_train failover pattern established in PR #105.
(END)
