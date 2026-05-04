# Track A v3 Case I — Analysis Observations

- Source run: `20260430T194507Z`
- Frontier: `http://10.10.10.3:8000` (nemotron-3-super)
- Overall wall: 2377.2s (39.6 min)
- Synthesizer cap (max_tokens): **20000**
- Total content chars across 11 emitted slots: 26356
- Total reasoning chars (LLM calls only): 192935

## Runaway-reasoning sections (finish=length)

| section | mode | reasoning_chars | content_chars | wall_s |
|---|---|---:|---:|---:|
| section_02_critical_timeline | synthesis | 71294 | 0 | 840.3 |
| section_07_email_intelligence_report | synthesis | 73407 | 0 | 835.48 |

## Productive synthesis sections — reasoning-to-content ratio

| section | content_chars | reasoning_chars | rsn_ratio | wall_s | tok/s |
|---|---:|---:|---:|---:|---:|
| section_04_claims_analysis | 7818 | 21656 | 2.77 | 306.09 | 6.38 |
| section_05_key_defenses_identified | 6271 | 19090 | 3.04 | 268.93 | 5.83 |
| section_08_financial_exposure_analysis | 3565 | 7488 | 2.1 | 125.75 | 7.09 |

## Mechanical sections (no LLM)

| section | content_chars |
|---|---:|
| section_01_case_summary | 511 |
| section_03_parties_and_counsel | 509 |
| section_06_evidence_inventory | 1376 |
| section_10_filing_checklist | 611 |

## Augmented sections (post-orchestrator legal-reasoning call)

| section | content_chars | reasoning_chars | wall_s | finish |
|---|---:|---:|---:|---|
| section_09_recommended_strategy_augmented | 5312 | 0 | 0.0 | n/a |

## Citation density by mode

| mode | sections | with_content | content_chars | cit_total | cit_unique | grounding_orch | density/kchar |
|---|---:|---:|---:|---:|---:|---:|---:|
| mechanical | 4 | 4 | 3007 | 0 | 0 | 0 | 0.00 |
| operator_written | 1 | 1 | 383 | 0 | 0 | 0 | 0.00 |
| synthesis | 5 | 3 | 17654 | 20 | 8 | 13 | 1.13 |
| synthesis_augmented | 1 | 1 | 5312 | 10 | 5 | 0 | 1.88 |
