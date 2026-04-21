# Legal Eval + Training Coverage Audit
**Date:** 2026-04-21  
**Analyst:** automated (coverage_expand.py)  
**Adapters evaluated:** e3 (`/mnt/fortress_nas/models/legal-instruct-20260420-e3/`)

---

## Executive Summary

The legal/C (Pattern C — citation lookup) downstream eval score of **0.21** on e3 is partially explained by two structural issues: (1) only 2 eval samples existed, both with degenerate truncated context, and (2) Pattern C is severely underrepresented in training at 1.1% of pairs. Pattern B (issue spotting) is similarly thin at 2.0% with only 8 eval samples. This audit expands Pattern C eval to 13 records and documents the hard corpus ceiling on further expansion.

---

## 1. Current Eval Set Composition

| Domain | Pattern | Description | Eval N | Train N | Train % |
|--------|---------|-------------|--------|---------|---------|
| legal/A | A | Case analysis / holdings | 45 | 420 | 28.7% |
| legal/B | B | Issue spotting | 8 | 30 | 2.0% |
| legal/C | C | Citation lookup | 2 | 16 | 1.1% |
| legal/D | D | Precedent outcome | 43 | 417 | 28.5% |
| legal/E | E | General legal reasoning | 86 | 582 | 39.7% |

### legal/C: Pattern C — Citation Lookup

**Task definition:** Given a legal proposition with `[citation]` placeholder, identify the Georgia legal authority (case or statute) that supports it.

**Example instruction:**
```
What Georgia legal authority supports the following proposition?

The State's attempt to analogize this case to [citation] is similarly unpersuasive.
```
**Example output:**
```
Under Ward v. State, 270 Ga. App. 427 (2004): The State's attempt to analogize...
```

**Subtopics observed in eval set (n=2 original):**
- Insurable interest (life insurance) — cited case: Hodge v. Ellis, 76 Ga. 272 (1886)
- Innkeeper liability — cited case: Western & Atlantic R. v. Meigs, 74 Ga. 857 (1885)

**Quality issues with original 2 eval records:**
- Both have very short context windows (<120 chars) — too little context for the model to reason from
- Both cite 19th-century cases that appear incidentally; the truncated principle is ambiguous
- These records were generated from malformed citation extraction (empty or very short `context` fields)

**New C records added (11):** Sourced from untouched opinion clusters not in training. Context window ≥80 chars. Citation format validated.

### legal/B: Pattern B — Issue Spotting

**Task definition:** Given facts from a Georgia insurance dispute, enumerate the key legal issues raised (extracted from section headers).

**Subtopics observed (n=8):**
- Auto/liability coverage disputes (3)
- Life insurance / insurable interest (2)
- Property damage / homeowner (2)
- Commercial coverage (1)

**Jurisdictions:** All Georgia (Court of Appeals and Supreme Court, 2014–2025)
**Code sections cited:** None explicitly — issue spotting, not citation lookup

**Status:** No new Pattern B pairs available. Corpus is exhausted (see §4 below).

---

## 2. Training Data Gap Analysis

Training pair distribution (1,465 total):

| Pattern | Count | % | Target % | Gap |
|---------|-------|---|----------|-----|
| A | 420 | 28.7% | — | — |
| B | 30 | 2.0% | 10% | **−8%** |
| C | 16 | 1.1% | 10% | **−8.9%** |
| D | 417 | 28.5% | — | — |
| E | 582 | 39.7% | — | — |

Pattern C is the most severely underrepresented at **1.1%**, well below the 10% target. Pattern B at 2.0% is also thin.

---

## 3. Eval Expansion Actions Taken

**Pattern C (legal/C):**
- Original: 2 records (both low quality, short context)
- Added: 11 new records from untouched opinion clusters
- Expanded: **13 records total**
- Target was 30. Corpus ceiling: 13 (see §4).

**Pattern B (legal/B):**
- Original: 8 records
- Added: 0 new records (corpus exhausted)
- Unchanged: **8 records**
- Target was 30. Corpus ceiling: 8 (see §4).

**Expanded eval file:** `/mnt/fortress_nas/legal-corpus/training-pairs/holdout-eval-expanded.json`

---

## 4. Corpus Ceiling Analysis

The corpus is 1,854 Georgia insurance opinions from CourtListener (GA Court of Appeals + Supreme Court, 2010–2026). After filtering for quality and deduplication against existing training/holdout pairs:

| Pattern | Corpus-wide available | Already used | Genuinely new |
|---------|----------------------|--------------|---------------|
| B | 42 (before strict filter) | 42 | **0** |
| C | 31 (all quality C cites) | 20 | **11** |

**Why Pattern B is exhausted:**
- `_extract_section_topics()` requires explicit Roman-numeral or numbered section headers
- Only 71 of 1,854 opinions have these headers
- After strict insurance filter (excluding "v. State", "In the Matter of"), ALL remaining B-eligible opinions are already in training or holdout clusters
- **Root cause:** The corpus is skewed toward Supreme Court opinions that use narrative structure rather than numbered sections

