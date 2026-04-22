# Legal/B Failure Mode Analysis — 2026-04-22

## Domain: legal/B
- Total eval samples: 14
- Passing (sim ≥ 0.6): 4
- Failing (sim < 0.6): 10
- Failure rate: 71.4%

## Failure Mode Distribution

| Category | Count | % of failures |
|---|---|---|
| topic_mismatch | 9 | 90.0% |
| single_topic_vs_multi | 1 | 10.0% |

## Topic Recall Distribution (legal/B)
- Mean topic recall: 0.043
- Median: 0.000
- Samples with topic_recall=0: 13
- Samples with topic_recall≥0.8: 0

## Training Pair Type Distribution

| Pair Type | Count | % |
|---|---|---|
| section_header_extraction | 30 | 100.0% |

## Diagnosis

### Pattern B Task Definition
Pattern B = extract numbered section headers from court opinion text.
Gold answers are section headers from each specific case — highly
idiosyncratic per opinion. Task does NOT involve statute citation or OCGA lookup.

### Root Cause Hypothesis
**Primary failure: topic mismatch.** Model extracts wrong section topics. The pair-generation corpus needs more structural variety.

## Sample Low-Scoring B Outputs

**Record 9510302 (sim=0.353, topic_recall=0.000):**
- Gold topics: ['Factual And Procedural Background']
- Model topics: ['Violation of OCGA § 22-1-9 (2): The Department of Transportation failed to provide Star Land Holdings, LLC with the opportunity to accompany the appraiser during his inspection of the property.', 'Violation of OCGA § 22-1-9 (3): The Department of Transportation failed to provide Star Land Holdings, LLC with a written summary of the basis for its estimation of just compensation.']

**Record 2687383 (sim=0.400, topic_recall=0.000):**
- Gold topics: ['The Rogator Epp Provides That Agco Will Repair Or Replace']
- Model topics: ['Breach of Contract']

**Record 2814251 (sim=0.492, topic_recall=0.000):**
- Gold topics: ['The Structural Damage Award', 'The Business Interruption Award']
- Model topics: ['Construction and Interpretation of a Contract']

**Record 10679882 (sim=0.521, topic_recall=0.000):**
- Gold topics: ['Analysis']
- Model topics: ['Whether the trial court erred in denying General Motors’ motion for a protective order barring the plaintiffs’ proposed deposition of General Motors’ CEO.']

**Record 4477631 (sim=0.523, topic_recall=0.000):**
- Gold topics: ['Yates Provides That Where']
- Model topics: ['Attorney Fees']
