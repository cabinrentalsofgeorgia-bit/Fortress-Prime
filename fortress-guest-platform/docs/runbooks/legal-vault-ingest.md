# Runbook: `vault_ingest_legal_case`

Operator playbook for the case-scoped vault ingestion script
(`backend/scripts/vault_ingest_legal_case.py`). Read this before running
against a new case, before triaging an interrupted run, and before
attempting a rollback.

Last updated: PR D (2026-04-25). Owner: Legal Platform.

---

## 1. What it is

A single command that ingests every file referenced by
`legal.cases.nas_layout` for a given case into the canonical legal
pipeline, populating both PostgreSQL state (`legal.vault_documents` in
`fortress_prod` and `fortress_db`) and the Qdrant `legal_ediscovery`
collection so Council can retrieve case-tagged chunks.

The script is the operational front-end for `process_vault_upload()`
(in `backend/services/legal_ediscovery.py`). It wraps that function
with:

- physical-path dedup (the same file referenced by two logical subdirs
  is processed once, not twice),
- bounded concurrency (`--jobs N`),
- a JSON manifest at `/mnt/fortress_nas/audits/`,
- a `legal.ingest_runs` audit row (PR D-pre1 IngestRunTracker),
- a lock file at `/tmp/vault-ingest-{slug}.lock`,
- a fully-formed `--rollback` path that nukes all of a case's
  vault_documents rows and Qdrant points with explicit confirmation.

It does **not** OCR. Run `ocr_legal_case.py` (PR C) first if any PDFs
in the case are image-only.

---

## 2. When to run

- **Onboarding a new case** — after PR A inserts the row into
  `legal.cases` (with `nas_layout` populated) and PR C has OCR'd any
  image-only PDFs, run this script to populate the Vault panel.
- **Adding new evidence to an existing case** — drop files into the
  configured subdirs and re-run. Resume mode (default on) skips files
  that already have a terminal `processing_status`, so the cost is
  bounded by the *new* file count.
- **Recovering a partial run** — if a previous run was killed, simply
  re-run. Files in `pending` / `vectorizing` / `processing` are
  re-processed; files in `complete`/`completed`/`ocr_failed`/
  `locked_privileged` are skipped.

Do not run this against a case whose nas_layout subdirs are not yet
mounted (NAS down) — the pre-flight gate will reject it.

---

## 3. Pre-flight gates (all must pass before any work)

The script refuses to open an `ingest_runs` audit row until every
gate passes — failed pre-flights do not pollute the audit table.

| # | Gate | Failure mode |
| --- | --- | --- |
| 1 | `legal.cases` row exists in **both** `fortress_prod` and `fortress_db` | run PR B first |
| 2 | `nas_layout` is populated (non-NULL) for non-canonical cases | populate `legal.cases.nas_layout` JSONB |
| 3 | `nas_layout.root` and every configured `subdirs.*` path exists on disk | mount the NAS / fix the layout JSON |
| 4 | PostgreSQL is writable in both DBs (SELECT 1 + scratch INSERT into `legal.ingest_runs`) | check `POSTGRES_ADMIN_URI` and DB up |
| 5 | PR D-pre2 constraints present in both DBs (`fk_*`, `uq_*`, `chk_*`) | apply alembic `d8e3c1f5b9a6` |
| 6 | Qdrant `legal_ediscovery` collection reachable, vector size 768 | spin up Qdrant or fix `QDRANT_URL` |
| 7 | `process_vault_upload` importable | resolve the import error before retry |
| 8 | Lock file at `/tmp/vault-ingest-{slug}.lock` not held by another live run | wait for the other run, or `--force` after confirming staleness |

Pre-flight exit code is **3**. Look for `PREFLIGHT FAILED:` on stderr.

---

## 4. How dedup works

Three layers, in order:

1. **Physical-path dedup (script-level).** `walk_unique_physical_files`
   tracks `Path.resolve()` results in a set; a file referenced by two
   logical subdirs (e.g. 7IL's `correspondence` and `certified_mail`
   both pointing at "Correspondence") is yielded exactly once.

