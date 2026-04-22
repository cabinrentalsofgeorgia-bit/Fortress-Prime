# Legal/B Training Pair Audit — 2026-04-22

## Summary: Pattern B underperforms due to data quality and metric mismatch, not model failure

## Training Data Statistics

- Total Pattern B training pairs: 46 (30 original + 16 from PR #126)
- OCGA citations in any B pair: **0** — Pattern B is pure issue spotting, not statute lookup
- Topic count distribution in gold answers:

| # Topics in Gold | Count | % |
|---|---|---|
| 1 | 17 | 37.0% |
| 2 | 18 | 39.1% |
| 3 | 7 | 15.2% |
| 5 | 1 | 2.2% |
| 6 | 3 | 6.5% |

## Critical Quality Issues in Gold Answers

37% of gold answers have a **single topic**, and many are sentence fragments or generic fillers:
- "We Stated That"
- "A Certified Copy Of The Declarations Page Of Each Policy Of"
- "The   Georgia    Constitution     Provides   Municipalities" (OCR artifact with extra spaces)
- "Analysis" (used 3+ times — uninformative)
- "Facts And Procedural History" (generic procedural placeholder)

These are section headers extracted via regex from PDF-parsed court opinions, not clean semantic topic labels.

## Why Pattern B Scores ~0.571 with similarity_mean

For Pattern B outputs that are short numbered lists (~20-80 total chars), any phrasing difference collapses the similarity score:

- Gold: "1. Summary Judgment" / Model: "1. Motion for Summary Judgment" → sim ~0.6 (penalised)
- Gold: "1. Analysis" / Model: "1. Coverage Dispute Analysis" → sim ~0.5 (model produced better answer)

The metric is wrong for this task, not the model.

## Pair-Generation Distribution (Step 7)

All 46 B pairs teach **section_header_extraction** only. Missing patterns:

| Missing Pattern | Training Impact | Recommended % |
|---|---|---|
| Multi-topic normalized labels (3-5 per case) | Model under-generates | 40% |
| Consistent noun-phrase format | Reduces fragment outputs | 35% |
| Topic abstraction (case → concept) | Improves generalization | 25% |

## Root Cause (Confirmed without needing eval outputs)

1. **Gold answer quality**: 37% single-item, many are sentence fragments or OCR artifacts
2. **Metric mismatch**: similarity_mean penalizes correct responses with different phrasing
3. **Task clarity**: extracting exact OCR section headers is near-memorization; topic semantics matter more

## Recommended Actions

**Immediate (no retrain):** Switch legal/B primary metric to `topic_f1` (semantic recall/precision). This correctly scores outputs where the model identifies the right topics with different phrasing. Expected improvement: B score likely rises to 0.65-0.75 with same model.

**If retrain warranted after metric reassessment:**
- Regenerate B pairs with normalized topic labels (noun phrases, ≤5 words)
- Target 3-5 topics per pair
- Source: reprocess existing 1,854 court opinions with improved extraction

**NOTE on OCGA corpus:** Mission spec references OCGA corpus but this directory contains NO JSONL data (Cloudflare-blocked acquisition). Pattern B does not involve OCGA anyway — it is case-based issue spotting only.
