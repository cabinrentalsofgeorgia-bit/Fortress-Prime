# Fortress Legal Production Readiness Audit

Date: 2026-05-05
Classification: PRODUCTION_BLOCKED_BACKUP_SNAPSHOT

## Executive Summary

Fortress Legal staging UI is certified, dependency high/critical advisories have been remediated, rollback and legal/compliance gates are documented, and legal operations remain `NOT_READY_BY_DESIGN`. Production deploy was not attempted because production backup/snapshot evidence is missing, the production Supabase/DB backup target is not recorded in local evidence, production backup creation authorization is absent, and production deploy authorization is absent.

## Production Target Identity

- Operator standing classification: `PRODUCTION_TARGET_VERIFIED_DEPLOY_BLOCKED_PENDING_BACKUP_ROLLBACK_ADVISORY_LEGAL_GATES`.
- Deployment provider/target observed: Vercel project `crog-ai-command-center`.
- Vercel project id observed: `prj_u90XAUhroRxPGIXKYCowt0uqULDg`.
- Vercel org/team id observed: `team_yGxCOcECYMqhFKB3Yve2wRVi`.
- Vercel target environment observed: `production`.
- Production backend/API target: `FORTRESS_BACKEND_BASE_URL` key observed, value redacted.
- Production app URL: not recorded in local evidence; `VERCEL_URL` is empty in the local production env snapshot.
- Production Supabase ref: not recorded in local evidence.
- Production database host/ref: not recorded in local evidence.
- Production Qdrant target: not recorded in local evidence.
- Production NAS/evidence target: not recorded in local evidence.
- Production deploy ID and previous deploy ID: not recorded in local evidence.

## Backup / Snapshot Gate

- Result: `BLOCKED`.
- Evidence file: `docs/operational/fortress-legal-production-backup-snapshot-gate-2026-05-05.md`.
- Production backup/snapshot evidence: missing.
- Backup creation authorization: present in `/tmp/fortress-production-backup.env`.
- Backup env handoff file: present at `/tmp/fortress-production-backup.env` with mode `600`.
- Production Supabase/DB backup target: present in env with values redacted, but the DB URL was unusable by `pg_dump`.
- Backup target validation: local validator reported `ENV_VALID_FOR_BACKUP`, then `pg_dump` rejected the connection string because the port value was not a valid integer.
- Backup tooling discovery: Vercel CLI absent; Supabase CLI absent; `pg_dump` present at `/usr/bin/pg_dump`.
- Existing backup script reviewed: `backend/scripts/g1_5_backup_fortress_shadow.sh`, rejected for this gate because it is a narrow legacy table backup and writes into the repo script directory.
- Restore path: not documented against a concrete snapshot.

## Rollback Plan Gate

- Result: `PASS_AS_PLAN`.
- Evidence file: `docs/operational/fortress-legal-production-rollback-plan-2026-05-05.md`.
- Provider-specific previous deployment ID remains required before deploy.
- Rollback verification steps are documented.

## Dependency Advisory Gate

- Result: `PASS_WITH_MODERATE_ACCEPTANCE_EXPIRY`.
- Evidence file: `docs/operational/fortress-legal-dependency-advisory-disposition-2026-05-05.md`.
- High/critical NPM findings: remediated.
- Remaining findings: two moderate Next/PostCSS findings accepted with expiry `2026-06-05`.
- Python audit tooling: unavailable on runner; no Python dependency audit pass is claimed.

## Legal / Compliance Gate

- Result: `PASS_FOR_UI_BACKEND_SCOPE`.
- Evidence file: `docs/operational/fortress-legal-production-legal-compliance-gate-2026-05-05.md`.
- Legal readiness: `NOT_READY_BY_DESIGN`.
- Legal operations: blocked pending explicit operator/legal decisions.
- Privilege inference: prohibited.
- HOLD policy: preserved.

## Build / Test / Security Gate

Commands run after dependency remediation:

- `git diff --check`
- `npx tsc --noEmit --pretty false`
- `npm run build`
- focused ESLint for Fortress Legal certification/release files
- static/browser secret scan

Results:

- `git diff --check`: PASS.
- `npx tsc --noEmit --pretty false`: PASS.
- `npm run build`: PASS on Next.js `16.2.4`.
- Focused ESLint: PASS for Fortress Legal certification/release files.
- Browser/static secret scan: PASS.
- Browser/static privileged server credential exposure: NO.
- Browser/static wrong Supabase ref: NO.
- Browser/static token patterns: NO.
- Browser/static DB/Qdrant credential patterns: NO.
- Browser/static NAS paths: NO.
- Browser/static localhost calls: NO.
- Production deploy authorization: ABSENT.
- Production backup creation authorization: PRESENT.
- Production backup env handoff: PRESENT.
- Production backup creation attempted: YES, failed before backup creation because `pg_dump` rejected the DB URL port.

## Staging Certification References

- `cb3d1a202` - authenticated-session UI certification.
- `74806ee7c` - password-login E2E certification and browser path redaction.

## Production Deploy Authorization

- `FORTRESS_ALLOW_PRODUCTION_DEPLOY`: absent during this audit.
- Production deploy: not attempted.
- Production smoke: not attempted.

## Mutation Invariants

- Production DB writes: NO.
- Legal DB writes: NO.
- Qdrant writes: NO.
- NAS/evidence changes: NO.
- Ingest: NO.
- Promotion: NO.
- Privilege changes: NO.
- Resolution application: NO.

## Remaining Blockers

1. Recreate `/tmp/fortress-production-backup.env` on spark-2 with a production Postgres URL whose port is numeric, by running `/tmp/create-fortress-production-backup-env.sh`.
2. Record the exact production Supabase/project ref or production DB target.
3. Provide current production backup/snapshot evidence matching that target, or authorize backup creation with `FORTRESS_ALLOW_PRODUCTION_BACKUP=1`.
4. Add previous deployment ID/artifact and concrete rollback command before deploy.
5. Provide explicit production deploy authorization with `FORTRESS_ALLOW_PRODUCTION_DEPLOY=1` and a completed approval packet.
6. Resolve or explicitly scope legal/operator blockers before claiming full legal-data production readiness.

## Exact Next Action

Attach current production backup/snapshot evidence matching the verified production target, or rerun with an explicit production Supabase/DB target and `FORTRESS_ALLOW_PRODUCTION_BACKUP=1`. Do not deploy until that evidence is present and the restore path is documented.