2. **Hash dedup with terminal-status skip (resume mode).** Before
   reading the file bytes, the script computes SHA-256 and checks
   `legal.vault_documents` for an existing row matching `(case_slug,
   file_hash)`. If the row's `processing_status` is in the resume
   skip-set (default: `complete,completed,ocr_failed,
   locked_privileged`), the file is logged and skipped.

3. **Constraint dedup (race-safe, DB-level).** Inside
   `process_vault_upload()`, the INSERT uses `ON CONFLICT ON CONSTRAINT
   uq_vault_documents_case_hash DO NOTHING RETURNING id`. If two
   workers race to ingest the same file, exactly one row lands; the
   loser deletes the file it just wrote to NFS and returns
   `{status: "duplicate"}`.

Same hash across **different cases** is allowed by design — each case
gets its own row, its own NFS copy, its own privilege classification.
Discovery in case A does not leak into case B's audit trail.

---

## 5. Status state machine (link)

See `docs/runbooks/legal-vault-documents.md` §2 for the full state
machine and the bilingual vocabulary explanation. The script emits
the following statuses to the manifest's `by_status` map:

- `completed` — happy path, vectors live in Qdrant
- `ocr_failed` — text extraction returned empty bytes on a PDF;
  re-run `ocr_legal_case.py` to fix
- `locked_privileged` — privilege shield triggered; legal review
  before any further action
- `failed` — pipeline blew up; check `manifest.errors` for
  diagnosis
- `skipped` — already done (resume), or above max-file-size, or
  dry-run

`vault_documents_inserted` counts only the first three terminal states
(rows that the UI will actually render).

---

## 6. Reading the manifest

Every successful run writes
`/mnt/fortress_nas/audits/vault-ingest-{case_slug}-{ts}.json`:

```json
{
  "case_slug":            "...",
  "started_at":           "...",
  "finished_at":          "...",
  "runtime_seconds":      ...,
  "args":                 {...},
  "host":                 "...",
  "pid":                  ...,
  "ingest_run_id":        "uuid",
  "layout_root":          "...",
  "layout_recursive":     true,
  "layout_subdirs":       {...},
  "total_unique_files":   N,
  "processed":            N,
  "skipped":              N,
  "errored":              N,
  "by_status":            {"completed": N, "ocr_failed": N, ...},
  "by_logical_subdir":    {"evidence": N, ...},
  "by_mime_type":         {"application/pdf": N, ...},
  "errors":               [{...}],
  "qdrant_points_estimate": N,
  "vault_documents_inserted": N
}
```

Quick triage by manifest:

- **`errored == 0` and `vault_documents_inserted == total_unique_files
  - skipped`** → clean run.
- **`by_status.ocr_failed > 0`** → run `ocr_legal_case.py` for the
  case, then re-run vault ingest.
- **`qdrant_points_estimate == 0` despite `completed > 0`** → Qdrant
  was unreachable or returned 0 indexed; check Qdrant health and
  re-run for rows with `vectors_indexed=0`.
- **`errored > 0`** → see `manifest.errors[]` — each entry has the
  exact path, logical subdir, and error string.

The `ingest_run_id` cross-references `legal.ingest_runs` for
durable audit.

---

## 7. Recovery

### 7.1  Ctrl-C / SIGTERM during a run

The IngestRunTracker exits with `status='interrupted'`. Files that
were in flight may have left rows in `pending` / `vectorizing` /
`processing` — these are the resume targets. Just re-run the same
command; resume mode picks up where it left off.

### 7.2  OOM / network blip

Same path. Re-run; resume skips terminal rows.

### 7.3  Lock file left behind by a crashed run

The lock contains the PID and an ISO timestamp. After confirming via
`ps` that the PID is no longer alive, either:

- delete the lock file manually and re-run, or
- pass `--force` if the lock is older than 6 h.

The script refuses `--force` on a fresh lock as a safety net.

### 7.4  A subset of files keep erroring

Inspect `manifest.errors` for the path and error class. The most
common patterns:

- **`mirror_failed:psycopg2.*`** — fortress_db unreachable when
  mirroring after fortress_prod write succeeded; the row is in
  fortress_prod but not yet in fortress_db. Re-run; the mirror is
  idempotent (`ON CONFLICT DO UPDATE`).
- **`stat_failed:` / `read_failed:`** — NAS hiccup on that specific
  file. Re-run.
