# Shared: Postgres Schemas

Last updated: 2026-04-26

## Technical overview

Four databases on `127.0.0.1:5432`. They serve different roles and are accessed via different SQLAlchemy session factories. Cross-DB sync happens via explicit dual-DB write patterns (e.g. PR D's `fortress_db` → `fortress_prod` mirror for legal vault rows), never via foreign keys.

| DB | Role | Session factory | Alembic chain head |
|---|---|---|---|
| `fortress_prod` | Canonical (mirror target for legal data); `legal.cases` source-of-truth for some workflows | n/a (admin-only writes from scripts) | `d4e5f6a7b8c9` (per session-summary historical reference) |
| `fortress_db` | Operational target for legal services (UI's LegacySession source) | `LegacySession` (`backend/services/ediscovery_agent.py`) | `7a1b2c3d4e5f` (orphaned per Issue #204) |
| `fortress_shadow` | Runtime VRS / booking DB; `AsyncSessionLocal` target | `AsyncSessionLocal` (`backend/core/database.py`) | `m8f9a1b2c3d4` |
| `fortress_shadow_test` | CI test DB; bootstrapped from shadow snapshot via `setup_test_db.sh` | env var `TEST_DATABASE_URL` | (mirrors fortress_shadow + manual legal patches per Issue #220) |

## Key schemas + tables

### `legal.*` (operationally in `fortress_db`; mirrored to `fortress_prod`)

| Table | Purpose | Notes |
|---|---|---|
| `legal.cases` | Case metadata | + `nas_layout`, `case_phase`, `privileged_counsel_domains`, `related_matters` (PR G phase B) |
| `legal.vault_documents` | Every ingested file | FK + UNIQUE + CHECK from PR D-pre2 (#193); 9-status union vocabulary tracked for cleanup as #194 |
| `legal.case_slug_aliases` | Backward-compat after slug renames | PR G phase C; one row today (`7il-v-knight-ndga` → `-i`) |
| `legal.privilege_log` | Audit trail of privilege classifications | Append-only; do not modify per [`legal-privilege-architecture.md`](../../runbooks/legal-privilege-architecture.md) §8 |
| `legal.ingest_runs` | Audit trail of script invocations | PR D-pre1 (#190); FK to `legal.cases.case_slug` ON DELETE CASCADE — see Issue #209 |
| `legal.correspondence`, `legal.deadlines`, `legal.filings`, `legal.case_actions`, `legal.case_evidence`, `legal.case_watchdog`, `legal.case_precedents` | Supporting tables | Mix of legacy + active |

Full runbook: [`../../runbooks/legal-vault-documents.md`](../../runbooks/legal-vault-documents.md)

### `public.*` (split across DBs)

| Table | DB | Purpose |
|---|---|---|
| `public.email_archive` | `fortress_db` (canonical, ~42k rows) + `fortress_prod` (mirror, ~42k rows) | Archived email correspondence; ingested_from is NULL for all rows historically |
| `public.trust_transactions`, `public.trust_ledger_entries` | `fortress_prod` (canonical) | Append-only sovereign ledger; immutable triggers raise on UPDATE/DELETE |
| `public.properties`, `public.bookings`, `public.reservations`, `public.guests` | `fortress_shadow` | CROG-VRS runtime |
| `public.streamline_*`, `public.channex_*` | `fortress_shadow` | PMS + channel-manager mirrors |
| `public.llm_training_captures` | `fortress_shadow` | Captain executive captures (~5,500 rows since 2026-04-24); training corpus |
| `public.restricted_captures` | `fortress_shadow` | Privilege-restricted prompts/responses |
| `public.email_messages` | `fortress_shadow` | Guest inquiry workflow (~38 rows) |

### `division_a.*`, `division_b.*`, `engineering.*`, `hedge_fund.*`

Per `fortress_atlas.yaml` — division-scoped schemas. Existence depends on alembic chain state per DB. Verify via `\dn` before assuming presence.

## Consumers

- Every backend service module
- Every ARQ worker
- Migrations: `backend/alembic/versions/*.py`
- Schema audit at startup: `backend/core/schema_audit.py` (validates a subset of tables on every backend boot)

## Contract / API surface

- **Sovereign ledger immutability:** `trust_transactions` / `trust_ledger_entries` are append-only via DB triggers. Always post via `backend/services/trust_ledger.py`. See `master-accounting` division doc.
- **Cross-DB writes:** dual-DB pattern (PR D / PR G) — write canonical to one DB, mirror to the other via psycopg2 with admin DSN. No FK across DBs.
- **Schema staleness check:** CI checks `git tree hash of backend/alembic/versions/` against `fortress-guest-platform/ci/schema.meta.json`. Stale snapshot blocks merge until regenerated via `make ci-schema-dump`.

## Where to read the code

- `backend/alembic/versions/*.py` — every migration in chronological order
- `backend/core/config.py` — `database_url`, `legacy_database_url` resolution
- `backend/core/database.py` — `AsyncSessionLocal`, engine, schema audit
- `backend/services/ediscovery_agent.py:51` — `_legacy_engine` + `LegacySession` (fortress_db target)
- `fortress-guest-platform/ci/schema.sql` — current snapshot
- `fortress-guest-platform/ci/schema.meta.json` — staleness fingerprint
- `scripts/ci-schema-dump.sh` — regeneration script

## Cross-references

- Issue #204 — fortress_db alembic_version `7a1b2c3d4e5f` orphaned (chain divergence)
- Issue #220 — fortress_shadow_test schema sync gap
- Issue #221 — alembic-on-test-DB CI gate (proposed)
- [`legal-vault-documents.md`](../../runbooks/legal-vault-documents.md) — vault_documents schema deep-dive

Last updated: 2026-04-26
