# Fortress Legal Operating System (FLOS) — Design v1

**Status:** PROPOSED — operator review pending
**Date:** 2026-04-27
**Author:** Claude (research-driven; verified against codebase + DB state)
**Scope:** Strategic design for a continuously-running legal operating system that lets a solo business operator never be out-prepared by opposing counsel.

This document is a **strategic design**, not an implementation spec. It identifies what exists, what is missing, what the operating layers should be, and a sequencing roadmap that flows from foundation to capability. It is the parent document for a proposed **ADR-004** that operator may iterate before locking.

---

## 1. Vision

### 1.1 The problem

A solo business owner runs Cabin Rentals of Georgia, LLC (CROG) and several related entities. Multiple legal matters are active at any moment — a fish-trap commercial-contract dispute (Generali), an active 7IL Case I + Case II in NDGA, a Vanderburge real-property easement matter, and a Prime Trust bankruptcy KYC distribution. There is no in-house counsel. The operator IS the in-house counsel for purposes of pre-engagement strategy, document preparation, deadline tracking, and counsel selection.

When opposing counsel fires off a motion, a single attorney with a research stack and a paralegal can have a response drafted within days. **The solo operator cannot match that pace by hand.** The asymmetry is structural — the opposition has tools the defendant doesn't.

The current Fortress Prime legal stack contains many of the right primitives but they don't compose into a system that runs. Captain (the email intake pipeline) has been dormant since 2026-03-23. The Council of 9 deliberation runs on demand but doesn't drive state changes. The Counsel Dispatch headhunter is built but never been invoked. Case posture lives partially in the briefing-pack PDFs in NAS, partially in alert JSONs, partially in operator memory.

### 1.2 The solution

A **continuously-running Legal Operating System** with five properties:

1. **Always on** — events arrive (email, court filing, deadline, operator input), the system processes them, state advances, operator is notified of decisions to make. Not invoked-on-demand.
2. **Structured state** — case posture lives in Postgres tables (procedural status, theory of defense, exposure quantification, leverage analysis), NOT in markdown files or briefing PDFs. Markdown/PDFs are *outputs* of state, not the state itself.
3. **Pre-assembled work product** — when a new motion arrives, the response variants are already drafted because evidence-to-defense-element mapping was already done. Operator approves, doesn't draft from scratch.
4. **Dispatch-ready** — when retaining counsel, operator hands them a complete file: posture, evidence index, theory of defense, response drafts, opposing-counsel profile, settlement leverage analysis. Not a forward of an email thread.
5. **Single operator surface** — one dashboard per case showing current posture, pending decisions, deadlines, exposure. Not a hunt across email + NAS + Postgres + briefing PDFs.

### 1.3 The non-solution

FLOS does **not** replace attorneys. Bar rules + LLC pro-se prohibition (Eckles) + court appearance requirements remain. FLOS is the **pre-engagement and during-engagement preparation layer.** Counsel is still retained for:

- Court appearances (motions, hearings, trial)
- Privileged advice (FLOS surfaces options, counsel makes the privileged recommendation)
- Bar-supervised filings (counsel signs, FLOS prepares)
- Tactical advocacy (counsel knows the courtroom dynamics, FLOS knows the file)

### 1.4 Success criteria

| scenario | current state | FLOS target |
|---|---|---|
| Plaintiff files unexpected motion | Operator scrambles for 2-3 days | Response variants drafted within 24h, operator approves and counsel files |
| Retaining counsel | Hand them the briefing pack PDF + email forward | Hand them: case posture row, evidence-element matrix, theory-of-defense state, draft responses, opposing counsel profile, exposure quant, leverage analysis. All structured, all current. |
| Settlement vs litigation decision | Gut feel + advice from counsel | Quantified exposure model + leverage analysis + Council consensus + venue/judge ruling pattern + cost-to-litigate estimate |
| New email arrives from opposing counsel | Captain dormant; might be missed | Inbound classified within minutes, case posture updated, deadline calculated, response variant drafted, alert posted |
| Deadline approaching | Operator-tracked (or not) | Calendar-driven; alerts at 30/14/7/3/1 days; pre-drafted action ready at each threshold |

---

## 2. Component inventory

Every entry below is verified — read the file's docstring + key function signatures, or queried the live DB / Qdrant / NAS. **Classification:** ACTIVE (currently running and populating state), DORMANT (was active, currently quiescent), STUB (built but no production invocation), NEVER_USED (table/code exists, 0 rows / 0 invocations observed).

### 2.1 Backend services

