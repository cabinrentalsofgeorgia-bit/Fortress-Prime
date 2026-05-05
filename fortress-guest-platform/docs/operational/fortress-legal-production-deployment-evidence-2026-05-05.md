# Fortress Legal Production Deployment Evidence

Date: 2026-05-05
Classification: PRODUCTION_DEPLOYED_STATIC_ASSETS_SMOKE_PASSED_LEGAL_OPS_BLOCKED

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

## Static Asset Production Fix - 2026-05-05

Classification: `PRODUCTION_DEPLOYED_STATIC_ASSETS_SMOKE_PASSED_LEGAL_OPS_BLOCKED`.

### Previous Static Failure Summary

The previous fixed-build deploy (`885002186`) reached Vercel successfully but production smoke failed on the custom domain because `https://crog-ai.com/_next/static/*` requests returned HTTP 500.

Recorded failing assets:

- `https://crog-ai.com/_next/static/chunks/962ab73620fd3bcd.css` -> HTTP 500, `text/plain`, body `Internal Server Error`.
- `https://crog-ai.com/_next/static/chunks/05b80fe276b4ed75.js` -> HTTP 500, `text/plain`, body `Internal Server Error`.
- `https://crog-ai.com/_next/static/chunks/turbopack-ab5cefb61acf62ae.js` -> HTTP 500.

### Root Cause

Root cause classification: `STALE_OR_BAD_DEPLOYMENT_ARTIFACT` with a custom-domain Cloudflare tunnel serving path.

Evidence:

- DNS for `crog-ai.com` resolves through Cloudflare.
- `/etc/cloudflared/config.yml` routes `crog-ai.com` and `www.crog-ai.com` to `http://127.0.0.1:3005`.
- Port `3005` was owned by an orphaned `next-server` process whose cwd was `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center (deleted)`.
- The running server rendered HTML referencing old chunk hashes, while the on-disk `.next/static` directory contained a different build's chunks.
- Next middleware/proxy was not intercepting `_next/static`; `src/proxy.ts` excludes `_next/static`, `_next/image`, common public files, and static extensions.

Why staging/local gates did not catch it: the clean local standalone proof used a matching server/static artifact, while the production custom-domain path was a long-running local standalone process left alive after `.next` was replaced by build/deploy verification.

### Fix Applied

Fix commit: `2cedcc16c`.

Files changed:

- `apps/command-center/package.json`.
- `apps/command-center/scripts/smoke-static-assets.mjs`.
- `apps/command-center/src/lib/system-health-websocket.ts`.
- `apps/command-center/src/__tests__/system-health-websocket.test.ts`.

Fix summary:

- Added `npm run smoke:static-assets` to verify that the root HTML references `_next/static` assets and that representative JS/CSS assets return HTTP 200.
- Removed the client-side localhost-only system-health WebSocket fallback from the production browser bundle; same-origin or explicit public env configuration is now used.
- Rebuilt a clean `2cedcc16c` artifact outside the dirty main worktree.
- Deployed `2cedcc16c` to Vercel production.
- Replaced the Cloudflare-served local standalone `.next` artifact with the matching clean `2cedcc16c` build and restarted the managed `crog-ai-frontend.service`.

### Pre-Deploy Gates

Clean release checkout: `/tmp/fortress-static-asset-release-2cedcc16c-20260505T221829Z`.

- Command-center `npm audit --audit-level=high`: PASS; no high/critical findings for the command-center release slice. The documented moderate `next`/`postcss` findings remain under prior expiry disposition.
- Workspace high-severity audit for `@fortress/command-center`: PASS.
- `git diff --check`: PASS.
- `npx tsc --noEmit --pretty false`: PASS.
- Focused tests: PASS (`62` tests across system-health websocket, legal, and command-search suites).
- `npm run build`: PASS.
- Standalone asset sync: PASS; `120` static files copied into standalone runtime static directory.
- Focused lint: PASS.
- Local standalone static smoke on port `3996`: PASS; representative JS and CSS returned HTTP 200.
- Middleware/proxy exclusion verification: PASS; `_next/static` is excluded in `src/proxy.ts` matcher.
- Legal-data mutation guard: PASS; no legal-data operation was authorized or run.

### Production Deploy

- Deploy command: `FORTRESS_ALLOW_PRODUCTION_DEPLOY=1 npx vercel --prod --yes`.
- Deploy working directory: clean detached checkout, `apps/command-center`.
- Vercel project: `crog-ai-command-center` (`prj_u90XAUhroRxPGIXKYCowt0uqULDg`).
- Deploy started: `2026-05-05T22:19:43Z`.
- Deploy finished: `2026-05-05T22:20:47Z`.
- Commit deployed: `2cedcc16c`.
- Deployment ID: `dpl_9PFbhnbh51vYtz3C4L7zDcZbwVsM`.
- Deployment URL: `https://crog-ai-command-center-ngsa52jch-cabin-rentals-of-georgia.vercel.app`.
- Vercel alias: `https://crog-ai-command-center-cabin-rentals-of-georgia.vercel.app`.
- Cloud build result: PASS / READY.
- Cloud build proof: Vercel ran `next build && node scripts/sync-next-standalone-assets.mjs`, then copied static assets to `/vercel/path0/.next/standalone/.next/static` and public assets to `/vercel/path0/.next/standalone/public`.

