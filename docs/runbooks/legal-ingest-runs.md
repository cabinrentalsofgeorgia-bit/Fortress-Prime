# `legal.ingest_runs` runbook

Audit trail for case-scoped ingest operations (OCR sweeps, vault
ingestion, ASR runs, re-ingest passes). One row per script
invocation.

## Schema

```
id              UUID PK              gen_random_uuid()
case_slug       TEXT NOT NULL        FK → legal.cases.case_slug ON DELETE CASCADE
script_name     TEXT NOT NULL        e.g. "ocr_legal_case", "vault_ingest", "asr_legal_case"
started_at      TIMESTAMPTZ          set by IngestRunTracker.__enter__
ended_at        TIMESTAMPTZ          set by IngestRunTracker.__exit__
args            JSONB                argparse Namespace dump
status          TEXT                 'running' | 'complete' | 'error' | 'interrupted'   (CHECK)
manifest_path   TEXT                 NAS path to per-run JSON manifest
total_files     INTEGER              set by run.set_total_files(N)
processed       INTEGER              cumulative running total
errored         INTEGER              cumulative running total
skipped         INTEGER              cumulative running total
error_summary   TEXT                 last 12 traceback lines on exception, or short note
host            TEXT                 socket.gethostname() at run start
pid             INTEGER              os.getpid() at run start
runtime_seconds NUMERIC(12,3)        ended_at - started_at, populated on exit
created_at      TIMESTAMPTZ          immutable
updated_at      TIMESTAMPTZ          touched on every update
```

## Status state machine

```
        ┌────────┐
        │running │ ← INSERT at __enter__
        └────┬───┘
             │
   clean exit│KeyboardInterrupt│other Exception
             │                 │                │
             ▼                 ▼                ▼
        complete          interrupted          error
                                                │
                                                └─ error_summary populated
```

`KeyboardInterrupt` and other exceptions are **re-raised** by `__exit__`;
the row write happens before the re-raise so the audit trail is
durable even when the operator Ctrl-C's a long sweep.

## DB-disconnect degradation

If three retries (≤ 30 s total) fail to write the start INSERT or any
update, the tracker:

- Sets `self.degraded = True`.
- Logs `[ingest_run_tracker] DEGRADED for {slug}/{script} pid={pid}: {reason}` to stderr.
- Emits a structured logger record at `ERROR` level
  (`ingest_run_tracker_degraded` event), greppable in journalctl.
- **Continues without raising** — the parent ingest job runs to
  completion. Subsequent counter calls are silent no-ops.

A degraded run leaves either zero rows (if the start INSERT failed)
or a stuck `running` row (if the start INSERT succeeded but updates
later failed). Use the queries below to find them.

## Operator queries

### last 10 runs across all cases
```sql
SELECT id, case_slug, script_name, status,
       to_char(started_at, 'YYYY-MM-DD HH24:MI') AS started,
       runtime_seconds AS rt, processed, errored
FROM legal.ingest_runs
ORDER BY started_at DESC
LIMIT 10;
```

### errored runs in last 7 days with summaries
```sql
SELECT id, case_slug, script_name,
       to_char(started_at, 'YYYY-MM-DD HH24:MI') AS started,
       errored, runtime_seconds,
       LEFT(error_summary, 200) AS summary
FROM legal.ingest_runs
WHERE status = 'error'
  AND started_at > NOW() - INTERVAL '7 days'
ORDER BY started_at DESC;
```

### still-running ops > 6 h old (likely orphaned)
```sql
SELECT id, case_slug, script_name, host, pid,
       to_char(started_at, 'YYYY-MM-DD HH24:MI') AS started,
       NOW() - started_at AS age
FROM legal.ingest_runs
WHERE status = 'running'
  AND started_at < NOW() - INTERVAL '6 hours'
ORDER BY started_at;
```

### runtime histogram by script_name
```sql
SELECT script_name,
       count(*)                          AS runs,
       round(avg(runtime_seconds), 1)    AS avg_s,
       round(max(runtime_seconds), 1)    AS max_s,
       sum(processed)                    AS total_processed,
       sum(errored)                      AS total_errored
FROM legal.ingest_runs
WHERE status = 'complete'
GROUP BY script_name
ORDER BY runs DESC;
```