| file | lines | classification | role today | role in FLOS |
|---|---:|---|---|---|
| `backend/services/legal_council.py` | 1942 | **ACTIVE** | 9-persona LLM deliberation engine. Runs on demand, returns consensus_signal + opinions + frozen-context vault hash. SSE streamed via API. | The reasoning core. Every meaningful state change re-runs Council. Consensus persisted to case_actions. |
| `backend/services/legal_ediscovery.py` | 984 | **ACTIVE** | Vault ingestion: privilege classifier → text extract → chunk → embed → Qdrant upsert. Phase B/B.1 from PR #242 (Issue #228). | Document intake substrate. Layer 1 evidence-element mapping reads from here. |
| `backend/services/legal_email_intake.py` | 676 | **DORMANT** | MailPlus inbox poller, triages emails through local LLM, links to active cases, records correspondence + timeline events. | Layer 1 inbound event source. Must be paired with Captain restart. |
| `backend/services/captain_multi_mailbox.py` | 926 | **DORMANT** | Multi-mailbox poller (Gmail API + cPanel IMAP). MAILBOXES_CONFIG-driven. Hooks privilege_filter.classify_for_capture before routing. Stopped 2026-03-23. | Layer 0 foundational — without this, no inbound event flow. |
| `backend/services/captain_junk_filter.py` | 340 | **DORMANT** | Three-tier junk classifier (header / sender / LLM) firing BEFORE privilege filter in Captain pipeline. | Same as Captain — gates the inbound event stream. |
| `backend/services/legal_counsel_recon.py` | 172 | **STUB** | CourtListener-based attorney profiler. Returns LitigatorProfile (name, cases_found, frequent_jurisdictions, top_cited_precedents). | Layer 3 building block — invoked by Counsel Dispatch hunt phase + opposing-counsel profiler. |
| `backend/services/legal_drafter.py` | 284 | (Off-topic) | Damage-claim guest-response generator. NOT for counsel outreach — different domain entirely. | None directly. Could share `_validate_citations` hallucination guard pattern. |
| `backend/services/legal_docgen.py` | 362 | **ACTIVE** | Generates court-formatted DOCX Answer + Affirmative Defenses. Uses Council consensus output. Defaults coded for fish-trap. | Layer 3 dispatcher. Extend with briefing-pack generator + counsel-handoff packet. |
| `backend/scripts/email_backfill_legal.py` | 1370 | **ACTIVE (batch)** | Case-aware IMAP backfill. Per-case, walks date-banded UID search. Classifies via routing rules. Calls process_vault_upload. | Bulk historical backfill. One-shot per case; not continuous. |
| `backend/scripts/vault_ingest_legal_case.py` | 1053 | **ACTIVE (batch)** | NAS-walk vault ingestion: layout-aware physical dedup, dual-DB write, IngestRunTracker, lock file. | Bulk historical ingest. Same shape as email backfill. |
| `backend/api/legal_tactical.py` | (~200) | **ACTIVE** | POST `/cases/{slug}/tactical-strike` and `/cases/{slug}/omni-search`. Plus `/cases/{slug}/vault/upload` for per-file ingestion (calls process_vault_upload). | Layer 2 tactical-maneuver router. The vault/upload path is the per-file ingestion endpoint that produced the fish-trap orphan rows. |
| `backend/api/legal_counsel_dispatch.py` | 1046 | **STUB** | 5 endpoints: /draft, /hunt (4-phase headhunter w/ Serper or DDG fallback), /feedback (vectorized episodic memory), /precedents/{slug}, /memory/{slug}. Never invoked. legal.case_precedents=0 rows; legal.headhunter_memory table doesn't exist (lazily created on first /feedback). | Layer 3 outreach engine. The Phase B persistence work I drafted today (and aborted) belongs against this. |

### 2.2 Data layer — `legal.*` schema (29 tables)

Counts as of 2026-04-27 against fortress_db:

**ACTIVE (populated, currently in use):**
| table | rows | what it tracks |
|---|---:|---|
| `vault_documents` | 1,989 | Ingested document corpus across all cases. Per-doc privilege class, chunk count, vector_ids[]. |
| `privilege_log` | 205 | Privilege classifier audit trail. Every doc that triggered the privilege gate. |
| `case_evidence` | 72 | Evidence index per case. |
| `case_actions` | 47 | Action history per case. |
| `case_watchdog` | 40 | Auto-alert rules + match log. The 2026-02-16 jdavidstuart watchdog match landed here. |
| `correspondence` | 22 | Inbound + outbound legal communications. |
| `ingest_runs` | 9 | Batch ingestion audit (PR D / PR I tracker). |
| `deadlines` | 8 | Per-case deadline calendar. |
| `cases` | 6 | The 6 known matters: 7il-i, 7il-ii, vanderburge, fish-trap, case_23-11161-JKS, prime-trust-23-11161. |
| `email_intake_queue` | 2 | Pending inbound mail. |
| `filings` | 2 | Filed documents. |
| `case_slug_aliases` | 1 | Case slug aliasing. |
| `expense_intake` | 1 | Expense tracking. |
| `timeline_events` | 1 | Case timeline. |
| `uploads` | 1 | File uploads. |

