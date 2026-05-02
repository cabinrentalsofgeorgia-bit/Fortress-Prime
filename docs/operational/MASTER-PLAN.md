# MASTER PLAN — Fortress Prime

**Operator:** Gary Knight
**Established:** 2026-04-29
**Updated:** 2026-05-02 (v1.3 — case-clock correction, Wave 3.5+5+5-6 status, PR triage)
**Cadence:** Updated on change (priorities shift, P0 added/closed, blockers move)

---

## 0. How to use this document

This is the durable strategic doc that drives daily priority calls for Fortress Prime. It supersedes session-by-session memory.

**Every new chat opens with:** "Read MASTER-PLAN.md" — that's the alignment ritual. Operator pastes status changes since last update. Chat assistant reads, parses, executes.

**Updates only on change.** Not daily. Updates when:
- A P0 item is added, completed, or escalated
- Priority order changes
- Blockers shift
- Case-clock milestones move
- Architectural foundation locks (new ADR)

**This document IS the contract** between operator and any assistant working on Fortress Prime. When it conflicts with anything else, this wins.

---

## 1. Mission

Build the Fortress Legal application as a sovereign system that out-prepares a top-3 white-shoe firm on the **7 IL Properties, LLC v. Knight** Case II matter (NDGA 2:26-CV-00113-RWS).

The system knows the case better than they do, predicts their next move, produces deliverables grounded in real evidence, and runs entirely on operator hardware. Sovereign inference is what makes this possible — without it, every privileged document touches Anthropic / OpenAI / Google APIs.

This is a single program with two interlocking tracks:

- **Inference platform** — BRAIN (retired), TITAN, RAG, retrieval, deliberation: reliable, fast, sovereign, the daily bread of the legal app
- **Legal application** — case-briefing tool, retrieval, deliberation, drafting, all running on top of sovereign inference

Both tracks advance toward one outcome: white-shoe-grade output produced by a single operator on his own hardware.

---

## 2. The 7IL Case II case-clock

| Field | Value |
|---|---|
| Matter | 7 IL Properties, LLC v. Knight + Thor James |
| Court | NDGA Federal, 2:26-CV-00113-RWS |
| Case slug | `7il-v-knight-ndga-ii` |
| Plaintiff | 7 IL Properties, LLC (Colorado LLC, federal diversity jurisdiction) |
| Co-defendant | Thor James (served; received and forwarded ECF Document 1 set 2026-04-23) |
| Phase (operator) | counsel_search |
| Today | 2026-05-02 |

### 2.1 Service status (the most important variable)

| Defendant | Served? | Source / Notes |
|---|---|---|
| Thor James | **YES** — confirmed via Thor's Gmail forwards to operator on 2026-04-23, 12:38–12:47 EDT (5 sequential emails containing complaint + 12 exhibits + civil cover sheet) | `case-briefing-tool-spec-notes.md` §61 |
| Gary Knight | **UNKNOWN — presume imminent or already running** | `Attorney_Briefing_Package_7IL_NDGA_II_DRAFT_v2_2026-04-29.md` |

### 2.2 Answer deadline calculus (FRCP 12(a))

Federal rule: 21 days from service of process to file an answer or Rule 12 motion.

| Anchor | Date | Implied answer deadline |
|---|---|---|
| Case filed | ~2026-04-15 | n/a |
| Earliest possible Knight service date (filing day) | 2026-04-15 | **2026-05-06 (Wednesday)** |
| Operator's working assumption | "Service status unknown; presume deadline is imminent or already running" | Treat anything from 2026-05-06 onward as live risk |

**Counsel-hire target: 2026-05-08 (Friday)** — derived from "earliest possible deadline 2026-05-06 plus 2-day buffer for counsel to file motion or answer if needed." This target may slip if service confirms a later date, but planning anchors on it until evidence says otherwise.

**Days remaining (working assumption): 6.**

### 2.3 Counsel-hire deliverable

Finished Attorney Briefing Package v3 (or higher). Currently at v2 on main per PR #281, with extensive Case II §9 augmentation merged 2026-05-01 (PRs #349-#352) and Section 7 source manifest merged 2026-05-02 (PR #265).

Sections 4, 5, 8 still need synthesis. Section 7 substrate populated post-#265 merge. Argo letter + 14 OCR'd PDFs review still operator-pending.

