# Fortress Legal Database And Supabase Classification

Status: read-only discovery snapshot on 2026-05-07.

## Classification

Fortress Legal database state is production-sensitive. Treat all database URLs, credentials, Supabase keys, service-role keys, storage keys, JWT secrets, and auth state as secrets.

## Known Database Evidence

Read-only repository evidence references:

- PostgreSQL databases: `fortress_prod`, `fortress_db`, `fortress_shadow`, `fortress_shadow_test`.
- Runtime config variables: `POSTGRES_API_URI`, `POSTGRES_ADMIN_URI`, `DATABASE_URL`, `TEST_DATABASE_URL`.
- Qdrant collections: `legal_ediscovery`, `legal_privileged_communications`, `legal_caselaw`, `legal_caselaw_federal`.
- Production Supabase provider/project documented as `Fortress Legal Production`.
- Production Supabase ref is documented in existing reports and should be redacted in normal operational docs as `hms...liap`.

## Runtime Split

Existing docs indicate:

- `fortress_shadow` has been used as a runtime/shadow database in historical architecture docs.
- `fortress_db` is used by legacy legal session paths.
- `fortress_shadow_test` is the intended isolated test database.
- Some backend tests warn that missing `TEST_DATABASE_URL` can target non-test runtime DBs.

Do not infer safety from a database name alone. Confirm active config read-only before any database operation.

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