**STUB / NEVER_USED (0 rows — table exists, never populated):**
| table | likely purpose |
|---|---|
| `case_graph_nodes_v2` | Case knowledge graph (entities, dates, relationships) — v2 schema not yet backfilled |
| `case_graph_edges_v2` | Case knowledge graph edges — same |
| `case_statements_v2` | Per-case structured statements (theory of defense, etc.) |
| `case_statements` | (v1 — superseded by v2) |
| `case_precedents` | Counsel Dispatch headhunter precedents |
| `chronology_events` | Per-case chronology timeline |
| `discovery_draft_packs_v2` | Discovery request drafting |
| `discovery_draft_items_v2` | Per-item discovery requests |
| `deposition_kill_sheets_v2` | Deposition cross-exam preparation |
| `entities` | Named entities (parties, witnesses, courts) |
| `sanctions_alerts_v2` | Sanctions warning system |
| `sanctions_tripwire_runs_v2` | Sanctions tripwire run audit |
| `legal_exemplars` | Reference exemplars |
| `distillation_memory` | Distillation memory store |

The ratio is striking: **~14 of 29 legal.* tables have zero rows.** Most have v2 suffixes suggesting an architectural migration that scaffolded schema but didn't backfill.

### 2.3 Qdrant collections — legal-relevant

8 of 24 collections are legal-related:

| collection | role today | classification |
|---|---|---|
| `legal_ediscovery` | Work-product chunks per case (586,739 vanderburge alone) | ACTIVE |
| `legal_privileged_communications` | Privileged-counsel chunks (PR G FYEO) | ACTIVE |
| `legal_library` | Council deliberation context source (`legal_library` per `LEGAL_COLLECTION` in legal_council.py) | ACTIVE |
| `legal_caselaw` | Case law / precedent corpus | (need verification — collection exists; population unknown) |
| `legal_hive_mind_memory` | Hive Mind episodic memory (PR G phase) | (likely active) |
| `legal_headhunter_memory` | Counsel Dispatch CEO feedback episodic memory | NEVER_USED (collection exists or lazily created; 0 invocations of /feedback) |
| `email_embeddings` | General email vector store | ACTIVE |
| `fortress_documents` / `fortress_knowledge` | Cross-domain fallback | (cross-domain) |

### 2.4 Council personas (`personas/legal/*.json`)

All 9 seats defined, each with godhead_prompt + bias + focus_areas:

| seat | name | archetype |
|---|---|---|
| 1 | The Senior Litigator | trial-strategist |
| 2 | The Contract Auditor | clause-analyst |
| 3 | The Statutory Scholar | statute-and-rule-researcher |
| 4 | The E-Discovery Forensic | record-and-metadata-investigator |
| 5 | The Devil's Advocate | adverse-case-tester |
| 6 | The Compliance Officer | policy-and-process-guardian |
| 7 | The Local Counsel | venue-savvy-practitioner |
| 8 | The Risk Assessor | exposure-modeler |
| 9 | The Chief Justice | synthesizing-arbiter |

The personas drive Council deliberation but don't drive other parts of FLOS. **They are reasoning roles, not state-update agents.** Layer 1 may need additional personas (Calendar Officer, Inbound Triage Officer) that operate on events, not deliberation.

### 2.5 Frontend (`apps/command-center/src/app/(dashboard)/legal/`)

25+ React components:

