# Legal vault upload — Qdrant resilience runbook

How to detect, triage, and recover from silent Qdrant upsert failures during
case-scoped legal vault ingestion. Companion runbook to
[`legal-ingest-runs.md`](./legal-ingest-runs.md); Issue #228 reference.

---

## 1. Failure mode

### How Issue #228 surfaced

Vanderburge ediscovery ingest sweep, 2026-04-25:

| Metric | Value |
|---|---|
| Total documents in case | 535 |
| Reported by `vault_ingest_legal_case` summary | `processed=535 failed=0` |
| Documents with `chunk_count > 0` | 535 |
| Documents with **zero Qdrant points** | **79** (14.77%) |
| ↳ in `legal_privileged_communications` | 23 |
| ↳ in `legal_ediscovery` | 56 |

The script reported a clean run. Postgres reported every row as
`processing_status='completed'`. Qdrant held nothing for 14.77% of the
case's documents. Privileged Council retrieval and work-product retrieval
both returned 0 hits for those doc IDs because there were no points to
return.

### Root cause

Inside `process_vault_upload`, the prior `_upsert_to_qdrant` helper:

1. Built a single Qdrant `PUT /collections/{name}/points` payload from
   every chunk (could be 3,000–12,000 chunks for an email archive).
2. Wrapped the request in a bare `try/except Exception` returning `0`.
3. The caller treated `0` indistinguishably as "no chunks to upsert" and
   "every chunk failed" — and flipped the row to `processing_status='completed'`
   with `chunk_count=N` regardless.

A single oversized payload, transient Qdrant timeout, or HTTP error
silently zeroed out indexing. Nothing in Postgres recorded the gap. The
ingest run summary looked clean. The first signal was retrieval-time
("Where are the privileged emails?").

---

## 2. Detection logic

### The gap query (post-Phase A migration)

```sql
SELECT case_slug, COUNT(*) AS silent_failures
FROM legal.vault_documents
WHERE chunk_count > 0
  AND vector_ids IS NULL
GROUP BY case_slug
ORDER BY silent_failures DESC;
```

A row matching this predicate claims it produced N chunks but no Qdrant
point UUIDs were ever recorded as indexed. That is the Issue #228
signature on **pre-fix** data (rows that landed before the Phase B writer
was deployed).

The partial index `idx_vault_documents_vector_ids_partial` (Phase A) keeps
this query cheap even on multi-million-row vault tables — the predicate
matches the index's `WHERE` clause exactly.

### `processing_status='qdrant_upsert_failed'` — post-fix new failures

Rows newly produced by the Phase B writer that hit a verifiable batch
failure transition to this status (Phase A.1 added the value to the
CHECK constraint). The row carries:

