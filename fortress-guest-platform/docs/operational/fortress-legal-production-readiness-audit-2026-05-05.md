# Fortress Legal Production Readiness Audit

Date: 2026-05-05
Classification: PRODUCTION_DEPLOYED_STATIC_ASSETS_SMOKE_PASSED_LEGAL_OPS_BLOCKED

## Executive Summary

Fortress Legal staging UI is certified, dependency high/critical advisories have been remediated, rollback and legal/compliance gates are documented, provider-native Supabase backup evidence is present, and production UI/backend/static asset smoke has passed for the authorized read-only scope. Legal operations remain `NOT_READY_BY_DESIGN` and production legal-data activation is blocked pending explicit operator/legal approval evidence.

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


## Fixed Production Deployment Attempt - 2026-05-05

- Build-root/script fix commit: `885002186`.
- Fix summary: `apps/command-center/package.json` now calls `node scripts/sync-next-standalone-assets.mjs`, and the script is tracked inside the app build root.
- Local proof: high-severity audit PASS, typecheck PASS, focused tests PASS, build PASS, focused lint PASS, source/static secret scan PASS.
- Cloud-build proof: Vercel build ran `next build && node scripts/sync-next-standalone-assets.mjs` and completed successfully.
- Deploy command: `FORTRESS_ALLOW_PRODUCTION_DEPLOY=1 npx vercel --prod --yes`.
- Deploy working directory: clean detached `885002186` checkout, `apps/command-center`.
- Vercel project: `crog-ai-command-center`.
- Deployment ID: `dpl_A6BbRNxgg3MnXCzBhjvA6fprTZNT`.
- Deployment URL: `https://crog-ai-command-center-j4zbkar4e-cabin-rentals-of-georgia.vercel.app`.
- Deployment result: READY.
- Production smoke result: FAILED because browser/static requests to `_next/static` returned HTTP 500 on `https://crog-ai.com`.
- Rollback command: `npx vercel rollback dpl_14JfuBDB1j14HTf2fdMdMjGUU5sE --yes`.
- Rollback result: SUCCESS; `https://crog-ai.com` resolved back to previous ready deployment `dpl_14JfuBDB1j14HTf2fdMdMjGUU5sE`.
- Post-rollback smoke: root/login/protected guards were safe, but `_next/static` HTTP 500 failures persisted.
- Legal/data mutation: NO.

## Production Deploy Authorization

- `FORTRESS_ALLOW_PRODUCTION_DEPLOY`: present for the 2026-05-05 fixed deploy attempt by operator prompt.
- Production deploy: fixed build deployed successfully to Vercel, then rolled back after smoke failure.
- Production smoke: failed because `_next/static` assets returned HTTP 500 on the production domain.

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

Fix the production static asset serving/proxy/hosting issue causing `_next/static` HTTP 500 responses on `https://crog-ai.com`, then rerun deploy and smoke under the same UI/backend-only authorization model. Do not claim legal-data readiness while legal/operator blockers remain unresolved.


## Static Asset Production Fix - 2026-05-05

- Final classification: `PRODUCTION_DEPLOYED_STATIC_ASSETS_SMOKE_PASSED_LEGAL_OPS_BLOCKED`.
- Root cause classification: `STALE_OR_BAD_DEPLOYMENT_ARTIFACT` on the custom-domain Cloudflare tunnel path.
- Evidence: `crog-ai.com` routes through Cloudflare to `http://127.0.0.1:3005`; the prior port-3005 `next-server` process was running from a deleted standalone directory and rendered chunk hashes that no longer existed on disk.
- Fix commit: `2cedcc16c` (`fix(deploy): restore production Next static asset serving`).
- Fix summary: added a static-asset smoke guard, removed client-side localhost-only WebSocket fallback from production chunks, rebuilt from a clean checkout, redeployed Vercel production, replaced the Cloudflare-served local `.next` artifact with the matching clean build, and restarted `crog-ai-frontend.service`.
- Vercel deployment ID: `dpl_9PFbhnbh51vYtz3C4L7zDcZbwVsM`.
- Vercel deployment URL: `https://crog-ai-command-center-ngsa52jch-cabin-rentals-of-georgia.vercel.app`.
- Custom-domain static smoke: PASS; root HTML HTTP 200, JS `/_next/static/chunks/02gvxgpfmpv-d.js` HTTP 200, CSS `/_next/static/chunks/08.6u19scv9s_.css` HTTP 200.
- Production app smoke: PASS for authorized unauthenticated/read-only scope; root/login loaded, dashboard/legal guarded, no critical API failures, no localhost calls, no secret exposure.
- Rollback executed: NO; smoke passed.
- Legal/data mutation: NO.

## Updated Production Standing

- Production deploy: PASS for UI/backend/static asset scope.
- Production smoke: PASS for authorized unauthenticated/read-only scope.
- Authenticated production smoke: NOT_RUN; no authorized production-safe credentials/session supplied.
- Legal readiness: `LEGAL_READINESS_NOT_READY_BY_DESIGN`.
- Legal operations: `LEGAL_OPS_BLOCKED_PENDING_OPERATOR_LEGAL_DECISIONS`.
- Real legal data status: `BLOCKED`.

## Exact Next Action After Static Asset Fix