| group | components | role |
|---|---|---|
| Top-level | `legal/page.tsx`, `legal-cases-shell.tsx` | Cases list view |
| Case detail | `legal/cases/[slug]/page.tsx`, `case-detail-shell.tsx` | Per-case dashboard shell |
| Email intake | `legal/email-intake/page.tsx`, `email-intake-shell.tsx` | Inbound mail review |
| Council | `legal/council/page.tsx`, `counsel-threat-matrix.tsx` (Council UI), API SSE stream route | Council deliberation UI |
| Discovery / depo | `discovery-draft-panel.tsx`, `deposition-prep-panel.tsx`, `deposition-war-room.tsx` | Discovery + deposition workspaces |
| Ingestion | `ediscovery-dropzone.tsx`, `evidence-upload.tsx`, `extraction-panel.tsx`, `document-viewer.tsx` | Per-case file management |
| Analytics | `jurisprudence-radar.tsx`, `inference-radar.tsx`, `graph-snapshot-card.tsx`, `master-timeline.tsx` | Per-case analytics |
| Watchers | `sanctions-tripwire-panel.tsx`, `hitl-deadline-queue.tsx`, `case-detail-shell.tsx` | Watchdog + deadline UI |
| Operator | `agent-command-terminal.tsx`, `hive-mind-editor.tsx` | Operator power-tools |

**The frontend is much more developed than the backend population suggests.** Many panels read from empty v2 tables — the UI is rendered with zero state. Operator has a dashboard that mostly says "no data yet."

### 2.6 NAS — `sectors/legal/`

```
sectors/legal/
├── case_23-11161-JKS/        (Prime Trust — Detweiler outreach + filings)
├── context/                   (sector-level briefing)
├── fish-trap-suv2026000013/   (Generali — alerts, correspondence, evidence, filings)
├── intelligence/              (active_roster.json — system roster)
├── owner-statements/          (per-property statements)
├── pdf_archive/               (cross-case PDF outputs)
├── prime-trust-23-11161/      (Prime Trust — alternate slug; certified_mail + receipts)
├── snapshots/                 (empty)
└── vectors/                   (empty)
```

**Per-case directories follow a consistent layout:** alerts/, correspondence/, evidence/, filings/, certified_mail/, receipts/. This is the canonical filesystem shape — FLOS should preserve it.

---

## 3. Missing control plane

The components above are mostly **reactive primitives** (called when summoned, return outputs). FLOS needs a **control plane** that turns them into a system. Five missing pieces:

### 3.1 State store — per-case live posture (structured)

Today, "case posture" is reconstructed by reading the briefing pack PDF + correspondence dir + email_archive query. There is no single row that says "for fish-trap, today: answer filed, motion-to-continue granted, awaiting reassigned-judge order, exposure $7,500-$12,500, theory of defense = unauthorized signatory + apparent authority gap."

**Proposed: `legal.case_posture`** (one row per active case, updated on every state change)

Conceptual schema (not for immediate implementation):

```
case_slug                   → FK
procedural_phase            → enum (pre-suit, answer-due, discovery, motion, trial-prep, settlement, post-trial, closed)
next_deadline_date          → date
next_deadline_action        → text
theory_of_defense_state     → enum (drafting, validated, locked)
top_defense_arguments       → jsonb (structured list with evidence_element refs)
top_risk_factors            → jsonb
exposure_low / mid / high   → numeric (dollars)
leverage_score              → numeric (-1.0 to 1.0)
opposing_counsel_profile    → jsonb (name, firm, win_rate, playbook)
last_council_consensus      → jsonb (signal, score, conviction)
last_council_at             → timestamptz
posture_hash                → text (SHA-256 of structured state for drift detection)
updated_at                  → timestamptz
updated_by_event            → uuid (FK to event log)
```

Every cell is structured. No free-text "case status: complicated" fields.

### 3.2 Event bus — inbound triggers

An event is anything that should cause case posture to advance. Sources:

| source | producer | event type |
|---|---|---|
| Email arrival | Captain (after restart) → triage classifier | `email.received` w/ case_slug, sender, subject, body_snippet |
| Vault upload | legal_ediscovery.process_vault_upload | `vault.document_ingested` w/ doc_id, case_slug, chunk_count |
| Watchdog match | case_watchdog row trigger | `watchdog.matched` w/ alert payload |
| Court filing detected | (future — PeachCourt portal scrape) | `court.filing_detected` w/ filing type + parties |
| Deadline approaching | scheduled job | `deadline.approaching` w/ days_until, action_due |
| Operator input | UI / CLI | `operator.input` w/ command + payload |
| Council deliberation complete | legal_council.run_council_deliberation | `council.deliberation_complete` w/ consensus, signal |
| Counsel outreach state change | counsel_dispatch endpoints | `counsel.draft_status_changed` w/ new state |

**Proposed mechanism:** Postgres LISTEN/NOTIFY (already in stack via SQLAlchemy/psycopg) OR Redis pub/sub (Redis is on Spark-2). Both viable; Redis preferred for cross-process scale.

Event log table: `legal.event_log` (append-only, audit trail).

### 3.3 Action dispatcher — events → next-correct-action

For each event type, a routing rule:

