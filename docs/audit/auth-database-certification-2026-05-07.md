# Auth And Database Certification - 2026-05-07

Enterprise: Fortress Legal.
Worktree: `/home/admin/Fortress-Prime-legal-next`.
Branch: `feature/fortress-legal-next`.
Mode: read-only auth/database certification with docs-only updates.

## Objective

Certify Fortress Legal auth and database boundaries from source, docs, and example config names only. No auth mutation, DB mutation, Supabase mutation, `.auth` access, deploy, migration, runtime mutation, Cloudflare/DNS mutation, or cross-enterprise mutation was authorized or performed.

## Auth Boundary Finding

Command-center uses a Next.js BFF auth boundary:

- Staff session cookie: `fortress_session`.
- Owner-scoped cookie: `fgp_owner_token`.
- Browser bearer-token cache: `fgp_token`.
- Browser user cache: `fgp_user`.
- Staff auth paths: `/api/auth/login`, `/api/auth/sso`, `/api/auth/me`, `/api/auth/logout`.
- Generic BFF path: `/api/[...path]`.
- Backend staff auth: FastAPI `/api/auth/*`.

The BFF bridges browser auth to upstreams:

- `fortress_session` can be bridged into `Authorization: Bearer`.
- Bearer tokens can be bridged into `fortress_session` for Command Center upstreams.
- Raw cookies are forwarded only through server-side proxy paths.
- Internal FGP requests can use ingress signature headers when configured.

Backend staff auth uses:

- RS256 JWTs with configured `kid`.
- bcrypt password hashing.
- sovereign Postgres `staff_users` table.
- role dependencies and route-specific `RoleChecker` guards.

Observed roles:

- `super_admin`
- `admin`
- `manager`
- `reviewer`
- `operator`
- `staff`
- `maintenance`

Frontend legal mutation controls are manager/admin/super-admin gated through `canManageLegalOps`, but frontend gates are only UI hardening. Backend route authorization remains the authoritative boundary.

## Database Boundary Finding

Backend runtime database access uses SQLAlchemy async sessions and `POSTGRES_API_URI` with the `fortress_api` role. Alembic uses `POSTGRES_ADMIN_URI` with the `fortress_admin` role.

Observed database names:

- `fortress_prod`
- `fortress_shadow`
- `fortress_shadow_test`
- `fortress_db`

Observed migration layer:

- `fortress-guest-platform/backend/alembic`
- `fortress-guest-platform/backend/alembic/versions`
- 123 Alembic migration files observed.

Observed vector/storage references:

- `QDRANT_URL`
- `QDRANT_HTTP_URL`
- `QDRANT_VRS_URL`
- `ENABLE_QDRANT_VRS_DUAL_WRITE`
- `READ_FROM_VRS_STORE`
- `fgp_knowledge`
- `fgp_vrs_knowledge`
- `legal_ediscovery`
- `legal_privileged_communications`
- `legal_caselaw`
- `legal_caselaw_federal`

Supabase classification remains production-sensitive. Existing docs identify a Fortress Legal production Supabase project, but this phase performed no live Supabase access.

## Environment Classification

| Environment | Classification |
| --- | --- |
| Local | Development examples and loopback defaults only. |
| Staging | Staging intent exists through example config names and `staging-api.crog-ai.com`; live lineage not certified here. |
| Production | `crog-ai.com`, `fortress_prod`, production Supabase docs, and production runtime references are production-sensitive. |
| Shadow/runtime | `fortress_shadow` is historically used as runtime/shadow and must be treated as production-sensitive. |
| Shadow/test | `fortress_shadow_test` is intended test isolation through `TEST_DATABASE_URL`. |
| Legacy | `fortress_db` is legacy production-sensitive and not the main Alembic runtime target. |
| Vector | Qdrant collections and dual-write settings are production-sensitive. |
| Unknown | Any env var or database reference not classified above must be treated as production-sensitive until proven otherwise. |

## Risk Areas

- Active DB lineage is historically ambiguous across `fortress_prod`, `fortress_shadow`, `fortress_db`, and `fortress_shadow_test`.
- Backend tests can fall back to runtime DB if `TEST_DATABASE_URL` is missing.
- RLS/storage policy state was not live-verified.
- Supabase project classification is docs-based only in this phase.
- BFF auth logs include token-prefix style diagnostics in some proxy paths; future hardening should prefer boolean auth-present logs.
- Multiple auth bridges exist: HttpOnly cookie, localStorage bearer cache, owner cookie, gateway SSO, and internal ingress token.
- Legal ingest docs mention dual writes and Qdrant upserts; those remain forbidden without explicit production mutation authorization.
- Cross-enterprise Qdrant/VRS settings must not be changed during Fortress Legal stabilization.

## Files Inspected

- `docs/auth/auth-boundaries.md`
- `docs/database/supabase-classification.md`
- `fortress-guest-platform/apps/command-center/src/app/api/auth/*`
- `fortress-guest-platform/apps/command-center/src/app/api/[...path]/route.ts`
- `fortress-guest-platform/apps/command-center/src/lib/auth.ts`
- `fortress-guest-platform/apps/command-center/src/lib/api.ts`
- `fortress-guest-platform/apps/command-center/src/lib/roles.ts`
- `fortress-guest-platform/backend/core/security.py`
- `fortress-guest-platform/backend/api/auth.py`
- `fortress-guest-platform/backend/core/config.py`
- `fortress-guest-platform/backend/core/database.py`
- `fortress-guest-platform/backend/alembic/env.py`
- `fortress-guest-platform/backend/core/qdrant.py`
- `fortress-guest-platform/backend/services/qdrant_dual_writer.py`
- env example files by key name only.

## Production Mutation Statement

No deploys, auth mutations, DB writes, Supabase mutations, migrations, env file changes, `.auth` reads, Cloudflare/DNS mutations, runtime mutations, CROG-VRS mutations, Hedge Fund mutations, or Market Club mutations were performed.