Resolve the remaining operator/legal blockers before any full legal-data production readiness claim: production legal data remains blocked, production matter/user setup remains blocked, approved filenames and numeric document count remain pending, and legal/operator decisions are still required. Authenticated production smoke can be scheduled only with an authorized production-safe smoke account/session.

## Final Legal Data Readiness Gate - 2026-05-05

- Execution path: `PATH_B_BLOCKED_GATE_CLOSED`.
- Evidence file: `docs/operational/fortress-legal-final-legal-data-readiness-gate-2026-05-05.md`.
- Final legal-data classification: `BLOCKED_PENDING_APPROVAL_EVIDENCE`.
- Reason: production UI/backend/static smoke is passed, but existing evidence does not explicitly authorize production legal-data upload, ingest, matter/user setup, exact filenames, numeric document count, data classification, retention, operation-specific rollback/delete, audit logging, or Qdrant/NAS write scope.
- Production Supabase read-only preflight: project `hms...liap` active/healthy; auth users `0`, profiles `0`, matters `0`, storage objects `0`, `matter-documents` bucket present/private, RLS enabled on observed app tables.
- Candidate legal-data inventory: metadata-only discovery found `83` candidate files under the curated 7IL Case II NAS directory; candidates are not approved files.
- Production legal-data mutation: NO.
- User creation: NO.
- Matter creation: NO.
- Document upload: NO.
- Ingest: NO.
- Qdrant/vector writes: NO.
- NAS/evidence writes: NO, except operational git documentation.
- Final standing production status remains: `PRODUCTION_DEPLOYED_STATIC_ASSETS_SMOKE_PASSED_LEGAL_OPS_BLOCKED`.
- Production legal-data status: `BLOCKED_PENDING_APPROVAL_EVIDENCE`.

## Production Review Mode Activation - 2026-05-05

- Final classification: `PRODUCTION_REVIEW_MODE_ACTIVE`.
- Evidence file: `docs/operational/fortress-legal-production-review-mode-2026-05-05.md`.
- Execution ID: `fortress-review-20260506-011528`.
- Runtime approval timestamp: `2026-05-05T21:15:28-04:00`.
- Operator: Gary Knight.
- Production app/domain: `https://crog-ai.com`.
- Production Supabase ref: `hms...liap` partial-safe.
- Production app smoke: PASS; root/login/static assets and unauthenticated guarded shells passed.
- Intake directory: `/home/admin/Fortress-Prime/fortress-guest-platform/production-legal-review-intake`.
- Approved intake file count: `0`.
- Real legal documents uploaded: NO.
- Real legal documents ingested: NO.
- Qdrant/vector writes: NO.
- Storage writes: NO.
- Review account/workspace: CREATED/CONFIRMED for Gary review mode.
- Supabase review user/profile id: `ba06adc5-4421-448e-ad80-e0bf8caa1f29`.
- Supabase review matter id: `497dfcfc-3f55-4fd8-9f34-92bf69c5f209`.
- Backend UI-visible review case id: `26`, slug `fortress-legal-production-review`.
- Authenticated production review smoke: PASS; `/api/internal/legal/cases` returned HTTP 200 and included `fortress-legal-production-review`.
- Rollback/delete identifiers: captured in the production review-mode evidence doc.
- Legal readiness: active for review-mode shell only; not active for real legal-data upload/ingest.
- Legal operations: review-mode active with no real legal data.
- Real legal data status: `BLOCKED_UNTIL_FILES_PLACED_IN_APPROVED_INTAKE`.
- Production legal-data status: `NO_REAL_LEGAL_DATA_INGESTED`.

## Approved Intake Ingest Check - 2026-05-05

- Final classification: `REAL_LEGAL_DATA_WAITING_FOR_APPROVED_INTAKE`.
- Evidence file: `docs/operational/fortress-legal-approved-intake-ingest-2026-05-05.md`.
- Execution ID: `fortress-intake-20260506-014252`.
- Runtime UTC: `2026-05-06T01:42:52+00:00`.
- Approved intake directory: `/home/admin/Fortress-Prime/fortress-guest-platform/production-legal-review-intake`.
- Approved intake file count at run start: `0`.
- Real legal documents uploaded: NO.
- Real legal documents ingested: NO.
- Storage writes: NO.
- Qdrant/vector writes: NO.
- Production DB/legal DB writes: NO.
- Production app health smoke: PASS.
- Review user/account: PRESENT.
- Review matter: PRESENT.
- Document records: `0`.
- Storage objects in `matter-documents`: `0`.
- Final production legal-data status: `WAITING_FOR_APPROVED_INTAKE_FILES`.

## Production Operator Auth Blocker - 2026-05-05