- **PDF parser stack traces from `process_vault_upload`** — the file
  is malformed. Move it out of the case tree, file an issue, and
  re-run.

---

## 8. Rollback

`--rollback` deletes:

- every `legal.vault_documents` row for the case in **both**
  fortress_prod and fortress_db,
- every Qdrant point in `legal_ediscovery` whose payload `case_slug`
  matches.

It does **not** touch:

- NAS files,
- `legal.cases` row,
- `legal.privilege_log` entries (audit trail must outlive the data),
- `fortress_knowledge` collection (Sentinel-owned).

```
python -m backend.scripts.vault_ingest_legal_case \
    --case-slug 7il-v-knight-ndga --rollback
```

You will be prompted to type the case_slug back as confirmation.
Pass `--force` to skip the prompt — only do this from automation
where the case_slug is already strongly bound. Rollback writes a
separate manifest at `/mnt/fortress_nas/audits/vault-rollback-
{case_slug}-{ts}.json` and emits its own `legal.ingest_runs` row
with `args.rollback=true` for audit.

If post-rollback counts are non-zero (concurrent writer beat us),
the script exits 1 with a `WARNING:` log line — investigate before
retrying.

---

## 9. Common errors and fixes

| Error | Fix |
| --- | --- |
| `case_slug 'X' not found in fortress_prod.legal.cases` | run PR B's case-insertion path for X |
| `nas_layout is NULL for X in fortress_prod` | populate the JSONB `nas_layout` column for the case |
| `nas_layout subdirs missing from disk` | mount the NAS or fix the relative paths in the layout |
| `qdrant collection 'legal_ediscovery' not found` | create with `vector_size=768 distance=Cosine` |
| `missing PR D-pre2 constraints` | apply alembic `d8e3c1f5b9a6` against that DB |
| `another vault ingest run appears active` | locate the live run via the PID in the lock file; wait for it or pass `--force` after confirming staleness |
| Long tail of `mirror_failed:` errors | fortress_db is down or migrating — run when it stabilizes |

---

## 10. Adding a new case to ingestion

1. Insert the row into `legal.cases` (PR B-style migration). Populate
   `nas_layout` JSONB matching the on-disk layout, e.g.:
   ```json
   {
     "root": "/mnt/fortress_nas/path/to/case",
     "subdirs": {
       "filings_incoming": "Pleadings",
       "evidence":         "Discovery",
       "correspondence":   "Mail"
     },
     "recursive": true
   }
   ```
2. Run `ocr_legal_case.py --case-slug <slug>` to add text layers to
   any image-only PDFs.
3. Run `vault_ingest_legal_case.py --case-slug <slug>` to populate
   `legal.vault_documents` and Qdrant.
4. Verify in the UI's Vault panel that the case renders.

---

## 11. Performance tuning

- `--jobs N` — bounded concurrency for per-file processing. Default
  4. Bottleneck is usually the embedding endpoint (nomic via
  Ollama); push to 6–8 only when the embed service is on a
  dedicated host. Past ~8, expect Qdrant upsert contention.
- `--max-file-size-mb N` — skip files above this cap. Default 500.
  Large PDFs (1 GB+ deposition transcripts) blow up text extraction
  and chunking; process them out-of-band with a tighter pipeline.
- `--limit N` — cap on unique physical files. Useful for smoke tests
  and incremental rollouts.
- File hashing streams above 100 MB; below that it loads into memory
  for speed.

For the 7IL corpus (~552 PDFs after dedup), expect 30–60 minutes wall
time at `--jobs 6` on a typical embed host.

---

## 12. Cross-references

- **PR A** — `legal.cases.nas_layout` JSONB column (`backend/api/legal_cases.py`)
- **PR B** — case-row insertion pattern (see PR #186 history)
- **PR C** — OCR sweep (`backend/scripts/ocr_legal_case.py`)
- **PR D-pre1** — `legal.ingest_runs` + `IngestRunTracker`
  (`backend/services/ingest_run_tracker.py`)
- **PR D-pre2** — `legal.vault_documents` schema integrity
  (`docs/runbooks/legal-vault-documents.md`)
- **Issue #189** — Whisper ASR for video evidence (out of scope here)
- **Issue #194** — vocabulary cleanup followup
