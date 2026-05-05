# Fortress Legal Production Readiness Audit

Date: 2026-05-05
Classification: PRODUCTION_DEPLOY_FAILED

## Executive Summary

Fortress Legal staging UI is certified, dependency high/critical advisories have been remediated, rollback and legal/compliance gates are documented, and provider-native Supabase backup evidence is now present. Production deploy was not attempted because deploy authorization is absent, and legal operations remain `NOT_READY_BY_DESIGN`.

## Production Target Identity

- Operator standing classification: `PRODUCTION_TARGET_VERIFIED_DEPLOY_BLOCKED_PENDING_BACKUP_ROLLBACK_ADVISORY_LEGAL_GATES`.
- Deployment provider/target observed: Vercel project `crog-ai-command-center`.
- Vercel project id observed: `prj_u90XAUhroRxPGIXKYCowt0uqULDg`.
- Vercel org/team id observed: `team_yGxCOcECYMqhFKB3Yve2wRVi`.
- Vercel target environment observed: `production`.
- Production backend/API target: `FORTRESS_BACKEND_BASE_URL` key observed, value redacted.
- Production app URL/domain: present in production runtime env, value redacted and not printed.
- Production Supabase ref: `hms...liap` partial-safe; selected from Supabase provider project metadata for `Fortress Legal Production` and distinct from known staging ref `ktppvqkiinlsmpsfiscr`.
- Production database host/ref: provider-native Supabase project backup evidence used; manual DB URL proof no longer required for this backup gate.
- Production Qdrant target: not recorded in local evidence.
- Production NAS/evidence target: not recorded in local evidence.
- Production deploy ID and previous deploy ID: not recorded in local evidence.

## Backup / Snapshot Gate

- Result: `PASS`.
- Evidence file: `docs/operational/fortress-legal-production-backup-snapshot-gate-2026-05-05.md`.
- Production backup/snapshot evidence: provider-native Supabase completed physical backup listing.
- Production project proof: Supabase provider project list identified `Fortress Legal Production`, ref `hms...liap` partial-safe, region `us-east-1`.
- Latest completed physical backup timestamp: `2026-05-05T11:09:03.536Z`.
- Previous completed physical backup timestamp: `2026-05-05T02:29:26.703Z`.
- Completed provider backups observed: `2`.
- WAL-G enabled: `true`; PITR enabled: `false`.
- Dump file created by this run: NO.
- Existing backup script reviewed: `backend/scripts/g1_5_backup_fortress_shadow.sh`, rejected for this gate because it is a narrow legacy table backup and writes into the repo script directory.
- Restore path: documented against provider-native completed backup evidence.

## Rollback Plan Gate

- Result: `PASS_AS_PLAN`.
- Evidence file: `docs/operational/fortress-legal-production-rollback-plan-2026-05-05.md`.
- Provider-specific previous deployment ID remains required before deploy.
- Backup evidence reference is present.
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
- Production backup evidence: PASS by provider-native Supabase backup listing.
- Production backup env handoff: previous hand-edited temp env moved aside and not trusted.
- Production backup creation attempted: NO; no dump was required because provider-native backup evidence exists.

## Staging Certification References

- `cb3d1a202` - authenticated-session UI certification.
- `74806ee7c` - password-login E2E certification and browser path redaction.


## Production Deployment Attempt - 2026-05-05

- Deployment authorization: PRESENT from operator prompt for UI/backend deploy and read-only smoke only.
- Deploy command: `FORTRESS_ALLOW_PRODUCTION_DEPLOY=1 npx vercel --prod --yes`.
- Deploy working directory: clean detached `d354339f6` checkout, `apps/command-center`.
- Vercel project: `crog-ai-command-center`.
- Deployment ID: `dpl_AqraMLyUH2FMD5sperEGLnWToMXV`.
- Deployment URL: `https://crog-ai-command-center-k0dj2um4y-cabin-rentals-of-georgia.vercel.app`.
- Deployment result: `FAILED`.
- Failure summary: Vercel cloud build completed `next build` but failed because the app-root build environment could not resolve `../../scripts/sync-next-standalone-assets.mjs`, yielding `MODULE_NOT_FOUND` at `/scripts/sync-next-standalone-assets.mjs`.
- Production smoke: NOT_RUN because deployment failed.
- Rollback: NOT_EXECUTED; `https://crog-ai.com` still resolves to previous ready deployment `dpl_14JfuBDB1j14HTf2fdMdMjGUU5sE`.
- Legal/data mutation: NO.

## Production Deploy Authorization

- `FORTRESS_ALLOW_PRODUCTION_DEPLOY`: present for the 2026-05-05 deploy attempt by operator prompt.
- Production deploy: attempted and failed during Vercel cloud build.
- Production smoke: not attempted because deploy failed.

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

1. Add previous deployment ID/artifact and concrete rollback command before deploy.
2. Provide explicit production deploy authorization with `FORTRESS_ALLOW_PRODUCTION_DEPLOY=1` and a completed approval packet.
3. Run production smoke only after authorized deployment.
4. Resolve or explicitly scope legal/operator blockers before claiming full legal-data production readiness.

## Exact Next Action

Fix the Vercel production build root/script mismatch for `scripts/sync-next-standalone-assets.mjs`, rerun all pre-deploy gates, and redeploy only under the same UI/backend-only production authorization model. Do not claim legal-data readiness while legal/operator blockers remain unresolved.