- Continuation timestamp: `2026-05-05T23:09:12-04:00`.
- Evidence file: `docs/operational/fortress-legal-app-visibility-completion-2026-05-05.md`.
- Observed login surface: `Fortress Prime` / `Command Center` password auth gate with `Port 3001 isolated` footer.
- Gary observed error: `Invalid email or password`.
- Email attempted: `gary@cabin-rentals-of-georgia.com`.
- Root cause classification: `EXPECTED_COMMAND_CENTER_AUTH_GATE` plus `OPERATOR_PASSWORD_RESET_REQUIRED`.
- Fortress Legal route: `/legal`.
- Review matter route: `/legal/cases/fortress-legal-production-review`.
- Staff auth backend: Fortress Prime sovereign Postgres `staff_users` through the Command Center BFF and FastAPI auth.
- Production Supabase ref remains recorded as `hms...liap`, but the observed Command Center staff login is not Supabase Auth.
- Gary staff user: EXISTS, active, `super_admin`, bcrypt password hash present.
- Gary staff user id: `2bf81aa6-35b8-4fb6-89e4-70a4051b05f1`.
- Password reset/invite action: NOT_PERFORMED; existing-user invite is not supported and no non-printed operator reset secret was available in this session.
- Review matter: PRESENT, id `26`, slug `fortress-legal-production-review`.
- Document metadata rows: `80`.
- Completed documents: `78`.
- Locked privileged documents: `2`.
- Public legal cases API exposure check: PASS, unauthenticated request returned HTTP 401.
- Public confidential content exposure: NOT_OBSERVED.
- Production deploy: NO.
- Production auth/data mutation: NO.

Final classification for this continuation:

- `PRODUCTION_OPERATOR_AUTH_BLOCKER_PRECISE_APP_VISIBILITY_PENDING`

Updated standing state:

- Production status: `PRODUCTION_AUTONOMOUS_INTAKE_BACKEND_COMPLETE`
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`
- Legal operations status: `LEGAL_OPS_BACKEND_INTAKE_COMPLETE_APP_VISIBILITY_PENDING`
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_INGESTED_WITH_PRIVILEGED_LOCKS`
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_COMPLETE_APP_VISIBILITY_UNVERIFIED`
- Pilot status: `BLOCKED_BY_PRODUCTION_OPERATOR_AUTH`

Exact next action:

- Complete a normal staff password reset for Gary without printing the password or reset link, then have Gary log into `https://crog-ai.com` and verify `/legal` plus the `fortress-legal-production-review` document metadata in the production UI.

## Gary-Only Staff Password Reset Command - 2026-05-05

- Continuation timestamp: `2026-05-05T23:13:05-04:00`.
- Reset capability classification: `SAFE_LOCAL_RESET_SCRIPT_ADDED_OPERATOR_INPUT_REQUIRED`.
- Script added: `backend/scripts/admin_reset_gary_staff_password.py`.
- Target email: `gary@cabin-rentals-of-georgia.com`.
- Target staff user id: `2bf81aa6-35b8-4fb6-89e4-70a4051b05f1`.
- Target role: `super_admin`.
- Required authorization flag: `FORTRESS_ALLOW_STAFF_PASSWORD_RESET=1`.
- Password input method: hidden interactive prompt.
- Hashing implementation: app `hash_password()` helper using the same bcrypt path as login verification.
- User creation capability: NO.
- Duplicate Gary user creation: NO.
- Session revocation support: NO; no token-version/session-revocation column or staff session table was found in the current auth schema.
- Reset executed in this Codex chat: NO.
- Reason reset was not executed: this chat cannot safely supply a hidden operator password to the TTY without exposing it through assistant/tool input.
- Production deploy: NO; script is local operator tooling, not runtime app code.
- Legal data mutation: NO.
- Document/Qdrant/ingest mutation: NO.

Focused verification:

- Python compile: PASS.
- Help output check: PASS.
- Non-Gary email refusal: PASS.
- Missing authorization flag refusal: PASS.
- Static output scan: PASS; no plaintext password/hash output path found.

Updated standing state:

- Production status: `PRODUCTION_AUTONOMOUS_INTAKE_BACKEND_COMPLETE`
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`
- Legal operations status: `LEGAL_OPS_BACKEND_INTAKE_COMPLETE_APP_VISIBILITY_PENDING`
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_INGESTED_WITH_PRIVILEGED_LOCKS`
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_COMPLETE_APP_VISIBILITY_UNVERIFIED`
- Pilot status: `BLOCKED_BY_PRODUCTION_OPERATOR_PASSWORD_RESET`

Exact next action:

- Run the Gary-only reset command from a real production operator terminal so the new password can be entered at the hidden prompt, then verify Gary login and Fortress Legal UI visibility.

## Production Staff Login Diagnosis Without Reset - 2026-05-05

- Continuation timestamp: `2026-05-05T23:20:41-04:00`.
- Current operator instruction: diagnose Gary's known valid `crog-ai.com` login without resetting the password.
- Password reset: NOT_PERFORMED.
- Password/token/cookie/hash/DB URL output: NO.

Login path diagnosis:

- Login screen route: `/login`.
- Login form endpoint: same-origin `/api/auth/login`.
- Command Center BFF route: `apps/command-center/src/app/api/auth/login/route.ts`.
- Direct backend route: FastAPI `/api/auth/login`.
- Staff model/table: `backend.models.staff.StaffUser` / `public.staff_users`.
- Email normalization: lower-case email lookup.
- Password field: `password_hash`.
- Password verifier: `backend.core.security.verify_password()`.
- Expected hash family: bcrypt.
- Session creation: RS256 JWT returned by FastAPI and stored by BFF in `fortress_session`.
- Generic failed login response: `Invalid email or password`.

Read-only production auth checks:

- Gary exact email lookup: FOUND.
- Gary normalized email lookup: FOUND.
- Gary active: YES.
- Gary role: `super_admin`.
- Gary password hash field: PRESENT, not printed.
- Gary hash family: bcrypt-compatible.
- Lockout/failed-login columns: NOT_PRESENT.
- Login endpoint and DB check point to the same model/table: YES.

Classification:

- `LOGIN_ENDPOINT_EXPECTED`.
- `UNKNOWN_LOGIN_FAILURE_PENDING_PASSWORD_MATCH_VERIFY`.

Verify-only tooling:

- Added `backend/scripts/verify_gary_staff_password.py`.
- Required flag: `FORTRESS_ALLOW_STAFF_PASSWORD_VERIFY=1`.
- Scope: Gary-only, read-only.
- Input: hidden no-echo prompt.
- Output: safe metadata only; no password/hash/token/session data.
- Uses exact production `verify_password()` helper.
- Writes/sessions: NO.

Focused verification:

- Python compile: PASS.
- Help output: PASS.
- Non-Gary email refusal: PASS.
- Missing authorization flag refusal: PASS.
- Static output scan: PASS.

Password match verification:

- NOT_RUN_IN_CODEX_CHAT because Gary must enter the password manually in a real hidden terminal prompt.

Updated standing state:

- Production status: `PRODUCTION_AUTONOMOUS_INTAKE_BACKEND_COMPLETE`
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`
- Legal operations status: `LEGAL_OPS_BACKEND_INTAKE_COMPLETE_APP_VISIBILITY_PENDING`
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_INGESTED_WITH_PRIVILEGED_LOCKS`
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_COMPLETE_APP_VISIBILITY_UNVERIFIED`
- Pilot status: `BLOCKED_BY_PRODUCTION_OPERATOR_PASSWORD_VERIFY`

