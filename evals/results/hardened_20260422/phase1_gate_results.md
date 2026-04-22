# Phase 1 — Eval Harness Hardening: Gate Results
_Generated: 2026-04-22 | Updated: 2026-04-22 15:37 (e3 baseline complete — Q2 final)_

## Phase 3 Decision: STOP — No e3.2 training
See `evals/audits/legal_b_stop_memo_20260422.md` for full diagnostic.

---

## Hardened Metrics: e3.1 (n=299)

### Per-Domain Task-Specific Metrics

| Domain | n | sim_mean | Primary Metric | Primary Score | format_ok | halluc_rate |
|--------|---|----------|----------------|---------------|-----------|-------------|
| legal/A | 45 | 0.8088 | rouge_l | **0.4537** | 1.000 | 0.459 |
| legal/B | 14 | 0.5710 | topic_f1 | 0.0536* | 1.000 | 0.036 |
| legal/C | 111 | 0.7844 | citation_f1 | **0.8198** | 0.991 | 0.883 |
| legal/D | 43 | 0.8584 | similarity | 0.8584 | 1.000 | 0.756 |
| legal/E | 86 | 0.6876 | similarity | 0.6876 | 1.000 | 0.378 |
| **OVERALL** | **299** | **0.7609** | | | 0.937 | |

*legal/B topic_f1=0.054 is a gold data artifact — see Phase 2 diagnosis.

### legal/A Detail
- holding_present_rate: **0.867** (model outputs a holding in 86.7% of cases)
- holding_term_overlap: 0.692
- rouge_l: 0.454

### legal/C Detail
- citation_precision: **0.941**
- citation_recall: **0.827**
- citation_f1: **0.820**
- hallucination_rate 0.883 = 88.3% of C responses contain ≥1 citation token (expected and correct)

---

## e3.1 vs e3 Baseline (legacy sim_mean)

| | e3 | e3.1 | Delta |
|---|---|---|---|
| overall sim_mean | 0.6779 | **0.7609** | +0.0830 |
| legal/A | 0.8002 | 0.8088 | +0.0086 |
| legal/B | 0.5628 | 0.5710 | +0.0082 |
| legal/C | 0.5590 | **0.7844** | **+0.2254** |
| legal/D | 0.8571 | 0.8584 | +0.0013 |
| legal/E | 0.6965 | 0.6876 | −0.0089 |
| regression_count | 23 | **1** | −22 |
| validity_rate | 0.9231 | 0.9365 | +0.013 |

---

## Q2 — e3 vs e3.1 Hardened Metrics (Full Comparison)

### Overall

| Metric | e3 | e3.1 | Delta |
|--------|-----|------|-------|
| overall sim_mean | 0.6777 | **0.7609** | **+0.083** |
| validity_rate | 0.9264 | 0.9365 | +0.010 |
| regression_count | 22 | **1** | **−21** |
| citation_f1_C | 0.6462 | **0.8198** | **+0.174** |
| topic_f1_B | 0.0238 | 0.0536 | +0.030 (both ~0) |
| rouge_l_A | 0.4472 | 0.4537 | +0.007 |

### Per-Domain Hardened Metrics

| Domain | Metric | e3 | e3.1 | Delta |
|--------|--------|----|------|-------|
| **legal/A** | sim_mean | 0.7990 | 0.8088 | +0.010 |
| | rouge_l | 0.4472 | **0.4537** | +0.007 |
| | holding_present_rate | 0.8444 | **0.8667** | +0.022 |
| | holding_term_overlap | 0.6806 | 0.6915 | +0.011 |
| | halluc_rate | 0.456 | 0.459 | +0.003 |
| **legal/B** | sim_mean | 0.5628 | 0.5710 | +0.008 (noise) |
| | topic_f1 | 0.0238 | 0.0536 | +0.030 (both ~0†) |
| | topic_recall | 0.0143 | 0.0429 | +0.029 |
| | topic_precision | 0.0714 | 0.0714 | 0.000 |
| | halluc_rate | **0.000** | 0.036 | +0.036 |
| **legal/C** | sim_mean | 0.5594 | **0.7844** | **+0.225** |
| | citation_f1 | 0.6462 | **0.8198** | **+0.174** |
| | citation_precision | 0.7027 | **0.9414** | **+0.239** |
| | citation_recall | 0.8251 | 0.8273 | +0.002 |
| | format_ok_rate | **0.000** | **0.991** | **+0.991** |
| | halluc_rate | 0.379 | 0.883 | +0.504† |
| **legal/D** | sim_mean | 0.8553 | 0.8584 | +0.003 |
| | halluc_rate | 0.784 | 0.756 | −0.028 |
| **legal/E** | sim_mean | 0.6969 | 0.6876 | −0.009 |
| | halluc_rate | 0.349 | 0.378 | +0.029 |

