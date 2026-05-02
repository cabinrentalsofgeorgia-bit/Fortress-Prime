# FORTRESS LEGAL CONSTITUTION

**Operator:** Gary Mitchell Knight ("Godhead")
**Status:** v1 — anchor doc, supersedes session-by-session memory
**Established:** 2026-05-02
**Cadence:** Updated only on architectural change (new ADR, mission shift, scope expansion)
**Hierarchy:** Subordinate to `CONSTITUTION.md` (sovereign doctrine) and `005-nemoclaw-swarm-architecture.md` (NemoClaw contract); supersedes `MASTER-PLAN*.md` on questions of mission and scope.

---

## 0. What this document is

This is the durable mission contract for Fortress Legal as a sovereign legal-AI **platform**, not a case-specific tool. Every assistant working on Fortress-Prime reads this **first** and treats it as authoritative. Every chat session opens with: "Read FORTRESS-LEGAL-CONSTITUTION.md and MASTER-PLAN.md."

Master plans describe what's happening this week. ADRs describe locked architectural decisions. **This describes what Fortress Legal is, what it's for, and what it must remain.**

When this document conflicts with anything other than the parent CONSTITUTION.md and 005-nemoclaw-swarm-architecture.md, this wins.

---

## 1. Mission

Build a sovereign legal-AI platform that out-prepares a top-3 white-shoe firm on any matter the operator chooses to feed it — federal, state, or local; civil or otherwise — running entirely on operator hardware.

Two interlocking goals, equal priority:

**Goal A — Win the live cases.** Out-prepare opposing counsel on `7il-v-knight-ndga-ii` (the active case) and on every subsequent matter the operator carries. Every section of every brief grounded in evidence on the cluster. No cloud-API touches privileged content.

**Goal B — Build the reusable platform.** Every component built for Goal A must be **case-agnostic, parameterized by `case_slug`, and tested against closed cases as regression**. The platform that wins Case II must drop in `vanderburge-v-knight-fannin`, `fish-trap-suv2026000013`, `prime-trust-23-11161`, or any future matter and run end-to-end without redesign.

These goals are not in tension. The architecture that produces white-shoe-grade output for one case is the same architecture that produces it for the next. Goal A is the proof; Goal B is the durable asset.

---

## 2. The customer hierarchy

| Tier | Customer | Status |
|---|---|---|
| 0 | Operator (Gary Knight) | Primary; every architectural decision serves this tier |
| 1 | Operator's active legal matters | `7il-v-knight-ndga-ii` (active, counsel-search), `fish-trap-suv2026000013` (Generali), `prime-trust-23-11161` |
| 2 | Operator's closed matters as regression dataset | `7il-v-knight-ndga-i` (judgment against — known outcome), `vanderburge-v-knight-fannin` (settled — known outcome) |
| 3 | Future matters operator chooses to onboard | Federal / state / local; civil / real property / financial / other |
| 4 | Eventual external customers (post-counsel-hire, post-product-validation) | Single operators, small firms, sophisticated pro se litigants |

Tier 0 → Tier 4 is the long arc. Tier 1 is the current focus. Tier 4 is not a P0 today and never preempts Tier 1.

---

## 3. The case-agnostic contract

Every component touching legal data **MUST** be parameterized by `case_slug` and **MUST NOT** hardcode any case-specific assumption. This is the platform contract.

### 3.1 Locked schema surfaces

Already in production, must remain:

- `legal.cases` keyed on `case_slug` — `docket`, `court`, `judge`, `case_phase`, `privileged_counsel_domains` JSONB, `related_matters` JSONB, `nas_layout` JSONB
- `legal.vault_documents` — UNIQUE `(case_slug, file_hash)`; every case has its own vault slice
- `legal.case_slug_aliases` — backward-compat after slug renames
- `legal.privilege_log` — immutable audit trail per privilege classification
- `legal.ingest_runs` — script-invocation audit trail
- `legal.email_case_links` (planned, B2) — many-to-many; cross-case email surfacing
- Qdrant `legal_ediscovery` / `legal_privileged_communications` — `case_slug` in payload; retrieval filtered per case

