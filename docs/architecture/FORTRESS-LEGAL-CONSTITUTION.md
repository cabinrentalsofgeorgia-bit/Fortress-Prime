# FORTRESS LEGAL CONSTITUTION

**Operator:** Gary Mitchell Knight ("Godhead")
**Status:** v2 — durable anchor; supersedes v1
**Established:** 2026-05-02
**Cadence:** Updated only on architectural change or intentional doctrinal amendment
**Hierarchy:** Subordinate to `CONSTITUTION.md` (sovereign doctrine) and `005-nemoclaw-swarm-architecture.md` (NemoClaw contract); supersedes `MASTER-PLAN*.md` on questions of identity, mission, and scope.

---

## 0. How to use this document

This is the durable mission contract for Fortress Legal as a sovereign legal-AI **platform**, not a case-specific tool. Every assistant working on Fortress-Prime reads this **first** and treats it as authoritative. Every chat session opens with: "Read FORTRESS-LEGAL-CONSTITUTION.md and MASTER-PLAN.md."

The document has two halves:

- **Part I — Doctrine** sets identity, mission, and scope. It changes only on intentional doctrinal amendment.
- **Part II — Contract & Execution** sets the platform's locked surfaces, regression discipline, priority order, mode-of-operation, and operational tests. It changes when architecture changes.

Master plans describe what's happening this week. ADRs describe locked architectural decisions. **This describes what Fortress Legal is, what it's for, and what it must remain.**

When this document conflicts with anything other than the parent CONSTITUTION.md and 005-nemoclaw-swarm-architecture.md, this wins.

---

# PART I — DOCTRINE

---

## 1. What Fortress Legal Is

Fortress Legal is a sovereign legal-AI platform, productized.

It was designed first around a single legal matter, `7il-v-knight-ndga`, and grew during 2026-Q2 into a multi-case, multi-counsel, multi-jurisdiction operating system for legal work. The first federal matter, Case I, is closed and provides hindsight. The second federal matter, Case II, is active and provides live pressure. Together they are not merely user stories. They are the first customer, the regression bench, and the proof points.

Fortress Legal serves the operator first. After that, it serves any matter the operator chooses to feed it: federal, state, or local; civil, real-property, financial, or other. Its purpose is not to be a one-off litigation assistant for one docket. Its purpose is to become a reusable sovereign legal command platform.

## 2. What Fortress Legal Is Not

Fortress Legal is not a single-case automation project.

It is not a prompt folder, a document summarizer, a chat wrapper, or a generic SaaS clone pointed at legal PDFs. It is not scoped to `7il-v-knight-ndga`, the Northern District of Georgia, federal court, real-property disputes, or any one judge, lawyer, plaintiff, defendant, or procedural posture.

Case I and Case II are foundational because they are real, high-stakes, document-rich, and adversarial. They validate the system. They do not define the system's outer boundary.

## 3. Mission

Fortress Legal exists to give the operator a sovereign, privileged, case-aware legal intelligence platform that can ingest, reason over, deliberate on, and operationalize legal matters without surrendering privileged data to frontier endpoints or public SaaS infrastructure.

The mission is to convert legal matter data into disciplined operator advantage:

- Accurate recall over the case record
- Privilege-aware retrieval and deliberation
- Multi-persona legal reasoning
- Repeatable regression against known outcomes
- Predictive intelligence over judges, counsel, parties, courts, and patterns of decision
- Reusable workflows that survive case boundaries

## 4. Customer Hierarchy

The operator is the first customer.

The platform is built for the operator's legal command needs before any public product, firm deployment, or external buyer. Every product decision must preserve the operator's sovereignty, privilege posture, and operational control.

| Tier | Customer | Status |
|---|---|---|
| 0 | Operator (Gary Knight) | Primary; every architectural decision serves this tier |
| 1 | Operator's active legal matters | `7il-v-knight-ndga-ii`, `fish-trap-suv2026000013`, `prime-trust-23-11161` |
| 2 | Operator's closed matters as regression dataset | `7il-v-knight-ndga-i` (judgment against — known outcome), `vanderburge-v-knight-fannin` (settled — known outcome) |
| 3 | Future matters operator chooses to onboard | Federal / state / local; civil / real property / financial / other |
| 4 | Eventual external customers | Single operators, small firms, sophisticated pro se litigants — post-product-validation |

Tier 0 → Tier 4 is the long arc. Tier 1 is the current focus. Tier 4 is not a P0 today and never preempts Tier 1. Future users at Tiers 3–4 are downstream of the original contract: Fortress Legal must remain sovereign, case-aware, privilege-aware, and operator-controlled.

## 5. Sovereign Doctrine