* `chunk_count` — how many chunks the embedder produced.
* `vector_ids UUID[]` — the partial accumulator of UUIDs from batches
  that succeeded **before** the failure (may be empty on a first-batch
  failure, may be partial on a mid-stream failure, will never be `NULL` —
  on partial-zero it's `'{}'::uuid[]`).
* `error_detail TEXT` — structured JSON, truncated at 8192 chars.

### `error_detail` JSON schema

```jsonc
{
  "batch_index": 3,                // 0-indexed, which batch failed
  "expected_count": 500,           // points in the failed batch
  "actual_count": 0,               // verified-OK points in failed batch (always 0)
  "qdrant_collection": "legal_ediscovery",   // or legal_privileged_communications
  "qdrant_error_payload": "...",   // repr(exc) or serialized HTTP body, ≤1024 chars
  "first_failed_uuid": "uuid-of-first-point-in-failed-batch",
  "accumulator_so_far_count": 3000,           // points in successful batches before failure
  "occurred_at": "2026-04-26T19:14:35.123+00:00",
  "track": "work_product",         // or "privileged"
  "doc_id": "vault-row-uuid",
  "case_slug": "vanderburge-v-...",
  "file_name": "...pdf",
  "accumulator_so_far": ["uuid-1", "uuid-2", ...],
  "source": "process_vault_upload"  // or "reprocess_failed_qdrant_uploads"
}
```

The truncation at exactly 8192 chars is deliberate: most operator queries
on a failed run want the head of this payload (`batch_index`, `track`,
`first_failed_uuid`). Programmatic re-parsing is not the design intent —
the column is operator/log readable. A truncation cut may fall inside a
string value, breaking strict JSON parse. Use substring queries:

```sql
SELECT id, case_slug, file_name,
       (regexp_match(error_detail, '"batch_index": (\d+)'))[1] AS batch_index,
       (regexp_match(error_detail, '"track": "([^"]+)"'))[1] AS track
FROM legal.vault_documents
WHERE processing_status = 'qdrant_upsert_failed'
ORDER BY case_slug, file_name;
```

---

## 3. Recovery decision tree

```
For each silent-failure row (chunk_count > 0 AND vector_ids IS NULL):

    Are Qdrant points present for this doc_id?
    (scroll legal_ediscovery + legal_privileged_communications
     filtered on payload.document_id = doc_id)

    │
    ├── YES, points exist
    │       Use ▶ backfill_vector_ids
    │       The chunks were indexed; the row just lost its accounting.
    │       Backfill scrolls Qdrant and writes the recovered UUIDs to
    │       vector_ids. Idempotent (UPDATE … WHERE vector_ids IS NULL).
    │
    └── NO, no points
            Use ▶ reprocess_failed_qdrant_uploads
            True silent failure — chunks were never indexed. Reprocess
            re-runs the (extract → privilege classifier → chunk → embed →
            batched upsert) pipeline against the original NFS file.
            Phase B.1 UUID5 makes the upsert idempotent — if some points
            DID land partially before the silent gap, the same UUIDs
            will overwrite cleanly (no orphans).

Rows with processing_status='qdrant_upsert_failed' (post-fix new
failures) — always use ▶ reprocess_failed_qdrant_uploads. The Phase B
writer already recorded what's missing in error_detail; reprocess
re-drives the pipeline against the same row identity.
```

### Concrete commands

**Decide on a case** — run the gap query above and pick a `case_slug`.

**Backfill** (recovers accounting only — points already in Qdrant):

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform

# Dry-run first, always.
python -m backend.scripts.backfill_vector_ids \
    --case-slug <slug> --dry-run

# After operator review:
python -m backend.scripts.backfill_vector_ids \
    --case-slug <slug>
```

**Reprocess** (re-drives the pipeline — for true silent failures and
post-fix `qdrant_upsert_failed` rows):

```bash
# Dry-run first.
python -m backend.scripts.reprocess_failed_qdrant_uploads \
    --case-slug <slug> --dry-run

# After operator review (full sweep):
python -m backend.scripts.reprocess_failed_qdrant_uploads \
    --case-slug <slug>

# Or staged batch:
python -m backend.scripts.reprocess_failed_qdrant_uploads \
    --case-slug <slug> --limit 250

# Or scoped to a specific UUID list:
python -m backend.scripts.reprocess_failed_qdrant_uploads \
    --case-slug <slug> \
    --doc-id-file /tmp/<slug>-228-doc-ids.txt
```

---

## 4. Sweep procedure — find silent failures across all cases

### Per-case audit query

```sql
WITH gap AS (
  SELECT case_slug,
         COUNT(*) FILTER (WHERE chunk_count > 0 AND vector_ids IS NULL) AS pre_fix_silent,
         COUNT(*) FILTER (WHERE processing_status = 'qdrant_upsert_failed') AS post_fix_failed,
         COUNT(*)                                                          AS total_rows
  FROM legal.vault_documents
  GROUP BY case_slug
)
SELECT case_slug, total_rows, pre_fix_silent, post_fix_failed,
       ROUND(100.0 * (pre_fix_silent + post_fix_failed) / NULLIF(total_rows, 0), 2)
         AS pct_failed
FROM gap
WHERE pre_fix_silent > 0 OR post_fix_failed > 0
ORDER BY (pre_fix_silent + post_fix_failed) DESC;
```

Run against `fortress_db` (LegacySession source of truth). Mirror the
same query against `fortress_prod` to verify drift is zero — the
bilateral mirror should keep them identical row-for-row.

### Recommended sweep order

Drives the cases known to have ediscovery vault data, biggest blast
radius first:

| Order | Case | Notes |
|---|---|---|
| 1 | `vanderburge-v-knight-fannin` | Issue #228 origin — already audited at 79 silent failures |
| 2 | `7il-v-knight-ndga` (Case I) | Closed judgment-against; high doc volume from Drupal era |
| 3 | `7il-case-ii` | Active counsel-search; smaller corpus, but live retrieval-impacting |
| 4 | `generali-...` | CSV email archives — most exposed to large-chunk thread shapes |
| 5 | `prime-trust-...` | Smaller corpus, lowest priority |

For each case: run the gap query → run the appropriate dry-run script →
operator review → execute. Treat each case as its own change-window;
don't sweep multiple cases in a single command-line burst.

---

## 5. Vanderburge-specific recovery commands

### Saved doc-ID files from the 2026-04-25 audit

```
/tmp/vanderburge-228-failed-privileged-doc-ids.txt    23 UUIDs
/tmp/vanderburge-228-failed-ediscovery-doc-ids.txt    56 UUIDs
```

Each file is one UUID per line; `#` comments and blanks are ignored by
`reprocess_failed_qdrant_uploads`.

### Recommended recovery sequence

**Step 1 — confirm the saved files are still on disk and match the audit:**

```bash
wc -l /tmp/vanderburge-228-failed-privileged-doc-ids.txt
wc -l /tmp/vanderburge-228-failed-ediscovery-doc-ids.txt
# Expect: 23 and 56 respectively.
```

**Step 2 — dry-run on the privileged track first** (smaller, narrower
blast radius if anything is wrong):

```bash
cd /home/admin/Fortress-Prime/fortress-guest-platform
python -m backend.scripts.reprocess_failed_qdrant_uploads \
    --case-slug vanderburge-v-knight-fannin \
    --doc-id-file /tmp/vanderburge-228-failed-privileged-doc-ids.txt \
    --dry-run
```

Inspect the dry-run manifest at
`/mnt/fortress_nas/audits/reprocess-vanderburge-v-knight-fannin-{ts}.json`.
The `candidates_count` should be 23. The `args` dict should echo the
flags. If anything looks wrong, stop and re-investigate.

**Step 3 — execute the privileged-track recovery:**

```bash
python -m backend.scripts.reprocess_failed_qdrant_uploads \
    --case-slug vanderburge-v-knight-fannin \
    --doc-id-file /tmp/vanderburge-228-failed-privileged-doc-ids.txt
```

Expected `# done:` line: `attempted=23 recovered=23 still_failed=0
mirror_drift=0 by_track={'privileged': 23}`.

**Step 4 — verify privileged track in Postgres:**

```sql
SELECT processing_status, COUNT(*)
FROM legal.vault_documents
WHERE case_slug = 'vanderburge-v-knight-fannin'
  AND id::text IN (... 23 UUIDs ...)
GROUP BY processing_status;
```

Expect: 23 rows in `locked_privileged`, all with `vector_ids IS NOT NULL`.

**Step 5 — repeat steps 2–4 for the work-product track** with
`/tmp/vanderburge-228-failed-ediscovery-doc-ids.txt`. Expected
`# done:` line: `attempted=56 recovered=56 still_failed=0`.

**Step 6 — final verification (full case):**

```sql
SELECT processing_status, COUNT(*),
       COUNT(*) FILTER (WHERE vector_ids IS NULL)  AS still_unindexed
FROM legal.vault_documents
WHERE case_slug = 'vanderburge-v-knight-fannin'
GROUP BY processing_status;
```

Expect: zero `still_unindexed` across all status buckets, zero rows in
`qdrant_upsert_failed`.

---

## 6. Operational runbook for future incidents

### Detection trigger

The first signal of a new Issue #228-style failure may come from any of:

* Retrieval-time: privileged Council or work-product retrieval returns 0
  hits for documents an operator knows are in the case.
* Post-run audit: the gap query returns non-zero `pre_fix_silent` or
  `post_fix_failed` counts on a case the operator believes was fully
  ingested.
* Tracker degraded warning: `ingest_run_tracker_degraded` log lines in
  journalctl indicate a run could not write its audit row — a degraded
  run can leave the gap query under-counting (the row's terminal status
  may not have been updated).

> **Note on Issue #233 (distinct bug):**
> `vault_ingest_legal_case` reports its own `processed/skipped/errored`
> counters from the tracker, *not* from a Qdrant cross-check. Until
> #233 is fixed, the script's `failed=0` summary line cannot be trusted
> as evidence the case is clean. Run the gap query independently
> after every ingest sweep.

### Triage checklist

1. Run the gap query (Section 2) — get per-case counts.
2. Run the sweep audit (Section 4) — confirm scope across cases.
3. For the most-affected case, sample 5–10 silent-failure rows:
   ```sql
   SELECT id, file_name, processing_status, chunk_count, error_detail
   FROM legal.vault_documents
   WHERE case_slug = '<slug>'
     AND ((chunk_count > 0 AND vector_ids IS NULL)
          OR processing_status = 'qdrant_upsert_failed')
   LIMIT 10;
   ```
4. Decide per Section 3 — backfill (points exist) vs reprocess (points
   missing or post-fix failure). When unsure, dry-run reprocess: it's
   idempotent and will report any drift.

### Execution gates

* Dry-run is **mandatory** before any production reprocess/backfill run.
* Operator must read the dry-run manifest and confirm `candidates_count`
  matches the gap query's count for that case.
* Staged retries via `--limit N` are preferred for cases with >500
  candidates — verify the first batch lands cleanly before sweeping the
  rest.
* Do not run reprocess and `vault_ingest_legal_case` concurrently on
  the same case. The reprocess script does not acquire the per-case
  `/tmp/vault-ingest-{slug}.lock` file (its safety is from UUID5
  idempotency + Postgres row-level UPDATE atomicity), but interleaving
  the two scripts produces ambiguous audit-trail attribution.

### Verification after recovery

1. Re-run the gap query — both `pre_fix_silent` and `post_fix_failed`
   should be 0 for the recovered case.
2. Cross-DB consistency check:
   ```sql
   -- Run against both fortress_db and fortress_prod, expect identical results.
   SELECT processing_status, COUNT(*),
          COUNT(*) FILTER (WHERE vector_ids IS NULL)  AS unindexed
   FROM legal.vault_documents
   WHERE case_slug = '<slug>'
   GROUP BY processing_status
   ORDER BY processing_status;
   ```
3. Spot-check Qdrant:
   ```bash
   curl -s -X POST "$QDRANT_URL/collections/legal_ediscovery/points/count" \
        -H 'Content-Type: application/json' \
        -d '{"filter":{"must":[{"key":"case_slug","match":{"value":"<slug>"}}]},"exact":true}'
   ```
   Compare the count against `SUM(chunk_count)` for the same case in
   `vault_documents` where `processing_status='completed'`. They should
   match.

---

## 7. Architecture notes

### UUID5 idempotency contract (Phase B.1)

Both Qdrant collections use deterministic point IDs:

```python
point_id = uuid5(NAMESPACE, f"{file_hash}:{chunk_index}")
```

Where `NAMESPACE` is `_QDRANT_WORK_PRODUCT_NS` for `legal_ediscovery` and
`_QDRANT_PRIVILEGED_NS` for `legal_privileged_communications`. Both
namespaces are module-level constants in `backend/services/legal_ediscovery.py`
and **must never be rotated** — point IDs in Qdrant are keyed on the
namespace, so changing the namespace would orphan every existing point.

Consequence: re-running the upload pipeline against the same physical
file produces the same point IDs. Qdrant's `PUT /collections/{name}/points`
is upsert-semantic — same ID, same payload, no duplication.

### Why batch size = 1000

Qdrant's per-PUT payload size starts erroring on requests carrying
~3,000+ chunks at the 768-dim embedding shape used by `nomic-embed-text`
(the precise threshold depends on memory pressure on the Qdrant node).
Splitting at 1,000 chunks per batch:

* Keeps every PUT well under the practical payload limit.
* Lets each batch own its own 60s timeout — no single-request timeout
  pile-up on multi-thousand-chunk emails.
* Surfaces the failure at a known boundary (`batch_index`) so partial
  recovery is precise rather than all-or-nothing.

The constant `batch_size=1000` lives in `_batch_upsert_with_verification`
and should be tuned only after a load-test against the production Qdrant
cluster. Don't lower it on a per-call basis — that just multiplies HTTP
overhead without changing the failure mode.

### `error_detail` truncation at 8192 chars

The Phase B writer trims `err_payload[:8192]` before `UPDATE`. The cut
falls inside the JSON body and may break strict parse. By design — the
column is operator/log-readable, not programmatically re-parsed. Use
substring/regex extraction (Section 2) for fields you care about. The
8KB ceiling protects the row from runaway accumulator-list bloat on
large failed batches (a 12,000-UUID accumulator at 36 chars/UUID + JSON
overhead would otherwise approach 500 KB per row).

If a future workflow needs structured access to the failure payload,
add a separate JSONB column rather than removing the truncation —
keeping the human-readable text column intact preserves the ops contract.

### Bilateral DB mirror

`legal.vault_documents` is mirrored across `fortress_db` (LegacySession
target — what FastAPI handlers and the operator UI read) and
`fortress_prod`. Every state transition from the upload pipeline,
backfill script, and reprocess script writes to **both** in lock-step.

* `process_vault_upload` writes to `fortress_db` (via LegacySession);
  `vault_ingest_legal_case._mirror_row_db_to_prod` mirrors to
  `fortress_prod` after each successful row.
* `backfill_vector_ids._update_vector_ids` writes both DBs directly.
* `reprocess_failed_qdrant_uploads._persist_success_state` /
  `_persist_failure_state` write both DBs directly.

If any of these helpers reports rowcount=1 on one DB and rowcount=0 on
the other, the script flags `mirror_drift` and exits with code 2. That
is the operator's signal to investigate concurrent writers (another
script, an interactive `psql` UPDATE, a stuck transaction) before
running anything else.