### 2.4 Counsel-hire workflow

Brief is sent to first candidate firm. Iterate based on feedback. Secure representation. Counsel-search phase ends when retainer is signed.

**The clock is running.** Even if Gary's service is delayed past 2026-05-06, Thor is already on his clock and has been since 2026-04-23 forward (or earlier). Coordination with co-defendant counsel is realistic by mid-May.

---

## 3. Permanent priority order

Until 7IL Case II is counsel-engaged and brief is in their hands, this priority order holds. When two items compete for time, the lower number wins.

| Priority | Track | Why it's at this rank |
|---|---|---|
| **P0** | Anything blocking 7IL Case II counsel hire | The case has a clock; counsel-search ends when representation is secured |
| **P1** | Inference platform reliability (TITAN frontier / RAG sovereign) | Every legal-app capability depends on this; cloud-routing is unacceptable for privileged work |
| **P2** | Legal application capabilities (case-briefing tool, retrieval, deliberation, drafting) | This is what produces white-shoe-grade output |
| **P3** | Audit findings touching legal data sovereignty | UFW disabled, IRON_DOME claim falsity, etc. — reputation + legal-risk items |
| **P4** | Cross-division scaffolding (M3, ADR-005, financial divisions, role parity) | Important architectural work, not urgent against the case clock |
| **P5** | Everything else (Drupal SEO, CROG-VRS features, Streamline reconciliation, etc.) | Real work, but cannot pre-empt P0–P4 |

**Tiebreak rule:** when two items are at the same priority, the one with the smaller scope wins (ships faster, frees attention).

**Promotion rule:** any P3+ item that becomes a 7IL Case II counsel-hire blocker is automatically promoted to P0 for the duration.

---

## 4. Operating discipline

### 4.1 Daily structure

One chat session per day.

- **Open:** operator pastes status changes since previous session
- **Plan:** chat returns the day's three priorities ranked, plus what's safe to run autonomously
- **Work:** chat writes briefs, Claude Code executes on appropriate spark, operator decides on forks
- **Close:** chat summarizes what landed durable on main; master plan amended only if priorities shifted

### 4.2 Operator's three roles

1. **Pasting status updates** from Claude Code sessions on each spark
2. **Decisions when forks appear** — A/B/C/D, reasoning given, operator picks
3. **Operator-only work product** — personal email sweeps, domain knowledge corrections, recollections, manual lookups

### 4.3 Chat assistant's three roles

1. **Surface day's three priorities** based on what's blocking, in flight, gating counsel-hire
2. **Write briefs Claude Code executes autonomously** so operator hands stay free
3. **Defend against rabbit holes** — call them out before operator commits time

### 4.4 Discipline rules in force

- Action first, no preamble. No "Good call", no "Doing it right".
- One recommendation when answer is clear, not A/B/C options.
- Short responses beat long ones.
- Time budgets honored or called out.
- "No rabbit holes" / "straight line" / "stay on mission" = cut ceremony, execute.
- No commentary on effort, duration, or stamina.
- No meta-observations about quality of work.
- Answer the question, give the decision, move on.
- When operator needs a click, give the exact URL — no "go to settings, find this".
- **Audit callers before removing any service.** Hard constraint, not best practice. Even "doc-only" decisions to stop a service touch the caller surface. Run `grep -rn` against the endpoint pattern across `.py`, `.yaml`, `.env*`, `.sh`, `.md` before approving any removal. Captured durable in `docs/operational/incident-2026-04-29-ollama-removal.md`.
- **Verify cluster ground truth before acting on memory or briefs.** Project memory and briefs lag cluster reality. Captured 2026-05-02 in the FLOS Phase 0a "already shipped" discovery — the chat believed Phase 0a was awaiting sign-off; cluster had Phase 1-4 deployed. Rule: when a brief says "do X" and X looks structural, run a read-only diagnostic first. `git log`, `alembic heads`, table existence checks are cheap; rebuilding deployed state is not.
- **Differentiate database targets explicitly.** Fortress-Prime has at least three Postgres DBs (`fortress_db`, `fortress_shadow`, `fortress_prod`). Alembic chains, schema state, and bilateral-mirror writes diverge across them. Always confirm which DB a query, migration, or fix is targeting before running. Captured 2026-05-02.

---