### errors by case_slug
```sql
SELECT case_slug, script_name, count(*) AS error_count,
       max(started_at) AS last_error_at
FROM legal.ingest_runs
WHERE status = 'error'
GROUP BY case_slug, script_name
ORDER BY error_count DESC;
```

### detail for a specific run
```sql
SELECT * FROM legal.ingest_runs WHERE id = '<uuid>';
```

### find the last successful sweep per case (for next-run dedup)
```sql
SELECT DISTINCT ON (case_slug, script_name)
       case_slug, script_name, id,
       started_at, manifest_path, runtime_seconds
FROM legal.ingest_runs
WHERE status = 'complete'
ORDER BY case_slug, script_name, started_at DESC;
```

### count ingestions per case in last 30 days
```sql
SELECT case_slug, count(*) AS runs_30d,
       sum(processed) AS files_30d,
       count(*) FILTER (WHERE status = 'error') AS errors_30d
FROM legal.ingest_runs
WHERE started_at > NOW() - INTERVAL '30 days'
GROUP BY case_slug
ORDER BY runs_30d DESC;
```

### compare consecutive sweeps for the same case+script
```sql
SELECT id,
       to_char(started_at, 'YYYY-MM-DD HH24:MI') AS started,
       processed, errored, runtime_seconds,
       processed - LAG(processed) OVER w AS delta_processed
FROM legal.ingest_runs
WHERE case_slug = '<slug>' AND script_name = '<name>'
WINDOW w AS (ORDER BY started_at)
ORDER BY started_at;
```

### orphaned (degraded-tracker) runs from a specific host
```sql
SELECT id, case_slug, script_name, pid,
       to_char(started_at, 'YYYY-MM-DD HH24:MI') AS started,
       updated_at - started_at AS write_silence
FROM legal.ingest_runs
WHERE status = 'running'
  AND host = 'spark-node-2'
  AND updated_at < NOW() - INTERVAL '1 hour'
ORDER BY started_at;
```

## Cleanup: stuck `running` rows older than 24 h

These represent either (a) a tracker that degraded after the start
INSERT, or (b) a script killed without graceful exit.

```sql
-- review first
SELECT id, case_slug, script_name, host, pid,
       to_char(started_at, 'YYYY-MM-DD HH24:MI') AS started
FROM legal.ingest_runs
WHERE status = 'running'
  AND started_at < NOW() - INTERVAL '24 hours';

-- then update — mark them interrupted with a note
UPDATE legal.ingest_runs
   SET status        = 'interrupted',
       ended_at      = updated_at,
       error_summary = 'Auto-cleanup: stuck running >24h, likely orphaned tracker',
       updated_at    = NOW()
 WHERE status = 'running'
   AND started_at < NOW() - INTERVAL '24 hours';
```

Verify the script is actually no longer running before cleanup:

```bash
ps aux | grep -E "<script_name>.*<case_slug>" | grep -v grep
```

If the process is alive, **do not** clean up — let it finish or kill
it gracefully (`SIGTERM` → tracker writes `interrupted`).

## Interaction with PR D rollback

PR D (vault ingestion) will:
- Open an `IngestRunTracker` per `process_vault_upload` invocation.
- Insert a row into `legal.vault_documents` per file.
- Roll back via deleting `legal.vault_documents` rows for the run's
  `started_at` window.

The `ingest_runs` row itself is **not** rolled back — it remains as a
record that the operation happened (and was rolled back). When PR D's
rollback tooling lands, it should set `status = 'error'` and append a
note to `error_summary` rather than deleting the run row.

`ON DELETE CASCADE` from `legal.cases.case_slug`: deleting a case
deletes its run history. If you ever delete a real case, archive
its `ingest_runs` first:

```sql
SELECT * FROM legal.ingest_runs
 WHERE case_slug = '<slug>'
\copy (SELECT * FROM legal.ingest_runs WHERE case_slug = '<slug>')
       TO '/mnt/fortress_nas/audits/archive-ingest-runs-<slug>-<ts>.csv' CSV HEADER;
```

## Detecting orphaned rows in CI

Add a periodic job (e.g. cron at 03:00 daily):

```sql
SELECT count(*) AS orphan_count
FROM legal.ingest_runs
WHERE status = 'running'
  AND started_at < NOW() - INTERVAL '6 hours';
```

If `> 0`, page operators. The accompanying journalctl line
`ingest_run_tracker_degraded` will show which host emitted the
orphan.