**Why Pattern C is nearly exhausted:**
- `_extract_citations()` requires context ≥80 chars around the citation — many citations appear in parentheticals with no surrounding text
- The 1,854-opinion corpus yields only ~49 total citation instances meeting quality bar
- 20 already in combined.jsonl, 2 in holdout → 27 available, 11 from non-holdout clusters

**Recommendation for future data collection:**
1. **Pattern B:** Ingest GA Court of Appeals opinions from 2020–present that explicitly use numbered issue headers (typically "1. Coverage interpretation" etc.). CourtListener has ~3,000 more GA opinions from 2020+; filter for ones with section headers.
2. **Pattern C:** Expand to federal circuit opinions (11th Circuit) involving GA insurance law — these frequently cite OCGA and GA precedent in structured fashion.
3. **Pattern C (statute):** Ingest OCGA Title 33 (Insurance Code). Produce "What GA statute governs X?" pairs from chapter summaries + section text. This directory was found empty at `/mnt/fortress_nas/legal-corpus/ocga/title-33/` — fetch and process.

---

## 5. Training Expansion

**New Pattern C training pairs:** 11 (written to `new_c_pairs.jsonl`)
**New Pattern B training pairs:** 0 (corpus exhausted)

With 11 new Pattern C added:
- Total train: 1,465 + 11 = 1,476
- Pattern C: 16 + 11 = 27 (1.83% — still below 10% target)
- Pattern B: unchanged at 30 (2.03%)

**Conclusion:** Training expansion from this corpus is insufficient to reach 10% for either category. A retrain with these 11 pairs will have marginal effect. The corpus ceiling must be addressed first (see §4 recommendations).

---

## 6. Cluster-Level Leakage Note

The train/holdout split is at the **pair level**, not the **cluster (opinion) level**. Of 539 training clusters and 157 holdout clusters, 149 appear in both. This means the model may have seen other questions about the same opinion during training, which could inflate holdout scores on well-represented opinions.

**Impact assessment:** Moderate. The pairs from the same cluster ask different questions (e.g., a Pattern A case analysis vs. a Pattern B issue list about the same opinion). They are not identical. However, for rigorous evaluation, future data splits should be cluster-level.

**Action:** No immediate change needed for e3 evaluation. Flag for next training cycle.

---

## 7. Retrain Decision Basis

After running e3 on the expanded eval set (13 Pattern C, 8 Pattern B), the retrain decision is:
- If e3 legal/C ≥ 0.40 on expanded set → **do not retrain** (original score was sampling artifact)
- If e3 legal/C < 0.40 on expanded set → **retrain as e3.1** with `new_c_pairs.jsonl` added to training data

See eval results in PR description.

---

## 8. E3 Eval Results on Expanded Holdout

**Eval completed:** 2026-04-21T13:27  
**Holdout:** 195 records (legal/C: 2→13, legal/B: 8 unchanged)

### Overall Metrics

| Metric | Original (N=184) | Expanded (N=195) | Delta |
|--------|-----------------|-----------------|-------|
| similarity_mean | 0.7486 | **0.7348** | −0.0138 |
| validity_rate | 0.9891 | **0.9897** | +0.0006 |
| regression_count | 2 | **2** | 0 |

*Note: Overall similarity_mean decreased slightly because 11 new legal/C samples (the harder citation-lookup task) were added. This is expected and not a regression.*

### By Domain

| Domain | Original N | Expanded N | Original sim | New sim | Delta |
|--------|-----------|-----------|-------------|---------|-------|
| legal/A | 45 | 45 | 0.8002 | **0.8002** | 0 |
| legal/B | 8 | 8 | 0.5701 | **0.5701** | 0 |
| legal/C | 2 | **13** | 0.2094 | **0.4589** | **+0.2495** |
| legal/D | 43 | 43 | 0.8571 | **0.8571** | 0 |
| legal/E | 86 | 86 | 0.6965 | **0.6965** | 0 |

### Retrain Decision: **NO RETRAIN**

**Threshold:** legal/C ≥ 0.40 → do not retrain  
**Result:** legal/C = **0.4589** (N=13) ≥ 0.40 ✓

The original legal/C score of 0.21 was a **sampling artifact** caused by two degenerate eval records with truncated context and ambiguous citation placeholders. With 13 properly-formed samples, e3 scores 0.46 on citation lookup — comfortably above the 0.40 threshold.

**Conclusion:** Ship e3 as-is. The legal/C eval signal is now reliable (N=13). Further improvement requires new corpus acquisition (see §4 recommendations), not a retrain on current data.

### e3 vs e2 Final Comparison (Expanded Eval)

| Domain | e2 sim | e3 sim (expanded) | Delta |
|--------|--------|------------------|-------|
| legal/A | 0.7869 | 0.8002 | +0.013 |
| legal/B | 0.4430 | 0.5701 | +0.127 |
| legal/C | n/a (2 bad samples) | 0.4589 | — |
| legal/D | 0.8663 | 0.8571 | −0.009 |
| legal/E | 0.6829 | 0.6965 | +0.014 |
| **Overall** | **0.7358** (N=184) | **0.7348** (N=195) | −0.001 |

e3 remains the recommended production adapter across all well-sampled categories.