## 5. Architectural foundation (locked)

These ADRs are settled. Reference them before proposing changes.

| ADR | Status | Decision (one line) |
|---|---|---|
| ADR-001 | LOCKED 2026-04-26, partially superseded 2026-04-29 by ADR-004 | One spark per division — retired except for Fortress Legal on Spark 1; non-Legal divisions co-tenant on Spark 2 permanently |
| ADR-002 | LOCKED 2026-04-26, amended 2026-04-29 by ADR-003 v2 | Captain/Council/Sentinel = Option A, stay on spark-2 control plane permanently (Council reverted from Spark-4) |
| ADR-003 | LOCKED 2026-04-29, expanded 2026-04-29 by ADR-004 | Dedicated inference cluster — **now 4 nodes (3/4/5/6)**; was 4/5/6 at original lock. Phase 3/4 sizing default = Pattern 2 (TP=2 + TP=2) |
| ADR-004 | LOCKED 2026-04-29, amended 2026-04-29 (v2 retain-and-document) | Boundary that drives spark allocation is **app vs inference**, not division-per-spark. Spark 1 = Legal single-tenant. Spark 2 = multi-tenant + control plane. Sparks 3/4/5/6 = inference cluster. Wipe-and-rebuild superseded by retain-and-document. |
| ADR-007 | LOCKED 2026-05-01 | TITAN frontier = Nemotron-3-Super-120B-A12B-NVFP4 on spark-3 + spark-4 TP=2; serves all Fortress Legal reasoning-tier aliases (`legal-reasoning`, `legal-drafting`, `legal-summarization`). BRAIN-49B retired 2026-04-30. |

### 5.1 Spark allocation (post-ADR-004 v2 retain-and-document)