Fortress Legal inherits and operationalizes the sovereign doctrine documented in `CONSTITUTION.md` and `005-nemoclaw-swarm-architecture.md`. The controlling principles:

- Privileged data never leaves the cluster
- Frontier endpoints never receive raw privileged payloads
- Masking happens before any external evaluator
- Heavy artifacts remain NAS-canonical
- Local retrieval, orchestration, and deliberation preserve privilege boundaries
- SWARM, BRAIN, TITAN, and ARCHITECT tiers exist to route work according to risk, cost, latency, and sensitivity

**Sovereignty is not branding. It is an architectural constraint.**

If a proposed feature breaks any of these, it is rejected before architecture review.

## 6. The Council of 9

The Council of 9 is the platform's multi-persona deliberation engine.

It runs on spark-2 seats such as Architect, Sovereign, Counselor, and related personas, backed by Super-120B as the reasoning frontier on spark-3 and spark-4 with tensor parallelism where required. It uses privilege-aware retrieval and stamps FYEO warnings into outputs when the content demands it.

The Council is not a one-case feature. It is the deliberation surface every case will use. Every matter must be able to call the Council with a case slug, scoped record, related-matter expansion where allowed, and an explicit privilege posture.

## 7. The Intelligence Layer

The intelligence layer turns matter work into durable strategic memory.

Judges, firms, attorneys, parties, courts, procedural patterns, factual motifs, and outcome signals must be represented as reusable feature stores keyed by slug and matter identity. The NDGA Story file is the first concrete judge intelligence artifact, not the last.

Future cases must be able to add another judge file, party profile, counsel profile, or court feature set without changing the basic shape of the system.

## 8. Surfaces

Fortress Legal has separate public and private surfaces.

- `crog-ai.com` glass — sovereign command center and staff/agent UI
- `cabin-rentals-of-georgia.com` — public storefront

These surfaces must not be crossed. Public web presence and privileged legal command must remain architecturally and operationally distinct.

## 9. The North Star

Fortress Legal's North Star is a reusable sovereign legal operating system:

- Matter-aware
- Jurisdiction-agnostic
- Privilege-preserving
- Retrieval-grounded
- Deliberation-capable
- Regression-tested
- Predictive over legal actors and forums
- Controlled by the operator

The platform began with a single matter because real systems need real pressure. It becomes a product by refusing to confuse the first matter with the whole platform.

## 10. The Single-Sentence Test

Any feature, brief, ADR, or PR proposed against Fortress Legal must pass this test:

> *"Does this make Fortress Legal better at giving the operator disciplined advantage on **any** matter the operator chooses to run through it, while keeping every privileged byte on operator hardware?"*

- "Yes for Case II but breaks the platform for the next case" → reshape before merging.
- "Yes for the platform but slows Case II counsel hire" → defer (file as issue).
- "No" → reject.

---

# PART II — CONTRACT & EXECUTION

---

## 11. The Case-Agnostic Contract

Every component touching legal data **MUST** be parameterized by `case_slug` and **MUST NOT** hardcode any case-specific assumption. This is the platform contract.

### 11.1 Locked schema surfaces

Already in production, must remain:

- `legal.cases` keyed on `case_slug` — `docket`, `court`, `judge`, `case_phase`, `privileged_counsel_domains` JSONB, `related_matters` JSONB, `nas_layout` JSONB
- `legal.vault_documents` — UNIQUE `(case_slug, file_hash)`; every case has its own vault slice
- `legal.case_slug_aliases` — backward-compat after slug renames
- `legal.privilege_log` — immutable audit trail per privilege classification
- `legal.ingest_runs` — script-invocation audit trail
- `legal.email_case_links` (planned, B2) — many-to-many; cross-case email surfacing
- Qdrant `legal_ediscovery` / `legal_privileged_communications` — `case_slug` in payload; retrieval filtered per case

### 11.2 Locked code surfaces

- `process_vault_upload(case_slug, ...)` — single canonical ingest entry
- `freeze_context(case_brief, top_k, case_slug)` — Council retrieval
- `freeze_privileged_context(case_brief, top_k, case_slug)` — privileged-track retrieval (PR G)
- `_resolve_related_matters_slugs(case_slug)` — one-hop cross-matter expansion
- `phase_b_v01 --case-slug <slug>` — briefing orchestrator
- `legal_vault_ingest.py --case-slug <slug>` — vault ingestion
- `email_backfill_legal.py --case-slug <slug>` — case-aware IMAP backfill
- `track_a_case_i_runner.py --case-slug <slug>` — Track A runner (despite name, slug-parameterized)

### 11.3 Locked NAS layout

