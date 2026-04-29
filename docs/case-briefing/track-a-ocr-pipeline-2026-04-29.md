# Track A §4.1 — OCR pipeline execution record (2026-04-29)

**Operator:** Gary Knight
**Executor:** Claude Code on spark-2
**Pipeline:** `ocrmypdf 15.2.0`, `--force-ocr` (after a `--skip-text` first pass that no-op'd 13/14 due to thin existing text layers)
**Source set:** 14 image-only PDFs identified by overnight Stage 5.3 (curated set)
**Input/output:** in-place (preserves curated structure)

## Two-pass approach

First pass used `--skip-text` to preserve any real text layer. Result: only 1 of 14 PDFs gained text (the truly blank Preliminary Survey). The other 13 had a vestigial text layer that triggered the skip, so no OCR was actually applied.

Second pass used `--force-ocr` against those 13 to overwrite the thin layer with real OCR output. All 13 succeeded.

## File-by-file (post-final-pass)

| File | Pre (chars) | Post (chars) | Δ | Pass | Notes |
|---|---:|---:|---:|---|---|
| `case-i-context/04_deposition_exhibits_7il/Exh._I___2021.05.31_Preliminary_Survey.pdf` | 0 | 4453 | +4453 | skip-text | Truly text-less — gained on first pass. |
| `case-i-context/01_pleadings/loas/88_LOA_-_Sanker.pdf` | 52 | 1518 | +1466 | force-ocr |  |
| `case-i-context/01_pleadings/loas/131_Response_to_Notice_at_Doc._129.pdf` | 53 | 1474 | +1421 | force-ocr |  |
| `case-i-context/01_pleadings/05_Affidavit_of_Service.pdf` | 102 | 2666 | +2564 | force-ocr |  |
| `case-i-context/01_pleadings/loas/114_Conflict_Notice_-_Sanker.pdf` | 106 | 3278 | +3172 | force-ocr |  |
| `02_complaint_exhibits/Exhibit_I_Unauthorized_Easement_2025-03-17.pdf` | 265 | 10104 | +9839 | force-ocr | High-priority — recorded easement is the Counts II–V centerpiece. |
| `02_complaint_exhibits/Exhibit_J_Warranty_Deed_River_Heights_2025-06-02.pdf` | 108 | 2359 | +2251 | force-ocr |  |
| `02_complaint_exhibits/Exhibit_K_Warranty_Deed_Fish_Trap_2025-06-02.pdf` | 108 | 2361 | +2253 | force-ocr |  |
| `02_complaint_exhibits/Exhibit_E_2021_Inspection_River_Heights.pdf` | 8241 | 36707 | +28466 | force-ocr | 121 pp — 315s OCR runtime. |
| `case-i-context/02_dispositive_motions/63-12_Exh._K_-_Emails.pdf` | 230 | 3064 | +2834 | force-ocr |  |
| `case-i-context/02_dispositive_motions/63-13_Exh._L_-_Emails.pdf` | 285 | 4185 | +3900 | force-ocr |  |
| `case-i-context/02_dispositive_motions/63-9_Exh._H_-_92_Fish_Trap_Package.pdf` | 3696 | 99589 | +95893 | force-ocr | 65 pp — 210s OCR runtime. |
| `case-i-context/02_dispositive_motions/63-11_Exh._J_-_Emails.pdf` | 740 | 17185 | +16445 | force-ocr | 12 pp. |
| `case-i-context/02_dispositive_motions/63-10_Exh._I_-_253_River_Heights_Package.pdf` | 3989 | 166550 | +162561 | force-ocr | 69 pp — 193s OCR runtime. Largest text gain in the set. |

Raw TSV at `/tmp/track-a-ocr-force-result.tsv`, raw log at `/tmp/track-a-ocr-force-2026-04-29.log`.

## Outcome

* Files OCR'd in place: **14/14** image-only PDFs in the curated set.
* Failures: **0**.
* Total runtime: ≈ 11 minutes wall-clock (dominated by Exhibit E + Exhibit H).
* Constraint: only files in §4.1's curated list of 14 were touched. No other curated PDFs were modified.