Exact next action:

- Run the verify-only script from a real production operator terminal. If `PASSWORD_MATCH yes`, continue diagnosing BFF gateway/direct-backend/session-cookie behavior. If `PASSWORD_MATCH no`, stop and require Gary's explicit decision before reset or backend switch.

## Production Login Path Repair After Password Match - 2026-05-05

- Continuation timestamp: `2026-05-05T23:40:46-04:00`.
- Operator password verification result: `PASSWORD_MATCH yes`.
- Gary user found/active/role: `yes` / `yes` / `super_admin`.
- Password reset: NOT_PERFORMED.
- Password/hash/token/cookie/DB URL output: NO.

Runtime findings:

- `https://crog-ai.com` is served through Cloudflare tunnel to local Next.js on port `3005`.
- Vercel project `crog-ai-command-center` exists and deploys, but generated deployment URLs are protected by Vercel Authentication and are not the direct public `crog-ai.com` runtime path.
- Vercel production env key observed: `FORTRESS_BACKEND_BASE_URL`, value redacted.
- Previous BFF backend helper read `FGP_BACKEND_URL` only and defaulted to local loopback when absent.
- Custom-domain Next process before restart was `crog-ai-frontend.service`, PID `1616627`, cwd in a deleted standalone directory.
- FastAPI auth process serving port `8000` remains the direct backend for `/api/auth/login`.

Root cause classification:

- `LOGIN_BFF_USES_WRONG_ENV_VAR` for the Vercel runtime path.
- `STALE_PRODUCTION_BUILD_OR_OLD_BFF` for the custom-domain runtime path.
- `PASSWORD_MATCH_CONFIRMED_LOGIN_RECHECK_PENDING` remains because Gary has not yet completed the post-restart login check in this session.

Fix and deploy/restart:

- Code fix committed: BFF backend URL helper now uses `FGP_BACKEND_URL` first and `FORTRESS_BACKEND_BASE_URL` as production fallback.
- BFF unreachable hint now documents both env var names.
- Vercel deployment: READY, id `dpl_4FjyAoySS7ea33dYj5QjZAH7Uk41`, URL `https://crog-ai-command-center-jy6uh35h2-cabin-rentals-of-georgia.vercel.app`.
- Custom-domain runtime restart: `crog-ai-frontend.service` restarted successfully.
- Runtime status after restart: active/running, PID `3236455`, cwd `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center`.

Checks:

- Targeted backend URL unit test: PASS.
- Focused lint: PASS.
- Command Center build: PASS.
- `git diff --check`: PASS.
- Static asset smoke on `https://crog-ai.com`: PASS.
- Login shell on `https://crog-ai.com/login`: PASS.
- Unauthenticated legal review route: guarded; no confidential document contents exposed.
- Invalid-password probe: HTTP 401 `Invalid email or password`, expected.

Authenticated visibility:

- Gary login after restart: PENDING_OPERATOR_RECHECK.
- Review matter visible: PENDING_AUTHENTICATED_UI.
- Document metadata visible: PENDING_AUTHENTICATED_UI.
- Locked privileged handling: PENDING_AUTHENTICATED_UI.

Mutation invariants:

- Password reset: NO.
- New user/profile/account: NO.
- Document rows/storage/Qdrant/ingest writes: NO.
- Schema/RLS/policy changes: NO.
- Secret or document-content exposure: NO.
- Production deploy/restart: YES, Command Center UI/BFF only.

Updated standing state:

