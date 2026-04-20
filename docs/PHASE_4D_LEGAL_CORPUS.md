# Phase 4d — Georgia Insurance Defense Corpus

## Target Use Case

Fine-tune `qwen2.5:32b` as the **Fortress Legal judge model** — specialized in Georgia insurance defense reasoning. The judge evaluates sovereign (qwen2.5:7b) responses on legal queries, deciding confident / uncertain / escalate.

Initial scope: Georgia appellate court insurance opinions + OCGA Title 33 (Georgia Insurance Code).

---

## Part 1 + 1b — Corpus Infrastructure (COMPLETE)

Acquire and stage public legal data. No training.

### Actual results (2026-04-19)

| Source | Result |
|--------|--------|
| CourtListener API v4 | **1,880 Georgia insurance opinions** staged (metadata JSONL) |
| Full-text fetch (Part 1b) | Fetches `plain_text` for all 1,880 via `/api/rest/v4/opinions/?cluster={id}` |
| OCGA Title 33 | Pending (manual run after bulk fetch complete) |

**Note on bulk CSVs:** CourtListener's S3 bulk files returned 404 (URL structure changed).
Switched to REST API v4 with direct keyword pre-filtering — better quality, same coverage.

### Data Sources

| Source | Coverage | License |
|--------|----------|---------|
| CourtListener REST API v4 | Georgia `ga` + `gactapp` + `gasupct` courts, insurance-filtered, 2010–2026 | Court opinions: public domain. CourtListener data: CC-BY (Free Law Project) |
| OCGA Title 33 | Georgia Insurance Code, all chapters | Published law: public domain |

**Expected NAS size after Part 1b:** ~30–80 MB (`opinions-full.jsonl` with full plain_text)

### Running Ingestion

```bash
# From repo root. Token not needed for bulk downloads.
python -m src.legal.corpus_ingest courtlistener-bulk --court ga,gactapp

# OCGA (rate-limited scraper — runs in background, takes ~30 min)
python -m src.legal.corpus_ingest ocga --title 33

# Verify what we have
python -m src.legal.corpus_ingest verify
```

### CourtListener API Token (optional)

Sign up at https://www.courtlistener.com/sign-in/ (free). Copy `.env.legal.example` to `.env.legal` and add your token. Token is used only for future API queries — bulk downloads work without it.

```bash
cp .env.legal.example .env.legal
# Edit .env.legal and set COURTLISTENER_API_TOKEN
```

`.env.legal` is gitignored and never committed.

### Storage Layout

All corpus data lives on NAS only — not in the repo.

```
/mnt/fortress_nas/legal-corpus/
├── courtlistener/
│   ├── raw/opinions/ga.csv.gz          # Downloaded bulk CSV, unmodified
│   ├── raw/opinions/gactapp.csv.gz
│   ├── filtered/ga_insurance_filtered.jsonl    # Filtered output (one JSON per line)
│   ├── filtered/gactapp_insurance_filtered.jsonl
│   └── manifest.json                   # Pull timestamp, sha256, row counts
├── ocga/
│   ├── raw/title-33/                   # Raw HTML from Justia
│   └── title-33/                       # Parsed sections: 33-4-6.json, etc.
└── README.md                           # Provenance and license notes
```

---

## Part 2 — Training Pair Preparation (THIS PHASE)

Hybrid extraction: rule-based Patterns A-D (bulk) + Godhead Pattern E (high-value cases).

### Actual results (2026-04-19)

| Source | Pairs | Notes |
|--------|-------|-------|
| Pattern A (case analysis) | 1,021 | Facts → holding |
| Pattern B (issue spotting) | 71 | Section headers → issues list |
| Pattern C (citation lookup) | 32 | Citation context pairs (no filter — structural) |
| Pattern D (precedent outcome) | 1,013 | Insurance fact pattern → outcome |
| **Scripted total** | **2,137** | In `scripted.jsonl` |
| Pattern E (Godhead) | ~750 target | 150 cases × 5 pairs, est. $2.40 |

**Filter applied to A/B/D:** shared `_INSURANCE_KEYWORDS` constant (16 terms) against full `plain_text`. Removed 37 false-positive opinions (attorney discipline, child welfare, estate cases) that leaked through the CourtListener search.

### Running

```bash
python -m src.legal.training_pairs_scripted              # Patterns A-D
python -m src.legal.training_pairs_godhead --dry-run     # Preview, no API cost
python -m src.legal.training_pairs_godhead --limit 150   # Run Pattern E (~$2.40)
python -m src.legal.training_pairs_consolidate           # Merge + 80/10/10 split
python -m src.legal.training_pairs_sample 20             # Quality review sample
```

### Quality notes

Patterns A, B, D all use the shared `_INSURANCE_KEYWORDS` filter against full opinion text.
37 of 1,067 opinions with text were rejected (attorney discipline, child welfare, estate cases).
Pattern C is structural (citation extraction) — no content filter needed.
Manual review via `training_pairs_sample` recommended before Part 3 training.

### Output files (NAS)

```
/mnt/fortress_nas/legal-corpus/training-pairs/
├── scripted.jsonl     1,718 pairs (Patterns A-D)
├── godhead.jsonl      ~750 pairs (Pattern E, after Godhead run)
├── combined.jsonl     merged + deduped
├── train.jsonl        80%
├── val.jsonl          10%
└── holdout.jsonl      10%
```

---

## Part 3 — Judge Training (FUTURE)

Fine-tune `qwen2.5:32b` on spark-1 using LoRA adapters:

```
Target models:
  legal_reasoning_judge   — evaluates legal analysis quality
  brief_drafting_judge    — evaluates argument structure + citations

Base model: qwen2.5:32b (already on spark-1, 18 GB, Path C)
Training:   LoRA rank 16, target_modules q_proj,v_proj
Platform:   spark-1 via Ollama / custom training script
```

Output models will be registered in `fortress_atlas.yaml` as active judges once eval thresholds are met.

---

## Separation from Work Product

The `privilege_filter` in the backend continues to route Gary's own legal captures to `restricted_captures` (never used for training). This corpus is **entirely separate** — it is public law and public court opinions, not work product.

---

## Tests

```bash
cd ~/Fortress-Prime
python3 -m pytest src/legal/tests/test_corpus_ingest.py -v
# 16 tests: filter logic, year range, missing token graceful, storage layout, idempotency
```
