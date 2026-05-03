# MASTER PLAN — Fortress Prime

**Operator:** Gary Knight
**Established:** 2026-04-29
**Updated:** 2026-05-03 (v1.9 — Dochia v0.3 whipsaw research closed)
**Cadence:** Updated on change

---

## 0. How to use this document

Durable strategic doc that drives daily priority calls for Fortress Prime. Supersedes session-by-session memory.

**Every new chat opens with:** "Read MASTER-PLAN.md" — alignment ritual. Operator pastes status changes since last update.

**Updates only on change:** P0 add/close/escalate, priority shift, blockers, case-clock milestones, ADR locks, durable lessons from incidents.

**This document IS the contract** between operator and any assistant.

---

## 1. Mission

Build Fortress Legal as a sovereign system that out-prepares a top-3 white-shoe firm on **7 IL Properties, LLC v. Knight** Case II (NDGA 2:26-CV-00113-RWS).

Sovereign inference is the foundation. Without it, every privileged document touches Anthropic / OpenAI / Google APIs.

Two interlocking tracks:
- **Inference platform** — BRAIN, TITAN, EMBED, RAG, retrieval, deliberation
- **Legal application** — case-briefing, retrieval, deliberation, drafting

Both advance toward: white-shoe-grade output produced by single operator on his own hardware.

---

## 2. The 7IL Case II case-clock

| Field | Value |
|---|---|
| Matter | 7 IL Properties, LLC v. Knight |
| Court | NDGA Federal, 2:26-CV-00113-RWS |
| Case slug | `7il-v-knight-ndga-ii` |
| Plaintiff | 7 IL Properties, LLC (Colorado LLC, federal diversity) |
| Phase | counsel_search |
| Target counsel-hire | **2026-06-15** |
| Today | 2026-05-03 |
| **Days remaining** | **~43** |

**Counsel-hire deliverable:** Phase B v0.1 dry-run on Case I produces v3 brief exceeding v2. Validation passes → Phase B runs on Case II.

---

## 3. Permanent priority order

| Priority | Track |
|---|---|
| **P0** | Anything blocking 7IL Case II counsel hire |
| **P1** | Inference platform reliability |
| **P2** | Legal application capabilities |
| **P3** | Audit + sovereignty + architectural debt + config + network debt |
| **P4** | Cross-division scaffolding |
| **P5** | Everything else |

**Tiebreak:** smaller scope wins.
**Promotion:** P3+ becomes P0 if it blocks counsel hire.

---

## 4. Operating discipline

### 4.1 Daily structure

One chat session per day. Open with status. Plan three priorities. Execute. Close with summary.

### 4.2 Operator's three roles

1. Status updates from Claude Code sessions
2. Decisions when forks appear
3. Operator-only work (sweeps, recollections, manual lookups, NIM weight pulls per W3)

### 4.3 Chat assistant's three roles

1. Surface day's three priorities
2. Write briefs Claude Code executes autonomously
3. Defend against rabbit holes

### 4.4 Discipline rules in force

- Action first, no preamble
- One recommendation when answer is clear, not A/B/C
- Short responses beat long
- Time budgets honored or called out
- "No rabbit holes" / "straight line" / "stay on mission" = cut ceremony, execute
- No commentary on effort, duration, stamina
- No meta-observations on quality of work
- Answer the question, give the decision, move on
- When operator needs a click, give exact URL
- **Audit callers before removing any service.** (v1.3 ollama incident.) `grep -rn` against the endpoint pattern.
- **Brief delivery requires SCP.** (v1.3.) Chat-generated briefs MUST be `scp`'d to spark-2.
- **Verify is-cached claims before service start.** (v1.4.) Pre-start validation is config story. Config story always wins.
- **Use IP literals when SSH alias divergence suspected.** (v1.5 NGC install incident.)
- **Verify the layer of effect before applying remediation.** (v1.6 docker MTU.) `daemon.json mtu` is bridge-only. Identify the actor's layer first.
- **Document persistence for every system-state change.** (v1.6.) iptables, sysctl, routes — explicit reboot survival or note as P3.
- **Verify NGC profile class before pulling weights.** (v1.7 ONNX-vs-TensorRT incident.) NIM models often have multiple deployment profiles (TensorRT-engine `cc_12_0-*`, ONNX-runtime `fp16-*`, tokenizer-only). Check the systemd unit's pinned `NIM_MODEL_PROFILE` before pulling. The profiles are not interchangeable.