### 3.2 Locked code surfaces

- `process_vault_upload(case_slug, ...)` — single canonical ingest entry
- `freeze_context(case_brief, top_k, case_slug)` — Council retrieval
- `freeze_privileged_context(case_brief, top_k, case_slug)` — privileged-track retrieval (PR G)
- `_resolve_related_matters_slugs(case_slug)` — one-hop cross-matter expansion
- `phase_b_v01 --case-slug <slug>` — briefing orchestrator
- `legal_vault_ingest.py --case-slug <slug>` — vault ingestion
- `email_backfill_legal.py --case-slug <slug>` — case-aware IMAP backfill
- `track_a_case_i_runner.py --case-slug <slug>` — Track A runner (despite name, slug-parameterized)

### 3.3 Locked NAS layout

- `/mnt/fortress_nas/legal_vault/<case_slug>/` — vault NFS copies
- `/mnt/fortress_nas/Corporate_Legal/Business_Legal/<case_slug>/` — case files (Pleadings/Discovery/Correspondence/Depositions per `nas_layout` JSONB)
- `/mnt/fortress_nas/intel/judges/<court>/<judge-slug>.md` — judge intel files (one per judge, drops into any case)
- `/mnt/fortress_nas/intel/firms/<firm-slug>.md` — firm intel
- `/mnt/fortress_nas/intel/attorneys/<attorney-slug>.md` — attorney intel
- `/mnt/fortress_nas/audits/` — every script invocation manifest
- `/mnt/fortress_nas/models/` — NAS-canonical model storage

### 3.4 Forbidden patterns

- Hardcoding `7il-v-knight-ndga-i` or `7il-v-knight-ndga-ii` in any code path that should accept a slug
- Case-specific column on a shared table when JSONB or a join table would generalize
- Single-case prompt templates when the same template parameterized by case metadata works
- Building Case II features that won't run on `vanderburge-v-knight-fannin` without redesign
- Building Case I regression scaffolding that won't run on closed cases generically

If a feature can only be tested against one case, it isn't a platform feature. File it as an issue and design the case-agnostic version before merging.

---

## 4. The regression discipline

**Closed cases are the regression bench. Active cases are production.**

| Case | Role | Known outcome |
|---|---|---|
| `7il-v-knight-ndga-i` | Regression — federal civil | `closed_judgment_against`; specific performance granted under severability clause; contempt motion denied (finding for operator) |
| `vanderburge-v-knight-fannin` | Regression — state civil | `closed_settled` |
| `7il-v-knight-ndga-ii` | Production — federal civil active | counsel_search, no answer filed yet |
| `fish-trap-suv2026000013` | Production — Generali | active, 2 vault docs (test corpus) |
| `prime-trust-23-11161` | Production — Prime Trust | active |

### 4.1 Regression contract

Every Phase B / Council / retrieval / classifier change passes through Case I before being applied to active cases. The validated Case I baseline is:

- **Brief artifact:** `Attorney_Briefing_Package_7IL_NDGA_I_v3_20260430T224403Z.md` (40,170 bytes)
- **Per-section metrics:** `track-a-v3-case-i-full-rerun-2026-04-30.md` (590s total wall, 10/10 finish=stop, format_compliant=true, zero first-person bleed, zero `<think>` leakage, citation counts per section)
- **Routing baseline:** PR #332 per-section reasoning policy table

A change "passes Case I" when:
1. Re-running Phase B v0.1 on `7il-v-knight-ndga-i` produces 10/10 sections finish=stop
2. Per-section content_chars within ±5% of v3 baseline (or measurably better with operator review)
3. Zero format-compliance regressions
4. Frontier endpoint stays healthy throughout the run
5. No soak halt events fire

A change that fails any of these is not applied to active cases.

### 4.2 Vanderburge as the second-jurisdiction regression bench

