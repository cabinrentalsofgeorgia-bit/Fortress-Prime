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

## Part 2 — Training Pair Preparation (NEXT)

Convert filtered corpus → instruction-tuning pairs for LoRA fine-tuning.

Stub: `src/legal/training_prep.py` — see docstring for full design.

**Pair types planned:**
1. Legal reasoning: `{facts}` → `{court's coverage analysis}`
2. Bad faith analysis: `{claims handling facts}` → `{O.C.G.A. § 33-4-6 analysis}`
3. Statutory interpretation: `{section query}` → `{text + relevant cases}`
4. Coverage denial: `{policy language + facts}` → `{denial analysis}`

**Output:** `/mnt/fortress_nas/finetune-artifacts/legal-corpus-v1/`
- `train.jsonl` (80%)
- `holdout.jsonl` (20%)
- `manifest.json` (provenance, split details)

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