### Why `vault_ingest_legal_case` reports `failed=0` while silent failures occur

Tracked separately as **Issue #233** — distinct from #228. The ingest
script's tracker counts rely on the per-row outcome dict returned by
`process_vault_upload`. Pre-Phase-B, that dict could not distinguish
"no chunks produced" from "every chunk failed to upsert" because the
upsert helper returned `0` in both cases. Phase B teaches the upsert
helper to return a structured `(uuids, failure_dict)` tuple, but the
ingest-script summary code still rolls up the row's final status, not
its Qdrant indexing outcome — a row that lands as
`processing_status='qdrant_upsert_failed'` increments `errored`, but a
row that landed as `completed` with empty `vector_ids` (the pre-fix
silent path) does not. The gap query is the correct cross-check until
#233 lands.

---

## Cross-references

* Issue #228 — silent Qdrant upsert failures (this runbook)
* Issue #233 — `vault_ingest_legal_case` summary cannot detect Qdrant gaps
* [`docs/runbooks/legal-ingest-runs.md`](./legal-ingest-runs.md) —
  general `legal.ingest_runs` audit trail and tracker semantics
* `backend/services/legal_ediscovery.py` — production pipeline + UUID5
  namespaces + batch upsert helper
* `backend/scripts/backfill_vector_ids.py` — pre-fix data recovery
* `backend/scripts/reprocess_failed_qdrant_uploads.py` — full pipeline
  re-drive for true silent failures and post-fix failures
* `backend/tests/test_legal_vault_upload_qdrant_resilience.py` —
  resilience coverage suite (23 tests)