- Production status: `PRODUCTION_AUTONOMOUS_INTAKE_BACKEND_COMPLETE`
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`
- Legal operations status: `LEGAL_OPS_BACKEND_INTAKE_COMPLETE_APP_VISIBILITY_PENDING`
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_INGESTED_WITH_PRIVILEGED_LOCKS`
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_COMPLETE_APP_VISIBILITY_UNVERIFIED`
- Pilot status: `BLOCKED_BY_GARY_MANUAL_LOGIN_RECHECK_AFTER_BFF_RESTART`

## Autonomous Intake Document Metadata Linkage Repair - 2026-05-06

- Continuation timestamp: `2026-05-06T00:01:33-04:00`.
- Gary authenticated observation before repair: login succeeded, Legal Command Center loaded, Fortress Legal Production Review was visible, and `/legal/cases/fortress-legal-production-review` opened.
- Observed blocker: the detail page still displayed the old synthetic review shell and message `Synthetic review shell only. No real legal documents uploaded or ingested.`
- Synthetic execution id displayed: `fortress-review-20260506-011528`.
- Expected autonomous intake execution id: `fortress-autointake-20260506-015341`.
- Root cause classification: `FRONTEND_DOCUMENT_TAB_NOT_CONNECTED`, `DOCUMENTS_WRITTEN_TO_VAULT_TABLE_NOT_UI_DOCUMENT_TABLE`, and `DOCUMENT_API_QUERIES_WRONG_DATABASE`.
- UI detail data source before fix: case detail/case notes/correspondence routes, with no autonomous vault-document hook in the Document tab.
- Autonomous intake data source: `legal.vault_documents` in the legacy legal database and production mirror.
- Case ID mapping: UI-visible legacy case id `26`; production mirror case id `13`; shared slug `fortress-legal-production-review`.
- Read-only counts: `fortress_db` vault rows `80`, `completed=78`, `locked_privileged=2`; `fortress_prod` vault rows `80`, `completed=78`, `locked_privileged=2`; runtime `fortress_shadow` vault rows `0`.
- Fix commit: `bcb54ba57` (`fix(legal): connect autonomous intake documents to review workspace`).
- Runtime-main cherry-pick: `f07bc9526`.
- Fix summary: the Document tab now consumes `/api/internal/legal/cases/{slug}/vault/documents`; the backend list route now reads from the legacy legal source used by the visible case detail; the response and UI remain metadata-only.
- Locked privileged handling: `locked_privileged` rows are included in the metadata list and displayed as locked/restricted; content, NAS paths, file hashes, and vector IDs are not returned.
- Production deploy/restart: `fortress-backend.service` and `crog-ai-frontend.service` restarted successfully; Vercel deploy not performed because the production custom domain is served by the local Cloudflare tunnel/runtime path.
- Verification: frontend metadata rendering test PASS; backend vault-document route test PASS; typecheck PASS; targeted ESLint PASS; production build PASS; `git diff --check` PASS; focused secret scan PASS.
- Full command-center lint: FAILS on pre-existing unrelated files outside this repair scope; unrelated dirty files were not touched.
- Production smoke: root HTTP 200; representative `_next/static` asset HTTP 200; unauthenticated legal vault-documents API HTTP 401.
- Runtime backend route direct metadata check: `total=80`, `completed=78`, `locked_privileged=2`, restricted fields exposed `NO`.
- Authenticated Gary browser refresh after repair: PENDING_OPERATOR_CONFIRMATION.
- Document metadata visibility in Gary's browser: PENDING_OPERATOR_CONFIRMATION.
- Public exposure check: unauthenticated API remained guarded; no document contents exposed.
- Legal/data mutation: NO.
- New document rows: NO.
- New storage writes: NO.
- New Qdrant writes: NO.
- New ingest: NO.
- Metadata linkage writes: NO.
- Schema/RLS/policy changes: NO.
- Secrets or document contents printed: NO.

Updated standing state:

- Production status: `PRODUCTION_OPERATOR_AUTH_REPAIRED_MATTER_VISIBLE`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_DOCUMENT_METADATA_VISIBILITY_PENDING_OPERATOR_CONFIRMATION`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_INGESTED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `AUTONOMOUS_INTAKE_BACKEND_COMPLETE_UI_DOCUMENTS_DEPLOYED_PENDING_OPERATOR_CONFIRMATION`.
- Pilot status: `BLOCKED_BY_AUTHENTICATED_DOCUMENT_METADATA_UI_CONFIRMATION_PENDING`.

Exact next action:

- Gary/operator must refresh or reopen `/legal/cases/fortress-legal-production-review` in an authenticated production browser session and confirm that the Document tab shows 80 metadata rows or UI-equivalent count with 78 completed and 2 locked/restricted privileged rows.

## Final Authenticated Document Metadata Visibility Confirmation - 2026-05-06

- Confirmation timestamp: `2026-05-06T00:08:07-04:00`.
- Confirmation source: Gary/operator authenticated browser observation in the production UI.
- Production domain: `https://crog-ai.com`.
- Route checked: `/legal/cases/fortress-legal-production-review`.
- Matter checked: `Fortress Legal Production Review`.
- Login result: SUCCESS.
- Review matter visible: YES.
- Document/Vault metadata view visible: YES.
- Document metadata list visible: YES.
- UI document count: `80`.
- UI completed count: `78`.
- UI locked count: `2`.
- Locked/restricted handling: `locked_privileged` documents remain restricted and display metadata only.
- Locked/restricted contents exposed: NO.
- Confidential document contents pasted into evidence: NO.
- Public/unauthenticated exposure observed: NO.

Backend evidence aligned with UI:

