# Track A — Phase B v0.1 Dry-Run on Case I (Super-120B Baseline) — END-TO-END

**Target:** Claude Code on spark-2
**Branch:** `feat/track-a-phase-b-v01-case-i-dryrun-2026-04-30`
**Date:** 2026-04-30
**Operator:** Gary Knight
**Mode:** END-TO-END AUTONOMOUS. Run start to finish. Hard stops only on real break conditions (production damage, sovereignty violation, catastrophic resource).
**Driver:** Phase 9 (PR #322) merged. TP=2 frontier endpoint live, 5/5 aliases hot, 7 Council reasoning seats routed to Super-120B. Track A produces the v3 Case I brief (MASTER-PLAN v1.7 §6.1 proof point) and the citation-density baseline that informs Wave 4 prompt tuning.

---

## 1. Mission

Run Phase B v0.1 orchestrator end-to-end on Case I (`7il-v-knight-ndga-i`). Produce v3 brief. Capture per-section metrics. Compare against v2 baseline. Generate operator review pack. Open PR. Single autonomous run.

---

## 2. Hard stops (the ONLY conditions that halt execution)

Halt + surface ONLY for:

1. **Frontier endpoint dead.** `curl /v1/health/ready` returns non-200 for >60s sustained.
2. **Soak halt trigger fires.** Phase 9 soak collector emits halt event (OOM, format regression, fabric error) — that's the cluster telling you to stop.
3. **Sovereignty violation.** Any LiteLLM call routes to a cloud provider for Case I privileged content. Should be impossible per Phase 9 alias surgery, but check.
4. **Phase B v0.1 orchestrator does not exist.** §4.2 enumeration finds nothing. Cannot run what isn't there.
5. **v2 baseline cannot be located.** Comparison is the deliverable; without v2 there's no comparison.
6. **Disk full on spark-2 or NAS.** Less than 5GB free anywhere in the write path.
7. **Catastrophic resource on frontier.** spark-3 or spark-4 OOM kill, or KV cache sustained >95% for >10 minutes (not >90% which is just busy).

**Everything else proceeds.** No operator confirmation gates. No "STOP and ask" for things that have known answers (run order, citation methodology, file paths, halt-on-format-regression behavior). Proceed with the brief's defaults; surface deviations in the final report.

---

## 3. Why Case I

Closed case, no risk. Has v2 baseline. Rich corpus (1,396 docs, 91,245 retrievable points). Stresses both retrieval and synthesis. Validates Section 5 precision-filter behavior on the full pipeline (not just Phase 7 smoke prompt).

47-day Case II clock starts when v3 quality is confirmed.

---

## 4. Execution

### 4.1 Branch + state

```bash
git fetch origin
git checkout origin/main
git checkout -b feat/track-a-phase-b-v01-case-i-dryrun-2026-04-30
git status
git log origin/main..HEAD --oneline
```

### 4.2 Locate Phase B v0.1 + v2 baseline (do not stop unless missing)

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  echo "=== Phase B entry point ==="
  find . -path "*phase_b*" -type f \( -name "*.py" -o -name "*.md" \) 2>/dev/null | grep -v __pycache__ | grep -v ".git/"
  echo "=== Orchestrator candidates ==="
  find . -name "*orchestrator*" -path "*legal*" -type f 2>/dev/null | grep -v __pycache__
  echo "=== TEN_SECTIONS ==="
  grep -rn "TEN_SECTIONS" --include="*.py" 2>/dev/null | grep -v __pycache__ | head -10
  echo "=== v2 Case I baseline ==="
  find /mnt/fortress_nas -path "*7il-v-knight-ndga-i*" \( -name "*Attorney_Briefing*" -o -name "*v2*" -o -name "*v1*" \) 2>/dev/null | head -20
  find /mnt/fortress_nas -path "*7il-v-knight-ndga*" -name "*.md" -size +10k 2>/dev/null | head -20
'
```

If Phase B v0.1 entry point is empty: **HARD STOP §2.4.**
If v2 baseline empty: **HARD STOP §2.5.**
Otherwise: pick the entry point with most recent mtime; pick the v2 baseline with "v2" in name (or most recent Attorney_Briefing if no version tagged); proceed.

### 4.3 Sanity check frontier + soak before burning wall time

```bash
ssh admin@192.168.0.100 '
  curl -fsS --max-time 10 http://10.10.10.3:8000/v1/health/ready | head -1
  curl -fsS --max-time 30 http://localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"legal-reasoning\", \"messages\": [{\"role\":\"user\",\"content\":\"PONG\"}], \"max_tokens\": 10}" \
    | jq -r ".choices[0].message.content"
  tail -20 /mnt/fortress_nas/audits/phase-9-soak/$(date +%Y-%m-%d).log 2>/dev/null | tail -20
'
```

Frontier 200 + PONG → proceed. Soak log silent on halt → proceed. Otherwise hard stop §2.1 or §2.2.

### 4.4 Stage output

```bash
ssh admin@192.168.0.100 '
  STAMP=$(date +%Y%m%dT%H%M%SZ)
  RUN_DIR=/tmp/track-a-case-i-v3-${STAMP}
  mkdir -p ${RUN_DIR}/{sections,raw,metrics,logs}
  echo "RUN_DIR=${RUN_DIR}" > /tmp/track-a-current-run.env
  echo "STAMP=${STAMP}" >> /tmp/track-a-current-run.env
  cat /tmp/track-a-current-run.env
'
```

### 4.5 Per-section invocation

For each section in TEN_SECTIONS, route per Wave 7 mapping. Run sections in this order to get early failure signal:

| Order | Section | Alias | Reasoning effort | Max tokens |
|---|---|---|---|---|
| 1 | 2. Critical Timeline | (deterministic) | — | — |
| 2 | 1. Case Summary | `legal-drafting` | medium | 2000 |
| 3 | 3. Parties & Counsel | `legal-drafting` | medium | 3000 |
| 4 | 6. Evidence Inventory | `legal-drafting` | medium | 5000 |
| 5 | 7. Email Intelligence | `legal-summarization` | low | 3000 |
| 6 | 8. Financial Exposure | `legal-summarization` | low | 2000 |
| 7 | 4. Claims Analysis | `legal-reasoning` | high | 6000 |
| 8 | 5. Defenses | `legal-reasoning` | high | 6000 |
| 9 | 9. Strategy | `legal-reasoning` | high | 5000 |
| 10 | 10. Filing Checklist | `legal-drafting` | medium | 2000 |

For each section, capture to `${RUN_DIR}/sections/section-N.md` and `${RUN_DIR}/raw/section-N.json`. Capture metrics to `${RUN_DIR}/metrics/section-N-metrics.json`:

```json
{
  "section": N,
  "alias": "...",
  "wall_time_sec": 0.0,
  "tokens_input": 0,
  "tokens_output": 0,
  "tokens_reasoning": 0,
  "finish_reason": "stop",
  "citations_total": 0,
  "citations_unique_sources": 0,
  "first_person_in_content": 0,
  "think_blocks_in_content": 0,
  "tok_per_sec": 0.0
}
```

### 4.6 In-flight behaviors (no operator gate)

- **Format regression detected** (first-person bleed or `<think>` leakage in content): log it, complete the section, flag in final report. Do NOT halt — Phase 9 soak is monitoring this independently and a single regression doesn't justify halting a 60-80 min run. If 3+ sections show regressions, then halt.
- **`finish_reason=length`**: log it, double max_tokens for that section, retry once. If retry also length-stops, accept truncated output and flag.
- **`finish_reason=content_filter`**: log it, accept output as-is, flag.
- **5xx error**: retry once after 30s sleep. If retry fails, hard stop §2.1.
- **Section wall time >10 min**: let it complete (interrupting mid-generation discards work). Flag in report.
- **KV cache spikes 90-95%**: log it. Don't halt. Sustained >95% for >10 min → hard stop §2.7.
- **Soak collector fires halt event during run**: hard stop §2.2.

### 4.7 Final assembly

```bash
ssh admin@192.168.0.100 '
  source /tmp/track-a-current-run.env
  for N in 1 2 3 4 5 6 7 8 9 10; do
    cat ${RUN_DIR}/sections/section-${N}.md
    echo
    echo "---"
    echo
  done > ${RUN_DIR}/Attorney_Briefing_Package_7IL_NDGA_I_v3_assembled.md
  
  cp ${RUN_DIR}/Attorney_Briefing_Package_7IL_NDGA_I_v3_assembled.md \
     /mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_I_v3_${STAMP}.md
  
  ls -la /mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/Attorney_Briefing_Package_7IL_NDGA_I_v3_${STAMP}.md
'
```

If destination directory doesn't exist, create it:

```bash
ssh admin@192.168.0.100 '
  mkdir -p /mnt/fortress_nas/Corporate_Legal/Business_Legal/7il-v-knight-ndga-i/filings/outgoing/
'
```

---

## 5. Comparison + scoring

### 5.1 v2-vs-v3 comparison table

Generate `${RUN_DIR}/metrics/v2-vs-v3-comparison.md`:

```
| Section | v2 tokens | v3 tokens | v2 cites | v3 cites | v2 unique srcs | v3 unique srcs | v3 first-person | v3 <think> | v3 wall (s) | v3 finish_reason |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ... | ... | ... | ... | ... | ... | 0 | 0 | ... | stop |
...
```

Rescore v2 with Track A's citation methodology (§5.3) so comparison is apples-to-apples. If v2's text isn't structured for automated scoring, do best-effort regex sweep and flag as approximate.

### 5.2 Citation density curve

`${RUN_DIR}/metrics/citation-density-curve.md`:

ASCII bar chart of cites per section, v2 vs v3:

```
Section 2 (Timeline)      v2 |#### #### #### #### ##| 22
                          v3 |#### #### #### #### ##| 22  (deterministic)
Section 4 (Claims)        v2 |#### #### #### ####  | 19
                          v3 |#### #### ##         | 11  ← precision filter expected
...
```

Expected behavior under Super-120B precision filter:
- Enumerative sections (2, 6): cites approximately equal v2
- Mechanical sections (7, 8): cites approximately equal v2
- Argumentative sections (4, 5, 9): cites LOWER than v2 (filter dropping weak sources)
- Drafting sections (1, 3, 10): cites approximately equal v2

If observed curve matches expected: Super-120B is behaving correctly. If it deviates (argumentative sections higher than v2, or enumerative lower): flag for prompt tuning.

### 5.3 Citation extraction methodology

```python
# Regex patterns applied to section text
patterns = {
    "complaint_para": r"¶\s*\d+(?:\(\w+\))?",
    "exhibit": r"(?:Exhibit|Ex\.?)\s*[A-Z](?:-\d+)?",
    "doc_ref": r"Doc\.?\s*\d+",
    "email_id": r"(?:email\s*#|archive\s*ID\s*)\d+",
    "vault_doc": r"vault\s*doc\s*\d+",
    "case_law": r"\d+\s+(?:F\.\d+|S\.E\.\d+|Ga\.|U\.S\.)\s+\d+",
    "docket": r"\d+:\d{2}-CV-\d+",
}
```

Total cites = sum of all matches. Unique sources = deduplicate by source-document identity (same exhibit referenced 5x = 1 unique source). Apply identical methodology to v2 and v3.

### 5.4 Synthesis quality probe (Sections 4, 5, 9)

`${RUN_DIR}/metrics/synthesis-quality-probe.md`:

For each of 4, 5, 9:
- Count distinct theories/arguments (heuristic: numbered or bulleted top-level items in section structure)
- For Section 5: count theories explicitly flagged "thin", "weak", "contradicted", "unsupported"
- v2 theory count vs v3 theory count
- New theories surfaced by v3 (not in v2)
- Theories in v2 dropped by v3 (precision filter dropped them — note them, may be intentional)

### 5.5 Format compliance summary

`${RUN_DIR}/metrics/format-compliance.md`:

```
| Section | First-person bleed | <think> in content | Format compliant |
|---|---|---|---|
| 1 | 0 | 0 | ✅ |
...
```

If any non-zero: flag prominently in final report. Phase 9 soak halt-trigger documentation already covers this; Track A surfaces it for the run-specific record.

---

## 6. PR

### 6.1 Files to commit

```bash
ssh admin@192.168.0.100 '
  source /tmp/track-a-current-run.env
  cd /home/admin/Fortress-Prime
  
  mkdir -p docs/operational
  mkdir -p backend/scripts
  
  # Brief itself
  cp /home/admin/Fortress-Prime/docs/operational/track-a-phase-b-v01-case-i-dryrun-brief.md \
     docs/operational/ 2>/dev/null || true
  
  # Run report consolidating metrics
  cat > docs/operational/track-a-case-i-run-report-${STAMP}.md <<EOF
# Track A — Case I v3 Run Report (${STAMP})

[Auto-generated content: §5.1 table + §5.2 curve + §5.4 probe + §5.5 compliance + run summary]
EOF
  
  # Place run artifacts
  cp ${RUN_DIR}/metrics/*.md docs/operational/track-a-${STAMP}-metrics/
  cp ${RUN_DIR}/metrics/*.json docs/operational/track-a-${STAMP}-metrics/
  
  git add docs/operational/track-a-*.md docs/operational/track-a-${STAMP}-metrics/
  git status
'
```

If a track-a runner script was created in execution: commit it to `backend/scripts/`. If existing Phase B v0.1 entry point was used as-is: no script commit, just document invocation.

### 6.2 Commit + push + PR

```bash
ssh admin@192.168.0.100 '
  cd /home/admin/Fortress-Prime
  git commit -m "feat(track-a): Phase B v0.1 dry-run on Case I — Super-120B v3 brief

- Track A end-to-end run against TP=2 frontier (Phase 9)
- v3 Case I brief generated; landed at NAS path in report
- v2 vs v3 comparison table, citation density curve, synthesis probe
- Per-section format compliance verified
- Soak clock unaffected; this PR adds doc/metrics only

Run STAMP: ${STAMP}
"
  
  git push -u origin feat/track-a-phase-b-v01-case-i-dryrun-2026-04-30
  
  gh pr create \
    --title "Track A — Phase B v0.1 dry-run on Case I (Super-120B v3 baseline)" \
    --body "$(cat docs/operational/track-a-case-i-run-report-${STAMP}.md)" \
    --draft
'
```

PR opens as draft. Operator promotes to ready after reviewing v3 brief on NAS.

---

## 7. Final report (auto-surface at run end)

Output to chat at end of run, in this order:

1. **Run summary**
   - Total wall time
   - Per-section wall time table
   - Total tokens generated
   - Any retries that fired (which section, why)

2. **v3 brief location**
   - NAS path
   - Token count (total)
   - Section count (10/10 expected)

3. **v2-vs-v3 comparison table** (full §5.1 output inline)

4. **Citation density curve** (full §5.2 output inline)

5. **Synthesis quality probe** (full §5.4 output inline)

6. **Format compliance summary** (§5.5)

7. **Halt triggers fired** (should be zero if clean run)

8. **Soak impact**
   - Frontier endpoint health post-run
   - KV cache peak observed
   - Memory peak on spark-3 + spark-4
   - Any soak halt events during run

9. **PR**
   - Branch
   - PR number
   - PR URL
   - Files committed

10. **Recommended operator next action**
    - If v3 dominates v2: pass; Case II briefing unblocks
    - If mixed: section-specific prompt tuning targets identified
    - If v3 loses: diagnose; do not proceed to Case II

---

## 8. Constraints

- Branches from `origin/main` only.
- Single Claude Code session at a time on the cluster.
- Never `--admin`, never self-merge, never force-push main.
- DO NOT touch Case II artifacts.
- DO NOT modify Phase B v0.1 orchestrator code.
- DO NOT pull any Wave 3 NIM weights.
- DO NOT modify LiteLLM config.
- DO NOT modify any service unit.
- DO NOT halt for soft conditions (single format regression, single length-stop, transient KV pressure). Hard stops in §2 only.

---

End of brief.
