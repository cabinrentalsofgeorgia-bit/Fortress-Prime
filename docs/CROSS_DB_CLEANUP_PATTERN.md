# Cross-Database Cleanup Pattern

**Context:** Discovered during P4 of the 2026-04-21 continuation brief while
attempting to drop `reservations_draft_queue` via Alembic.

---

## Database topology

Fortress Prime runs three PostgreSQL databases on the same cluster (127.0.0.1:5432):

| Database | Role user | Managed by | Purpose |
|---|---|---|---|
| `fortress_shadow` | fortress_api / fortress_admin | **Alembic** | Backend runtime (FastAPI, all ORM models, migrations) |
| `fortress_prod` | fortress_api / fortress_admin | Alembic (nominal target per `alembic.ini`) | Production target — mirrors shadow schema |
| `fortress_db` | miner_bot | **Not Alembic** | Legacy standalone scripts (watchers, mining jobs, pre-pipeline data) |

`fortress_shadow` is the Alembic-managed database. All `backend/` models and
migration files in `backend/alembic/versions/` apply to `fortress_shadow`
(and nominally to `fortress_prod`).

`fortress_db` is a legacy database created before the FastAPI backend existed.
It is accessed only by standalone Python scripts in `src/` (e.g., the
reservations IMAP watcher) using the `miner_bot` role. Alembic has no
knowledge of this database.

---

## Why Alembic can't drop fortress_db tables

`alembic upgrade head` connects as `fortress_admin` to `fortress_shadow`.
It cannot reach `fortress_db` at all. Attempting to write an Alembic migration
that references `fortress_db` tables would silently succeed (Alembic would
record the migration as applied) but never actually drop anything.

For tables in `fortress_db`, use standalone SQL scripts (see below).

---

## Standalone SQL cleanup pattern

For one-way destructive operations in `fortress_db` (or any database outside
Alembic's scope):

1. Write a `.sql` file in `scripts/` with:
   - Guards that abort if the table is already gone or still active
   - Diagnostic NOTICE showing row count before the drop
   - The destructive operation wrapped in `BEGIN/COMMIT`
   - Clear operator instructions at the top

2. Commit the script to main via PR so it is reviewed before execution.

3. **Gary runs it manually** against the target database after the PR merges:
   ```bash
   psql -h 127.0.0.1 -U miner_bot -d fortress_db \
     -f scripts/drop_deprecated_reservations_draft_queue.sql
   ```

4. One-time scripts can be left in `scripts/` as an audit trail, or removed
   in a follow-up commit once confirmed executed.

---

## This instance: reservations_draft_queue

`reservations_draft_queue` was the original sink for the reservations@ IMAP
watcher (PR #101). It was deprecated when the email pipeline replaced it
(PR #104). The write path was nullified in `src/ingest_reservations_imap.py`
and the deprecation comment was added in PR #110.

As of 2026-04-21: 2 rows, last write 2026-04-20 18:14 UTC (>48h prior to
the cleanup script being written). Table is confirmed dead.

Drop script: `scripts/drop_deprecated_reservations_draft_queue.sql`
