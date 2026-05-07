# Fortress Legal Database And Supabase Classification

Status: auth/database certification snapshot on 2026-05-07.

## Classification

Fortress Legal database state is production-sensitive. Treat all database URLs, credentials, Supabase keys, service-role keys, storage keys, JWT secrets, and auth state as secrets.

## Known Database Evidence

Read-only repository evidence references:

- PostgreSQL databases: `fortress_prod`, `fortress_db`, `fortress_shadow`, `fortress_shadow_test`.
- Runtime config variables: `POSTGRES_API_URI`, `POSTGRES_ADMIN_URI`, `DATABASE_URL`, `TEST_DATABASE_URL`, `SPARK1_DATABASE_URL`.
- Qdrant config variables: `QDRANT_URL`, `QDRANT_HTTP_URL`, `QDRANT_VRS_URL`, `ENABLE_QDRANT_VRS_DUAL_WRITE`, `READ_FROM_VRS_STORE`.
- Qdrant collections: `fgp_knowledge`, `fgp_vrs_knowledge`, `legal_ediscovery`, `legal_privileged_communications`, `legal_caselaw`, `legal_caselaw_federal`.
- Production Supabase provider/project documented as `Fortress Legal Production`.
- Production Supabase ref is documented in existing reports and should be redacted in normal operational docs as `hms...liap`.

## Runtime Split

Existing docs indicate:

- `fortress_shadow` has been used as a runtime/shadow database in historical architecture docs.
- `fortress_prod` is documented as a production target that mirrors shadow schema in some operational docs.
- `fortress_db` is used by legacy legal session paths.
- `fortress_shadow_test` is the intended isolated test database.
- Some backend tests warn that missing `TEST_DATABASE_URL` can target non-test runtime DBs.
- Backend runtime SQLAlchemy uses `POSTGRES_API_URI` and requires the `fortress_api` role.
- Alembic uses `POSTGRES_ADMIN_URI` and requires the `fortress_admin` role.
- The backend config only allows local/approved backplane PostgreSQL hosts, port `5432`, and database names in the allowlist.
- Alembic migrations live under `fortress-guest-platform/backend/alembic/versions`; 123 migration files were observed in read-only discovery.

Do not infer safety from a database name alone. Confirm active config read-only before any database operation.

## Environment Classification

| Environment | Evidence | Classification |
| --- | --- | --- |
| Local | `.env.example`, loopback backend defaults, local package examples | Development only; may contain placeholder values and must not be treated as production proof. |
| Staging | `apps/command-center/.env.staging.example`, `staging-api.crog-ai.com` docs/config references | Staging intent exists; live lineage must be verified before use. |
| Production | `crog-ai.com`, `POSTGRES_API_URI`, `POSTGRES_ADMIN_URI`, `fortress_prod`, documented Supabase production project | Production-sensitive; no writes or migrations without explicit authorization. |
| Shadow/runtime | `fortress_shadow`, Alembic reconciliation docs, runtime warnings | Ambiguous historical runtime lane; production-sensitive until proven isolated. |
| Shadow/test | `fortress_shadow_test`, `TEST_DATABASE_URL`, backend `conftest.py` | Intended test isolation lane; unsafe if `TEST_DATABASE_URL` is missing. |
| Legacy | `fortress_db`, standalone scripts, historical dual-DB legal ingest docs | Legacy production-sensitive lane, not managed by the main Alembic path. |
| Vector storage | Qdrant primary/secondary variables and legal collections | Production-sensitive when carrying legal or guest retrieval data. |
| Supabase | `Fortress Legal Production` provider/project docs | Production-sensitive; project ref redacted in routine docs. |

## Query And Migration Layer

- ORM/query layer: SQLAlchemy async engine/session factory in `backend/core/database.py`.
- Runtime dependency: FastAPI `get_db()` yields async SQLAlchemy sessions.
- Migration layer: Alembic in `backend/alembic`.
- Alembic runtime URL source: `POSTGRES_ADMIN_URI`.
- Application runtime URL source: `POSTGRES_API_URI`.
- Test isolation source: `TEST_DATABASE_URL`.
- Vector layer: Qdrant HTTP APIs through backend helpers and legal ingest/upload services.

## Risk Areas

- Active environment lineage remains ambiguous between `fortress_prod`, `fortress_shadow`, legacy `fortress_db`, and test `fortress_shadow_test`.
- Missing `TEST_DATABASE_URL` can cause backend tests to write fixtures to the runtime DB.
- Some historical docs describe dual writes to `fortress_prod` and `fortress_db`; those paths are production-sensitive and must not be exercised in certification phases.
- Supabase project identity is documented, but no live Supabase read was performed in this phase.
- RLS/storage policy state was not live-verified; treat RLS and storage policy changes as forbidden without separate approval.
- Qdrant dual-write/read-cutover settings can cross enterprise boundaries if changed; no Qdrant writes or config changes are authorized.
- Root-level legacy scripts and docs may contain direct database examples; do not run them during Fortress Legal stabilization.

## Supabase Rules

Agents must not:

- run `supabase db push`,
- run `supabase migration up`,
- run `supabase db reset`,
- change RLS,
- change storage policies,
- write production rows,
- ingest real legal documents,
- print Supabase credentials or project secrets.

## Read-Only Allowed

Allowed only when explicitly required and redacted:

- inspect repo references to env var names,
- inspect docs for project classification,
- inspect migration filenames,
- run tests that do not mutate production.

## Future Agent Rule

Any discovery of a new Supabase project, database role, schema lane, storage bucket, Qdrant collection, or legal ingest path must update this file.