`vanderburge-v-knight-fannin` is Fannin County state court. When the platform handles state-court matters end-to-end, it must run end-to-end on Vanderburge as a state-court regression. This is deferred work — file as issue, do not block Case II — but it is the test that closes the multi-jurisdiction loop.

### 4.3 The fish-trap and prime-trust slots

These are real active matters. They are also the platform's test slots for non-NDGA cases. As the platform stabilizes through Case II, fish-trap and prime-trust prove the platform is not 7IL-specific.

---

## 5. The sovereign data boundary (non-negotiable)

Inherits from `CONSTITUTION.md` and `005-nemoclaw-swarm-architecture.md`. Restated here because legal data has the highest sensitivity tier in the cluster.

- **Privileged data never leaves the cluster.** No cloud LLM (Anthropic / OpenAI / Google) touches privileged content. Ever. ARCHITECT (Gemini) is for planning only and never receives PII or evidence.
- **Frontier consensus is masking-required.** External evaluator tiers receive only masked, derived, minimum-necessary artifacts. Raw vault content does not flow outbound.
- **NAS-canonical for heavy artifacts.** Vault NFS copies, model weights, audits, intel files. Spark nodes treat NAS as ground truth.
- **Privilege track is physically separate.** `legal_privileged_communications` collection is not the same Qdrant collection as `legal_ediscovery`. A misconfigured filter on work-product cannot leak privileged chunks.
- **FYEO warnings are byte-stable.** `FOR_YOUR_EYES_ONLY_WARNING` is a fixed-text constant. Never paraphrased. Court filings would expose drift.
- **Privilege classifier in the ingest path.** Qwen2.5 confidence ≥ 0.7 + `is_privileged=true` → `processing_status='locked_privileged'`. Decisions logged immutably to `legal.privilege_log`.
- **Domain separation.** `cabin-rentals-of-georgia.com` (public storefront) and `crog-ai.com` (staff/agent glass) never cross. Legal surfaces only on `crog-ai.com`.

If a proposed feature breaks any of these, it is rejected before architecture review.

---

## 6. The platform layers (Iron Dome view)

| Layer | Owner | Purpose | Status |
|---|---|---|---|
| **Iron** — sovereign hardware | Cluster (sparks 1–6, NAS, ConnectX 100Gbps) | All compute on operator hardware | Production |
| **Inference** — model serving tier | spark-3+4 TP=2 frontier (Super-120B), spark-5 BRAIN, spark-2 SWARM, TITAN TBD | SWARM → BRAIN → TITAN → ARCHITECT (cloud, planning-only) tiering | Production with active soak |
| **Retrieval** — embed + rerank + qdrant | spark-3:8102 EMBED, spark-5:8103 BGE rerank, spark-2 Qdrant `legal_ediscovery_active` (2048-dim) | Case-scoped retrieval over vault + caselaw | Production post-Wave-3.5 |
| **Council** — deliberation engine | spark-2 multi-persona panel, privilege-aware, related_matters expansion | Case deliberation with FYEO warnings | Production |
| **Captain** — email intake | spark-2 IMAP daemon, classifier-routed | All inbound legal email goes through Captain | Production |
| **Sentinel** — NAS walker | spark-2 (does NOT own legal vault content) | NAS document indexing for non-legal divisions | Production |
| **Phase B orchestrator** — briefing pipeline | spark-2; entry `phase_b_v01 --case-slug` | Produces 10-section attorney briefing packages | Production v0.1 (Track A v3 validated) |
| **Intel layer** — judge/firm/attorney/party intel | NAS `intel/`; resolver `fortress.legal.intel_resolver` | Drops `{{ judge:slug }}` etc. into §9 prompt augmentation | Manual seed (Story); CourtListener automation Q3 |
| **Predictive seat** — Lex-Machina-style moat | Postgres `fortress_intel`, feature stores, new Council seat | Judge/counsel/party behavior models + comparable-case retrieval | Q3 2026, post-counsel-hire |
| **Glass** — staff/agent UI | crog-ai.com (Next.js 16 standalone on spark-2:3005) | Council page, command center, deliberation streaming | Production |
| **FLOS** — Fortress Legal Operating System (dispatcher + workers) | spark-2 worker.py + ARQ + Redis | Async choreography per NemoClaw contract | Phase 0a in flight |