- Execution ID: `fortress-autointake-20260506-015341`.
- PDFs selected/ingested: `80`.
- Completed: `78`.
- Locked privileged: `2`.
- Qdrant/vector points: `3,785`.
- Document UI repair commit: `bcb54ba57`.
- Document visibility evidence commit before final confirmation: `209167f95`.
- Runtime-main backend cherry-pick: `f07bc9526`.
- Auth/BFF repair commits: `ca7db58d4`, `9437e618a`.

Mutation invariants:

- New document upload: NO.
- New ingest: NO.
- New document rows: NO.
- Duplicate document rows: NO.
- New Qdrant writes: NO.
- Duplicate vectors: NO.
- Password reset: NO.
- Production data mutation: NO.
- Schema changes: NO.
- RLS/policy changes: NO.
- Production deploy: NO.
- Secrets printed/exposed: NO.
- Document contents printed/exposed: NO.
- Unrelated dirty files touched: NO.

Governance note:

- `PILOT_READY_FOR_GARY_REVIEW` means the autonomous intake pilot is app-visible and ready for Gary review. It does not remove broader counsel/legal-governance review requirements or authorize unrestricted production legal operations beyond this approved review scope.

Final standing state:

- Production status: `PRODUCTION_AUTONOMOUS_INTAKE_APP_VISIBLE`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_AI_ASSISTED_DOCUMENT_REVIEW`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_INGESTED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_COMPLETE_APP_VISIBLE`.
- Pilot status: `PILOT_READY_FOR_GARY_REVIEW`.

## Litigation Intelligence Review Layer - 2026-05-06

- Evidence file: `docs/operational/fortress-legal-litigation-intelligence-phase-2026-05-06.md`.
- Execution ID: `fortress-intel-20260506-041839`.
- Authorization timestamp: `2026-05-06T00:12:57-04:00`.
- Matter slug: `fortress-legal-production-review`.
- Baseline document count: `80`.
- Analysis eligible documents: `78`.
- Locked/restricted documents preserved metadata-only: `2`.
- Text extracted from non-locked documents: `78`.
- Derived graph nodes: `448`.
- Derived graph edges: `1,227`.
- Draft chronology events: `180`.
- Contradiction/tension candidates: `14`.
- Review queue items: `20`.
- Entity mentions counted: `11,252`.
- Rollback manifest: `/mnt/fortress_nas/audits/fortress-intel-20260506-041839.json`.
- Code commit: `65752cf43` (`feat(legal): add litigation intelligence review layer`).
- Runtime-main cherry-pick: `5e39ca165`.
- Production restart: `fortress-backend.service` restarted and active.
- Frontend deploy/restart: NOT_REQUIRED.
- Public exposure check: unauthenticated document, graph, chronology, and sanctions endpoints returned HTTP 401.
- Locked-content-derived edges: `0`.
- New raw documents/uploads/ingest/vector writes: NO.
- Schema/RLS/policy changes: NO.
- Authenticated Gary UI confirmation of populated intelligence panels: PENDING_OPERATOR_CONFIRMATION.

Updated standing state:

- Production status: `PRODUCTION_INTELLIGENCE_EXTRACTION_COMPLETE_UI_PENDING`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_AI_ASSISTED_LITIGATION_REVIEW`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_ANALYZED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_ANALYZED_UI_CONFIRMATION_PENDING`.
- Product status: `LITIGATION_INTELLIGENCE_BACKEND_READY_UI_PENDING`.
- Counsel status: `COUNSEL_REVIEW_REQUIRED`.

## Final Litigation Intelligence UI Visibility Confirmation - 2026-05-06

- Confirmation timestamp: `2026-05-06T07:20:07-04:00`.
- Confirmation source: Gary/operator authenticated production UI observation.
- Production route checked: `https://crog-ai.com/legal/cases/fortress-legal-production-review`.
- Matter checked: `Fortress Legal Production Review`.
- Draft posture banner: `DRAFT / COUNSEL REVIEW REQUIRED` visible.
- Panopticon / Deliberation / Vanguard / Graph Radar panels visible: YES.
- UI observed: `448 Entities Mapped`.
- UI observed: `14 Contradiction Edges`.
- UI observed: `Graph Synced: 448 Entities`.
- UI observed: `Master Chronology: 180 events`.
- UI observed: `Entity Graph Pressure Map: 448 Entities, 1227 Edges`.
- Timeline/Master Chronology populated: YES.
- Entity Graph / Graph Radar / Panopticon populated: YES.
- Contradiction candidates/edges visible: YES.
- Counsel-review posture preserved: YES.

Backend/product evidence aligned with UI:

- Intelligence execution ID: `fortress-intel-20260506-041839`.
- Documents analyzed: `78`.
- Locked/restricted preserved: `2`.
- Timeline events: `180`.
- Normalized entities: `140`.
- Entity mentions: `11,252`.
- Graph nodes: `448`.
- Graph edges: `1,227`.
- Contradiction candidates: `14`.
- Review queue items: `20`.
- Qdrant/vector points unchanged: `3,785`.
- Product code commit: `65752cf43`.
- Product evidence commit: `609d4c504`.
- Runtime-main cherry-pick: `5e39ca165`.
- Document metadata visibility evidence commit: `52dc750a85eec60d2ddf168767aa2b0ce75f1e26`.

Document/Vault baseline retained:

