# Fortress Legal Production Deployment Evidence

Date: 2026-05-05
Classification: PRODUCTION_SMOKE_FAILED_ROLLED_BACK

## Authorization

- Operator: Gary Knight.
- Authorization timestamp: 2026-05-05.
- Authorization flag: `FORTRESS_ALLOW_PRODUCTION_DEPLOY=1` supplied by operator prompt.
- Authorized scope: fix production deploy configuration/build-root issue, production UI/backend deployment, read-only production smoke, audit documentation, and rollback if smoke failed critically.
- Production target: Vercel project `crog-ai-command-center`.
- Legal operations: blocked pending operator/legal decisions.
- Real legal data readiness: not claimed.

This deployment authorization did not authorize production DB migration, Supabase schema mutation, legal data upload, document ingest, production matter creation, production user creation, Qdrant write, NAS/evidence mutation outside audit docs, privilege clearance, promotion, or legal resolution application.

## Previous Failure

The previous deploy attempt from release commit `d354339f6` failed during Vercel cloud build.

- Failed command: `FORTRESS_ALLOW_PRODUCTION_DEPLOY=1 npx vercel --prod --yes`.
- Failed deployment ID: `dpl_AqraMLyUH2FMD5sperEGLnWToMXV`.
- Failed deployment URL: `https://crog-ai-command-center-k0dj2um4y-cabin-rentals-of-georgia.vercel.app`.
- Failure symptom: Vercel cloud build completed `next build` but failed when the app build script attempted `node ../../scripts/sync-next-standalone-assets.mjs`.
- Actual missing path in cloud build: `/scripts/sync-next-standalone-assets.mjs`.
- Cause: Vercel built from the app root, so the repo-root-relative script path escaped the uploaded build context.

## Fix Applied

- Fix commit: `885002186`.
- Commit message: `fix(deploy): align Vercel build root asset sync script`.
- Files changed:
  - `apps/command-center/package.json`.
  - `apps/command-center/scripts/sync-next-standalone-assets.mjs`.
- Fix summary: the standalone asset sync script is now included inside the app build root and the app build command calls `node scripts/sync-next-standalone-assets.mjs`.
- Durability: the production app-root upload now contains the script that the build invokes; no manual file copy or local-only path is required.

## Release Baseline

- Main worktree: `/home/admin/Fortress-Prime/fortress-guest-platform`.
- Branch baseline: `safety/foundation-audit-snapshot`.
- Starting commit for this phase: `190f8d12b`.
- Fix commit: `885002186`.
- Deploy checkout: clean detached `/tmp` checkout from `885002186`.
- Relevant certification/gate commits included: `cb3d1a202`, `74806ee7c`, `69d8b57e4`, `e8b1bd358`, `63373212a`, `d354339f6`, `190f8d12b`, `885002186`.
- Main worktree unrelated dirty files: present in MarketClub/hedge-fund/backend areas and left untouched.

## Pre-Deploy Gates

Fresh gates were run against a clean detached `885002186` checkout before deployment:

- High-severity NPM audit: PASS.
- `git diff --check`: PASS.
- Build-root/script verification: PASS; app build script points to `scripts/sync-next-standalone-assets.mjs` and the script exists in the app root.
- `npx tsc --noEmit --pretty false`: PASS.
- Focused unit tests: PASS.
- `npm run build`: PASS.
- Standalone asset sync local evidence: static and public assets copied successfully.
- Focused ESLint: PASS.
- Source/docs/static/browser secret scan: PASS.
- Browser/static service-role exposure: NO.
- Browser/static known staging ref exposure: NO.
- Browser/static token patterns: NO.
- Browser/static DB/Qdrant credential patterns: NO.
- Browser/static NAS/backup paths: NO.
- Browser/static localhost calls: NO.

Existing gate posture:

- Backup/snapshot gate: PASS.
- Rollback plan gate: PASS_AS_PLAN.
- Dependency advisory gate: PASS.
- Legal/compliance gate: PASS_FOR_UI_BACKEND_SCOPE.
- Legal readiness: NOT_READY_BY_DESIGN.
- Legal operations: blocked pending operator/legal decisions.

## Fixed Deployment Attempt

- Deploy command: `FORTRESS_ALLOW_PRODUCTION_DEPLOY=1 npx vercel --prod --yes`.
- Deploy working directory: clean detached checkout, `apps/command-center`.
- Vercel project: `crog-ai-command-center`.
- Deploy started: `2026-05-05T21:48:27Z`.
- Deploy finished: `2026-05-05T21:50:36Z`.
- Commit deployed: `885002186`.
- Deployment ID: `dpl_A6BbRNxgg3MnXCzBhjvA6fprTZNT`.
- Deployment URL: `https://crog-ai-command-center-j4zbkar4e-cabin-rentals-of-georgia.vercel.app`.
- Production alias: `https://crog-ai.com`.
- Deployment result: SUCCESS / READY.
- Cloud-build proof: Vercel build ran `next build && node scripts/sync-next-standalone-assets.mjs`; the cloud log recorded `sync-next-standalone-assets: static -> /vercel/path0/.next/standalone/.next/static` and `sync-next-standalone-assets: public -> /vercel/path0/.next/standalone/public`.