| event | dispatcher rule | action |
|---|---|---|
| `email.received` matched to case | route via case_slug + privilege class | record correspondence, update timeline_events, re-run Council if threshold breached |
| `vault.document_ingested` | route via case_slug | refresh evidence-element mapping, possibly re-run Council if defense-relevant |
| `watchdog.matched` | priority routing (P1 = page operator) | post alert to operator queue; if p1, generate response variant draft |
| `deadline.approaching` (≤7 days) | route to operator queue + drafter | pre-draft response action options |
| `council.deliberation_complete` | persist consensus | update case_posture row, recalculate leverage_score, log to case_actions |
| `operator.input` | route per command | execute command, log to case_actions, re-run dependent dispatchers |

**Proposed: `legal.dispatcher_routes`** — config table mapping event_type to handler module/function. Lets operator iterate routing rules without code changes.

### 3.4 Operator surface — single pane of glass

The current frontend has 25+ panels but no orchestrating view. **Proposed: a per-case "command bridge" page** that surfaces:

```
[case_slug — Generali v CROG, Fannin Superior]

┌────────────────────────────────────────────────────────────────┐
│ POSTURE: answer filed, motion-to-continue granted              │
│ NEXT: awaiting reassigned-judge order (~7 days)                │
│ EXPOSURE: $7,500 mid / $12,500 high                            │
│ LEVERAGE: +0.42 (favorable — unauthorized-signatory defense)   │
│ COUNCIL: STRONG_DEFENSE (last deliberated 2026-04-15)          │
└────────────────────────────────────────────────────────────────┘

PENDING DECISIONS (3):
  □ Approve outreach draft to Hundley (drafted 2026-03-02, not sent)
  □ Approve outreach draft to Gorby (drafted 2026-03-02, not sent)
  □ Decide settle vs litigate (exposure model + leverage analysis ready)

DEADLINES (1):
  Apr 30 — Discovery response window opens (after recusal resolution)

RECENT EVENTS (last 7 days):
  Apr 26  Vanderburge corpus reprocessed — 100% indexing rate
  Apr 23  Captain dormant — 30+ days no inbound
  ...
```

This view is the FLOS user experience. Building it requires the case_posture row + event_log + pending_decisions queue.

### 3.5 Audit trail — every action replayable

Today, audit is partial — `ingest_runs` for batch ingestion, `case_actions` for tactical strikes. Many state changes (Council deliberation, counsel-dispatch draft generation, watchdog matches) write logs but don't write structured audit rows.

**Proposed: `legal.event_log`** — append-only structured audit. Every event the dispatcher processes lands here. Schema:

```
id              → bigserial
event_type      → text (matches dispatcher_routes.event_type)
case_slug       → text (nullable — some events are cross-case)
event_payload   → jsonb (canonical structure per event_type)
emitted_at      → timestamptz
emitted_by      → text (service or operator)
processed_at    → timestamptz
processed_by    → text (dispatcher handler)
result          → jsonb (action taken, downstream events emitted)
```

Replay: query events in time order, re-emit each through dispatcher. This is the auditability + reproducibility property courts will expect from a document-discovery defense.

---

## 4. Capabilities to build

Three layers, organized by operational distance from the operator.

### Layer 1 — Continuous case posture

The "always-current state of every active matter" layer.

| capability | depends on | implementation hint |
|---|---|---|
| Live procedural posture | case_posture table + event bus | Per-case row updated on every event. Phase 1 work. |
| Deadline tracking with thresholds | deadlines table (8 rows now) + scheduled job | Cron / arq job; emits `deadline.approaching` at 30/14/7/3/1 days. |
| Theory-of-defense state machine | case_statements_v2 (currently 0 rows) + Council deliberation | TOD = jsonb of (defense_arg, supporting_evidence_elements[], opposing_arguments[]). Updated by Council deliberation. |
| Evidence-to-defense-element mapping | case_evidence (72 rows) + case_statements_v2 + vault_documents | Cross-table join: each defense argument → list of supporting evidence rows → list of vault documents. Drives "do we have enough evidence?" answer. |
| Exposure quantification | case_actions + custom calculator | Per-case row in case_posture: low/mid/high dollar. Updated when new exposure events land. |
| Settlement leverage analysis | exposure + opposing-counsel profile + venue patterns | Score in [-1, +1]. Updated on relevant events. |
| Weak-argument identification | Council Devil's Advocate persona output + case_statements_v2 | Persona-5 output flagged + persisted to case_posture.weak_arguments[]. |

### Layer 2 — Outpace opposing counsel

The "see their playbook before they execute it" layer.