- Documents: `80`.
- Completed: `78`.
- Locked/restricted: `2`.
- Locked/restricted handling: metadata-only; restrictions preserved.

Confirmation-step mutation invariants:

- Intake rerun: NO.
- Litigation-intelligence extraction rerun: NO.
- New document upload: NO.
- New document rows: NO.
- Duplicate derived intelligence rows: NO.
- New Qdrant/vector points: NO.
- Schema changes: NO.
- RLS/policy changes: NO.
- Privilege changes: NO.
- Production deploy: NO.
- Secrets printed/exposed: NO.
- Confidential document contents printed/exposed: NO.
- Unrelated dirty files touched: NO.

Final standing state:

- Production status: `PRODUCTION_LITIGATION_INTELLIGENCE_ACTIVE`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_AI_ASSISTED_LITIGATION_REVIEW`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_ANALYZED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_AND_INTELLIGENCE_COMPLETE`.
- Product status: `LITIGATION_INTELLIGENCE_READY_FOR_GARY_REVIEW`.
- Counsel status: `COUNSEL_REVIEW_REQUIRED`.

Governance note: this confirms the AI-assisted litigation-intelligence review layer is production-visible and ready for Gary/operator review. It does not remove counsel-review requirements, does not convert AI outputs into final legal conclusions, and does not authorize unrestricted production legal operations beyond this approved review scope.

## Counsel Review Workbench Deployment - 2026-05-06

- Evidence file: `docs/operational/fortress-legal-counsel-review-workbench-2026-05-06.md`.
- Workbench execution ID: `fortress-counsel-review-20260506-073330`.
- Source intelligence execution ID: `fortress-intel-20260506-041839`.
- Matter slug: `fortress-legal-production-review`.
- Baseline documents: `80`.
- Completed/analyzed: `78`.
- Locked/restricted: `2`, metadata-only.
- Timeline events: `180`.
- Graph nodes: `448`.
- Graph edges: `1,227`.
- Contradiction candidates: `14`.
- Qdrant/vector points: `3,785`, unchanged.
- Issue matrix records: `20`.
- Evidence binder records: `17`.
- Chronology review packet: COMPLETE.
- Contradiction triage records: `14`.
- Entity dossier records: `40`.
- Counsel questions/actions: `24`.
- Consolidated review queue items: `18`.
- Workbench manifest: `/mnt/fortress_nas/audits/fortress-counsel-review-20260506-073330.json`.
- Code commit: `920a9a7c2`.
- Runtime-main cherry-pick: `1db1f1201`.
- Production restart: `fortress-backend.service` and `crog-ai-frontend.service` restarted and active.
- Public exposure check: unauthenticated workbench API returned HTTP `401`.
- Production root smoke: HTTP `200`.
- Production matter-route smoke: HTTP `200`.
- Authenticated Gary UI confirmation: PENDING.

Mutation invariants:

- New raw document upload: NO.
- New ingest: NO.
- New document rows: NO.
- New Qdrant document vectors: NO.
- Duplicate derived intelligence rows: NO.
- New workbench derived records: YES, file-backed manifest only.
- Schema changes: NO.
- RLS/policy changes: NO.
- Privilege changes: NO.
- Secrets printed/exposed: NO.
- Document contents printed/exposed in evidence: NO.
- Locked/restricted content analyzed: NO.
- Unrelated dirty files touched: NO.

Updated standing state:

- Production status: `PRODUCTION_COUNSEL_WORKBENCH_BACKEND_COMPLETE_UI_PENDING`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_COUNSEL_REVIEW_WORKBENCH`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_ANALYZED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_INTELLIGENCE_AND_WORKBENCH_DEPLOYED_PENDING_UI_CONFIRMATION`.
- Product status: `COUNSEL_WORKBENCH_BACKEND_READY_UI_PENDING`.
- Counsel status: `COUNSEL_REVIEW_REQUIRED`.

## Counsel Workbench UI Mapping Repair - 2026-05-06

- Prior authenticated UI observation: Document/Vault and litigation-intelligence panels visible; Counsel Review Workbench sections not visible.
- Root cause classification: `COUNSEL_WORKBENCH_COMPONENT_EXISTS_NAV_HIDDEN`.
- Workbench manifest: `/mnt/fortress_nas/audits/fortress-counsel-review-20260506-073330.json`.
- Fix commit: `232055866` (`fix(legal): surface counsel review workbench in matter UI`).
- Fix applied: first-class default `Workbench` tab added to the matter UI.
- Fix applied: required workbench section labels exposed for Issue Matrix, Evidence Binders, Contradiction Triage, Entity Dossier, Theory / Counter-Theory, Counsel Questions / Actions, and Review Queue.
- Workbench regeneration: NOT_PERFORMED.
- Backend API change: NOT_REQUIRED.
- Frontend restart: `crog-ai-frontend.service` restarted and active.
- Production root smoke: HTTP `200`.
- Production matter-route smoke: HTTP `200`.
- Public exposure check: unauthenticated workbench API returned HTTP `401`.
- Authenticated Gary/operator post-repair UI confirmation: PENDING.

Mutation invariants:

- New raw document upload: NO.
- New ingest: NO.
- New document rows: NO.
- New Qdrant document vectors: NO.
- Duplicate derived records: NO.
- Schema changes: NO.
- RLS/policy changes: NO.
- Privilege changes: NO.
- Secrets printed/exposed: NO.
- Document contents printed/exposed in evidence: NO.
- Locked/restricted content exposed: NO.
- Unrelated dirty files touched: NO.