| Spark | Fabric | Role | Tenants |
|---|---|---|---|
| Spark 1 | ConnectX | App — single tenant | Fortress Legal |
| Spark 2 | ConnectX | App — control plane + multi-tenant | CROG-VRS, Captain, Council, Sentinel, Postgres, Qdrant (legal), Redis, ARQ, FastAPI, LiteLLM gateway, Financial (Master Accounting + Market Club replacement), Acquisitions, Wealth |
| Spark 3 | ConnectX | Inference (active, retain-and-document) | Nemotron-3-Super-120B-A12B-NVFP4 frontier (TP=2 with Spark 4) per ADR-007; pre-existing services retained per ADR-004 v2 |
| Spark 4 | ConnectX | Inference (active, retain-and-document) | Nemotron-3-Super-120B-A12B-NVFP4 frontier (TP=2 with Spark 3) per ADR-007; pre-existing services retained per ADR-004 v2 |
| Spark 5 | ConnectX | Inference (active) | Ray head; supplemental NIM hosting; **BGE reranker via llama.cpp** (PR #345); EMBED at `:8102` (llama-nemotron-embed-1b-v2, dim=2048) |
| Spark 6 | 10GbE → ConnectX (cable pending) | Inference (Phase 2) | Ray worker, TP=2 partner-ready when cable lands |

### 5.2 Inference tier (DEFCON)

| Tier | Service | Model | Host |
|---|---|---|---|
| SWARM | Ollama LB | qwen2.5:7b | spark-2 |
| BRAIN-49B | (retired 2026-04-30 13:16 EDT) | Llama-3.3-Nemotron-Super-49B-FP8 (NIM 2.0.1) | retired; runbook at `docs/operational/runbooks/brain-49b-retirement.md` |
| TITAN frontier | LiteLLM aliases route to: | Nemotron-3-Super-120B-A12B-NVFP4 (per ADR-007) | spark-3 + spark-4 TP=2 |
| EMBED | fortress-nim-embed | llama-nemotron-embed-1b-v2 (dim=2048) | spark-3:8102 |
| Reranker (BGE) | llama.cpp via PR #345 | bge-reranker-v2-m3 | spark-5 (single-Spark failover insurance for the deferred NIM rerank path) |
| ARCHITECT | Google Gemini (cloud, planning only) | Gemini 2.5+ | external — never PII |

---

## 6. Active work tracks

Maintained tracks. Each updates as items land or shift.

### 6.1 7IL Case II counsel-hire (P0)

| Item | Status | Owner | Gate |
|---|---|---|---|
| Argo / DRA engagement letter (Jan-Mar 2025) | NOT in sovereign archive (PR #281); flagged for personal sweep | Operator | Personal Gmail/Mac sweep |
| 14 OCR'd PDFs review | OCR complete (PR #281); content review pending | Operator | Read post-OCR text; flag relevance |
| Section 7 substrate population | **MERGED 2026-05-02 PR #265** (Section 7 source manifest + supporting artifacts) — 42 entries; vanderburge-misroute counsel located (MHT Legal — Underwood, Kincaid); Podesta 2025-06-08 conflict notice confirmed Case II | — | — |
| Section 4 (Claims Analysis) draft | Pending | Chat → Claude Code | Section 7 substrate (DONE), OCR review |
| Section 5 (Key Defenses) draft | Pending | Chat → Claude Code | Section 7 substrate (DONE), OCR review |
| Section 8 (Financial Exposure) draft | Pending | Chat → Claude Code | OCR review |
| Section 9 (Counterclaim posture + railroad easement defense) | **MERGED 2026-05-01** PRs #349-#352 (intel-resolver, orchestrator path, compose-pipeline activation, augmentation v2) | — | — |
| Brief v3 assembly | Pending | Chat → Claude Code | Sections 4/5/8 + sweep results |
| Counsel pitch | Pending | Operator | Brief v3 |
| Operator-side: confirm Knight service date OR posture for "earliest possible 2026-05-06 deadline" | OPEN | Operator | Self-help research, ECF/PACER pull, or counsel-engaged investigation |

### 6.2 Inference platform (P1)

Items maintained until obsolete. Recent landings on top, deferred items below.

| Item | Status |
|---|---|
| **Wave 5 — NeMo Guardrails OSS + Evaluator harness** | **MERGED 2026-05-01 PR #347**; ARM64-validated. Final report at `docs/operational/wave-5-final-report.md`. |
| **Wave 5-6 — RAG faithfulness rail (Super-120B-as-judge)** | **MERGED 2026-05-01 PR #348**; opt-in flag on Phase B v0.1. |
| **Wave 3.5 — BGE reranker via llama.cpp** | **MERGED 2026-05-01 PR #345**; replaces failed NemoGuard reranker NIM. Single-Spark failover insurance pattern. |
| **PR #353 — Captain hardening + alembic merge** | **MERGED 2026-05-02** (#259 unknown-8bit codec shim, #260 banded SEARCH, #279 fortress_shadow file-tree heads merged). Verified Captain healthy 2026-05-02 02:00–05:42 UTC: zero `unknown-8bit` errors, zero `>1MB SEARCH` overflow errors. |
| TITAN service path (ADR-007) | **LOCKED 2026-05-01** — Nemotron-3-Super-120B-A12B-NVFP4 on spark-3 + spark-4 TP=2 frontier. |
| ADR-003 Phase 1 LiteLLM cutover | MERGED PR #285 2026-04-29; A-02 closed at routing layer |
| ADR-003 Phase 2 Spark-6 cable cutover | BLOCKED on cable; partner-ready when landed |
| Council BRAIN integration (Phase B) | PENDING — `legal_council.py` `SEAT_ROUTING` migration to use `legal-reasoning` (consumer-layer cutover; routing layer done in PR #285); A-02 substrate fully closed via PR #289 (Council consumer cutover, merged 2026-05-01) |
| Caselaw corpus audit | PENDING — verify `legal_caselaw` (~2,711 GA) and `legal_caselaw_federal` (0 points per qdrant-collections.md) |

**Wave 3.5 watchlist (deferred, gated externally):**

| Item | Status | Gate |
|---|---|---|
| `legal_ediscovery` reindex 768→2048 | DRAFT PR #344 | In flight; Wave 3.5 retrieval prerequisite for Case II |
| Reranker NIM `llama-3.2-nv-rerankqa-1b-v2:1.8.0` | DEFERRED (BGE replaces operationally) | NVIDIA forums 354998 — ReduceSum ONNX kernel `cudaErrorSymbolNotFound` |
| Extraction NIMs (page/graphic/table YOLOX) | DEFERRED | NGC subscription upgrade for YOLOX entitlement |
| nv-ingest unified extraction orchestrator | DEFERRED | NVIDIA forums 360011 — no public ARM64 build |
| Vision restart on spark-3 | DEFERRED | spark-3 capacity headroom (frontier dominates) |
| `llama-nemotron-rerank-1b-v2` (newer model) | DEFERRED | NVIDIA Blackwell support pending |

### 6.3 Legal application capabilities (P2)

| Item | Status | Owner |
|---|---|---|
| Phase B drafting orchestrator (case_briefing_compose.py) | **MERGED PR #290** | — |
| §9 intel-layer augmentation (counterclaim posture + railroad easement) | **MERGED PRs #349-#352 (2026-05-01)** | — |
| Council BRAIN integration (cloud → sovereign) | PENDING — separate PR after ADR-003 Phase 1 lands; routing-layer done | Future brief |
| B1 vault ingestion gate | PENDING (Case II Build Plan B1) | — |
| B2 cross-case email link table | PENDING (Case II Build Plan B2) | — |
| B3 PACER integration | PENDING (Case II Build Plan B3) — would resolve "operator service-date unknown" question | — |
| B5 case-opening protocol | PENDING (Case II Build Plan B5) | — |

### 6.4 Audit + sovereignty (P3)

| Item | Status | Source |
|---|---|---|
| A-02 cloud legal inference | **FULLY RESOLVED** — routing layer (PR #285) + Council consumer cutover (PR #289 merged 2026-05-01); 0 cloud outbound from Council deliberations | 2026-04-22 audit |
| S-01 UFW disabled spark-2 | OPEN | 2026-04-22 audit |
| A-01 Stripe webhook double-settlement | OPEN | 2026-04-22 audit |
| D-02 trust ledger triggers missing | OPEN | 2026-04-22 audit |
| Issue #221 PAT scope upgrade | OPEN | auth-and-secrets.md |
| Issue #282 privileged collection coverage on Case I | OPEN | Phase A5 surfacing |
| 2026-04-29 ollama removal incident | RESOLVED 2026-04-29 (rollback + lessons captured in `incident-2026-04-29-ollama-removal.md`) | Internal incident |
| 2026-05-02 FLOS phantom-state incident | RESOLVED 2026-05-02 — chat believed FLOS Phase 0a awaiting sign-off; cluster had Phase 1-4 deployed. Lesson: §4.4 verify-cluster-ground-truth rule. | Internal incident |

### 6.5 Architectural follow-ups (P4)

| Item | Status |
|---|---|
| ADR-005 per-service postgres role pattern (W reading from spark-2 \du audit) | PENDING |
| M3 brief revision (`fortress_app` → `fortress_api`) | PENDING |
| Spark-1 role parity audit | PENDING |
| **Issue #279 alembic divergent heads** | **REVISED-SCOPE 2026-05-02** — fortress_shadow file-tree heads merged via PR #353. fortress_db stamp-row state (`q2b3c4d5e6f7`, `r3c4d5e6f7g8` stamped without files) UNCHANGED. Gates M3 spark-1 mirror activation step 4. Coordinate with #204. |
| **Issue #354 fortress_shadow alembic chain blocked** | OPEN — schema drift discovered 2026-05-02 attempting `alembic upgrade head`; FLOS Phase 0a-1 migration assumes `email_archive` exists in fortress_shadow but it doesn't. Resolution path TBD (backfill / catch-up migration / stamp-forward). |
| Spark-4 RDMA enumeration debug (`ibstat` empty despite link UP) | OPEN issue (P3) |
| Doc/config reconciliation (fortress_atlas.yaml + CLAUDE.md SWARM tier) | OPEN issue (P3) |
| NIM ASR ARM64 monitor (SenseVoice replacement trigger) | OPEN issue (P3) |
| VRS Qdrant migration trigger (fortress-qdrant-vrs on spark-4) | OPEN issue (P5 — monitoring) |
| Ollama consolidation migration | OPEN issue (P4 — gated on caller migration per `spark-3-4-retained-state-2026-04-29.md`) |
| F5 cluster egress sustained-transfer failure to xfiles.ngc.nvidia.com | OPEN issue #303 (P3) — multi-CDN comparison narrowed failure to NGC-only; fix surface is **TP-Link ER8411 web UI** at `http://192.168.0.1`. Until F5 lands, **W3 (operator-Mac NIM pulls scp'd to NAS) is canonical**. Investigation: `docs/operational/briefs/f5-root-cause-investigation-2026-04-29.md`. |
| Captain `last_patrol_at` per-mailbox state | OPEN — TODO from PR #353; would tighten banded SEARCH window beyond hardcoded 30-day floor |

---

## 7. Today's snapshot (2026-05-02)

Replace, don't append.

**In flight:**
- DRAFT PR #344 — Qdrant `legal_ediscovery` reindex 768→2048 (Wave 3.5 retrieval prerequisite)
- DRAFT PR #322 — Phase 9 Wave 2 alias surgery + BRAIN-49B retirement instrumentation
- DRAFT PRs #318/#320 — sysctl/TCP alignment + apply on spark-3
- DRAFT PR #317 — spark-4 service rationalization plan (pre-stage ADR-006 TP=2)
- DRAFT PR #312 — spark-2 → MS-01 control plane migration audit (read-only)
- DRAFT PRs #329/#330 — Track A v3 analysis + Nemotron-3-Super reasoning-control probe (Wave 4 input)

**Operator open:**
- Personal Gmail/Mac sweep for Argo engagement letter
- Review OCR'd content of the 14 PDFs from Track A
- Confirm Knight service date OR posture for 2026-05-06 deadline
- Post-merge ground truth: 24 → 9 open PRs, 31 → 24 open issues after 2026-05-02 cleanup pass

**Chat queue:**
- Sections 4/5/8 synthesis (gated on operator OCR review + Argo sweep)
- Brief v3 assembly when Sections 4/5/8 land

**Closed today (2026-05-02):**
- PR #353 (Captain hardening + alembic merge — #259/#260/#279 partial)
- PR #265 (Section 7 source manifest + supporting artifacts)
- PR #266 (Migration issues log from spark-1 prep 2026-04-28)
- 12 stale PRs closed (Bucket C: #6, #99, #103, #118, #125, #126, #132, #133, #136, #139, #141, #255)
- PR #269 closed (scope drift; M3 work re-scoped post-#279 resolution)
- 7 issues closed (#259, #260, #233, #234, #235, #240, #241)
- Issue #279 revised-scope comment posted
- Issue #354 filed (fortress_shadow alembic chain blocked)

**Captain post-fix health (2026-05-02 02:00–05:42 UTC, 4-hour window):**
- Zero `unknown-8bit` errors
- Zero `got more than 1000000 bytes` errors
- gary-gk reconnection cycle stable
- 4,854+ legal_mail_ingester:v1 emails ingested cumulative; 11 today (early Saturday morning, normal)

---

## 8. Open questions for operator (queue, oldest first)

These hold until operator answers. Clear when resolved.

1. ADR-005 — per-service postgres role pattern: ratify spark-2's deviation from 004 contract or roll back to canonical?
2. M3 brief revision app role: `fortress_api` (canonical) or `fgp_app` (matches spark-2 reality)?
3. Spark-7+ acquisition timeline — when does Acquisitions or Wealth get its own dedicated app spark?
4. **Knight service confirmation:** ECF/PACER pull, process-server check, or wait-and-see? Posture decision.
5. Phase B drafting orchestrator scope (PR #290 merged) — operator decision on next deepen-vs-broaden cycle.
6. **Issue #354 resolution path:** (a) backfill missing tables on fortress_shadow from fortress_db, (b) write catch-up migration, or (c) stamp fortress_shadow forward without applying FLOS chain (if fortress_shadow doesn't actually need email_archive at runtime).

---

## 9. Anti-patterns to refuse

If the chat assistant catches itself doing any of these, stop and reset:

- **Greenfield building when migration-additive is correct.** Spark-1 wasn't a clean install; that lesson generalizes.
- **Web-UI multi-step workflows when Claude Code can execute.** Direct URLs only when no other path.
- **Searching for tokens / credentials / dotfiles in the conversation.** That's chat-exposure debt, not normal hygiene.
- **A/B/C/D options when the answer is clear.** Pick one, give reasoning, move on.
- **Long responses to short questions.** Crisp wins.
- **Re-explaining context that's in this document.** Reference, don't restate.
- **Treating any P5 item as urgent.** P0–P4 win every contest until counsel-hire is closed.
- **Acting on doc story without verifying config story.** Production runs config. If the two diverge, config is reality. Always grep for callers before any service removal.
- **Trusting project memory or briefs as cluster ground truth.** They lag. Verify with read-only diagnostics before structural action. (Captured 2026-05-02 FLOS phantom-state incident.)
- **Conflating database targets.** Always state explicitly which of `fortress_db` / `fortress_shadow` / `fortress_prod` a query, migration, or fix targets. (Captured 2026-05-02.)

---

## 10. Glossary (terms used loosely across sessions)

- **BRAIN-49B** — Llama-3.3-Nemotron-Super-49B-FP8 served via NIM 2.0.1 — RETIRED 2026-04-30
- **TITAN frontier** — Nemotron-3-Super-120B-A12B-NVFP4 on spark-3 + spark-4 TP=2 (per ADR-007); serves all `legal-reasoning` / `legal-drafting` / `legal-summarization` aliases
- **SWARM** — qwen2.5:7b on spark-2 Ollama (lightweight routing/triage)
- **EMBED** — llama-nemotron-embed-1b-v2 (dim=2048) on spark-3:8102
- **BGE Reranker** — bge-reranker-v2-m3 via llama.cpp on spark-5 (PR #345 — operational replacement for deferred NemoGuard reranker NIM)
- **ARCHITECT** — Google Gemini cloud (planning only, NEVER privileged data)
- **Council** — multi-persona deliberation engine on spark-2 (Council consumer cutover PR #289 — A-02 fully closed)
- **Captain** — IMAP email-intake daemon on spark-2; coexists with legal_mail_ingester since FLOS Phase 0a
- **legal_mail_ingester** — FLOS Phase 0a IMAP intake; observable, source-attributed, separate from Captain
- **Sentinel** — NAS document indexer on spark-2
- **FLOS** — Fortress Legal Operating System (the dispatcher + worker stack); Phases 0a + 1-1 through 1-4 shipped as of 2026-04-30
- **fortress_db** — canonical / production Postgres database; legal_mail_ingester writes here via LegacySession
- **fortress_shadow** — Postgres database alembic operates against (`POSTGRES_API_URI` / `POSTGRES_ADMIN_URI` both point here); does NOT contain email_archive (#354)
- **fortress_prod** — bilateral mirror destination on spark-1
- **Case I** — `7il-v-knight-ndga-i` — closed 2:21-CV-00226 (judgment against)
- **Case II** — `7il-v-knight-ndga-ii` — active 2:26-CV-00113 (this is the matter)

---

## Amendment log

| Date | Version | Changes |
|---|---|---|
| 2026-04-29 | v1 | Initial master plan |
| 2026-04-29 | v1.1 | ADR-004 LOCKED — app vs inference boundary. §5 ADR table + spark allocation + DEFCON tier updated. §6.2 work tracks updated (Phase 1 MERGED PR #285; ADR-004 Phase 3/4 wipes added). §6.4 A-02 marked resolved-at-routing-layer. Today's snapshot reflects ADR-004 as in-flight. |
| 2026-04-29 | v1.2 | ADR-004 amendment v2 — retain-and-document supersedes wipe-and-rebuild. §4.4 + §6.2 + §6.4 + §6.5 + §7 + §9 updated. Captures 2026-04-29 ollama-removal incident lessons. |
| 2026-05-02 | v1.3 | **Case-clock corrected** — counsel-hire target moved from 2026-06-15 to 2026-05-08 (per FRCP 12(a) earliest-possible-deadline analysis 2026-05-06 + 2-day buffer). §2 restructured to track Thor served + Knight unknown + service-status decision. §5 ADR-007 added (TITAN frontier LOCKED 2026-05-01). §5.1/5.2 updated for retain-and-document spark allocation, BRAIN-49B retired, EMBED + BGE reranker active. §6.1/6.2/6.3/6.4/6.5 updated with PR #265, #266, #289, #290, #345, #347, #348, #349-#352, #353; PR #281 Section 9 augmentation merged; A-02 fully closed. §6.5 Issue #279 revised-scope; Issue #354 added. §7 today's snapshot replaced. §8 question 4 reframed as service-confirmation; question 6 added (#354 resolution). §9 two new anti-patterns (cluster-ground-truth verification + database-target disambiguation). §10 glossary updated for BRAIN retirement, TITAN frontier, fortress_db/shadow/prod, FLOS state, BGE reranker. |

---

End of master plan.