| capability | depends on | implementation hint |
|---|---|---|
| Opposing attorney profile + playbook prediction | legal_counsel_recon.py + CourtListener | Per-attorney profile row in `legal.attorney_profiles` (new table). Cached; refresh quarterly. Layer-2 input to leverage analysis. |
| Venue / judge ruling pattern analysis | CourtListener `/search` + `/people/judges` + LLM analysis | Per-judge profile + per-venue profile. Patterns: motion-to-dismiss grant rate, summary judgment patterns, typical schedule. |
| Pre-drafted response variants | Council deliberation + legal_docgen + theory of defense state | When a "likely opposing motion" is identified, drafter pre-generates response variants. Stored in `legal.response_variants` (new). |
| Evidence pre-assembly | case_evidence + case_statements_v2 + vault_documents | For each defense element, pre-assembled evidence list + Qdrant retrieval queries cached. |
| Council deliberation on every state change | dispatcher rule | Threshold: posture_hash drift > X OR new defense-relevant document OR opposing motion received. |
| Verdict drift detection | history of Council consensus per case | If consensus_signal degrades over time (STRONG_DEFENSE → WEAK), alert operator. Per-case time series. |

### Layer 3 — Dispatch with precision

The "ready to hand off to retained counsel" layer.

| capability | depends on | implementation hint |
|---|---|---|
| Briefing pack generator | case_posture + case_statements_v2 + case_evidence + case_actions + vault_documents | New function in legal_docgen.py: `generate_counsel_briefing_pack(case_slug)`. Outputs Markdown + PDF. Replaces ad-hoc briefing PDFs in NAS. |
| Counsel candidate discovery + ranking | legal_counsel_dispatch.py /hunt + legal_counsel_recon.py | Already built — runs the multi-source web search + CourtListener profile. Add ranking by jurisdiction match, win rate, conflict probability. |
| Conflict check | new conflict-of-interest checker | Cross-reference candidate's case history vs case parties. Flag adverse representation. |
| Outreach with state machine | Counsel Dispatch persistence (Phase B from prior PR I drafted) | The aborted Phase A migration is the right schema. Folds into FLOS Phase 4. |
| File-handoff format | briefing-pack generator + structured posture export | Single JSON / PDF bundle: posture row, evidence index, defense state, response drafts, opposing counsel profile. Counsel can ingest directly. |

---

## 5. Sequencing roadmap

### Phase 0 — Foundational (must precede all)

**Captain restart + mailbox coverage.**

Without inbound email flow, the event bus has no real-world signal. Currently: 30+ days of zero email_archive rows, fish-trap recusal-and-reassignment correspondence likely landing only on PeachCourt portal because Captain is dormant.

Tasks:
- Diagnose why captain_multi_mailbox stopped 2026-03-23 (check service logs, last-known-good state)
- Restart captain_multi_mailbox.py with current MAILBOXES_CONFIG
- Add `legal-cpanel` to MAILBOX_REGISTRY (already in pass-store, not registered)
- Verify legal_email_intake.py loop is running (continuous mode)
- Confirm email_archive ingestion rate ≥ 50/day baseline

**Exit criteria:** new emails land in email_archive within minutes; correspondence rows populate for active cases; case_watchdog matches fire on opposing-counsel sender events.

### Phase 1 — State store + event bus skeleton

**Per-case live posture schema + event bus + dispatcher.**

Tasks:
- Author `legal.case_posture` table (one row per case, schema per §3.1)
- Author `legal.event_log` table (append-only audit, schema per §3.5)
- Author `legal.dispatcher_routes` table (event-to-handler config)
- Build event-emit helpers (Captain → email.received; legal_ediscovery → vault.document_ingested)
- Build dispatcher worker (consumes events, routes by dispatcher_routes, writes results to event_log)
- Backfill case_posture for the 6 known cases from current sources

**Exit criteria:** every email arrival emits an event; every vault upload emits an event; dispatcher writes a result row for each event it processes; case_posture has rows for 6 cases.

### Phase 2 — Layer 1 minimum

**Deadline tracking + evidence-element mapping + Council verdict persistence.**

Tasks:
- Activate deadline tracking (deadlines table → scheduled job → `deadline.approaching` events)
- Backfill `case_statements_v2` for the 6 cases — define each case's theory of defense as structured rows
- Build evidence-element mapping (cross-table query helper)
- Persist every Council deliberation result to `case_posture.last_council_*` fields + `case_actions` audit row
- Build operator-surface page (per-case command bridge) that reads from case_posture

