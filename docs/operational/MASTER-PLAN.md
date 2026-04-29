# MASTER PLAN — Fortress Prime

**Operator:** Gary Knight
**Established:** 2026-04-29
**Updated:** 2026-04-29 (v1)
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

- **Inference platform** — BRAIN, TITAN, RAG, retrieval, deliberation: reliable, fast, sovereign, the daily bread of the legal app
- **Legal application** — case-briefing tool, retrieval, deliberation, drafting, all running on top of sovereign inference

Both tracks advance toward one outcome: white-shoe-grade output produced by a single operator on his own hardware.

---

## 2. The 7IL Case II case-clock

| Field | Value |
|---|---|
| Matter | 7 IL Properties, LLC v. Knight |
| Court | NDGA Federal, 2:26-CV-00113-RWS |
| Case slug | `7il-v-knight-ndga-ii` |
| Plaintiff | 7 IL Properties, LLC (Colorado LLC, federal diversity jurisdiction) |
| Phase (operator) | counsel_search |
| Target counsel-hire date | **2026-06-15** |
| Today | 2026-04-29 |
| **Days remaining** | **~47** |

**Counsel-hire deliverable:** finished Attorney Briefing Package v3 (or higher). Currently at v2 on main per PR #281. Sections 4, 5, 8 still need synthesis after Argo letter + 14 OCR'd PDFs are reviewed. Section 7 substrate needs to populate via personal-records sweep.

**Counsel-hire workflow:** brief is sent to first candidate firm. Iterate based on feedback. Secure representation. Counsel-search phase ends when retainer is signed.

**The clock starts mattering** when Argo letter is located, OCR'd PDFs are reviewed, and Sections 4/5/8 enter synthesis. Until then, days elapsed are days of evidence assembly, not days of counsel pitch.

---

## 3. Permanent priority order

Until 7IL Case II is counsel-engaged and brief is in their hands, this priority order holds. When two items compete for time, the lower number wins.

| Priority | Track | Why it's at this rank |
|---|---|---|
| **P0** | Anything blocking 7IL Case II counsel hire | The case has a clock; counsel-search ends when representation is secured |
| **P1** | Inference platform reliability (BRAIN / TITAN / RAG sovereign) | Every legal-app capability depends on this; cloud-routing is unacceptable for privileged work |
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

---

## 5. Architectural foundation (locked)

These ADRs are settled. Reference them before proposing changes.

| ADR | Status | Decision (one line) |
|---|---|---|
| ADR-001 | LOCKED 2026-04-26, amended by ADR-003 | One spark per *app* division (1=Legal, 2=CROG-VRS+ctrl plane, 3=Financial+Acq+Wealth co-tenant) |
| ADR-002 | LOCKED 2026-04-29 (resolved by ADR-003) | Captain/Council/Sentinel = Option A, stay on spark-2 control plane permanently |
| ADR-003 | LOCKED 2026-04-29 | Sparks 4/5/6 form dedicated inference cluster; Phase 3 sizing = TP=2 + hot replica |

### 5.1 Spark allocation (post-ADR-003)

| Spark | Fabric | Role | Tenants |
|---|---|---|---|
| Spark 1 | ConnectX | App | Fortress Legal |
| Spark 2 | ConnectX | App + control plane | CROG-VRS, Captain, Sentinel, Postgres, Qdrant (legal), Redis, ARQ, FastAPI, LiteLLM gateway |
| Spark 3 | ConnectX | App | Financial; Acquisitions + Wealth co-tenant pending Spark-7+ |
| Spark 4 | ConnectX | Inference (Phase 3) | Ray worker, joins inference cluster |
| Spark 5 | ConnectX | Inference (active) | Ray head; Nemotron-Super-49B-FP8 NIM; LLAMA-3.3 |
| Spark 6 | 10GbE → ConnectX (cable pending) | Inference (Phase 2) | Ray worker, TP=2 partner with Spark 5 |

### 5.2 Inference tier (DEFCON)

| Tier | Service | Model | Host |
|---|---|---|---|
| SWARM | Ollama LB | qwen2.5:7b | spark-2 |
| BRAIN | fortress-nim-brain.service :8100 | Llama-3.3-Nemotron-Super-49B-v1.5-FP8 (NIM 2.0.1) | spark-5 (today); spark-5+6 TP=2 (Phase 2); 4/5/6 Pattern 1 (Phase 3) |
| TITAN | DeepSeek-R1 671B llama.cpp RPC | DeepSeek-R1 | TBD inference cluster placement |
| ARCHITECT | Google Gemini (cloud, planning only) | Gemini 2.5+ | external — never PII |

---

## 6. Active work tracks

Maintained tracks. Each updates as items land or shift.

### 6.1 7IL Case II counsel-hire (P0)