- `/mnt/fortress_nas/legal_vault/<case_slug>/` — vault NFS copies
- `/mnt/fortress_nas/Corporate_Legal/Business_Legal/<case_slug>/` — case files (Pleadings/Discovery/Correspondence/Depositions per `nas_layout` JSONB)
- `/mnt/fortress_nas/intel/judges/<court>/<judge-slug>.md` — judge intel files (one per judge, drops into any case)
- `/mnt/fortress_nas/intel/firms/<firm-slug>.md` — firm intel
- `/mnt/fortress_nas/intel/attorneys/<attorney-slug>.md` — attorney intel
- `/mnt/fortress_nas/audits/` — every script invocation manifest
- `/mnt/fortress_nas/models/` — NAS-canonical model storage

### 11.4 Forbidden patterns

- Hardcoding `7il-v-knight-ndga-i` or `7il-v-knight-ndga-ii` in any code path that should accept a slug
- Case-specific column on a shared table when JSONB or a join table would generalize
- Single-case prompt templates when the same template parameterized by case metadata works
- Building Case II features that won't run on `vanderburge-v-knight-fannin` without redesign
- Building Case I regression scaffolding that won't run on closed cases generically

If a feature can only be tested against one case, it isn't a platform feature. File it as an issue and design the case-agnostic version before merging.

---

## 12. Regression Discipline

**Closed cases are the regression bench. Active cases are production.**

Fortress Legal must be evaluated against known legal truth, not vibe. Closed matters provide hindsight. Active matters provide pressure. Both are necessary. The system must preserve outputs, metrics, retrieval provenance, citation counts, finish reasons, format compliance, and operator-facing usefulness in a way that allows future model, prompt, retrieval, and orchestration changes to be tested against prior baselines.

### 12.1 The case roster

| Case | Role | Known outcome |
|---|---|---|
| `7il-v-knight-ndga-i` | Regression — federal civil | `closed_judgment_against`; specific performance granted under severability clause; contempt motion denied (finding for operator) |
| `vanderburge-v-knight-fannin` | Regression — state civil | `closed_settled` |
| `7il-v-knight-ndga-ii` | Production — federal civil active | `counsel_search`, no answer filed yet |
| `fish-trap-suv2026000013` | Production — Generali | active, 2 vault docs (test corpus) |
| `prime-trust-23-11161` | Production — Prime Trust | active |

### 12.2 The validated Case I baseline

- **Brief artifact:** `Attorney_Briefing_Package_7IL_NDGA_I_v3_20260430T224403Z.md` (40,170 bytes)
- **Per-section metrics:** `track-a-v3-case-i-full-rerun-2026-04-30.md` (590s total wall, 10/10 finish=stop, format_compliant=true, zero first-person bleed, zero `<think>` leakage, citation counts per section)
- **Routing baseline:** PR #332 per-section reasoning policy table

### 12.3 Numerical pass criteria

A change "passes Case I" when:

1. Re-running Phase B v0.1 on `7il-v-knight-ndga-i` produces 10/10 sections finish=stop
2. Per-section content_chars within ±5% of v3 baseline (or measurably better with operator review)
3. Zero format-compliance regressions
4. Frontier endpoint stays healthy throughout the run
5. No soak halt events fire

A change that fails any of these is not applied to active cases.

### 12.4 The strategic-regression rule

A change that improves one bench while degrading the other must be treated as a **product decision**, not as an invisible implementation detail.

Mechanical metrics (§12.3) catch implementation regressions. The strategic-regression rule catches the case where metrics pass but the platform got worse — for example, a prompt change that improves Case II §5 quality but silently weakens Case I §5 reasoning depth. These cases require operator review and explicit accept/reject.

### 12.5 The other benches

`vanderburge-v-knight-fannin` is Fannin County state court. When the platform handles state-court matters end-to-end, it must run end-to-end on Vanderburge as a state-court regression. Deferred work — file as issue, do not block Case II — but it is the test that closes the multi-jurisdiction loop.

`fish-trap-suv2026000013` and `prime-trust-23-11161` are real active matters and the platform's test slots for non-NDGA cases. As the platform stabilizes through Case II, fish-trap and prime-trust prove the platform is not 7IL-specific.

---

## 13. Platform Layers

The Iron Dome view of Fortress Legal:

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

## 14. Permanent Priority Order

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

## 15. Documentation Hierarchy