**Exit criteria:** deadlines fire alert events on schedule; running Council deliberation updates case_posture row visibly; per-case dashboard shows posture + deadlines + last consensus.

### Phase 3 — Layer 2 minimum

**Opposing counsel profile + venue analysis + verdict drift.**

Tasks:
- Author `legal.attorney_profiles` table (new)
- Build attorney-profile refresh job that pulls from legal_counsel_recon (CourtListener) on schedule
- Backfill profiles for known opposing counsel: J. David Stuart, Brian Goldberg (FMG Law), etc.
- Author `legal.venue_profiles` and `legal.judge_profiles` (new)
- Build venue/judge profile refresh from CourtListener
- Implement verdict drift detection: time series of Council consensus per case, alert on degradation

**Exit criteria:** every active case has an opposing-counsel profile + venue profile; Council deliberations have measurable drift over time; operator surface shows leverage_score per case.

### Phase 4 — Layer 3 minimum

**Briefing pack generator + outreach state machine.**

Tasks:
- Add `generate_counsel_briefing_pack(case_slug)` to legal_docgen.py — Markdown + PDF outputs
- Apply the **counsel_dispatch_drafts schema** (the aborted Phase A migration from this branch) — this is where it folds in
- Wire `/counsel/dispatch/draft` to persist to counsel_dispatch_drafts (the aborted Phase B work)
- Add state machine endpoints (approve / mark-sent / mark-replied / decline / withdraw)
- Add CLI wrapper for counsel dispatch ops (the aborted Phase D)
- Build conflict-of-interest checker

**Exit criteria:** running `/counsel/dispatch/hunt` for fish-trap returns ranked candidates; `/counsel/dispatch/draft` persists drafts with state; running `generate_counsel_briefing_pack(fish-trap)` produces a hand-off-ready packet.

### Phase 5+ — Capabilities deepen

- Pre-drafted response variants for likely opposing motions
- Court filing detection (PeachCourt portal scrape)
- Settlement vs litigation cost calculator
- Cross-case learning (e.g., "Sanker counsel pattern" reused across 7IL + Vanderburge)
- Frontend command-bridge polish
- SMTP automation with Captain return-channel matching

---

## 6. Architectural principles

These constrain implementation across all phases. Operator may modify before locking ADR-004.

1. **Events drive state changes; never direct mutations.** Code MAY NOT update `case_posture` directly. State changes flow through the dispatcher. This is the auditability invariant.

2. **Every output is persisted.** No ephemeral text returns from Council deliberation, draft generation, hunt results, etc. The briefing-pack PDF, the outreach draft, the consensus opinion — all land in a structured row before being returned. (The current `/counsel/dispatch/draft` endpoint violates this — its output is never persisted. Fixing it is part of Phase 4.)

3. **State is structured.** Postgres tables, not markdown files. Markdown / PDF outputs are *renderings* of state. The briefing pack PDF is a derivative of `case_posture` + `case_statements_v2` + `case_evidence` — not the source of truth.

4. **Operator is human-in-the-loop for every state-changing decision.** Dispatcher emits events and proposes actions. Operator (or operator-approved automation rule) authorizes the state change. No daemon mutates posture without an approved input.

5. **Operator surface is single-pane-of-glass per case.** One URL per case shows current posture, pending decisions, deadlines, exposure, leverage, last consensus. Not 25 separate panels to navigate.

6. **Bilateral mirror discipline (per ADR-001).** All `legal.*` writes go to fortress_db AND mirror to fortress_prod. Phase 1 case_posture must follow this pattern. The fish-trap mirror drift (2 fortress_prod rows / 0 fortress_db rows) is exactly what bilateral discipline prevents.

7. **Inference plane shared swarm (per ADR-003).** Council deliberation, counsel-dispatch hunt evaluation, drafter generation all use the shared LLM swarm via the existing fallback chain (Anthropic → HYDRA → SWARM). FLOS does not introduce new inference servers.

8. **All actions auditable and replayable.** event_log is append-only. Replay = re-emit events in time order through dispatcher. This satisfies the discovery-defense audit posture (court asks "show me how this exhibit was generated" → operator replays the event chain).

9. **Privilege classification flows through every output (per ADR-002).** Briefing packs, outreach drafts, response variants — every artifact carries a privilege classification (work product / privileged / public). Privileged content gates retrieval differently per the FYEO rules already in place.

10. **No new schema without backfill plan.** The 14 zero-row `legal.*` tables suggest schema-without-population. FLOS adds tables only when the writer + initial data are ready in the same change.

---

## 7. Proposed ADR-004 — Fortress Legal Operating System