---

## 5. Architectural foundation (locked)

| ADR | Status | Decision (one line) |
|---|---|---|
| ADR-001 | LOCKED 2026-04-26, amended ADR-003+004 | One spark per *app* division (1=Legal sole; rest co-tenanted on spark-2) |
| ADR-002 | LOCKED 2026-04-29 (resolved by ADR-003) | Captain/Council/Sentinel = Option A, on spark-2 |
| ADR-003 | LOCKED 2026-04-29 + Phase 1 cutover (PR #285) | Sparks 4/5/6 inference cluster; Phase 3 sizing TP=2 + hot replica |
| ADR-004 | LOCKED 2026-04-29 + Amendment v2 (PR #293) | App vs inference boundary. Retain-and-document for spark-3/4. |

### 5.1 Cluster IP truth table (canonical, confirmed 2026-04-29)

| Operator name | Hostname | Mgmt IP | Fabric IPs | Tailscale | Role |
|---|---|---|---|---|---|
| spark-1 | spark-node-1 | 192.168.0.104 | 10.10.10.1, 10.10.11.1 | — | Fortress Legal app |
| spark-2 | spark-node-2 | 192.168.0.100 | (per audit) | 100.80.122.100 | Control plane |
| spark-3 | spark-node-3 | 192.168.0.105 | 10.10.10.3, 10.10.11.3 | — | Vision NIM 8101, Embed NIM 8102 (in flight), Ray, ollama vision-specialist, docling, cached NIM stack |
| spark-4 | spark-node-4 | 192.168.0.106 | 10.10.10.4, 10.10.11.4 | — | Ollama deep-reasoning + SWARM, qdrant-vrs, SenseVoice, Ray |
| spark-5 | spark-node-5 | TBD audit | TBD audit | 100.96.13.99 | BRAIN — Llama-3.3-Nemotron-Super-49B-FP8 NIM 8100 |
| spark-6 | spark-node-6 | TBD audit | 10GbE → ConnectX pending | — | Inference Phase 2 |

### 5.2 Inference tier (DEFCON)

| Tier | Service | Model | Host:Port |
|---|---|---|---|
| SWARM | Ollama (multi-node) | qwen2.5:7b/32b, deepseek-r1:70b, llama3.2-vision:90b/latest, nomic-embed-text, others | spark-2/3/4 :11434 |
| EMBED | NIM | llama-nemotron-embed-1b-v2 | spark-3:8102 (deployment in flight 2026-04-29 — image staged, weights restructured to HF-cache layout, awaiting service start) |
| VISION | NIM | nemotron-nano-12b-v2-vl | spark-3:8101 |
| BRAIN | NIM 2.0.1 | Llama-3.3-Nemotron-Super-49B-FP8 | spark-5:8100 |
| TITAN | TBD | DeepSeek-R1 671B / nemotron-3-super-120b / deepseek-r1-distill-70b (cached on spark-3) | TBD post-Phase 2 |
| ARCHITECT | Cloud | Gemini 2.5+ | external (planning only, NEVER privileged) |

### 5.3 Cluster operational state (NGC + cluster credentials + network)

| Capability | State | Notes |
|---|---|---|
| NGC personal account | `cabin-rentals-of-georgia` org `0884097966485844`, `cabin.rentals.of.georgia@gmail.com` | AI Foundations through 2027-01-23 |
| NGC CLI on spark-2 | INSTALLED 2026-04-29 (v3.41.4 at /usr/local/bin/ngc) | Persistent config at ~/.ngc/config (chmod 0600), telemetry disabled |
| NGC CLI on operator's Mac | INSTALLED 2026-04-29 (May 2022 build, last public Mac release; configured with same key + org) | Required for W3 path until F5 lands |
| Cluster NGC API access | LIMITED — old `/etc/fortress/nim.env` key returns 403; new account key works for image registry but NOT sustained xfiles transfers (F5 defect) | Cluster CANNOT pull weights even with broad key. W3 mandatory. |
| SSH alias canonical | Operator Mac matches §5.1; Claude Code spark-2 harness DIVERGED (`spark-2` → 192.168.0.104 = spark-1) | Reconciliation brief drafted v1.5 |
| Internet egress PMTU | 1420 (80-byte tunnel overhead = WireGuard signature) | F2 + F4 applied. Sustained transfers from xfiles.ngc.nvidia.com still fail (deeper than MTU). F5 root cause investigation pending. |
| iptables MSS clamp persistence | IN-MEMORY ONLY | Brief drafted v1.6 |
| F1 docker daemon.json mtu | 1420 — turns out cosmetic (bridge-only) | Leave; harmless |
| F4 spark-2 enP7s7 host MTU | 1420 in-memory; reverts on reboot | Persistence pending |

### 5.4 NIM deployment pattern (canonical, post embed deployment)

**Until F5 is fixed, all NIM weight pulls go through W3:**

#### W3 procedure (proven 2026-04-29):

1. **Operator's Mac pulls weights via NGC CLI** (clean ISP egress, no tunnel)
2. **Critical: pull the correct profile class.** NIM models have multiple profiles. Check pinned `NIM_MODEL_PROFILE` in systemd unit BEFORE pulling. Common profile classes:
   - `cc_12_0-*` — TensorRT compiled engine for GB10 (single .plan file + memory_footprint.json)
   - `fp16-*` (e.g., `fp16-7af2b653`) — ONNX runtime weights (~150 layer files + supporting)
   - `extra-*` — supporting metadata (triton.yaml, embedding_ranges.npy, VERSION)
   - `tokenizer-*` — tokenizer JSON files
   ONNX profile typically requires three pulls: main weights + extras + tokenizer.
3. **Operator scp's to NAS canonical path:** `/mnt/fortress_nas/nim-cache/nim/<model>/nim-weights-cache/ngc/hub/<flat-NGC-CLI-dirs>/`
4. **Claude Code restructures flat NGC layout into HF-cache layout on NAS** (Path B):
   - Source: flat `*_v<profile>/<files>` from NGC CLI download
   - Target: HuggingFace `models--<org>--<team>--<model>/blobs/<hash>/` + `snapshots/<commit>/<symlinks>`
   - Reference: BRAIN + Vision NIM cache structures on NAS for canonical example
   - Restructure script must be: atomic mv, dedup by content hash, idempotent on retry, preserves source backup
5. **Inference cluster spark loads from NAS-mounted weights** — no NGC traffic from spark
6. **Service starts with NAS-mounted weights**, no runtime NGC fetches

**Inference cluster sparks (3, 4, 5, 6) do NOT need NGC API access.** Sovereignty-preserving.

**Rack-side direct-NAS-mount alternative** (when operator on home LAN):
- Operator's Mac mounts NAS over SMB directly (`smb://<NAS-IP>/<share>`)
- NGC CLI pulls weights to NAS mount directly (bypasses scp middleman)
- Half the bandwidth path of scp-via-spark-2
- Procedure runbook: `docs/operational/runbooks/rack-side-nas-mount-nim-pull.md`

---

## 6. Active work tracks

### 6.1 7IL Case II counsel-hire (P0)

| Item | Status |
|---|---|
| Argo / DRA engagement letter | On NAS as PDF; surface via NAS legal corpus pipeline |
| 14 OCR'd PDFs review | Deferred until Phase B v0.1 dry-run validates pipeline |
| Sections 4 / 5 / 8 synthesis | Phase B v0.1 dry-run brief drafted v1.4 |
| Brief v3 assembly | Phase B orchestrator (PR #290) |
| Counsel pitch | Operator action, post v3 |

### 6.2 Inference platform (P1)

| Item | Status |
|---|---|
| BRAIN incident INC-2026-04-28 | RESOLVED PR #277 |
| Phase A1 spark-1 legal overlays | MERGED PR #278 |
| Phase A5 BRAIN+RAG probe | MERGED PR #280 |
| ADR-003 Phase 1 LiteLLM cutover | MERGED PR #285 |
| Council consumer cutover | MERGED PR #289 |
| Phase B drafting orchestrator v0.1 | MERGED PR #290 |
| NIM stack audit | MERGED PR #291 |
| NGC catalog refresh | MERGED PR #292 (BLOCKED HTTP 400) |
| ADR-004 amendment v2 | MERGED PR #293 |
| llama-nemotron-embed deployment | IN FLIGHT — 6 STOPs handled, image staged, W3 ONNX weights restructured to HF-cache layout, awaiting service start |
| ADR-003 Phase 2 Spark-6 cable cutover | BLOCKED on cable |
| Caselaw federal ingestion | PENDING — brief drafted v1.4 |
| TIER 1 NIM batch-pull (parse, page-elements, table-structure, graphic-elements, reranker) | PENDING — brief drafted v1.6, REVISION needed for W3-execution path (drafted v1.7) |
| TITAN service path | UNKNOWN — DeepSeek-R1 / nemotron-3-super-120b / distill-70b candidates cached |

### 6.3 Legal application capabilities (P2)

| Item | Status |
|---|---|
| Phase B v0.1 dry-run on Case I | PENDING — brief drafted v1.4 |
| Phase B retrieval cutover to legal-embed | PENDING — gated on embed deployment |
| Council BRAIN integration | DONE PR #289 |
| Qdrant legal collections reindex | PENDING — gated on embed deployment |
| B1-B5 vault / cross-case / PACER / case-opening | PENDING |

### 6.4 Audit + sovereignty (P3)

| Item | Status |
|---|---|
| A-02 cloud legal inference | RESOLVED PR #285 + #289 |
| S-01 UFW disabled spark-2 | OPEN |
| A-01 Stripe webhook double-settlement | OPEN |
| D-02 trust ledger triggers missing | OPEN |
| Issue #221 PAT scope upgrade | OPEN |
| Issue #282 privileged collection coverage | OPEN |
| 2026-04-29 ollama removal incident | RESOLVED PR #293 |
| 2026-04-29 embed deployment 6-STOP journey | IN FLIGHT — Principles 6, 7, 8, 9 captured |
| 2026-04-29 SSH alias divergence | IN FLIGHT — reconciliation brief drafted v1.5 |
| 2026-04-29 PMTU + sustained-transfer defect | IN FLIGHT — F2/F4 applied; F5 root cause investigation drafted v1.6 |

### 6.5 Financial Division — MarketClub / Dochia replacement (P4-A)

**Objective:** Replace discontinued MarketClub / INO Trade Triangles with a sovereign Financial Division app that is more auditable, explainable, and portfolio-aware than the original product.

**Outside fact locked 2026-05-02:** MarketClub / INO.com discontinued on **2026-04-20**. This is no longer an adjunct dashboard; it is a replacement product track.

**Current spark-2 asset inventory:**

| Asset | State |
|---|---|
| Code root | `/home/admin/Fortress-Prime/crog-ai-backend` |
| Database schema | `hedge_fund` in `fortress_db` |
| Historical MarketClub observations | 24,204 daily observations, 368 unique tickers |
| EOD bars | 169,100 rows across 354 tickers, 2024-04-29 through 2026-04-24 |
| Parser runs | 3 completed runs: NAS corpus + IMAP harvest |
| Current parameter sets | Production `dochia_v0_estimated`; non-production candidate `dochia_v0_2_range_daily` |
| Signal scores | 328 fresh latest rows written for 2026-04-24 |
| Signal transitions | 1,005 recent rows written for 2026-03-25 through 2026-04-24 |
| Legacy watchlist context | `watchlist` has 431 rows; `market_signals` has 1,105 rows through 2026-02-12; read-only grant applied for app overlays |
| Calibration baseline | 24,204 daily observations; 91.44% coverage; 62.05% carried daily color accuracy; 40.67% exact alert match; 52.54% ±3-day alert match; score MAE 43.94 |
| Calibration sweep | Best validated candidate: 3-session intraday range trigger; exact alert F1 76.64% vs 44.59% baseline, exact recall 91.93% vs 40.67%, precision 65.71%, ±3-day recall 95.21%; holdout after 2025-09-25 scores 83.18% F1 vs 46.26% baseline |
| v0.3 guardrail research | Closed as research-only: simple guardrails, ATR/cooldowns, ticker clusters, and rolling whipsaw suppressors all miss the promotion gate. Rolling date-safe holdout confirms suppression destroys recall: no candidate keeps at least 95% of raw v0.2 F1; strongest reducers cut 95%+ of events but stay below 7.41% F1 |
| Candidate persisted state | v0.2 candidate has 328 `signal_scores` rows and 1,624 `signal_transitions` rows under non-production parameter set; internal API/BFF selector live for scanner, transitions, symbol detail, Portfolio Lens, and chart overlays |
| Candidate lane comparison | v0.2 bullish lane unchanged at 129, risk unchanged at 47, re-entry 164→145, mixed 202→203, 61 daily states/scores change |
| Promotion contract | Fresh Dochia scores still staged; legacy `market_signals` remains contextual until calibration/promotion |
| UI state | Hedge Fund route live in production at `https://crog-ai.com/financial/hedge-fund` with scanner, synced chart overlays, alert feed, symbol panel, Portfolio Lens, Calibration Baseline, and internal Production/v0.2 Range toggle |

**Signal doctrine:**

| Layer | MarketClub meaning | Dochia v1 implementation stance |
|---|---|---|
| Daily | Short-term timing, prior 3-day high/low break | Use historical truth corpus for calibration and generated ongoing signals |
| Weekly | Intermediate entry/exit, prior 3-week high/low break | Generate from EOD bars; label as Dochia-derived, not original INO truth |
| Monthly | Long-term trend, prior 3-month high/low break | Generate from EOD bars; label as Dochia-derived, not original INO truth |
| Score | -100 to +100 trend strength | Start deterministic; calibrate; only promote if out-of-sample beats baseline |

**Build sequence:**

1. Deterministic Trade Triangle engine: pure daily/weekly/monthly state calculation from EOD bars. Complete initial slice.
2. Database scorer: populate `hedge_fund.signal_scores` and `signal_transitions` idempotently. Complete initial fresh batch.
3. Calibration harness: compare generated daily state/score against 24,204 MarketClub observations. Baseline complete; refinement remains.
4. Production contract: promote approved signals to `hedge_fund.market_signals`.
5. API surface: scanner, symbol detail, portfolio board, alert inbox, backtest lab, model health. Scanner, symbol detail, chart data, alert feed, watchlist-candidate lanes, and daily calibration endpoint complete.
6. Command Center UI: Financial / Hedge Fund route with sober cockpit UX, not gamified retail nudges. First route, chart overlays, Portfolio Lens, and Calibration Baseline complete at `/financial/hedge-fund`.

**Product principles:**

- Every signal must explain why it fired: channel high/low, close, lookback window, prior state.
- Default to **sidelines** when timeframes conflict.
- Show backtest and whipsaw risk before action.
- No live brokerage execution until risk, audit, auth, and compliance review exist.
- Do not call generated weekly/monthly states "MarketClub truth"; they are Dochia-derived.
- Avoid gamified trading prompts; build an evidence cockpit.

**Immediate next step:** Build a user-facing Whipsaw Risk / Backtest panel in the Hedge Fund cockpit so noisy names are visible and explainable without suppressing the validated v0.2 daily range signal.

### 6.6 Architectural follow-ups

| Item | Issue | Priority |
|---|---|---|
| Spark-4 RDMA enumeration debug | #294 | P3 |
| NIM ASR ARM64 monitor | #295 | P3 |
| Doc/config reconciliation | #298 (brief drafted v1.4) | P3 |
| NGC enumerator API surface fix | (brief drafted v1.4) | P3 |
| SSH alias reconciliation | (brief drafted v1.5) | P3 |
| iptables MSS clamp persistence | (brief drafted v1.6) | P3 |
| F4 host MTU persistence | (note in cluster network topology brief) | P3 |
| Cluster network topology + F5 root cause | (briefs drafted v1.6) | P3 |
| Lessons-learned addendum (Principles 7+8+9) | (brief drafted v1.6, P9 added v1.7) | P3 |
| Rack-side direct-NAS-mount procedure | (brief drafted v1.6) | P3 |
| Spark-5 + spark-6 IP audit | (master plan track) | P3 |
| Cluster NGC key migration to broader-scope | (master plan track) | P3 |
| Ollama consolidation migration | #296 | P4 |
| ADR-005 per-service postgres role pattern | (master plan track) | P4 |
| M3 brief revision | (master plan track) | P4 |
| Spark-1 role parity audit | (master plan track) | P4 |
| Issue #279 alembic-merge | OPEN | P4 |
| VRS Qdrant migration trigger | #297 | P5 monitoring |
| NAS quarantine cache cleanup policy | (master plan track) | P5 |
| nim.env permissions divergence | (fold into #298) | P3 |

---

## 7. Today's snapshot (2026-05-03 — MarketClub/Dochia activation)

**New Financial Division build track activated.**

**Research findings:**
- MarketClub / INO.com discontinued 2026-04-20.
- MarketClub doctrine: stocks/ETFs use monthly trend + weekly timing; futures/forex use weekly trend + daily timing; daily is lowest signal timeframe.
- Chart Analysis Score is trend strength from five timing thresholds and moving averages.
- Spark-2 has enough historical daily MarketClub data to build a replica/calibration harness, but not enough original weekly/monthly truth to claim exact INO weekly/monthly replication.

**Build decision:**
- Build Dochia as an auditable replacement, not a cosmetic clone.
- Start with deterministic daily/weekly/monthly channel-break signals.
- Calibrate daily signal/score against the 24,204 historical observations.
- Generate weekly/monthly states from EOD bars and label them as Dochia-derived.
- Surface the app under Financial / Hedge Fund once API contract exists.

**Current implementation action:**
- Added first pure signal-engine slice to `crog-ai-backend`.
- Added read-only preview and idempotent sync scripts for latest scores and recent transition events.
- Wrote 328 current `signal_scores` rows, all dated 2026-04-24.
- Wrote 1,005 recent `signal_transitions` rows from 2026-03-25 through 2026-04-24.
- Added FastAPI endpoints for latest scores, recent transitions, and symbol detail explainability.
- Added FastAPI `watchlist-candidates` endpoint with bullish alignment, risk alignment, re-entry, and mixed-timeframe lanes.
- Added read-only daily calibration harness and FastAPI endpoint. Baseline: 24,204 observations, 91.44% coverage, 62.05% daily color accuracy, score MAE 43.94.
- Added read-only daily parameter sweep harness and candidate validation report. Best candidate is the 3-session intraday range trigger: exact alert F1 76.64%, exact recall 91.93%, precision 65.71%, ±3-day recall 95.21%, and carried-state agreement 94.91%. Chronological holdout after 2025-09-25 scores 83.18% F1 vs 46.26% baseline.
- Registered non-production `dochia_v0_2_range_daily` and wired daily trigger mode through score/transition previews. Dry run: 328 candidate score rows, 1,624 candidate transitions since 2026-03-25, bullish/risk lane counts unchanged, 61 daily states/scores changed.
- Persisted v0.2 candidate scores/transitions under non-production parameter set and added internal `parameter_set` selectors to scanner, transitions, symbol detail, Portfolio Lens, and chart-overlay API reads. Production remains default.
- Added v0.2 chart-overlay parity: the symbol chart now follows the active Production/v0.2 Range mode, using close-break daily events for production and range-trigger daily events for the v0.2 candidate.
- Added read-only v0.2 promotion-review harness covering top-lane churn, recent whipsaw/transition pressure, and chart-level candidate event deltas.
- Ran first v0.2 promotion-review report. Decision: do not promote range trigger yet. Risk lane is stable, but re-entry lane churn is 66.7%, mixed-timeframe churn is 52.9%, top whipsaw tickers show 8-9 candidate transitions in the 30-day window, and reviewed chart overlays add up to 29 candidate-only daily events on some symbols.
- Added and ran read-only v0.3 range-trigger guardrail research for break buffers, same-direction close confirmation, ATR-normalized buffers, trailing per-symbol adaptive cooldowns, return-conditioned outcomes, ticker whipsaw clusters, chronological ticker-cluster holdout, and rolling date-safe whipsaw suppressors. Decision: do not persist any v0.3 suppression filter; expose whipsaw risk and backtest evidence in the app instead.
- Added internal Production/v0.2 Range toggle to the Command Center Hedge Fund page and promoted the production frontend build.
- Added chart-data endpoint and chart overlay with close, daily/weekly channel bands, and generated triangle event markers.
- Refined calibration metrics to separate carried-state agreement from exact new-alert agreement: 40.67% same-day alert match and 52.54% ±3-day alert match.
- Added Command Center Financial / Hedge Fund route at `/financial/hedge-fund` with scanner, chart overlay, Portfolio Lens, Calibration Baseline, alert feed, and symbol explainability panel.
- Applied read-only Hedge Fund legacy-table grants for the app role; grant SQL tracked in `deploy/sql/marketclub_legacy_read_grants.sql`.
- Added and enabled `crog-ai-backend.service` on spark-node-2 for the Dochia signal API.
- Promoted the Command Center production build and restarted `crog-ai-frontend.service`; `https://crog-ai.com/financial/hedge-fund` returns 200.
- Verification passed: 28 backend tests, ruff, backend health, focused UI tests, focused UI lint, TypeScript, production Command Center build, service status, and live backend/BFF reads for both production and v0.2 candidate selectors.

### 7.1 Prior snapshot (2026-04-29 — embed deployment closing)

**Massive day. 13 PRs merged + 5 issues filed + 13 briefs drafted + 4 incidents handled.**

**PRs merged on main today:**
- #277-#293 (15 commits)

**Issues filed today:**
- #294 spark-4 RDMA debug (P3)
- #295 NIM ASR ARM64 monitor (P3)
- #296 ollama consolidation (P4)
- #297 VRS Qdrant migration trigger (P5)
- #298 doc/config reconciliation (P3)

**Incidents today:**

1. **2026-04-29 ollama removal** — 10 min downtime, atomic rollback, Principles 1-5 captured (PR #293)

2. **2026-04-29 embed deployment 6-STOP journey:**
   - STOP 1 §5.2: port 8101 collision with Vision NIM → resolved by moving to 8102
   - STOP 2 §5.3: NIM_MODEL_PROFILE=auto rejected → resolved by pinning to GB10 profile
   - STOP 3 weights: NGC API key 403 → resolved via NGC CLI install + cabin-rentals-of-georgia org key
   - STOP 4 weights pull cluster-side fails: F1 daemon.json (cosmetic), F2 iptables MSS clamp (TLS handshake fixed), F4 host MTU (still fails sustained transfer)
   - STOP 5 W3 weights wrong profile: pulled cc_12_0 TensorRT, systemd unit pinned to fp16-7af2b653 ONNX → resolved by re-pull on Mac of correct three ONNX versions
   - STOP 6 layout mismatch: NGC CLI flat layout vs NIM HF-cache requirement → resolved by Path B restructure script on NAS
   - Principles 6, 7, 8, 9 captured

3. **2026-04-29 SSH alias divergence** — Operator's `spark-2` ≠ Claude Code's `spark-2`. Reconciliation brief drafted

4. **2026-04-29 PMTU + sustained-transfer cluster defect** — F2/F4 applied, F5 root cause investigation pending

**Briefs drafted, staged for SCP to spark-2 (13 total):**
- `MASTER-PLAN-v1.7.md` (this doc, supersedes v1.6)
- `embed-deployment-final-stretch-brief.md`
- `ngc-enumerator-api-surface-fix-brief.md`
- `issue-298-doc-config-reconciliation-brief.md`
- `phase-b-v01-dry-run-brief.md`
- `caselaw-federal-ingestion-brief.md`
- `ssh-alias-reconciliation-brief.md`
- `lessons-learned-addendum-brief.md` (extended for Principle 9)
- `cluster-network-topology-brief.md`
- `iptables-mss-persistence-brief.md`
- `tier-1-nim-batch-pull-brief.md` (REVISION needed for W3 — drafted v1.7)
- `rack-side-nas-mount-procedure-brief.md`
- `f5-root-cause-investigation-brief.md`

**Operator queue (deferred):**
- Personal Gmail/Mac sweep — surface via NAS pipeline
- Review OCR'd content of 14 PDFs — post Phase B v0.1 dry-run
- Edit `~/.ssh/config` on Mac to confirm canonical alias map

**Chat queue for next session:**
- Embed deployment service start + health probe + LiteLLM alias + quality validation
- Issue #298 doc/config reconciliation
- NGC enumerator fix
- Phase B v0.1 dry-run on Case I
- Caselaw federal ingestion
- SSH alias reconciliation
- Lessons-learned addendum (Principles 7+8+9)
- Cluster network topology
- iptables MSS persistence
- Rack-side NAS mount procedure
- F5 investigation surface
- TIER 1 NIM batch-pull (after embed validates)
- Spark-5 + spark-6 IP audit
- Cluster NGC key migration
- Qdrant reindex with legal-embed
- Phase B retrieval cutover to legal-embed
- TITAN service path

---

## 8. Open questions for operator

1. ADR-005 — per-service postgres role pattern: ratify or roll back?
2. M3 brief revision app role: `fortress_api` or `fgp_app`?
3. Spark-7+ acquisition timeline?
4. Caselaw federal ingestion — operator authorize CourtListener bulk pull?
5. Cluster-canonical NGC key migration — replace narrow `/etc/fortress/nim.env` key with broad `cabin-rentals-of-georgia` key?
6. TITAN service candidate — DeepSeek-R1 671B vs nemotron-3-super-120b vs distill-70b?
7. SSH alias reconciliation: file new issue OR fold into #298?
8. F5 root cause investigation: Mikrotik or Tailscale or both?
9. cc_12_0 TensorRT backup files on NAS: keep indefinitely or delete after embed validates?

---

## 9. Anti-patterns to refuse

- **Greenfield building when migration-additive is correct.**
- **Web-UI multi-step workflows when Claude Code can execute.**
- **Searching for tokens / credentials / dotfiles in conversation.**
- **A/B/C/D options when answer is clear.**
- **Long responses to short questions.**
- **Re-explaining context that's in this document.**
- **Treating any P5 item as urgent.**
- **Acting on doc story without verifying config story.** (v1.3 ollama incident.)
- **Writing a brief in chat without verifying SCP to spark-2.** (v1.3.)
- **Trusting brief-asserted state without runtime verification.** (v1.4 embed deployment.)
- **Trusting SSH aliases as canonical across clients.** (v1.5 NGC install incident.)
- **Applying remediation at the wrong layer.** (v1.6 docker MTU.) `daemon.json mtu` does NOT fix daemon outbound.
- **Treating iptables/sysctl changes as durable.** (v1.6.) In-memory only on Ubuntu/Debian.
- **Pulling NIM weights without verifying profile class first.** (v1.7 ONNX-vs-TensorRT incident.) Check the pinned `NIM_MODEL_PROFILE` in the systemd unit before pulling. Profiles are not interchangeable; TensorRT engine bytes don't substitute for ONNX layer weights or vice versa.
- **Assuming NGC CLI download produces HF-cache layout directly.** (v1.7.) NGC CLI produces flat directory of files. NIM containers expect HuggingFace cache layout (`models--<org>--<team>--<model>/blobs/<hash>/` + `snapshots/<commit>/<symlinks>`). Restructure step required.

---

## 10. Glossary

- **BRAIN** — Llama-3.3-Nemotron-Super-49B-FP8 NIM 2.0.1, spark-5:8100
- **VISION** — nemotron-nano-12b-v2-vl NIM, spark-3:8101
- **EMBED** — llama-nemotron-embed-1b-v2 NIM, spark-3:8102 (deployment in flight)
- **TITAN** — TBD; candidates DeepSeek-R1 671B / nemotron-3-super-120b / distill-70b
- **SWARM** — Multi-node Ollama (spark-2/3/4) per fortress_atlas.yaml
- **ARCHITECT** — Google Gemini cloud (planning only, NEVER privileged)
- **Council** — multi-persona deliberation engine on spark-2 (sovereign post #289)
- **Captain** — IMAP email-intake daemon on spark-2
- **Sentinel** — NAS document indexer on spark-2
- **FLOS** — Fortress Legal Operating System
- **Case I** — `7il-v-knight-ndga-i` — closed 2:21-CV-00226
- **Case II** — `7il-v-knight-ndga-ii` — active 2:26-CV-00113
- **F1 / F2 / F4 / F5** — Network remediation paths from 2026-04-29 PMTU investigation
- **W1 / W2 / W3** — Weights pull paths. W1 = NGC pull on spark-2 (failed for sustained xfiles transfers per F5). W2 = NGC fetch on inference spark direct (rejected as non-sovereign). W3 = operator pulls on Mac, scp to NAS (proven 2026-04-29).
- **HF-cache layout** — HuggingFace model cache directory structure: `models--<org>--<team>--<model>/blobs/<hash>` content-addressable + `snapshots/<commit>/<symlinks>`. NIM containers expect this; NGC CLI produces flat layout. Restructure step bridges them.
- **NIM profile class** — Per-model deployment artifact: `cc_12_0-*` (TensorRT engine), `fp16-*` (ONNX runtime), `extra-*` (metadata), `tokenizer-*`. Not interchangeable. Verify systemd unit's pinned `NIM_MODEL_PROFILE` before pulling.

---

## Amendment log

| Date | Version | Changes |
|---|---|---|
| 2026-04-29 | v1 | Initial master plan |
| 2026-04-29 | v1.1 | Post ADR-004 PR #286 |
| 2026-04-29 | v1.2 | Post ADR-004 amendment v2 PR #293 |
| 2026-04-29 | v1.3 | End-of-day snapshot — 13 PRs merged, 5 issues filed |
| 2026-04-29 | v1.4 | Late-session embed STOPs — Principle 6 |
| 2026-04-29 | v1.5 | Late-late-session — SSH alias divergence, NGC CLI installed, IP truth table |
| 2026-04-29 | v1.6 | Closing-session — F2 PMTU fix, W1 pull pattern, Principles 7+8, 4 new briefs |
| 2026-04-29 | v1.7 | Embed deployment closing — full 6-STOP journey, W3 weights path proven, Principle 9 (NIM profile class verification), Principle 10 anti-pattern (NGC CLI layout vs HF-cache), §5.4 NIM deployment pattern fully documented end-to-end, 13 briefs total staged for next session |

---

End of master plan.