| Document | Role | Update cadence |
|---|---|---|
| `CONSTITUTION.md` (parent) | Sovereign doctrine across all of Fortress-Prime | On architectural change |
| `005-nemoclaw-swarm-architecture.md` | NemoClaw / swarm orchestration contract | On architectural change |
| **`FORTRESS-LEGAL-CONSTITUTION.md` (this doc)** | **Fortress Legal mission + platform contract** | **On architectural change or doctrinal amendment** |
| `MASTER-PLAN.md` (canonical) | Fortress-Prime priority + case-clock + active-track inventory | On priority shift |
| `MASTER-PLAN-case-ii-2026-05-01.md` | 7-day window narrative for Case II counsel hire | EOD on each day of the window |
| `_architectural-decisions.md` | ADR ledger | On every locked decision |
| `docs/architecture/divisions/fortress-legal.md` | Division surface (cases, schemas, services, owners) | On schema or service change |
| `docs/architecture/shared/*.md` | Cross-cutting service docs | On service change |
| `docs/operational/*.md` | Per-task briefs Claude Code executes against | Per task |
| Per-case briefs (`Attorney_Briefing_Package_*`) | Case work product | Versioned per case |

When two master plans disagree (e.g., counsel-hire date), the MORE RECENT master plan wins **on dated facts** (clocks, milestones). On mission and scope, this constitution wins.

**Silent drift is a defect.** When future plans drift from this constitution, the plan must be corrected or the constitution must be intentionally amended.

---

## 16. Mode of Operation

### 16.1 Operator's three roles

1. Pasting status updates from Claude Code sessions on each spark
2. Decisions when forks appear — operator picks; assistant gives the reasoning
3. Operator-only work product (personal email sweeps, recollections, manual lookups, NIM weight pulls per Wave 3, signed engagement letters, the things that need a human)

### 16.2 Planning chat's three roles

1. Surface the day's three priorities based on what's blocking, in flight, gating counsel-hire
2. Write briefs Claude Code executes autonomously
3. Refuse rabbit holes and call them out before operator commits time

### 16.3 Claude Code's role

Executes briefs autonomously per hard stops on the appropriate spark via tmux. Never self-merges. Never `--admin`, never `--force`, never force-push main. Single Claude Code session per host at a time. Always cuts branches from `origin/main`.

### 16.4 Discipline rules

- Action first, no preamble
- One recommendation when answer is clear, not A/B/C/D
- Short responses beat long ones
- Time budgets honored or called out
- "No rabbit holes" / "straight line" / "stay on mission" = cut ceremony, execute
- No commentary on effort, duration, or stamina
- No meta-observations about quality of work
- When operator needs a click, give the exact URL — no "go to settings, find this"
- **Before assuming a doc doesn't exist, search project knowledge first**

### 16.5 Anti-patterns to refuse

- Asking operator for "rough notes" when the information is on the cluster
- Greenfield building when migration-additive is correct
- A/B/C/D options when the answer is clear
- Re-explaining context already in this document or master plan
- Treating any P5 item as urgent
- Hardcoding case-specific assumptions in platform code (§11.4)
- Letting any privileged byte exit the cluster
- Web-UI multi-step workflows when Claude Code can execute

---

## 17. The Reusable-Product North Star (Build Sequence)

When `7il-v-knight-ndga-ii` is counsel-engaged and the brief is in firm hands, Fortress Legal does NOT pause. The Q3 2026 build (already documented in `fortress-prime-deep-research-perfection-2026-05-01.md`) is the actual moat:

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

**Don't pre-build it during the Case II clock; do build it the moment the clock closes.**

---

## 18. Today's Three Priorities (2026-05-02)

Per `saturday-runbook-2026-05-02.md`, in order:

1. **Qdrant reindex verify → atomic alias swap** (`legal_ediscovery_active` → `legal_ediscovery_v2` 2048-dim). Block B.
2. **§9 resolver smoke against Case I** (intel layer drops in via `{{ judge:richard-w-story }}` → operator-relevant context body). Block C.
3. **Wave 7 Phase B v0.1 kickoff on `7il-v-knight-ndga-ii`** → v1 brief. Operator review gate. Section regen → v2 by EOD.

These are P0 because they're on the active-case clock. Everything else waits.

This section is updated by amendment as the case-clock advances. It is the only Part II section that legitimately churns; all others change only on architectural event.

---

## Amendment log

| Date | Version | Author | Changes |
|---|---|---|---|
| 2026-05-02 | v1 | Gary Knight + Claude (planning) | Initial constitution draft |
| 2026-05-02 | v2 | Gary Knight + Claude (planning) | Merged operator's doctrinal draft (Part I) with planning chat's contract+execution draft (Part II). Adds §2 negative-space definition, §3 mission reframe ("disciplined operator advantage"), §10 single-sentence test reframe, §12.4 strategic-regression rule, §15 silent-drift-is-a-defect clause. Retains §11 locked code/schema/NAS surfaces, §11.4 forbidden patterns, §12.3 numerical pass criteria, §13 platform layer table, §14 priority order, §16 mode-of-operation, §17 Waves A–E. |

---

End of constitution.
