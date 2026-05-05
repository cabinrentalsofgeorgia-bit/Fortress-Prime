# Fortress Legal Production Backup / Snapshot Gate

Date: 2026-05-05
Status: BLOCKED

## Scope

This gate covers production deploy safety for Fortress Legal and the Command Center production surface. It is read-only unless `FORTRESS_ALLOW_PRODUCTION_BACKUP=1` is present and the production database target is explicitly identified.

The current approved production scope remains UI/backend release preparation only. This gate does not authorize legal data mutation, Qdrant mutation, NAS/evidence mutation, ingest, promotion, privilege clearance, resolution application, vector movement, migration execution, or production deployment.

## Target Evidence Captured

Read-only target discovery on spark-2 captured the following local deployment metadata:

- Deployment provider/target: Vercel project `crog-ai-command-center`.
- Vercel project id: `prj_u90XAUhroRxPGIXKYCowt0uqULDg`.
- Vercel org/team id: `team_yGxCOcECYMqhFKB3Yve2wRVi`.
- Vercel target environment observed: `production`.
- Vercel production env source: `apps/command-center/.vercel/.env.production.local`.
- Vercel production env values: redacted; not printed or committed.
- Production backend/API key observed: `FORTRESS_BACKEND_BASE_URL`, value redacted.
- Production deploy URL from local env snapshot: empty/not recorded.
- Production Git ref/commit fields from local env snapshot: empty/not recorded.

Fields still missing from local evidence:

- Production database URL/host that is tied to the production Supabase/project ref.
- Production Qdrant endpoint and collection names.
- Production NAS/evidence target.
- Current production deploy ID.
- Previous deploy ID/artifact for rollback.
- Redacted production environment snapshot artifact reference.

Fields discovered after the initial packet:

- Production Supabase identity exists in `/home/admin/.config/fortress-legal/production.env`; value redacted and not printed.
- Production domain exists in the production runtime env; value redacted and not printed.

The operator standing state treats the production target identity as verified, but backup creation cannot safely proceed until the production database/Supabase target is explicitly recorded and matched to the approved production target.

## 2026-05-05 Backup Rerun Evidence

An additional backup-gate rerun was performed from commit `63373212a`.

- `/tmp/fortress-production-backup.env`: absent on spark-2.
- `FORTRESS_ALLOW_PRODUCTION_BACKUP`: absent.
- `FORTRESS_PRODUCTION_SUPABASE_REF`: absent.
- `FORTRESS_PRODUCTION_DB_HOST`: absent.
- `FORTRESS_PRODUCTION_DB_URL`: absent.
- `FORTRESS_PRODUCTION_BACKUP_DIR`: absent.
- `FORTRESS_PRODUCTION_DOMAIN`: absent.
- `FORTRESS_PRODUCTION_DEPLOY_TARGET`: absent.
- `FORTRESS_ALLOW_PRODUCTION_DEPLOY`: absent.

Because no production backup authorization flag or production DB/Supabase target material was present, no production backup command was run.

## 2026-05-05 Env Validation Rerun

A subsequent rerun found `/tmp/fortress-production-backup.env` present with mode `600`, but the file did not validate for backup execution.

Validation result:

- `FORTRESS_ALLOW_PRODUCTION_BACKUP`: present.
- `FORTRESS_PRODUCTION_SUPABASE_REF`: present but invalid shape.
- `FORTRESS_PRODUCTION_DB_URL`: present but invalid shape.
- `FORTRESS_PRODUCTION_DOMAIN`: present but invalid shape.
- `FORTRESS_PRODUCTION_DB_URL`: invalid Postgres URL shape.
- `FORTRESS_PRODUCTION_BACKUP_DIR`: safe non-repo path shape.
- Final validator result: `ENV_NOT_VALID_FOR_BACKUP`.

No secret values were printed. No backup command was run. A secure helper was installed at `/tmp/create-fortress-production-backup-env.sh` so the operator can recreate the env file with real production values without writing secrets into the repository.

## 2026-05-05 pg_dump Attempt

The env file was corrected enough to pass the local validator and expose the required values as present, with values redacted. `pg_dump` was then attempted against the redacted production DB URL.

Result: `BLOCKED`.

Sanitized failure:

- `pg_dump` rejected the connection string because the port value was not a valid integer.
- No DB URL, password, or credential was printed.
- Any partial backup file was removed.
- No backup snapshot was created.
- No restoreable backup evidence exists from this attempt.

