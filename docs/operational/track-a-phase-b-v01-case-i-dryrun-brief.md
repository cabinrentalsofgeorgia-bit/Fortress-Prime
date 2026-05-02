# Track A — Phase B v0.1 Dry-Run on Case I (Super-120B Baseline)

**Target:** Claude Code on spark-2
**Branch:** `feat/track-a-phase-b-v01-case-i-dryrun-2026-04-30`
**Date:** 2026-04-30
**Operator:** Gary Knight
**Driver:** Phase 9 (PR #322) reviewed. TP=2 frontier endpoint live, 5/5 aliases hot, 7 Council reasoning seats routed to Super-120B. Soak clock active but does NOT gate Case II briefing work. Track A produces the v3 Case I brief that proves capability and the citation-density baseline that informs Wave 4 prompt tuning.
**Stacks on:**
- PR #322 (Phase 9 alias surgery + BRAIN retirement + soak instrumentation)
- PR #321 (ADR-007 TP=2 deployment, draft, soak gate)
- Phase B v0.1 orchestrator (PR #290 merged)
- Existing v2 Case I brief baseline (per MASTER-PLAN v1.7 §6.1 — "v3 brief that beats v2")
**Resolves:** MASTER-PLAN v1.7 §6.1 — "Phase B v0.1 dry-run on Case I — PENDING"

---

## 1. Mission

Run Phase B v0.1 orchestrator end-to-end on Case I (`7il-v-knight-ndga-i`, closed_judgment_against, no risk). Produce v3 brief. Capture per-section citation density. Compare v3 against v2 baseline. Surface the empirical curve that drives Wave 4 prompt tuning for Case II.

This is the proof point per MASTER-PLAN §6.1: pass on Case I → Phase B unlocks for Case II.

This is NOT a deployment brief. No new services. No code changes. Pure execution + evaluation against existing infrastructure.

---

## 2. Why Case I and not Case II directly

- **Case I is closed.** No risk if v3 is wrong. Case II is active, counsel-search, 46 days to target hire.
- **Case I has v2 baseline** for comparison. Case II has no prior brief.
- **Case I corpus is rich.** 1,396 vault docs ingested, 91,245 retrievable points in `legal_ediscovery`. Stresses retrieval and synthesis depth.
- **Case I's Section 5 (Defenses) was where Nano-9B failed and Super-120B's Phase 7 smoke showed precision-filter behavior.** Track A validates that behavior on the FULL section pipeline, not just the Phase 7 smoke prompt.
- **Operator's brief targets are calibrated against this case.** The 47-day Case II clock starts when v3 quality is confirmed; Track A is the start of that clock.

---

## 3. Scope

**In scope:**
- Run Phase B v0.1 orchestrator against `7il-v-knight-ndga-i` corpus
- Generate full 10-section brief (TEN_SECTIONS structure)
- Capture per-section: token counts, citation counts, unique source counts, format compliance, finish_reason, wall time, tok/s
- Generate side-by-side comparison table v2 (existing baseline) vs v3 (Super-120B)
- Per-section diff scoring (where does v3 win, where does v3 lose, where parity)
- Citation density curve per section type (enumerative vs argumentative vs mechanical)
- Operator review pack: surface v3 brief inline + comparison table + per-section diff

**Out of scope:**
- Any service modification
- Any model deployment
- Wave 3 retrieval pipeline (reranker, NeMo Extraction)
- Case II work
- Phase B v0.4 spec writing
- NeMo Evaluator deployment (would be Wave 5; this Track uses simpler scoring)

---

## 4. Pre-flight

### 4.1 State checks

```bash
# Branch hygiene
git fetch origin
git status
git log origin/main..HEAD --oneline

# Soak clock still healthy?
ssh admin@192.168.0.100 'tail -50 /mnt/fortress_nas/audits/phase-9-soak/$(date +%Y-%m-%d).log 2>/dev/null'
# Confirm no halt triggers fired since Phase 9 merge

# Frontier endpoint healthy?
ssh admin@192.168.0.100 '
  curl -fsS --max-time 10 http://10.10.10.3:8000/v1/health/ready
  curl -fsS http://localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"legal-reasoning\", \"messages\": [{\"role\":\"user\",\"content\":\"PONG\"}], \"max_tokens\": 10}" \
    | jq ".choices[0].message.content"
'
# Expected: ready / "PONG"
```

If anything fails: STOP, surface, do not proceed.

### 4.2 Locate Phase B v0.1 orchestrator

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  find . -path "*phase_b*" -type f \( -name "*.py" -o -name "*.md" \) 2>/dev/null | grep -v __pycache__ | grep -v ".git/"
  find . -name "*orchestrator*" -path "*legal*" -type f 2>/dev/null | grep -v __pycache__
  grep -rn "TEN_SECTIONS" --include="*.py" 2>/dev/null | grep -v __pycache__ | head -10
'
```

Surface:
- Phase B v0.1 entry point script path
- TEN_SECTIONS definition path
- Any CLI flags (case slug, output dir, dry-run mode)
- v2 baseline brief location on NAS

### 4.3 Locate v2 Case I baseline brief

```bash
ssh admin@192.168.0.100 '
  find /mnt/fortress_nas -path "*7il-v-knight-ndga-i*" -name "*v2*" -o -name "*Attorney_Briefing*" 2>/dev/null | head -20
  find /mnt/fortress_nas -path "*7il-v-knight-ndga*" -name "*.md" 2>/dev/null | head -30
  find /mnt/fortress_nas -path "*case-briefing*" -name "*.md" 2>/dev/null | head -20
'
```

Surface paths to:
- v2 Case I attorney briefing package (the baseline to beat)
- Any prior partial briefs / sections
- The case-briefing build plan + spec notes (if not already in project knowledge)

### 4.4 Pre-flight gate

**STOP after pre-flight enumeration.** Surface findings inline. Operator confirms:
- Phase B v0.1 entry point path
- v2 baseline location
- Soak still green
- Frontier still healthy

Operator greenlights before §5 execution.

---

## 5. Execution

### 5.1 Output staging

```bash
ssh admin@192.168.0.100 '
  STAMP=$(date +%Y%m%dT%H%M%SZ)
  RUN_DIR=/tmp/track-a-case-i-v3-${STAMP}
  mkdir -p ${RUN_DIR}/sections
  mkdir -p ${RUN_DIR}/raw
  mkdir -p ${RUN_DIR}/metrics
  echo "RUN_DIR=${RUN_DIR}" > /tmp/track-a-current-run.env
  cat /tmp/track-a-current-run.env
'
```

Final assembled v3 brief lands at:
`/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_I_v3_<STAMP>.md`

### 5.2 Per-section invocation pattern

For each section in TEN_SECTIONS, run Phase B v0.1 orchestrator with the appropriate alias per Wave 7 routing:

| Section | Content | Alias | Reasoning effort | Max tokens |
|---|---|---|---|---|
| 1. Case Summary | Header + summary paragraph | `legal-drafting` | medium | 2000 |
| 2. Critical Timeline | Dated event list | (deterministic from `legal.deadlines` + curated chronology — orchestrator handles, no LLM) | — | — |
| 3. Parties & Counsel | Tables of plaintiff/defendant/counsel | `legal-drafting` | medium | 3000 |
| 4. Claims Analysis | Per-count doctrinal analysis | `legal-reasoning` | high | 6000 |
| 5. Defenses | Defense theories with thin/contradicted flagging | `legal-reasoning` | high | 6000 |
| 6. Evidence Inventory | Structured manifest of vault + email | `legal-drafting` | medium | 5000 |
| 7. Email Intelligence | Categorized email findings | `legal-summarization` | low | 3000 |
| 8. Financial Exposure | Damages range + calculation | `legal-summarization` | low | 2000 |
| 9. Strategy | Sequencing + leverage + risk weighting | `legal-reasoning` | high | 5000 |
| 10. Filing Checklist | Procedural action list | `legal-drafting` | medium | 2000 |

**For each section, capture:**
- Output text → `${RUN_DIR}/sections/section-N.md`
- Raw API response (full JSON) → `${RUN_DIR}/raw/section-N.json`
- Wall time start/end
- Token counts (input, output, reasoning if separate, total)
- finish_reason
- citation count + unique source count (regex match on section text against citation patterns)
- First-person bleed in content (count of "I will", "I'll", "let me", "my analysis")
- `<think>` block leakage in content (count)

### 5.3 Citation extraction methodology

Per-section citation count uses the same regex sweep that Phase 7 smoke used. Capture:

- Total citation tokens (exhibit references, paragraph numbers, doc IDs, archive IDs, email IDs, case numbers)
- Unique sources (deduplicate to source documents, not individual cite tokens)

Example patterns:
- Complaint references: `¶ \d+`, `Ex\. [A-Z]`, `Exhibit [A-Z]`, `Doc\. \d+`
- Email refs: `email #\d+`, `archive ID \d+`
- Vault refs: `vault doc \d+`, file path patterns
- Case law: standard reporter citations (`\d+ F\.\d+ \d+`, `\d+ S\.E\.\d+ \d+`)

Surface methodology in metrics output. Methodology must be identical to v2 baseline scoring or comparison is invalid; if v2 used different scoring, score v2 with the same methodology under Track A and use the rescored value.

### 5.4 Run order

Run sections in dependency order:
1. Section 2 first (deterministic, no LLM call) — sanity check the timeline pipeline
2. Section 1, 3, 6 (mechanical) — drafting tier shakedown
3. Section 7, 8 (mechanical) — summarization tier shakedown
4. Section 4, 5, 9 (synthesis) — reasoning tier where the model earns its keep
5. Section 10 (filing checklist) — depends on 4/5/9 strategy outputs

This order gives early failure signal on cheap sections before spending wall time on expensive synthesis sections. If §1 or §3 fails, the run halts before burning Council reasoning cycles.

### 5.5 Halt triggers during run

Halt the run + surface findings if any:
- Format compliance regression on any section (first-person bleed in content, `<think>` leakage in content) — Nano-9B failure mode reappearing
- `finish_reason=length` on any section (means max_tokens too low; tune and retry just that section)
- `finish_reason=content_filter` on any section (unexpected; investigate)
- 5xx error on alias call (LiteLLM or frontier endpoint issue)
- Wall time per section exceeds 10 minutes (something is stuck)
- KV cache utilization on spark-3 or spark-4 sustained >90% (capacity issue under real load)

Halt = surface, do not auto-retry, operator decides.

### 5.6 Final assembly

```bash
ssh admin@192.168.0.100 '
  source /tmp/track-a-current-run.env
  cat ${RUN_DIR}/sections/section-1.md \
      ${RUN_DIR}/sections/section-2.md \
      ${RUN_DIR}/sections/section-3.md \
      ${RUN_DIR}/sections/section-4.md \
      ${RUN_DIR}/sections/section-5.md \
      ${RUN_DIR}/sections/section-6.md \
      ${RUN_DIR}/sections/section-7.md \
      ${RUN_DIR}/sections/section-8.md \
      ${RUN_DIR}/sections/section-9.md \
      ${RUN_DIR}/sections/section-10.md \
    > ${RUN_DIR}/Attorney_Briefing_Package_7IL_NDGA_I_v3_assembled.md
  
  STAMP=$(echo $RUN_DIR | sed "s|.*track-a-case-i-v3-||")
  cp ${RUN_DIR}/Attorney_Briefing_Package_7IL_NDGA_I_v3_assembled.md \
     /mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_I_v3_${STAMP}.md
'
```

---

## 6. Comparison + scoring

### 6.1 Per-section comparison table

Generate `${RUN_DIR}/metrics/v2-vs-v3-comparison.md` with this structure:

```
| Section | v2 tokens | v3 tokens | v2 cites | v3 cites | v2 unique srcs | v3 unique srcs | First-person v3 | <think> v3 | v3 wall (s) | Operator verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ... | ... | ... | ... | ... | ... | 0 | 0 | ... | TBD |
| 2 | ... | ... | ... | ... | ... | ... | 0 | 0 | ... | TBD |
| ...
```

Operator fills "Operator verdict" column post-run. Verdict options: `v3 wins`, `v3 parity`, `v3 loses`, `inconclusive`.

### 6.2 Per-section qualitative diff

For each section, produce a 5-10 line summary at `${RUN_DIR}/metrics/section-N-diff.md`:

```
# Section N diff — v2 vs v3

## v2 approach (1-2 lines)
What v2 did, by retrieval pattern + prose shape.

## v3 approach (1-2 lines)
What v3 did. Note: precision-filter behavior expected on argumentative
sections (4, 5, 9) per Phase 7 smoke.

## Where v3 wins (3-5 lines)
Specific examples with line refs.

## Where v3 loses (3-5 lines)
Specific examples with line refs. Empty section if v3 dominates.

## Operator review notes
TBD — operator fills.
```

### 6.3 Citation density curve

Generate `${RUN_DIR}/metrics/citation-density-curve.md` with:

- Bar chart (ASCII or markdown table) of v2 vs v3 cite counts per section
- Mean cites/1000 tokens per section type:
  - Enumerative (Sections 2, 6): expect high density both
  - Mechanical (Sections 7, 8): expect medium density both
  - Argumentative (Sections 4, 5, 9): expect v3 LOWER (precision filter)
  - Drafting (Sections 1, 3, 10): expect medium density both
- Per-section observation: did v3 follow expected behavior or deviate?

This is the empirical curve that informs Wave 4 prompt tuning. Specifically: which sections need prompt tuning to push citation density up (because density too low even for precision filter), which sections are at optimal precision-filter equilibrium.

### 6.4 Synthesis quality probe (Sections 4, 5, 9 specifically)

For each of Sections 4, 5, 9:
- Count distinct theories/arguments surfaced
- For Section 5 specifically: count "thin" or "contradicted" flagged theories (per Phase 7 smoke pattern)
- Compare to v2's theory count
- Note any analytical moves v3 made that v2 didn't (or vice versa)

Land at `${RUN_DIR}/metrics/synthesis-quality-probe.md`.

---

## 7. Operator review pack

Surface to operator at end of run:

**Inline in chat:**
1. Run wall time (total) + per-section breakdown
2. v2-vs-v3 comparison table (§6.1)
3. Citation density curve (§6.3) — most important single artifact
4. Synthesis quality probe (§6.4) — second most important
5. Any halt triggers fired during run + how they were resolved
6. Path to assembled v3 brief on NAS
7. Path to RUN_DIR on spark-2 for full artifacts

**File outputs (all on NAS):**
- v3 brief: `/mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_I_v3_<STAMP>.md`
- Per-section diffs: `${RUN_DIR}/metrics/section-N-diff.md`
- Citation density curve: `${RUN_DIR}/metrics/citation-density-curve.md`
- Synthesis quality probe: `${RUN_DIR}/metrics/synthesis-quality-probe.md`
- Run metadata: `${RUN_DIR}/metrics/run-summary.json` (all token counts, wall times, finish reasons)

**Operator decision points after review:**
- Pass: v3 beats v2. Phase B v0.1 dry-run validated. Case II briefing unblocks (separate brief).
- Fail: v3 loses or parity-only. Diagnose why — prompt issues, retrieval issues, model behavior issues. Wave 4 prompt tuning prerequisite to Case II.
- Mixed: v3 wins on some sections, loses on others. File section-specific Wave 4 work; partial unblock.

---

## 8. PR scope

This brief produces a PR for documentation + observability artifacts only. The v3 brief itself lives on NAS, not in the repo.

**Files added/modified:**
- `docs/operational/track-a-phase-b-v01-case-i-dryrun-2026-04-30.md` — this brief, full content
- `docs/operational/track-a-case-i-run-report-<STAMP>.md` — summary of run findings, comparison table, citation density curve, synthesis quality probe (the operator review pack consolidated)
- `backend/scripts/track_a_case_i_runner.py` — wrapper script that runs the per-section invocations + collects metrics (if Phase B v0.1 entry point doesn't already provide this) **OR** documentation of how to invoke existing entry point with metrics capture, no new script
- `backend/scripts/track_a_compare_v2_v3.py` — the v2-vs-v3 comparison + citation density curve generator (new utility)

**State changes:**
- v3 brief written to NAS (read-only from repo perspective)
- Run artifacts at `${RUN_DIR}` on spark-2 (preserved at least 30 days)

**No state changes:**
- LiteLLM config (untouched — aliases set in Phase 9)
- Frontier endpoint (untouched — soak in progress)
- Any service unit
- Council orchestration code
- Phase B v0.1 orchestrator code

---

## 9. Constraints

- Branches from `origin/main` only.
- `git fetch origin && git status && git log origin/main..HEAD` at session start.
- Single Claude Code session at a time on the cluster.
- Never `--admin`, never self-merge, never force-push main.
- Pre-flight gate (§4.4) is hard. STOP after enumeration. Operator greenlights before §5 execution.
- Halt triggers in §5.5 are hard. Halt = surface, do not auto-retry, operator decides.
- Soak clock continues independently. If soak halt triggers fire during Track A run, soak takes precedence — halt Track A.
- The 14-day soak does NOT gate Track A. Track A consumes the frontier under real load and is itself a soak data point.
- DO NOT modify Phase B v0.1 orchestrator code. If it has bugs, surface and file follow-up; don't fix in this PR.
- DO NOT pull any Wave 3 NIM weights.
- DO NOT touch Case II artifacts. This is Case I only.

---

## 10. Wall time budget

Estimated:
- Pre-flight + enumeration: 5 min
- Section 2 deterministic: 1 min
- Mechanical sections (1, 3, 6, 7, 8, 10) at ~3-5 min each: 18-30 min
- Synthesis sections (4, 5, 9) at ~5-8 min each: 15-24 min
- Comparison + scoring + diffs: 10 min
- Final assembly + PR commit: 10 min

**Total: ~60-80 minutes wall time.** Outliers possible on synthesis sections if reasoning effort high produces longer chains. If any single section exceeds 10 min, halt trigger fires per §5.5.

If total run wall time exceeds 2 hours, surface the run as in-progress with partial results; operator decides whether to continue or halt.

---

## 11. Report format

After Track A completes, surface:

**Run summary:**
- Total wall time
- Per-section wall time + tok/s
- Per-section token counts
- Per-section finish_reason distribution
- Total tokens generated (for Soak metrics)

**Comparison findings:**
- Per-section v2-vs-v3 comparison table
- Citation density curve (the chart)
- Synthesis quality probe (Sections 4/5/9)
- Operator verdict template (operator fills)

**Halt triggers:**
- Any halts fired + how resolved
- Any sections rerun + why

**Soak impact:**
- Any soak halt triggers fired during Track A
- Frontier endpoint health post-Track-A
- KV cache peak utilization observed
- Memory peak on spark-3 + spark-4

**Files:**
- v3 brief NAS path
- RUN_DIR path
- All metrics file paths

**PR:**
- Branch name
- PR number + URL
- Files added/modified

End of brief.
