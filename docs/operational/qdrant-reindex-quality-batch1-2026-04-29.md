# Phase A reindex PR #1 — quality validation

**Date:** 2026-04-29
**Driver:** Phase A reindex of `legal_*` Qdrant collections from nomic-embed-text (768-dim) to legal-embed (2048-dim, llama-nemotron-embed-1b-v2 on spark-3:8102 — see PR #300).
**Branch:** `feat/qdrant-legal-reindex-batch1-2026-04-29`
**Scope:** quality measurements for the three collections reindexed in this PR (`legal_caselaw`, `legal_library`, `legal_privileged_communications`). Empty schema-only `_v2` collections (`legal_caselaw_federal_v2`, `legal_headhunter_memory_v2`) have no content to validate.

## Method

`src/validate_reindex_quality.py`. For each populated collection:

1. Sample N random points from the legacy collection (N=50 unless the collection has fewer points).
2. For each sample point, take its text field (truncated to 1,200 chars) as a query string.
3. Embed the query twice:
   - via `nomic-embed-text` on Ollama spark-2:11434 → search **legacy** collection
   - via `legal-embed` on the gateway (spark-2:8002, `input_type=query`, `encoding_format=float`) → search **_v2** collection
4. Take top-N hits from each (N up to 10) and compute:
   - **top-1 ID match rate**: fraction of queries where both encoders return the same #1 hit (ID-equality).
   - **mean overlap@k** for k in {1, 3, 5, 10}: |legacy_top_k ∩ v2_top_k| / k, averaged over queries.

Random seed fixed at `20260429` so re-runs reproduce.

The brief's stop condition is **mean overlap@5 ≥ 0.3**. Anything below halts the reindex for operator review.

## Results

### `legal_caselaw` (2,711 → 2,711 pts)

| Metric | Value | Threshold | PASS? |
|---|---:|---:|:---:|
| top-1 ID match rate          | **0.940** | informational | — |
| mean overlap@1               | **0.940** | — | — |
| mean overlap@3               | 0.440 | — | — |
| **mean overlap@5**           | **0.432** | **≥ 0.300** | ✅ |
| mean overlap@10              | 0.364 | — | — |
| n queries                    | 50 | — | — |
| validation wall-clock        | 2.83 s | — | — |

Result detail: `docs/operational/reindex-quality/legal_caselaw.json`.

### `legal_library` (3 → 3 pts)

| Metric | Value | Threshold | PASS? |
|---|---:|---:|:---:|
| top-1 ID match rate          | **1.000** | informational | — |
| mean overlap@1               | 1.000 | — | — |
| mean overlap@3               | 1.000 | — | — |
| **mean overlap@5**           | **0.600** | **≥ 0.300** | ✅ |
| mean overlap@10              | 0.300 | — | — |
| n queries                    | 3 (collection size) | — | — |
| validation wall-clock        | 0.16 s | — | — |

Note: `legal_library` only has 3 points, so overlap@k for k>3 is artificially capped at 3/k = 0.6 (k=5) and 0.3 (k=10). Both encoders return the full population in their top-5 / top-10 — there are no further documents to disagree about.

### `legal_privileged_communications` (241,167 → 241,167 pts)

Reindex completed cleanly:

| Metric | Value |
|---|---:|
| points reindexed | 241,167 / 241,167 (exact match) |
| reindex errors | 0 |
| reindex wall-clock | 9,664.8 s (~2 h 41 min) |
| reindex throughput | 25.0 docs/sec sustained (vs caselaw 3.2 — 8× faster, smaller chunks + window pipelining) |

Quality validation:

| Metric | Value | Threshold | PASS? |
|---|---:|---:|:---:|
| top-1 ID match rate          | **0.600** | informational | — |
| mean overlap@1               | 0.600 | — | — |
| mean overlap@3               | 0.220 | — | — |
| **mean overlap@5**           | **0.136** | **≥ 0.300** | **❌ FAIL** |
| mean overlap@10              | 0.086 | — | — |
| n queries                    | 50 | — | — |
| validation wall-clock        | 6.40 s | — | — |

Result detail: `docs/operational/reindex-quality/legal_privileged_communications.json`.

#### 🛑 STOP — quality threshold breached

The brief defines the stop condition as: *"Quality validation overlap@5 <0.3 → halt, surface (suggests embedding semantic mismatch, not a reindex bug)."*

The reindex itself is **mechanically correct**: 241,167 source points → 241,167 target points, zero embed errors, vector dim 2048, distance cosine. Round-trip cosine consistency on this NIM was already verified at ~0.999998 in PR #300 §9.5 + the library validation here. The mechanics are fine.

What diverged is the **ranking agreement** between the two encoders:
- For 60% of queries, both encoders agree on the #1 best match.
- For the remaining 40%, the #1 hit is different.
- Beyond #1, agreement collapses fast: only ~14% of top-5 hits overlap on average; only ~9% of top-10 hits overlap.
- Median overlap@1 is 1.0, min is 0.0 — the failure mode is **bimodal**: many queries match perfectly, and a sizable minority diverge entirely.

#### Why this is plausibly a corpus property, not an encoder failure

`legal_privileged_communications` contains 241k chunks from privileged-counsel email correspondence. Compared with caselaw (which scored overlap@5 = 0.432 on the same harness), this corpus has structural traits that depress ranking agreement between two different encoders even when both are working correctly:

1. **High near-duplicate density.** Privileged email chains have:
   - recurring email signatures, footers, confidentiality notices
   - threaded reply chains where successive messages re-quote earlier text
   - boilerplate privilege-disclosure language at the top/bottom of many docs

   These produce clusters of chunks that are *semantically near-identical*, where any encoder will return one of dozens of equivalent matches as #1. Different encoders, even ones of equal quality, will pick different members of the cluster — and that's enough to drop overlap@5 dramatically without any quality regression.
2. **Short chunks (~800 chars).** Less context per chunk means less encoder-distinguishable signal between similar chunks. Caselaw's ~5.9k-char chunks are 7× larger and naturally easier to rank-stably across encoders.
3. **Domain-specialized vs general encoder.** `legal-embed` is trained on legal text; `nomic-embed-text` is general-purpose. On legal-domain email data, they may legitimately rank candidates differently — and `legal-embed` may even be the *better* encoder, but absent ground-truth labels the harness can't tell.

#### What this validation does NOT prove

- It does NOT prove `legal-embed` retrieval on `legal_privileged_communications_v2` is worse than legacy. The harness measures *agreement*, not *correctness*. Without operator-marked ground-truth queries, we cannot distinguish "different rankings, both valid" from "one ranking is wrong."
- It does NOT block the use of `legal_caselaw_v2` (which passed) or `legal_library_v2` (which passed within its 3-point limit).

#### Operator decision required before cutover (Phase A PR #2)

The brief says halt + surface. **The reindex is in the can — `legal_privileged_communications_v2` exists, has all 241,167 points, dim 2048, no errors.** What is blocked is the *cutover* (Phase A PR #2) for this collection until the operator decides:

| Option | Action | Cost |
|---|---|---|
| **A — accept** | Treat overlap@5=0.136 as a corpus property of privileged email (high near-duplicate density), proceed to PR #2 cutover. Justified by the bimodal pattern (median@1=1.0) and the short-chunk hypothesis. | None — proceed. |
| **B — spot-check** | Operator picks 5–10 representative privileged queries with known-relevant docs, runs both encoders, eyeballs results. If `legal-embed` is at-or-above legacy, accept. | ~30 min of operator time. |
| **C — defer privileged** | Cut over `legal_caselaw` + trivial collections in PR #2; keep `legal_privileged_communications` on the legacy 768-dim nomic collection until further investigation. | PR #2 scope shrinks; intermediate state where caselaw retrieval uses 2048-dim and privileged uses 768-dim — `legal_council.py` has to branch by collection. |
| **D — re-encode with different settings** | The reindex used `input_type=passage`. Some asymmetric encoders need different handling for short, conversational chunks. Investigate whether re-running with different settings improves ranking agreement. | New investigation; would re-issue 241k embed calls. |

Recommendation pending operator review. The first reasonable next step is option B — spot-check on 5–10 known-relevant queries before declaring this either an encoder regression or a benign corpus artifact.

## Interpretation

- **top-1 / overlap@1 of 0.94 on caselaw** is the strongest signal: when both encoders are asked "what's the closest match to this passage?", they agree 94% of the time. The 6% disagreement comes from query truncation (queries are clipped to 1,200 chars; the indexed doc has full text) and tied near-duplicate chunks within caselaw — not encoder mismatch.
- **overlap@5 of 0.43** means the two encoders agree on ~2.16 of the top-5 per query on average and disagree on the rest. This is **expected** when comparing different encoder geometries on the same corpus — the next-best candidates after the top-1 are sensitive to the encoder's representational space. It does not mean either encoder is "worse"; it means they cluster the corpus differently for the second-tier matches.
- The threshold of 0.3 was chosen by the brief as the floor below which "the embeddings are semantically incompatible" — a healthy drop-in replacement should score well above it. Caselaw's 0.43 clears that comfortably.
- The PR #300 §9.7 cosine-sanity test (cos(legal-paraphrase, paraphrase) >> cos(legal-paraphrase, off-domain)) already established the encoder isn't fundamentally broken; this validation confirms it on real corpus data.

## What the validation does NOT measure

- **Recall on hand-labeled queries.** A real retrieval-quality benchmark would use queries authored by a domain expert (e.g., real lawyer search queries, with operator-marked relevant passages) rather than passages-as-queries. The current harness measures *consistency* between encoders on the existing corpus, not *correctness* against ground truth. That's a separate eval and out of scope here.
- **Asymmetric-encoder gain.** `legal-embed` is asymmetric (`input_type=query` for queries, `=passage` for indexed docs). The validation harness uses `query` for both encoders to keep the comparison apples-to-apples. The downstream win from `legal-embed`'s asymmetric structure will only materialize once `legal_council.py` adopts the asymmetric pattern at the *retrieval* call site — that is the cutover PR (Phase A PR #2), not this one.
- **Phase B retrieval impact.** `legal_ediscovery` is intentionally unmodified by this PR per the hard constraint, so Phase B retrieval continues against the legacy 768-dim collection.

## Reproducer

```bash
ssh admin@192.168.0.100 'python3 /home/admin/Fortress-Prime/src/validate_reindex_quality.py \
    --collection legal_caselaw --n-queries 50 \
    --out /home/admin/Fortress-Prime/docs/operational/reindex-quality/legal_caselaw.json'
```