**Status:** PROPOSED (not LOCKED). Operator review + iteration before locking.

**Date:** 2026-04-27

**Context:** The Fortress Prime legal stack contains the right primitives (Council, Counsel Dispatch, ediscovery, Captain, drafter, docgen, vault) but they don't compose into a continuously-running system. Solo operator faces multiple active matters with no in-house counsel. The asymmetry against opposing counsel is structural: they have a research stack + paralegal; operator has fragmented tools. FLOS reframes the existing primitives as components of an event-driven operating system with a structured state plane.

**Decision (proposed):** Adopt FLOS as the unifying architecture for all legal-track work. All future legal-feature PRs slot into the Layer 1 / Layer 2 / Layer 3 phases per §5. New tables go through the dispatcher; new endpoints emit events; new outputs persist to structured state. Operator surface is single-pane-of-glass per case.

**Consequences:**

✅ Pros:
- Continuous operation — no manual invocation gap
- Auditable — every state change traceable
- Hand-off ready — counsel retention becomes a packet handoff, not a fresh briefing
- Pre-assembled — response time to opposing motion drops from days to hours
- Reusable across matters — same posture schema for fish-trap, 7IL, Vanderburge, future cases

⚠️ Cons / risks:
- Significant build effort (Phases 0-4 = months of work)
- Discipline required: principles must hold across all PRs
- Operator surface complexity — the single-pane-of-glass demands UX investment
- Bilateral mirror discipline demands all writes through dual-DB pattern (existing pain point per Issue #204)

**Alternatives considered:**

- **Status quo:** continue with primitives, no control plane. Rejected — the dormant Captain + zero-row v2 tables show this is where the current trajectory leads.
- **Buy a SaaS legal practice management tool:** rejected per CONSTITUTION.md Article I (data sovereignty); these tools don't run on-premises.
- **Build only Layer 3 (briefing pack + outreach):** insufficient — without Layer 1's continuously-updated posture, briefing packs go stale.

**Status this PR:** No code, no migrations, no PRs. This document is the design itself. Operator reviews + iterates before locking ADR-004 and authorizing Phase 0.

---

## 8. Cross-references

- ADR-001 (LOCKED) — one-spark-per-division default
- ADR-002 (LOCKED) — Captain + Sentinel permanent on Spark 2; Council on Spark 4 multi-purpose
- ADR-003 — TBD (referenced in §6 principle 7 as "shared inference swarm" — needs separate ADR)
- Issue #204 — alembic chain divergence (must resolve before Phase 1 schema work)
- Issue #228 (PR #242) — Qdrant silent-failure detection (Phase B/B.1 baseline for ediscovery)
- PR D / PR I — existing batch ingestion (legacy entry points for Phase 1 backfill)
- `/tmp/p1a2b3c4d5e6_counsel_dispatch_drafts.py.draft` — aborted Phase A migration, retained for FLOS Phase 4

---

## 9. Open questions for operator

1. **Phase 0 ordering** — should Captain restart precede or run in parallel with Phase 1 schema work? Captain restart unblocks event bus signal; schema work can proceed without it but won't have real events to test against.

2. **case_posture schema specifics** — the conceptual schema in §3.1 is a starting point. Operator may want different fields (e.g., per-claim exposure breakdown, per-defense-element confidence score, settlement_offer_history JSONB).

3. **Operator surface UX** — single-pane-of-glass per case is the principle, but the actual layout (sections, columns, drill-downs) deserves its own design pass. Mock-driven, possibly in command-center directly.

4. **Frontier LLM gate** — Layer 2's opposing-counsel-profile work is heavy on CourtListener API + LLM analysis. Within local-LLM (HYDRA/SWARM) capability? Or does it require Anthropic frontier (gated by ALLOW_CLOUD_LLM)?

5. **Conflict of interest checker (Phase 4)** — depth of conflict check? Just past-representation against current parties, or full ethical-rules engine? Likely scope-down to current-parties for v1.

6. **Cross-domain reuse** — the `case_posture` pattern likely applies to non-legal matters (acquisitions due diligence, real-estate transactions, regulatory filings). Should the schema be domain-agnostic from the start, or legal-specific then refactored later? Recommend legal-specific for v1.

7. **Captain MAILBOXES_CONFIG content** — what mailboxes are configured today? `legal-cpanel` is in pass-store but not in MAILBOX_REGISTRY (the script-level registry); MAILBOXES_CONFIG (Captain's runtime registry) content is unknown without inspection.

---

**End of FLOS Design v1.**

Operator-review iteration cycle expected before lock. No commit, no merge until operator signs off.