The frontier endpoint is the protected resource. Sustained `/health` non-200 >60s halts every workstream until it's recovered.

---

## 7. Permanent priority order

Inherited from `MASTER-PLAN.md §3` (canonical). Restated for self-contained reading:

| Priority | Track |
|---|---|
| **P0** | Anything blocking 7IL Case II counsel hire (active matter clock) |
| **P1** | Inference platform reliability (BRAIN / TITAN / RAG sovereign) |
| **P2** | Legal application capabilities (briefing, retrieval, deliberation, drafting) |
| **P3** | Audit + sovereignty + architectural debt + config + network debt |
| **P4** | Cross-division scaffolding (M3, financial, role parity, predictive seat scaffolding) |
| **P5** | Everything else (CROG-VRS features, Drupal SEO, Streamline reconciliation, etc.) |

**Tiebreak:** smaller scope wins.
**Promotion:** any P3+ item that becomes a Case II counsel-hire blocker is automatically promoted to P0.

The active-case clock dominates priority calls. Platform-generality work that doesn't slow Case II runs in parallel; platform-generality work that *would* slow Case II is deferred until counsel hire is closed.

---

## 8. The doc hierarchy

| Document | Role | Update cadence |
|---|---|---|
| `CONSTITUTION.md` (parent) | Sovereign doctrine across all of Fortress-Prime | On architectural change |
| `005-nemoclaw-swarm-architecture.md` | NemoClaw / swarm orchestration contract | On architectural change |
| **`FORTRESS-LEGAL-CONSTITUTION.md` (this doc)** | **Fortress Legal mission + platform contract** | **On architectural change** |
| `MASTER-PLAN.md` (canonical) | Fortress-Prime priority + case-clock + active-track inventory | On priority shift |
| `MASTER-PLAN-case-ii-2026-05-01.md` | 7-day window narrative for Case II counsel hire | EOD on each day of the window |
| `_architectural-decisions.md` | ADR ledger | On every locked decision |
| `docs/architecture/divisions/fortress-legal.md` | Division surface (cases, schemas, services, owners) | On schema or service change |
| `docs/architecture/shared/*.md` | Cross-cutting service docs | On service change |
| `docs/operational/*.md` | Per-task briefs Claude Code executes against | Per task |
| Per-case briefs (`Attorney_Briefing_Package_*`) | Case work product | Versioned per case |

When two master plans disagree (e.g., counsel-hire date), the MORE RECENT master plan wins, **but only on dated facts (clocks, milestones)**. On mission and scope, this constitution wins.

---

## 9. The mode-of-operation

### 9.1 Operator's three roles

1. Pasting status updates from Claude Code sessions on each spark
2. Decisions when forks appear — operator picks; assistant gives the reasoning
3. Operator-only work product (personal email sweeps, recollections, manual lookups, NIM weight pulls per Wave 3, signed engagement letters, the things that need a human)

### 9.2 Planning chat's three roles

1. Surface day's three priorities based on what's blocking, in flight, gating counsel-hire
2. Write briefs Claude Code executes autonomously
3. Refuse rabbit holes and call them out before operator commits time

### 9.3 Claude Code's role

Executes briefs autonomously per hard stops on the appropriate spark via tmux. Never self-merges. Never `--admin`, never `--force`, never force-push main. Single Claude Code session per host at a time. Always cuts branches from `origin/main`.

### 9.4 Discipline rules

- Action first, no preamble
- One recommendation when answer is clear, not A/B/C/D
- Short responses beat long ones
- Time budgets honored or called out
- "No rabbit holes" / "straight line" / "stay on mission" = cut ceremony, execute
- No commentary on effort, duration, or stamina
- No meta-observations about quality of work
- When operator needs a click, give the exact URL — no "go to settings, find this"
- Before assuming a doc doesn't exist, **search project knowledge first**