Updated standing state:

- Production status: `PRODUCTION_COUNSEL_WORKBENCH_UI_MAPPING_DEPLOYED_PENDING_OPERATOR_CONFIRMATION`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_COUNSEL_REVIEW_WORKBENCH`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_ANALYZED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_INTELLIGENCE_AND_WORKBENCH_DEPLOYED_PENDING_UI_CONFIRMATION`.
- Product status: `COUNSEL_WORKBENCH_UI_MAPPING_DEPLOYED_PENDING_OPERATOR_CONFIRMATION`.
- Counsel status: `COUNSEL_REVIEW_REQUIRED`.

## Final Counsel Review Workbench Visibility Confirmation - 2026-05-06

- Confirmation timestamp: `2026-05-06T07:59:57-04:00`.
- Confirmation source: Gary/operator authenticated production UI observation.
- Route checked: `https://crog-ai.com/legal/cases/fortress-legal-production-review`.
- Default Workbench tab/section visible: YES.
- Issue Matrix visible/reviewable: YES.
- Evidence Binders visible/reviewable: YES.
- Contradiction Triage visible/reviewable: YES.
- Entity Dossier visible/reviewable: YES.
- Theory / Counter-Theory visible/reviewable: YES.
- Counsel Questions / Actions visible/reviewable: YES.
- Review Queue visible/reviewable: YES.
- `DRAFT / COUNSEL REVIEW REQUIRED` posture preserved: YES.
- Existing Document/Vault, Master Chronology, Panopticon, Deliberation, Vanguard, and Graph Radar panels remain available: YES.
- Locked/restricted documents remain metadata-only: YES.
- Public confidential-content exposure observed: NO.

Final confirmation-step mutation invariants:

- Workbench records regenerated: NO.
- New raw document upload: NO.
- New ingest: NO.
- New document rows: NO.
- New Qdrant document vectors: NO.
- Duplicate derived records: NO.
- Schema changes: NO.
- RLS/policy changes: NO.
- Privilege changes: NO.
- Production deploy/restart: NO.
- Secrets printed/exposed: NO.
- Document contents printed/exposed in evidence: NO.
- Unrelated dirty files touched: NO.

Final standing state:

- Production status: `PRODUCTION_COUNSEL_REVIEW_WORKBENCH_ACTIVE`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_COUNSEL_REVIEW_WORKBENCH`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_ANALYZED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_INTELLIGENCE_AND_WORKBENCH_COMPLETE`.
- Product status: `COUNSEL_REVIEW_WORKBENCH_READY_FOR_GARY_AND_COUNSEL`.
- Counsel status: `COUNSEL_REVIEW_REQUIRED`.

## Counsel Validation Workflow - 2026-05-06

- Evidence timestamp: `2026-05-06T08:17:45-04:00`.
- Validation execution ID: `fortress-validation-20260506-081435`.
- Validation manifest: `/mnt/fortress_nas/audits/fortress-validation-20260506-081435.json`.
- Source workbench execution ID: `fortress-counsel-review-20260506-073330`.
- Baseline reconciled:
  - Documents: `80`.
  - Completed/analyzed: `78`.
  - Locked/restricted: `2`.
  - Issues: `20`.
  - Evidence binders: `17`.
  - Contradiction candidates: `14`.
  - Entity dossier: `40`.
  - Counsel questions/actions: `24`.
- Validation workflow records created: `299`.
- Locked metadata-only validation records: `2`.
- Validation store: file-backed manifest; no schema/RLS/policy change.
- UI/API change: deployed protected counsel validation API and default matter-page Validation tab.
- Controls exposed in deployed UI bundle: accept, reject, correct, needs source check, needs counsel review, note, reopen, audit/history.
- Final legal conclusion/signoff state set: NO.
- Production root smoke: HTTP `200`.
- Production matter-route smoke: HTTP `200`.
- Unauthenticated validation API: HTTP `401`.
- Runtime-main cherry-pick: `5ad1ac35a`.
- Backend restart: `fortress-backend.service` restarted and active.
- Frontend restart: `crog-ai-frontend.service` restarted and active.
- Authenticated Gary/operator UI confirmation: PENDING.

Mutation invariants:

- New raw document upload: NO.
- New ingest: NO.
- New document rows: NO.
- New Qdrant document vectors: NO.
- Duplicate workbench records: NO.
- New validation records: YES, file-backed validation manifest only.
- Schema changes: NO.
- RLS/policy changes: NO.
- Privilege changes: NO.
- Secrets printed/exposed: NO.
- Document contents printed/exposed in evidence: NO.
- Locked/restricted content analyzed or exposed: NO.
- Unrelated dirty files touched: NO.

Current standing state:

- Production status: `PRODUCTION_COUNSEL_VALIDATION_BACKEND_COMPLETE_UI_PENDING`.
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_COUNSEL_VALIDATION_WORKFLOW`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_ANALYZED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_INTELLIGENCE_WORKBENCH_AND_VALIDATION_COMPLETE`.
- Product status: `COUNSEL_VALIDATION_BACKEND_READY_UI_PENDING`.
- Counsel status: `COUNSEL_REVIEW_REQUIRED`.
