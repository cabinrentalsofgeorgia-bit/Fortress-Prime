# Legal/B Failure Mode Analysis — 2026-04-22

## Domain: legal/C
- Total eval samples: 111
- Passing (sim ≥ 0.7): 84
- Failing (sim < 0.7): 27
- Failure rate: 24.3%

## Failure Mode Distribution

| Category | Count | % of failures |
|---|---|---|
| citation_miss | 12 | 44.4% |
| good_enough | 12 | 44.4% |
| wrong_citation_right_prose | 2 | 7.4% |
| missing_under_prefix | 1 | 3.7% |

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
Primary failure mode: citation_miss. See table above.

## Sample Low-Scoring B Outputs

**Record 10350503 (sim=0.209, topic_recall=0.000):**
- Gold topics: []
- Model topics: []

**Record d3e0b9a62e (sim=0.402, topic_recall=0.000):**
- Gold topics: []
- Model topics: []

**Record 10679788 (sim=0.433, topic_recall=0.000):**
- Gold topics: []
- Model topics: []

**Record 0b0b0a6276 (sim=0.471, topic_recall=0.000):**
- Gold topics: []
- Model topics: []

**Record f8acaf1f8c (sim=0.502, topic_recall=0.000):**
- Gold topics: []
- Model topics: []