| Item | Status | Owner | Gate |
|---|---|---|---|
| Argo / DRA engagement letter (Jan-Mar 2025) | NOT in sovereign archive (PR #281); flagged for personal sweep | Operator | Personal Gmail/Mac sweep |
| 14 OCR'd PDFs review | OCR complete (PR #281); content review pending | Operator | Read post-OCR text; flag relevance |
| Section 7 substrate population | Thin substrate documented (PR #281); fills after personal sweep | Chat + operator | Argo letter + Wilson + Pugh personal sweep |
| Section 4 (Claims Analysis) draft | Pending | Chat → Claude Code | Section 7 substrate, OCR review |
| Section 5 (Key Defenses) draft | Pending | Chat → Claude Code | Section 7 substrate, OCR review |
| Section 8 (Financial Exposure) draft | Pending | Chat → Claude Code | OCR review |
| Brief v3 assembly | Pending | Chat → Claude Code | Sections 4/5/8 + sweep results |
| Counsel pitch | Pending | Operator | Brief v3 |

### 6.2 Inference platform (P1)

| Item | Status | Owner |
|---|---|---|
| BRAIN incident INC-2026-04-28 | RESOLVED PR #277; durable on main | — |
| Phase A1 spark-1 legal overlays | MERGED PR #278 | — |
| Phase A5 BRAIN+RAG probe | MERGED PR #280; revised contracts (TTFT-based, semantic-equivalence determinism) | — |
| ADR-003 Phase 1 LiteLLM cutover | IN FLIGHT branch `adr/003-inference-cluster-topology` on spark-2 | Claude Code |
| ADR-003 Phase 2 Spark-6 cable cutover | BLOCKED on cable | Operator |
| ADR-003 Phase 3 Spark-4 join | DEFERRED post-Phase 2 | — |
| Caselaw corpus audit | PENDING — verify `legal_caselaw` (~2,711 GA) and `legal_caselaw_federal` (0 points per qdrant-collections.md) | Chat → Claude Code |
| TITAN service path | UNKNOWN — DeepSeek-R1 671B placement after ADR-003 inference cluster lands | Future brief |

### 6.3 Legal application capabilities (P2)

| Item | Status | Owner |
|---|---|---|
| Phase B drafting orchestrator (case_briefing_compose.py) | PENDING — brief to be drafted | Chat → Claude Code |
| Council BRAIN integration (cloud → sovereign) | PENDING — separate PR after ADR-003 Phase 1 lands | Future brief |
| B1 vault ingestion gate | PENDING (Case II Build Plan B1) | — |
| B2 cross-case email link table | PENDING (Case II Build Plan B2) | — |
| B3 PACER integration | PENDING (Case II Build Plan B3) | — |
| B5 case-opening protocol | PENDING (Case II Build Plan B5) | — |

### 6.4 Audit + sovereignty (P3)

| Item | Status | Source |
|---|---|---|
| A-02 cloud legal inference | RESOLVING via ADR-003 Phase 1 | 2026-04-22 audit |
| S-01 UFW disabled spark-2 | OPEN | 2026-04-22 audit |
| A-01 Stripe webhook double-settlement | OPEN | 2026-04-22 audit |
| D-02 trust ledger triggers missing | OPEN | 2026-04-22 audit |
| Issue #221 PAT scope upgrade | OPEN | auth-and-secrets.md |
| Issue #282 privileged collection coverage | OPEN | Phase A5 surfacing |

### 6.5 Architectural follow-ups (P4)

| Item | Status |
|---|---|
| ADR-005 per-service postgres role pattern (W reading from spark-2 \du audit) | PENDING |
| M3 brief revision (`fortress_app` → `fortress_api`) | PENDING |
| Spark-1 role parity audit | PENDING |
| Issue #279 alembic-merge on spark-2 fortress_db | OPEN — gates M3 activation |

---

## 7. Today's snapshot (2026-04-29)

Update this section as items land. Replace, don't append.

**In flight:**
- ADR-003 Phase 1 LiteLLM cutover on spark-2 (branch `adr/003-inference-cluster-topology`)

**Operator open:**
- Personal Gmail/Mac sweep for Argo engagement letter
- Review OCR'd content of the 14 PDFs from Track A

**Chat queue:**
- Caselaw corpus audit brief (verify `legal_caselaw_federal` has 0 points; ingest path needed?)
- Phase B drafting orchestrator brief

**Closed today:**
- PR #277 BRAIN incident RESOLVED
- PR #278 Phase A1 spark-1 legal overlays MERGED
- PR #280 Phase A5 BRAIN+RAG probe MERGED (revised contracts)
- PR #281 Track A Case II briefing v2 MERGED
- Issue #279 filed (alembic merge prereq)
- Issue #282 filed (privileged collection coverage)

---

## 8. Open questions for operator (queue, oldest first)

These hold until operator answers. Clear when resolved.

1. ADR-005 — per-service postgres role pattern: ratify spark-2's deviation from 004 contract or roll back to canonical?
2. M3 brief revision app role: `fortress_api` (canonical) or `fgp_app` (matches spark-2 reality)?
3. Spark-7+ acquisition timeline — when does Acquisitions or Wealth get its own dedicated app spark?
4. Council deliberation BRAIN cutover — separate PR after ADR-003 Phase 1 lands; operator approves order?
5. Phase B drafting orchestrator scope — full Case II Build Plan B6 spec, or narrower MVP first?

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

---

## 10. Glossary (terms used loosely across sessions)

- **BRAIN** — Llama-3.3-Nemotron-Super-49B-FP8 served via NIM 2.0.1 on spark-5 (today)
- **TITAN** — DeepSeek-R1 671B (placement TBD post-ADR-003)
- **SWARM** — qwen2.5:7b on spark-2 Ollama (lightweight routing/triage)
- **ARCHITECT** — Google Gemini cloud (planning only, NEVER privileged data)
- **Council** — multi-persona deliberation engine on spark-2
- **Captain** — IMAP email-intake daemon on spark-2
- **Sentinel** — NAS document indexer on spark-2
- **FLOS** — Fortress Legal Operating System (the dispatcher + worker stack)
- **Case I** — `7il-v-knight-ndga-i` — closed 2:21-CV-00226 (judgment against)
- **Case II** — `7il-v-knight-ndga-ii` — active 2:26-CV-00113 (this is the matter)

---

## Amendment log

| Date | Version | Changes |
|---|---|---|
| 2026-04-29 | v1 | Initial master plan |

---

End of master plan.
