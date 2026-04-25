# Runbook: `legal.vault_documents`

This is the integrity contract and operations playbook for the table that
backs every uploaded artifact in the Legal vault (filings, productions,
emails, deposition transcripts). Read this before bulk ingestion, before
recovering a stuck case, or when triaging a privilege-shielded row.

Owner: Legal Platform. Last hardened: PR D-pre2 (alembic
`d8e3c1f5b9a6_vault_documents_integrity`).

---

## 1. Schema

```sql
CREATE TABLE legal.vault_documents (
    id                UUID NOT NULL,
    case_slug         TEXT NOT NULL,
    file_name         TEXT NOT NULL,
    nfs_path          TEXT NOT NULL,
    mime_type         TEXT NOT NULL,
    file_hash         TEXT NOT NULL,            -- SHA-256
    file_size_bytes   BIGINT NOT NULL,
    processing_status TEXT NOT NULL DEFAULT 'pending',
    chunk_count       INTEGER,
    error_detail      TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT vault_documents_pkey PRIMARY KEY (id),
    CONSTRAINT fk_vault_documents_case_slug
        FOREIGN KEY (case_slug) REFERENCES legal.cases (case_slug)
        ON DELETE CASCADE,
    CONSTRAINT uq_vault_documents_case_hash
        UNIQUE (case_slug, file_hash),
    CONSTRAINT chk_vault_documents_status
        CHECK (processing_status IN (
            'pending', 'processing', 'vectorizing',
            'complete', 'completed',
            'ocr_failed', 'error', 'failed', 'locked_privileged'
        ))
);
```

Index inventory (every one is hot):

| Index | Purpose |
| --- | --- |
| `vault_documents_pkey` | by `id` |
| `uq_vault_documents_case_hash` | dedup + the `ON CONFLICT` target |
| `idx_vault_documents_case_slug` | per-case listing in the UI |
| `idx_vault_documents_status` (partial — active states) | sweep queries that look for stuck rows |
| `idx_vault_documents_created_at` (DESC) | recent-uploads view |
| `idx_vault_documents_file_hash` | cross-case dedup analytics |

The partial status index covers exactly the "needs operator attention or
will move soon" states: `pending`, `processing`, `vectorizing`, `error`,
`failed`, `ocr_failed`. Terminal states (`complete`, `completed`,
`locked_privileged`) are excluded — sweeping them every minute would be
wasteful and they are reachable via `case_slug` instead.

---

## 2. State machine (Option A — bilingual vocabulary)

```
                        ┌──────────────────┐
                        │   pending        │  initial INSERT
                        └────────┬─────────┘
                                 │
                                 ▼
              ┌──────────────────┴──────────────────┐
              │                                     │
              ▼                                     ▼
     ┌──────────────────┐                  ┌──────────────────┐
     │  vectorizing     │                  │  ocr_failed      │
     │  (live code)     │                  │  empty extract   │
     │                  │                  │  on a PDF        │
     │  or 'processing' │                  └──────────────────┘
     │  (spec target)   │                          │
     └────────┬─────────┘                          │
              │                                    │ → pickup by
       ┌──────┴──────────┐                          OCR sweep
       ▼                 ▼                           script
┌─────────────┐    ┌─────────────────┐
│ completed   │    │  failed / error │
│  (live)     │    │                 │
│  or         │    │  privilege rule:│
│  'complete' │    │ locked_privileged│
│  (spec)     │    │                 │
└─────────────┘    └─────────────────┘
```

