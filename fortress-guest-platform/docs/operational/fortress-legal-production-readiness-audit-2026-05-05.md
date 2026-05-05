# Fortress Legal Production Readiness Audit

Date: 2026-05-05
Classification: PRODUCTION_BLOCKED_TARGET_APPROVAL

## Executive Summary

Fortress Legal staging UI is certified, dependency high/critical advisories have been remediated, rollback and legal/compliance gates are documented, and legal operations remain `NOT_READY_BY_DESIGN`. Production deploy was not attempted because automated production env discovery did not find a Postgres connection string that can be tied to the declared production Supabase/project ref.

## Production Target Identity

- Operator standing classification: `PRODUCTION_TARGET_VERIFIED_DEPLOY_BLOCKED_PENDING_BACKUP_ROLLBACK_ADVISORY_LEGAL_GATES`.
- Deployment provider/target observed: Vercel project `crog-ai-command-center`.
- Vercel project id observed: `prj_u90XAUhroRxPGIXKYCowt0uqULDg`.
- Vercel org/team id observed: `team_yGxCOcECYMqhFKB3Yve2wRVi`.
- Vercel target environment observed: `production`.
- Production backend/API target: `FORTRESS_BACKEND_BASE_URL` key observed, value redacted.
- Production app URL/domain: present in production runtime env, value redacted and not printed.
- Production Supabase ref: present in production runtime env, value redacted; it does not match known staging ref `ktppvqkiinlsmpsfiscr`.
- Production database host/ref: unresolved; discovered Postgres-family values do not prove a Supabase production target by hostname or username.
- Production Qdrant target: not recorded in local evidence.
- Production NAS/evidence target: not recorded in local evidence.
- Production deploy ID and previous deploy ID: not recorded in local evidence.

## Backup / Snapshot Gate

- Result: `BLOCKED_TARGET_APPROVAL`.
- Evidence file: `docs/operational/fortress-legal-production-backup-snapshot-gate-2026-05-05.md`.
- Production backup/snapshot evidence: missing.
- Vercel production env pull: PASS to `/tmp/fortress-vercel-production.env`; values redacted and not committed.
- Selected DB variable from Vercel production env: NONE.
- Production runtime Supabase identity: present in `/home/admin/.config/fortress-legal/production.env`, value redacted, not staging.
- Server-side Postgres candidates: present in `/home/admin/Fortress-Prime/.env.security`, but none can be tied to the production Supabase ref by hostname or pooler username.
- Supabase CLI/access token: unavailable on the runner.
- `pg_dump`: present at `/usr/bin/pg_dump`, but not run because target proof failed.
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
- Production backup creation authorization: not used by auto-discovery; backup target proof failed before backup execution.
- Production backup env handoff: previous hand-edited temp env moved aside and not trusted.
- Production backup creation attempted: NO during auto-discovery rerun.

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

1. Provide an approved production DB target proof: direct Supabase host/ref match, Supabase pooler username/ref match, provider-native backup evidence, or explicit approved target attestation binding the DB host to the production Supabase/project ref.
2. Provide current production backup/snapshot evidence matching that target, or rerun backup creation only after the target proof exists.
3. Add previous deployment ID/artifact and concrete rollback command before deploy.
4. Provide explicit production deploy authorization with `FORTRESS_ALLOW_PRODUCTION_DEPLOY=1` and a completed approval packet.
5. Resolve or explicitly scope legal/operator blockers before claiming full legal-data production readiness.

## Exact Next Action

Attach provider-native backup evidence for the redacted production Supabase ref, or provide an approved Postgres target whose hostname/username proves the same ref. Do not run `pg_dump` or deploy until that target proof and restore path are documented.