Required correction: recreate `/tmp/fortress-production-backup.env` with a production Postgres URL whose port is a real numeric port, not placeholder text. Then rerun `/tmp/validate-fortress-production-backup-env.sh` and the backup gate.

## 2026-05-05 Automatic Port Repair Guard

A follow-up rerun attempted the narrowest safe repair: replace an exact `PORT` placeholder only if the DB URL also referenced the declared production Supabase ref. The guard refused the repair because the redacted DB URL did not reference the declared production Supabase ref.

Result: `PRODUCTION_BLOCKED_TARGET_APPROVAL`.

No DB URL, password, or credential was printed. No backup command was rerun after the guard refusal. The production DB target remains ambiguous until `/tmp/fortress-production-backup.env` contains a numeric-port production Postgres URL that can be tied to the declared production Supabase/project ref.

## 2026-05-05 Strict Target Validator Rerun

The strict production target validator was run from commit `3041d4118`. Required env fields were present, but the redacted DB URL failed validation before target proof because it still contained placeholder or pasted command text.

Result: `PRODUCTION_BLOCKED_TARGET_APPROVAL`.

Validator result:

- `FORTRESS_PRODUCTION_DB_URL`: `INVALID_PLACEHOLDER_OR_COMMAND_TEXT`.
- Target proof was not evaluated because URL shape validation failed first.
- Secret values printed: `NO`.
- Production backup run: `NO`.

Required correction: recreate `/tmp/fortress-production-backup.env` with a real production Postgres URL containing a numeric port and no placeholder or pasted command text. The DB URL must also be tied to the production Supabase/project ref by hostname match, username match, or explicit target attestation.


## 2026-05-05 Production Env Auto-Discovery Rerun

A backup-target auto-discovery rerun was performed from commit `ae2929f9a`. The previous hand-edited `/tmp/fortress-production-backup.env` was moved aside before discovery and was not used as source of truth.

Discovery results:

- Vercel project metadata: `crog-ai-command-center`, project id `prj_u90XAUhroRxPGIXKYCowt0uqULDg`, team id `team_yGxCOcECYMqhFKB3Yve2wRVi`.
- Vercel CLI path: `npx vercel` succeeded and reported version `53.1.1`.
- Vercel production env pull: `PASS`; values were written only to `/tmp/fortress-vercel-production.env` with mode `600` and were not committed.
- Vercel production env DB candidates: `NONE` among the approved Postgres URL variable names.
- Vercel production env Supabase ref candidates: `NONE` among the approved Supabase identity variable names.
- Production runtime env file discovered from `fortress-legal-production.service`: `/home/admin/.config/fortress-legal/production.env`.
- Production runtime Supabase identity: `PRESENT_REDACTED`; it does not match known staging ref `ktppvqkiinlsmpsfiscr` and matches the historical production-ref candidate noted in the operator prompt.
- Server-side Postgres candidates in `/home/admin/Fortress-Prime/.env.security`: `DATABASE_URL`, `TEST_DATABASE_URL`, `POSTGRES_ADMIN_URI`, and `POSTGRES_API_URI` were present with valid Postgres-family shape, but their host/user metadata did not contain the production Supabase ref and their host did not prove a Supabase production target.
- `FORTRESS_DB_HOST`, `FORTRESS_DB_PORT`, `FORTRESS_DB_USER`, `FORTRESS_DB_NAME`, and `FORTRESS_DB_PASS` were present in the server-wide env, but the host/user metadata did not contain the production Supabase ref.
- Supabase CLI: absent on the spark-2 runner.
- Supabase access token files checked in approved local locations: absent.
- `pg_dump`: present at `/usr/bin/pg_dump`, PostgreSQL `16.13`.

Result: `PRODUCTION_BLOCKED_TARGET_APPROVAL`.

No DB URL, password, service-role key, or production secret was printed. No production backup env was regenerated because no Postgres URL discovered from deployment/runtime env could be tied to the declared production Supabase/project ref by hostname match, pooler username match, or explicit approved target attestation. No backup command was run.

## Backup Tooling Discovery

Read-only tooling discovery found:

- Vercel CLI: absent on the spark-2 runner.
- Supabase CLI: absent on the spark-2 runner.
- `pg_dump`: present at `/usr/bin/pg_dump`, PostgreSQL `16.13`.
- Existing project backup script: `backend/scripts/g1_5_backup_fortress_shadow.sh`.