## Production Smoke Result

Authorized smoke scope: unauthenticated/read-only.

Smoke against `https://crog-ai.com` after fixed deploy:

- Root route: HTTP 200, page title `Fortress Prime`, login shell content visible.
- Login route: HTTP 200, login shell content visible.
- Protected dashboard route: HTTP 200 with `Verifying session...`; no dashboard content exposed unauthenticated.
- Protected legal route: HTTP 200 with `Verifying session...`; no legal case/readiness content exposed unauthenticated.
- Authenticated dashboard: NOT_RUN; no authorized production-safe credentials/session supplied.
- Authenticated legal route: NOT_RUN; no authorized production-safe credentials/session supplied.
- Readiness observed: NOT_RUN; authenticated smoke not run.
- Legal API calls: NOT_RUN; authenticated smoke not run.
- Localhost calls: NO.
- Secret exposure: NO.
- Page errors: NO.
- Critical failure: YES; `_next/static` chunk/font requests returned HTTP 500.
- Static failure samples:
  - `https://crog-ai.com/_next/static/chunks/962ab73620fd3bcd.css` -> HTTP 500.
  - `https://crog-ai.com/_next/static/chunks/05b80fe276b4ed75.js` -> HTTP 500.
  - `https://crog-ai.com/_next/static/chunks/turbopack-ab5cefb61acf62ae.js` -> HTTP 500.
- Browser console errors: 84 resource-load errors caused by `_next/static` HTTP 500 responses.

Result: PRODUCTION_SMOKE_FAILED.

## Rollback

Rollback was executed because the deployed browser UI could not be certified while `_next/static` assets returned HTTP 500.

- Previous ready deployment before fixed deploy: `dpl_14JfuBDB1j14HTf2fdMdMjGUU5sE`.
- Previous ready deployment URL: `https://crog-ai-command-center-7s7mm8iii-cabin-rentals-of-georgia.vercel.app`.
- Rollback command: `npx vercel rollback dpl_14JfuBDB1j14HTf2fdMdMjGUU5sE --yes`.
- Rollback started: `2026-05-05T21:54:46Z`.
- Rollback finished: `2026-05-05T21:54:50Z`.
- Rollback result: SUCCESS.
- Post-rollback Vercel inspect: `https://crog-ai.com` resolved to `dpl_14JfuBDB1j14HTf2fdMdMjGUU5sE`, status `Ready`.

Post-rollback smoke:

- Root route: HTTP 200, login shell content visible.
- Login route: HTTP 200, login shell content visible.
- Protected dashboard route: guarded by `Verifying session...`; no dashboard content exposed unauthenticated.
- Protected legal route: guarded by `Verifying session...`; no legal content exposed unauthenticated.
- Localhost calls: NO.
- Secret exposure: NO.
- Post-rollback critical static failure persisted: `_next/static` assets still returned HTTP 500 on `https://crog-ai.com`.

Rollback restored the previous provider deployment but did not produce a smoke-certified production UI. The remaining failure appears to be a production static asset serving/proxy/hosting issue, not the original build-root script failure.

## Mutation Invariants

- Production deployment touched: YES, Vercel deploy and provider rollback only.
- Production DB writes: NO.
- Legal DB writes: NO.
- Qdrant writes: NO.
- NAS/evidence changes: NO, except this operational audit document in git.
- Ingest: NO.
- Promotion: NO.
- Privilege changes: NO.
- Resolution application: NO.
- Auth metadata write: NO.
- Production Supabase schema changes: NO.
- Storage object writes: NO.
- Matter creation: NO.
- User creation: NO.
- Document upload: NO.

## Remaining Blockers

- Production UI smoke: BLOCKED by `_next/static` HTTP 500 responses on `https://crog-ai.com`.
- Production static asset serving/proxy/hosting path must be repaired and re-smoked.
- Production authenticated smoke remains not run because no production-safe credentials/session were authorized or available.
- Full legal-data operations remain blocked pending operator/legal decisions.

## Final Standing State

- Final classification: PRODUCTION_SMOKE_FAILED_ROLLED_BACK.
- Staging UI certification: STAGING_AUTHENTICATED_UI_CERTIFIED.
- Production status: PRODUCTION_SMOKE_FAILED_ROLLED_BACK_TO_PREVIOUS_READY_DEPLOYMENT; production UI is not smoke-certified.
- Legal readiness: LEGAL_READINESS_NOT_READY_BY_DESIGN.
- Legal operations: LEGAL_OPS_BLOCKED_PENDING_OPERATOR_LEGAL_DECISIONS.
- Real legal data status: BLOCKED.
