# Fortress Legal Production Deployment Evidence

Date: 2026-05-05
Classification: PRODUCTION_DEPLOY_FAILED

## Authorization

- Operator: Gary Knight.
- Authorization timestamp: 2026-05-05.
- Authorization flag: `FORTRESS_ALLOW_PRODUCTION_DEPLOY=1` supplied by operator prompt.
- Authorized scope: production UI/backend deployment and read-only smoke validation only.
- Production target: Vercel project `crog-ai-command-center`.
- Legal operations: blocked pending operator/legal decisions.
- Real legal data readiness: not claimed.

This deployment authorization did not authorize production DB migration, Supabase schema mutation, legal data upload, document ingest, production matter creation, production user creation, Qdrant write, NAS/evidence mutation, privilege clearance, promotion, or legal resolution application.

## Release Baseline

- Worktree used for deploy attempt: clean detached worktree created from `d354339f6` under `/tmp`.
- Release commit: `d354339f6`.
- Branch baseline: `safety/foundation-audit-snapshot`.
- Relevant commits included: `cb3d1a202`, `74806ee7c`, `69d8b57e4`, `e8b1bd358`, `63373212a`, `d354339f6`.
- Main worktree unrelated dirty files: present in MarketClub/hedge-fund/backend areas and left untouched.
- Fortress Legal release slice in main worktree before deploy: no unexpected dirty release files.

## Pre-Deploy Gates

Fresh gates were run against the clean detached `d354339f6` checkout before deployment:

- High-severity NPM audit: PASS.
- `git diff --check`: PASS.
- `npx tsc --noEmit --pretty false`: PASS.
- Focused unit tests: PASS.
- `npm run build`: PASS locally from clean checkout.
- Focused ESLint: PASS.
- Static/browser secret scan: PASS.
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

## Rollback Metadata

- Previous/current live production deployment before deploy attempt: `dpl_14JfuBDB1j14HTf2fdMdMjGUU5sE`.
- Previous/current live production URL before deploy attempt: `https://crog-ai-command-center-7s7mm8iii-cabin-rentals-of-georgia.vercel.app`.
- Production domain inspected after failed deploy: `https://crog-ai.com` still resolves to `dpl_14JfuBDB1j14HTf2fdMdMjGUU5sE`, status `Ready`.
- Rollback command template: `npx vercel rollback <deployment id/url> --yes`.
- Rollback readiness: LIMITED/PASS_FOR_PROVIDER_LEVEL_ROLLBACK; live alias did not move to the failed deployment.
- Rollback executed: NO.

## Deployment Attempt

- Deploy command: `FORTRESS_ALLOW_PRODUCTION_DEPLOY=1 npx vercel --prod --yes`.
- Deploy working directory: clean detached checkout, `apps/command-center`.
- Vercel project: `crog-ai-command-center`.
- Deploy started: `2026-05-05T21:37:46Z`.
- Commit deployed: attempted from `d354339f6` clean checkout.
- Deployment URL: `https://crog-ai-command-center-k0dj2um4y-cabin-rentals-of-georgia.vercel.app`.
- Deployment ID: `dpl_AqraMLyUH2FMD5sperEGLnWToMXV`.
- Deployment result: FAILED.

Sanitized failure summary:

- Vercel uploaded the deployment and began a production build.
- The cloud build successfully compiled the Next.js app and generated static pages.
- The cloud build failed during the app build script after `next build` because `node ../../scripts/sync-next-standalone-assets.mjs` resolved to `/scripts/sync-next-standalone-assets.mjs` in the Vercel build environment.
- Error class: `MODULE_NOT_FOUND`.
- Missing module path: `/scripts/sync-next-standalone-assets.mjs`.
- No secret values were printed.

Likely narrow fix path:

- Align Vercel deployment root/build command with the monorepo layout so `../../scripts/sync-next-standalone-assets.mjs` is present at build time, or adjust the production build script so the standalone asset sync is safe in the Vercel app-root build environment.
- Re-run full pre-deploy gates after the fix before redeploying.

## Production Smoke

Production smoke was not run because the deployment failed.

- Root: NOT_RUN.
- Login shell: NOT_RUN.
- Protected dashboard guard: NOT_RUN.
- Protected legal guard: NOT_RUN.
- Authenticated dashboard: NOT_RUN.
- Authenticated legal route: NOT_RUN.
- Readiness observed: NOT_RUN.
- Legal API calls: NOT_RUN.
- Console/page errors: NOT_RUN.
- Critical API failures: NOT_RUN.
- Localhost calls: NOT_RUN.
- Secret exposure: NO.

## Mutation Invariants

- Production deployment touched: YES, failed Vercel deployment attempt only.
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

## Final Standing State

- Final classification: PRODUCTION_DEPLOY_FAILED.
- Staging UI certification: STAGING_AUTHENTICATED_UI_CERTIFIED.
- Production status: PRODUCTION_DEPLOY_FAILED; live production domain remains on the prior ready deployment.
- Legal readiness: LEGAL_READINESS_NOT_READY_BY_DESIGN.
- Legal operations: LEGAL_OPS_BLOCKED_PENDING_OPERATOR_LEGAL_DECISIONS.
- Real legal data status: BLOCKED.