### 9.5 Anti-patterns to refuse

- Asking operator for "rough notes" when the information is on the cluster
- Greenfield building when migration-additive is correct
- A/B/C/D options when the answer is clear
- Re-explaining context already in this document or master plan
- Treating any P5 item as urgent
- Hardcoding case-specific assumptions in platform code (§3.4)
- Letting any privileged byte exit the cluster
- Web-UI multi-step workflows when Claude Code can execute

---

## 10. The reusable-product North Star

When `7il-v-knight-ndga-ii` is counsel-engaged and the brief is in firm hands, Fortress Legal does NOT pause. Q3 2026 build (already documented in `fortress-prime-deep-research-perfection-2026-05-01.md`) is the actual moat:

**Wave A — Data infrastructure (1–2 weeks post-counsel-hire):**
- `fortress_intel` Postgres database
- CourtListener bulk dataset ingestion (full federal dockets, opinions, judges, attorneys, parties)
- RECAP S3 embeddings sync (Qdrant `legal_caselaw_recap`, ~2TB)
- Daily ETL delta from CourtListener API

**Wave B — Feature stores (2–3 weeks):**
- Judge behavior model
- Counsel behavior model
- Party behavior model
- Entity resolution (Wilson Pruitt / Wilson Hamilton / Terry Wilson — explicit matcher)

**Wave C — Predictive Council seat (1–2 weeks):**
- New LiteLLM alias `legal-predictive`
- Council seat routing update
- Validation against Case I (closed, hindsight available)

**Wave D — Pre-emptive monitoring (ongoing):**
- @recap.email integration
- Docket alerts via CourtListener webhooks → Captain → Council
- Weekly judge/counsel behavior diff reports

**Wave E — Action layer (Q4 2026):**
- Motion-timing recommendations
- Deposition outlines targeted at known-vulnerable opposing-counsel patterns
- Settlement-position-shift alerts

This is what Lex Machina, Pre/Dicta, Trellis, Docket Alarm, and Pacer Legal sell to AmLaw 100 firms for $50K–200K/seat/year. Sovereign on cluster hardware. Free or near-free data sources. Legal under hiQ Labs v. LinkedIn. Already-running infrastructure does most of the work.

This is the platform North Star. **Don't pre-build it during the Case II clock; do build it the moment the clock closes.**

---

## 11. The single-sentence test

Any feature, brief, ADR, or PR proposed against Fortress Legal should pass this test:

> *"Does this make Fortress Legal better at out-preparing top-3 white-shoe firms on **any** matter the operator chooses to run through it, while keeping every privileged byte on operator hardware?"*

If the answer is "yes for Case II but breaks the platform for the next case," reshape it before merging.
If the answer is "yes for the platform but slows Case II counsel hire," defer it (file as issue).
If the answer is "no," reject it.

---

## 12. The first three priorities (today, 2026-05-02)

Per `saturday-runbook-2026-05-02.md`, in order:

1. **Qdrant reindex verify → atomic alias swap** (`legal_ediscovery_active` → `legal_ediscovery_v2` 2048-dim). Block B.
2. **§9 resolver smoke against Case I** (intel layer drops in via `{{ judge:richard-w-story }}` → operator-relevant context body). Block C.
3. **Wave 7 Phase B v0.1 kickoff on `7il-v-knight-ndga-ii`** → v1 brief. Operator review gate. Section regen → v2 by EOD.

These are P0 because they're on the active-case clock. Everything else waits.

---

## Amendment log

| Date | Version | Author | Changes |
|---|---|---|---|
| 2026-05-02 | v1 | Gary Knight (operator) + Claude (planning) | Initial constitution. Codifies platform mission, customer hierarchy, case-agnostic contract, regression discipline, sovereign data boundary, doc hierarchy, mode-of-operation, reusable-product North Star. |

---

End of constitution.