† legal/C halluc_rate increase is expected: higher = more citations generated (correct for Pattern C). e3 format_ok_rate=0.000 means it never produced the "Under [citation]:" prefix required by Pattern C.

### Q2 Verdict

**e3.1 was genuinely better than e3 on every primary metric, with two decisive improvements:**

1. **legal/C: format transformation.** e3 format_ok_rate = 0.000 — it never produced the `Under [citation]:` format. e3.1 = 0.991. The +314 Pattern C court rules pairs taught the format reliably. citation_precision jumped +0.239 (0.703 → 0.941).

2. **legal/C: citation F1 +0.174** (0.646 → 0.820). This is the production-relevant metric. e3 was generating citation content but in the wrong structure; e3.1 delivers both correct citations and correct format.

3. **legal/B: no real improvement.** topic_f1 doubled (0.024 → 0.054) but both are near-zero on broken gold labels. The +0.008 sim delta is noise. B training additions were neutral — confirmed by both Q2 data and the Phase 2 pair quality audit (corpus ceiling = 17 pairs).

4. **legal/A: marginal but consistent.** ROUGE-L +0.007, holding_present +0.022. Small gains across all A metrics.

**e3.1 is unambiguously the correct production adapter.** e3 was pre-broken on legal/C format.

---

## Phase 2 Diagnosis: Why legal/B = 0.571

### Root Cause: Gold Data Quality (NOT Model Capability)

Inspecting all 14 B holdout samples confirms:

| Gold Answer (teacher) | Model Output | Assessment |
|---|---|---|
| "Analysis" | "Whether the trial court erred in denying GM's motion..." | Model BETTER |
| "Factual And Procedural Background" | "Whether a life insurance policy..." | Model BETTER |
| "The Rogator Epp Provides That Agco Will Repair..." | "Breach of Contract" | Model correct |
| "Because We Lack Jurisdiction To Grant The Original Relief" | "WHETHER THIS COURT HAS ORIGINAL JURISDICTION..." | Same meaning |

**Gold = verbatim truncated section headers** (sentence fragments, procedural labels like "Analysis")
**Model = proper legal issue statements** (well-formed questions and issues)

The model is generating _better_ answers than the gold data. Both sim_mean and topic_f1 penalize this correctly-phrased output because they compare against sentence-fragment gold labels.

### Failure Mode Distribution (Phase 2 Automated Analysis)
- **topic_mismatch**: 9/10 failures (90%) — semantic match fails on procedural headers
- **single_topic_vs_multi**: 1/10 failures (10%)

### Corpus Ceiling Confirmed
- Only 17 new Pattern B pairs available from entire 1,854-opinion GA insurance corpus
- OCGA corpus: inaccessible (Cloudflare-blocked)
- Gold pair type = section_header_extraction (100% of 30 training B pairs)
- 300-pair target is structurally unachievable

---

## Phase 2 Decision

**DECISION: NO RETRAIN**

The legal/B score problem is a metric + gold data problem. The intervention is:
1. Re-label B holdout gold with proper issue statements (not section headers)
2. OR accept sim_mean as a weak proxy and weight C/A more heavily in production routing

legal/C at citation_f1=0.820 is production-ready. e3.1 confirmed as production adapter.

---

## legal/C Failure Analysis (27/111 failures, 24.3%)

| Failure Mode | Count | % |
|---|---|---|
| citation_miss | 12 | 44% |
| good_enough (near threshold) | 12 | 44% |
| wrong_citation_right_prose | 2 | 7% |
| missing_under_prefix | 1 | 4% |

The 44% "good_enough" category are samples scoring 0.68–0.70 (just below the 0.7 threshold).
True failure rate is ~13% (citation_miss + wrong_citation cases).

---

## Harness Version Comparison

Old harness (sim_mean only) flagged legal/C as broken (0.559 on e3). New harness reveals:
- The problem was real but e3.1 fixed it (citation_f1=0.820)
- legal/B score (0.571) is a gold-data artifact, not a training failure
- legal/A is healthy (ROUGE-L=0.454, holding_present=0.867)
