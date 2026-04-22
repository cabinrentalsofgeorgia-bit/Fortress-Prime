# Legal/B Phase 3 Stop Memo
_Date: 2026-04-22 | Decision: STOP — do not train e3.2_

## Decision Summary

Phase 3 (regenerate Pattern B pairs + train e3.2) is **cancelled**. The failure analysis
revealed that legal/B's low scores are a gold data quality and task definition problem, not
a training data coverage problem. Retraining from the existing corpus cannot fix this.

---

## Q1 — Failure Mode Distribution

**Task definition (actual):** Pattern B = "Identify the key legal issues raised in this
Georgia insurance dispute" given a GA court opinion. Gold labels are verbatim section
headers extracted from each opinion.

All 14 holdout records classified by failure root cause:

| Category | Count | % | Fixable by more pairs? |
|---|---|---|---|
| Gold = pure procedural header ("Analysis", "Factual And Procedural Background", "Pertinent Facts And Procedural History") | 6 | 43% | NO |
| Gold = truncated partial sentence ("Yates Provides That Where", "The Rogator Epp Provides That Agco Will Repair Or Replace") | 4 | 29% | NO |
| Gold = meaningful heading, model output correct but different phrasing | 2 | 14% | PARTIAL |
| Gold conflates procedural + substantive (includes "Facts" as a "legal issue") | 2 | 14% | NO |

**Fixable failures: 14%** (2/14). Decision gate threshold: ≥60%. Gate **FAILS**.

Note: The diagnostic questions were framed around OCGA statute citation accuracy
("wrong section cited", "hallucinated OCGA section"). That framing is **incorrect** —
Pattern B is not an OCGA citation task. None of the 30 training B pairs or 14 holdout
records contain OCGA citations in the gold answer. The failure categories above replace
those framing assumptions with what the data actually shows.

---

## Q2 — e3 vs e3.1 on Hardened Legal/B Metrics

| Metric | e3 | e3.1 | Delta |
|---|---|---|---|
| similarity_mean | 0.5628 | 0.5710 | +0.0082 (noise) |
| topic_f1 | 0.0238 | 0.0536 | +0.030 (both ~0) |
| topic_recall | 0.0143 | 0.0429 | +0.029 |
| topic_precision | 0.0714 | 0.0714 | 0.000 |
| halluc_rate | 0.000 | 0.036 | +0.036 |

The +0.008 sim gain is within measurement noise. topic_f1 doubled (0.024 → 0.054) but
both are near-zero on broken gold labels — not a real signal. The Pattern B training
additions contributed nothing measurable. The existing 30 training B pairs cannot teach
the model to reproduce procedural section headers because the model already generates
_better_ answers (proper legal issue statements).

---

## Q3 — Hallucination Rate on Legal/B

e3.1 legal/B hallucination_rate: **3.57%** (1/14 records, 0.5 score on B-05).

B-05: model generated "OCGA § 22-1-9 (2)" and "OCGA § 22-1-9 (3)" — real eminent
domain sections, wrong context. Gold was "Factual And Procedural Background". This is
task boundary confusion (Pattern C bleeding into Pattern B), not base model faithfulness
failure. One isolated incident.

Threshold ≤5%: **PASSES**. Hallucination is not the blocking factor.

---

## Q4 — Pair Pattern Distribution vs Failure Modes

| Training pair type | Count | % |
|---|---|---|
| section_header_extraction (court opinion → numbered section list) | 30 | 100% |

Zero variety across the 30 Pattern B training pairs — all are structurally identical. The
dominant failure mode (gold = procedural header, model = proper issue statement) has
**no corresponding underrepresented training pattern to add** because:

1. The corpus only generates procedural section headers. Sampling more pairs from the
   same corpus produces more of the same label quality.
2. The model's output behavior already exceeds the gold standard. Adding 300 more
   pairs teaching the model to output "Analysis" would be anti-improvement.

Gate condition (≥1 underrepresented pattern mapping to dominant failure): **FAILS**.

---

## Q5 — Corpus Coverage

The OCGA corpus at `/mnt/fortress_nas/legal-corpus/ocga/` (title-33 insurance) is
not relevant to Pattern B. Pattern B uses court opinions, not statutes.

Source breakdown of 14 holdout B records:
- `legal_corpus` (GA insurance court opinions): 8/14 (57%)
- `courtlistener_expanded` (expanded civil opinions): 6/14 (43%)

All source texts are accessible. Corpus coverage is **not the blocker**.

Reframed corpus question: "Are enough new opinions available to generate 300 properly
labeled B pairs?" The Phase 2 dry-run (`generate_b_pairs_v2.py`) confirmed **17 max**
from the 1,854-opinion GA insurance corpus. The 300-pair target is structurally
unachievable regardless of labeling quality.

---

## Upstream Fix Required

The correct intervention for legal/B is **gold label relabeling**, not retraining:

1. Annotate the 14 holdout records with proper legal issue statements (not section headers).
   This is a ~2-hour annotation task.
2. Optionally annotate the 30 training B pairs with the same relabeling pass.
3. Re-run hardened eval against relabeled gold to get the true topic_f1 score.
4. Decide on e3.2 only after seeing the true score: if topic_f1 ≥ 0.70 against
   relabeled gold, no retrain needed. If topic_f1 < 0.50, investigate model capability
   with a targeted 50-pair labeled set before committing to full retraining.

**Estimate:** relabeling takes 1 person × 2–3 hours. Reveals the actual performance gap
in one eval run. Retrain decision can be made the same day.

---

## What Ships in This PR

- `src/eval/run_eval_v2.py` — hardened harness with task-specific metrics
- `src/eval/metrics/citations.py` — citation F1 implementation
- `src/eval/metrics/topics.py` — topic F1 with MiniLM semantic matching
- `src/eval/metrics/holdings.py` — ROUGE-L + holding term overlap
- `src/eval/analyze_failures.py` — automated failure categorization
- `evals/harness/audit_20260422.md` — harness gap documentation
- `evals/audits/legal_b_pair_audit_20260422.md` — Phase 2 pair quality audit
- `evals/audits/legal_b_failure_modes_20260422.md` — automated failure mode report
- `evals/audits/legal_c_failure_modes_20260422.md` — legal/C failure mode report
- `evals/audits/legal_b_stop_memo_20260422.md` — this document
- `evals/results/hardened_20260422/` — e3.1 v2 metrics + gate results

**Not in this PR:** e3 baseline v2 metrics (eval still running; will ship as follow-up commit).