The existing `g1_5_backup_fortress_shadow.sh` script is not an approved production backup method for this gate. It is scoped to five legacy owner-statement tables in `fortress_shadow` and writes into the repository script directory. It must not be used as the Fortress Legal production snapshot.

Preferred backup methods, once explicitly authorized:

1. Provider-native Supabase production backup/snapshot evidence tied to the production project/ref.
2. Supabase CLI dump against the explicit production project ref, if the CLI and access token are available.
3. `pg_dump` against the explicit production database URL, writing only to a secure non-repository location.

Approved output locations must be outside the git repository, such as `/var/backups/fortress-legal/` or another production-approved backup store. `/tmp` is acceptable only for transient verification if no approved backup storage exists.

## Required Evidence

Before production deploy or mutation, the release packet must include:

- Production Supabase ref or production DB target.
- Backup/snapshot identifier.
- Backup timestamp.
- Backup type.
- Backup scope.
- Backup storage location outside the git repository.
- Backup checksum if a dump file is created.
- Restore procedure.
- Rollback owner/operator.
- Evidence location.
- Verification that the backup matches the approved production target.
- Previous deployment ID or artifact.
- Redacted production environment snapshot reference.

## Restore Path Requirements

The restore path is not complete because no concrete production backup exists. Once authorized backup evidence is present, the restore packet must document:

1. The production project/ref and backup identifier.
2. The restore owner/operator.
3. The exact restore command or provider restore action, with secrets redacted.
4. The target environment verification before restore.
5. Verification steps after restore:
   - production root loads or fails safely,
   - login shell loads or fails safely,
   - protected routes are guarded,
   - Fortress Legal readiness does not falsely report ready,
   - legal API reads return the expected guarded/read-only state,
   - no legal evidence, Qdrant, NAS, privilege, ingest, promotion, or resolution state is changed by guesswork.

No DB rollback, Qdrant rollback, NAS/evidence deletion, evidence overwrite, privilege rewrite, or audit rewrite may rely on guesswork.

## Authorized Backup Command Templates

These are templates only. They are not approved for execution until `FORTRESS_ALLOW_PRODUCTION_BACKUP=1` is present and the production database/Supabase target is explicit.

Provider-native preferred path:

```bash
# Capture provider-native production backup evidence for <production_project_ref>.
# Record snapshot id, timestamp, scope, retention, and restore procedure.
```

Supabase CLI path, if the CLI and access token are available:

```bash
supabase db dump --project-ref <production_project_ref> --file <secure_non_repo_path>/<timestamp>-fortress-legal-production.sql
```

Direct PostgreSQL path, if the production database URL is already available in the authorized server-side environment:

```bash
pg_dump "$PRODUCTION_DATABASE_URL" --file <secure_non_repo_path>/<timestamp>-fortress-legal-production.sql
sha256sum <secure_non_repo_path>/<timestamp>-fortress-legal-production.sql
```

Do not place dump files in the git repository. Do not print database URLs, passwords, privileged keys, or backup contents.

## Current Gate Result

- Production backup/snapshot evidence: `BLOCKED`.
- Backup creation authorization flag: `NOT_USED_IN_AUTO_DISCOVERY`; previous hand-edited temp env was moved aside.
- Production backup creation attempted: `NO`.
- Vercel production env pull: `PASS`.
- Selected production DB variable: `NONE`.
- Production Supabase ref recorded: `PRESENT_REDACTED` from production runtime env.
- Production DB URL to Supabase ref proof: `MISSING`.
- Production Supabase/DB target recorded: `PARTIAL_SUPABASE_REF_PRESENT_DB_TARGET_UNPROVEN`.
- Restore path documented against concrete snapshot: `NO`.
- Production DB mutation: `NO`.
- Legal DB mutation: `NO`.
- Qdrant mutation: `NO`.
- NAS/evidence mutation: `NO`.
- Ingest/promotion/privilege/resolution actions: `NO`.

## Required Next Action

Provide one approved production database backup target proof path:

1. a production Postgres URL whose hostname contains the production Supabase ref,
2. a Supabase pooler URL whose username contains the production Supabase ref,
3. provider-native Supabase backup/snapshot evidence for the redacted production ref, or
4. a committed/approved production target attestation that explicitly binds the redacted production DB host to the production Supabase/project ref.

After that proof exists, rerun backup creation with an approved backup storage location and `FORTRESS_ALLOW_PRODUCTION_BACKUP=1`. Do not deploy until the backup/snapshot evidence matches the verified production target and the restore path is documented.