The vocabulary is intentionally **bilingual** while a cleanup PR (Issue
#193) is pending. Both sets of terminal-ish words mean the same thing:

| Spec target | Live code writer | Meaning |
| --- | --- | --- |
| `processing` | `vectorizing` | Chunking + embeddings in flight |
| `complete` | `completed` | Successful end state |
| `error` | `failed` | Pipeline blew up |

Two states are unique and not part of the synonym map — keep them as-is:

- `ocr_failed` — text extraction returned empty bytes for a PDF. The OCR
  sweep (`backend/scripts/ocr_legal_case.py`) picks these up.
- `locked_privileged` — CoCounsel privilege shield triggered with
  confidence ≥ 0.7. **Compliance-distinct:** the row is intentionally
  withheld from vector indexing. Do not "recover" these without legal
  review.

---

## 3. Dedup contract

```sql
UNIQUE (case_slug, file_hash)
```

- Same hash, **same case**: rejected as a duplicate. The file is not
  written to NFS a second time and no new row is created.
- Same hash, **different case**: allowed. Two cases that legitimately share
  a discovery PDF (e.g. the same filed exhibit) each get their own row,
  their own NFS copy, and their own privilege classification. This is the
  correct legal posture — discovery in case A does not silently leak
  evidence into case B's audit trail.

The race is held by the constraint, not by an application-level lock.
`process_vault_upload()` first does a fast `SELECT` for early exit, then
relies on `INSERT ... ON CONFLICT ON CONSTRAINT
uq_vault_documents_case_hash DO NOTHING RETURNING id`. If the second
INSERT loses the race, the function deletes the file it just wrote and
returns `{status: "duplicate"}`.

---

## 4. Operator queries

```sql
-- 4.1  How is each case doing?
SELECT case_slug,
       processing_status,
       count(*) AS rows
FROM   legal.vault_documents
GROUP  BY case_slug, processing_status
ORDER  BY case_slug, processing_status;

-- 4.2  What is stuck?
--      (uses the partial active-states index)
SELECT id, case_slug, file_name, processing_status,
       error_detail, created_at
FROM   legal.vault_documents
WHERE  processing_status IN
       ('pending', 'processing', 'vectorizing',
        'error', 'failed', 'ocr_failed')
ORDER  BY created_at DESC
LIMIT  100;

-- 4.3  What needs OCR right now?
SELECT case_slug, count(*) AS image_only_pdfs
FROM   legal.vault_documents
WHERE  processing_status = 'ocr_failed'
GROUP  BY case_slug
ORDER  BY image_only_pdfs DESC;

-- 4.4  Privilege register (do NOT vectorize these)
SELECT id, case_slug, file_name, created_at
FROM   legal.vault_documents
WHERE  processing_status = 'locked_privileged'
ORDER  BY created_at DESC;

-- 4.5  Recent uploads (uses created_at DESC index)
SELECT case_slug, file_name, processing_status, created_at
FROM   legal.vault_documents
ORDER  BY created_at DESC
LIMIT  50;

-- 4.6  Cross-case hash analysis (uses file_hash index)
SELECT file_hash, count(DISTINCT case_slug) AS cases
FROM   legal.vault_documents
GROUP  BY file_hash
HAVING count(DISTINCT case_slug) > 1;
```

---

## 5. Recovery playbook

### 5.1  A row is stuck in `pending`

Means the worker died between the `INSERT` and the privilege classifier.
The row is safe to retry. Re-run the upload pipeline against the row's
`nfs_path`. Verify by hand first:

```sql
SELECT id, nfs_path, file_size_bytes, error_detail
FROM   legal.vault_documents
WHERE  id = :doc_id;
```

If `nfs_path` exists on disk and bytes match, kick the pipeline. If the
file is gone, mark `failed` with an explanation and re-upload from the
source.

### 5.2  A row is stuck in `vectorizing`

Means embeddings or Qdrant upsert hung. The row carries the chunked text
intent but no `chunk_count`. Safe to nudge it: re-run vectorization. If
the issue is Qdrant down, the helper `_upsert_to_qdrant` returns 0 and
the pipeline moves the row to `completed` with `vectors_indexed=0` —
that is the design contract; operators triage by `vectors_indexed=0`,
not by leaving the row in pending.

### 5.3  A row is `ocr_failed`

Run the OCR sweep:

```bash
python backend/scripts/ocr_legal_case.py \
    --case-slug <slug> \
    --status ocr_failed
```

The sweep is idempotent (`ocrmypdf --skip-text`) and resets affected
rows to `pending` after writing the OCR'd text layer in place.

### 5.4  A row is `locked_privileged`

**Do not move it to `completed` casually.** The privilege shield is a
compliance gate. Recovery requires:

1. Pull the privilege classification record from `legal.privilege_log`
   (joined by `doc_id`). Read the model's reasoning.
2. If the classification was wrong (false positive), legal counsel signs
   off. Then update the row's status to `pending` and re-run the
   pipeline; the new classification will overwrite the prior log.
3. If the classification was correct, the row stays out of vector
   search forever. It remains queryable by case but never indexed.

### 5.5  A duplicate INSERT happened (constraint fired)

Service code handles this by deleting the just-written NFS file and
returning `{status: "duplicate"}`. If you see the constraint firing in
the logs at high frequency, check whether a producer is uploading the
same artifact twice on its own retry path — that is the bug to fix
upstream, not here.

---

## 6. Rollback

The migration's `downgrade()` drops only what it added: the FK, the
CHECK, and the three new query-pattern indexes (`status`, `created_at`,
`file_hash`). It does **not** drop:

- The table itself (fortress_prod owned it before this migration).
- The `idx_vault_documents_case_slug` index (pre-existed in fortress_prod).
- The unique constraint `uq_vault_documents_case_hash` — its underlying
  index carries the dedup invariant. Rolling that back would require an
  app-side rewrite of the ON CONFLICT clause, which is outside the
  migration's blast radius.

If you need to fully undo the dedup constraint, do it as a separate
migration that drops the constraint and (optionally) re-creates the
legacy unnamed unique index.

---

## 7. References

- Migration: `backend/alembic/versions/d8e3c1f5b9a6_vault_documents_integrity.py`
- Service: `backend/services/legal_ediscovery.py::process_vault_upload`
- OCR sweep: `backend/scripts/ocr_legal_case.py`
- Schema tests: `backend/tests/test_vault_documents_integrity.py`
- Service tests: `backend/tests/test_legal_ediscovery_vault.py`
- Vocabulary cleanup followup: Issue #194
- Audit trail (run history): `legal.ingest_runs` (PR D-pre1)