### Custom Domain Runtime Repair

- Custom domain production route: Cloudflare tunnel -> `http://127.0.0.1:3005`.
- Runtime service: `crog-ai-frontend.service`.
- Broken artifact backup: `/tmp/fortress-command-center-next-before-2ced-runtime-20260505T222116Z`.
- New runtime artifact: clean `2cedcc16c` `.next` build copied to `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next`.
- Runtime restart: `crog-ai-frontend.service` stopped and started successfully.
- Runtime status after repair: active/running, `next-server (v16.2.4)`.
- Runtime cwd after repair: `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center` (not deleted).

### Production Static Asset Smoke

Smoke target: `https://crog-ai.com`.

- Root HTML: PASS, HTTP 200, referenced `22` `_next/static` assets.
- Representative JS asset: `/_next/static/chunks/02gvxgpfmpv-d.js` -> HTTP 200.
- Representative JS content type: `application/javascript; charset=UTF-8`.
- Representative JS content length: `5363`.
- Representative CSS asset: `/_next/static/chunks/08.6u19scv9s_.css` -> HTTP 200.
- Representative CSS content type: `text/css; charset=UTF-8`.
- Representative CSS content length: `2108`.
- Cache/Vercel headers on custom domain: Cloudflare served, `cf-cache-status: BYPASS`, `cache-control: no-store, must-revalidate`.
- Direct Vercel deployment URL result: HTTP 401 for root/static due deployment protection on generated URL; production smoke certification is based on the authorized custom domain.
- Remaining asset errors: NONE observed in static smoke.

### Production App Smoke

Authorized smoke scope: unauthenticated/read-only.

- Root route: PASS, HTTP 200, redirected/guarded to login shell as expected for no session.
- Login shell: PASS, HTTP 200, login form visible.
- Protected dashboard guard: PASS, HTTP 200 with redirect/guard to login shell; no dashboard content exposed unauthenticated.
- Protected legal guard: PASS, HTTP 200 with redirect/guard to login shell; no legal content exposed unauthenticated.
- Authenticated dashboard: NOT_RUN; no authorized production-safe credentials/session supplied.
- Authenticated legal route: NOT_RUN; no authorized production-safe credentials/session supplied.
- Readiness observed: NOT_RUN; authenticated smoke not run.
- Legal API calls: NOT_RUN; authenticated smoke not run.
- Console/page errors: PASS; only expected unauthenticated auth 401 resource errors were observed.
- Critical API failures: NONE.
- Localhost calls: NONE.
- Secret exposure: NONE.

### Final Static / Browser Security Scan

- Service-role exposure: NO.
- Known staging ref exposure: NO.
- Token patterns: NO.
- DB credential patterns: NO.
- Qdrant credential patterns: NO.
- NAS paths in browser/static output: NO.
- Browser localhost network calls: NO.
- Browser/static localhost text note: a bundled URL parser dependency still contains the literal `localhost`; no app-level localhost-only production endpoint or browser localhost request was observed.

### Rollback Readiness

- Previous Vercel deployment before final deploy: `dpl_EFmycvUU4GDgW4jz7HTPzJsggFJk` / `https://crog-ai-command-center-cwk442tdh-cabin-rentals-of-georgia.vercel.app`.
- Vercel rollback template: `npx vercel rollback <deployment-id-or-url> --yes`.
- Custom-domain artifact rollback backup: `/tmp/fortress-command-center-next-before-2ced-runtime-20260505T222116Z`.
- Rollback readiness: PASS.
- Rollback executed: NO; production smoke passed.

### Mutation Invariants

- Production DB writes: NO.
- Legal DB writes: NO.
- Qdrant writes: NO.
- NAS/evidence changes: NO, except operational audit docs in git.
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
- Production resources touched beyond Vercel deploy: Cloudflare-served local Next runtime artifact replacement and managed `crog-ai-frontend.service` restart only.

### Remaining Blockers

- Production legal data: BLOCKED.
- Production matter/user setup: BLOCKED.
- Approved filenames: BLOCKED_PENDING_OPERATOR_LEGAL_DECISIONS.
- Numeric document count: BLOCKED_PENDING_OPERATOR_LEGAL_DECISIONS.
- Legal/operator decisions: REQUIRED before legal-data production readiness can be claimed.

### Final Standing State After Static Asset Fix

- Staging UI certification: STAGING_AUTHENTICATED_UI_CERTIFIED.
- Production status: PRODUCTION_DEPLOYED_STATIC_ASSETS_SMOKE_PASSED_LEGAL_OPS_BLOCKED.
- Legal readiness: LEGAL_READINESS_NOT_READY_BY_DESIGN.
- Legal operations: LEGAL_OPS_BLOCKED_PENDING_OPERATOR_LEGAL_DECISIONS.
- Real legal data status: BLOCKED.
