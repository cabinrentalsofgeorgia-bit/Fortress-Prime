# CI Schema Bootstrap

## Why

Fortress Prime's Alembic migration graph was designed for **incremental deployment** to live servers where core tables (`properties`, `reservations`, `guests`, etc.) already existed. The graph has ~30 parallel branch roots with `down_revision = None`, all written on servers where those tables were pre-existing.

On a fresh CI database, Alembic's topological sort runs these branches before the main chain creates the core tables, causing cascading `UndefinedTableError` failures. Fixing the migration graph would require restructuring dozens of migration files — scope disproportionate to the CI goal.

**Solution:** Bootstrap CI from a `pg_dump --schema-only` snapshot of the live production schema. This is fast, reliable, and always correct.

## Files

```
fortress-guest-platform/ci/
├── schema.sql                  — pg_dump output, CI-adapted (committed to repo)
├── schema.meta.json            — alembic heads, tree hash, timestamp
├── check_schema_staleness.py   — CI gate: verifies snapshot matches live migrations
scripts/
└── ci-schema-dump.sh           — generates both files above
Makefile                        — make ci-schema-dump target
```

## Workflow (what CI does)

```
Provision DB roles (fortress_admin, fortress_api)
    ↓
Check schema snapshot is current (check_schema_staleness.py exits 0)
    ↓
Load CI schema from snapshot (psql < ci/schema.sql)
    ↓
Start FastAPI backend (connects to freshly bootstrapped DB)
    ↓
Seed deterministic CI admin
    ↓
Run Playwright E2E tests
```

## Staleness detection

`check_schema_staleness.py` compares the git tree hash of
`fortress-guest-platform/backend/alembic/versions/` stored in `schema.meta.json`
against the current `HEAD` tree hash. If any migration file was added or modified
since the last dump, CI fails with:

```
::error::Schema snapshot is stale.
  Stored tree:  9aaa17e5ccba
  Current tree: <new hash>
  Migration files have changed since the last 'make ci-schema-dump'.
  Fix: run 'make ci-schema-dump' and commit fortress-guest-platform/ci/
```

## Refreshing the snapshot

Run this whenever you add or modify a migration:

```bash
make ci-schema-dump
git add fortress-guest-platform/ci/schema.sql fortress-guest-platform/ci/schema.meta.json
git commit -m "chore: refresh CI schema snapshot (add <migration name>)"
```

The script connects to `fortress_shadow` (local default) or a configurable DB:

```bash
make ci-schema-dump DB=fortress_shadow_test
```

## CI adaptations

The schema dump is modified for CI compatibility:

| Issue | Adaptation |
|-------|-----------|
| `postgis` extension not in `postgres:16` container | `CREATE EXTENSION postgis` removed |
| `vector` extension not in `postgres:16` container | `CREATE EXTENSION vector` removed |
| `geometry` column type (parcels.geom) requires postgis | Replaced with `text` |
| `vector(768)` column type requires pgvector | Replaced with `text` |

The affected tables (`parcels`, `property_knowledge_chunks`) are not exercised by the Playwright E2E tests. On production these tables already have the correct types.

## Production migrations

**This approach does NOT change how migrations run on production.** Alembic migrations continue to be applied normally to `fortress_shadow` via `alembic upgrade heads`. The CI schema snapshot is only used by the CI test pipeline.

When new migrations are applied to production, the snapshot becomes stale and CI will fail on the staleness check until `make ci-schema-dump` is run and committed.
