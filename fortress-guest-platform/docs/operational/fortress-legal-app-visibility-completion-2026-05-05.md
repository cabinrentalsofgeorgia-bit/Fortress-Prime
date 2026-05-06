# Fortress Legal App Visibility Completion Evidence

Date: 2026-05-05
Continuation timestamp: 2026-05-06T00:08:07-04:00

## Current Classification

Final classification: `PILOT_READY_FOR_GARY_REVIEW`

Gary Knight can log into the production Command Center, open the Fortress Legal Production Review matter, and view the autonomous intake document metadata. The authenticated production UI shows `Documents: 80`, `Completed: 78`, and `Locked: 2`, with locked/restricted rows remaining metadata-only.

## Observed Login Surface

- Production domain: `https://crog-ai.com`
- Observed screen: `Fortress Prime` / `Command Center`
- Screen text: secure staff access for Command Center, System Health, Crog VRS, and Fortress Legal
- Footer text: `Port 3001 isolated` / `Internal use only`
- Login result observed by Gary: `Invalid email or password`
- Email attempted: `gary@cabin-rentals-of-georgia.com`

Classification:

- `EXPECTED_COMMAND_CENTER_AUTH_GATE`
- `OPERATOR_PASSWORD_RESET_REQUIRED`

The observed screen matches the live Command Center app source and production shell. It is not, by itself, evidence of a stale deployment or wrong route.

## Release State

- Recovered release worktree used: `/home/admin/Fortress-Prime`
- Branch: `safety/foundation-audit-snapshot`
- HEAD: `80ca7a2a4090973ac6cde7fd0f8e8c8ec28010af`
- Remote: `origin git@github.com:cabinrentalsofgeorgia-bit/Fortress-Prime.git`
- Evidence commits present in this repo: `28e0bcd`, `b247f76`, `0a8a0f4`, `cd0e91e9`
- Unrelated dirty files were observed in the broader worktree and were not touched.

## App/Auth Surface

- Root/login surface: Command Center password auth gate.
- Fortress Legal route: `/legal`
- Review matter route: `/legal/cases/fortress-legal-production-review`
- Document metadata route/API: `/api/internal/legal/cases/fortress-legal-production-review/vault/documents`
- Command Center login gates Fortress modules through the `fortress_session` app session.
- Staff auth backend: Fortress Prime sovereign Postgres `staff_users` via FastAPI auth, proxied by the Next.js Command Center BFF.
- Production legal data backend used by the Command Center: `fortress_db` legal schema through backend legal APIs.
- Production Supabase ref `hmswfyohuzjzemryliap` remains the recorded production Supabase/legal-data baseline, but the observed Command Center staff login is not Supabase Auth.

## Production App Health Check

Read-only production checks:

- Root route: HTTP 200
- Login route: HTTP 200
- Legal route unauthenticated shell: HTTP 200 client guard shell
- Unauthenticated legal cases API: HTTP 401
- Public legal metadata exposure: NOT_OBSERVED
- Public confidential content exposure: NOT_OBSERVED
- Localhost/static secret scan of fetched shells: PASS for checked indicators
- Static assets: production shell referenced `_next/static` assets; representative root/login/legal shells loaded successfully

No cookies, tokens, auth headers, DB URLs, service role keys, secrets, or document contents were printed.

## Production Auth/Account Preflight

Read-only production account check:

- Gary staff user exists: YES
- Gary email: `gary@cabin-rentals-of-georgia.com`
- Gary staff user id: `2bf81aa6-35b8-4fb6-89e4-70a4051b05f1`
- Gary role: `super_admin`
- Gary active: YES
- Gary password hash present and bcrypt-compatible: YES
- Last login recorded: YES

Result:

- `OPERATOR_ACCOUNT_PROVISIONED`
- `OPERATOR_PASSWORD_RESET_REQUIRED`

No duplicate user was created.

## Review Data Preflight

Read-only production legal data check:

- Review matter/case exists: YES
- Review case id: `26`
- Review case slug: `fortress-legal-production-review`
- Review case name: `Fortress Legal Production Review`
- Document metadata rows linked to review matter: `80`
- Completed documents: `78`
- Locked privileged documents: `2`

No document contents were printed.

## Repair Attempt Result

No credential repair was performed in this continuation because:

- Gary's existing user account is active and privileged.
- The supported invite flow cannot create or resend an invite for an existing user.
- The supported password-reset path requires a new password from an authenticated super-admin/operator or an operator-provided `FGP_STAFF_PASSWORD_RESET` secret.
- No operator reset secret was present in this session.
- Generating or printing a password/reset link would violate the no-secret/no-password handling rules.

No production data, schema, RLS policy, document rows, Qdrant vectors, uploads, ingestion, or deployment were changed.

## Authenticated UI Verification

Not completed in this continuation.

Blocked item:

- Gary must complete normal production login after the staff password is reset or confirmed out-of-band.

Checks still pending after successful login:

- Dashboard/Command Center loads.
- Fortress Legal workspace is reachable at `/legal`.
- `Fortress Legal Production Review` is visible.
- 80 document metadata rows or UI-equivalent count are visible.
- 78 completed documents are visible if exposed.
- 2 locked privileged documents are visible only as locked/restricted metadata if exposed.
- No privileged/confidential contents are exposed publicly.
- No blocking UI/API errors prevent review.

## Mutation Invariants

- New auth user: NO
- New profile/account: NO
- New matter relationship: NO
- New document rows: NO
- New storage writes: NO
- New Qdrant writes: NO
- New ingest: NO
- Schema changes: NO
- RLS/policy changes: NO
- Production deploy: NO
- Unauthorized resources touched: NO

## Final Standing State

- Production status: `PRODUCTION_AUTONOMOUS_INTAKE_BACKEND_COMPLETE`
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`
- Legal operations status: `LEGAL_OPS_BACKEND_INTAKE_COMPLETE_APP_VISIBILITY_PENDING`
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_INGESTED_WITH_PRIVILEGED_LOCKS`
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_COMPLETE_APP_VISIBILITY_UNVERIFIED`
- Pilot status: `BLOCKED_BY_PRODUCTION_OPERATOR_AUTH`

## Exact Next Action

Use the normal Command Center staff password-reset path with a non-printed password/secret for `gary@cabin-rentals-of-georgia.com`, then have Gary log into `https://crog-ai.com` and verify the Fortress Legal review workspace/document metadata in the production UI.

## Staff Login Path Diagnosis

Timestamp: 2026-05-05T23:20:41-04:00

Runtime approval source:

- Current operator instruction to diagnose Gary's known valid `crog-ai.com` credentials without resetting the password.

Login path:

- Frontend route: `/login`
- Form submit endpoint: same-origin `/api/auth/login`
- BFF route: `apps/command-center/src/app/api/auth/login/route.ts`
- BFF behavior: tries configured gateway SSO first, then direct FGP FastAPI login fallback.
- Direct backend endpoint: FastAPI `/api/auth/login`
- Staff table/model: `public.staff_users` / `backend.models.staff.StaffUser`
- Email normalization: lower-case email lookup.
- Password field: `password_hash`
- Verifier: `backend.core.security.verify_password()`
- Hash family expected: bcrypt `$2a$`, `$2b$`, or `$2y$`
- Session issuance: RS256 JWT from FastAPI; BFF stores it in `fortress_session`.
- Generic failure path: missing user or password mismatch returns `Invalid email or password`.

Read-only production auth checks:

- Exact Gary email lookup: FOUND
- Normalized Gary email lookup: FOUND
- Gary active: YES
- Gary role: `super_admin`
- Password hash field: PRESENT, not printed
- Hash algorithm family: bcrypt-compatible
- Lockout/failed-login columns: NOT_PRESENT in `staff_users`
- Login endpoint and read-only DB check use the same code model/table: YES

Classification:

- `LOGIN_ENDPOINT_EXPECTED`
- `UNKNOWN_LOGIN_FAILURE_PENDING_PASSWORD_MATCH_VERIFY`

No evidence found for:

- `LOGIN_ENDPOINT_WRONG_ROUTE`
- `LOGIN_BACKEND_WRONG_TABLE`
- `EMAIL_LOOKUP_MISMATCH`
- `PASSWORD_HASH_FIELD_MISMATCH`
- `STAFF_USER_INACTIVE_OR_LOCKED`

## Verify-Only Password Check Added

Timestamp: 2026-05-05T23:20:41-04:00

Reset policy for this continuation:

- Password reset: PROHIBITED_BY_CURRENT_SCOPE
- Password pasted into Codex: PROHIBITED

Implementation:

- Added `backend/scripts/verify_gary_staff_password.py`.
- Exact target email: `gary@cabin-rentals-of-georgia.com`.
- Required flag: `FORTRESS_ALLOW_STAFF_PASSWORD_VERIFY=1`.
- Password input method: hidden `getpass` prompt.
- Verification method: exact production `verify_password()` helper.
- Database writes: NO.
- Session creation: NO.
- User creation: NO.
- Printed output: only `USER_FOUND`, `ACTIVE`, `ROLE`, `PASSWORD_MATCH`, `HASH_ALGORITHM_MATCH`, `LOGIN_BACKEND_TABLE`, and `EMAIL_NORMALIZATION_USED`.

Focused checks:

- Python compile: PASS.
- Help output: PASS.
- Non-Gary email refusal: PASS.
- Missing authorization flag refusal: PASS.
- Static output scan: PASS.

Password match verification:

- NOT_RUN_IN_CODEX_CHAT.

Reason:

- Gary must enter the password manually at a real hidden terminal prompt. The password must not be pasted into Codex or passed through assistant/tool input.

Current standing:

- Production status: `PRODUCTION_AUTONOMOUS_INTAKE_BACKEND_COMPLETE`
- Legal operations status: `LEGAL_OPS_BACKEND_INTAKE_COMPLETE_APP_VISIBILITY_PENDING`
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_COMPLETE_APP_VISIBILITY_UNVERIFIED`
- Pilot status: `BLOCKED_BY_PRODUCTION_OPERATOR_PASSWORD_VERIFY`

Next branch:

- If `PASSWORD_MATCH yes`, diagnose BFF gateway/direct-backend/session-cookie behavior as the remaining login failure.
- If `PASSWORD_MATCH no`, classify as `PASSWORD_HASH_DOES_NOT_MATCH_OPERATOR_KNOWN_PASSWORD` and require Gary's explicit decision before any reset or backend switch.

## Gary-Only Reset Command Added

Timestamp: 2026-05-05T23:13:05-04:00

Runtime approval source:

- Current operator instruction to finish Fortress Legal production access.

Reset capability classification:

- `SAFE_LOCAL_RESET_SCRIPT_ADDED_OPERATOR_INPUT_REQUIRED`

Implementation:

- Added `backend/scripts/admin_reset_gary_staff_password.py`.
- Exact target email required: `gary@cabin-rentals-of-georgia.com`.
- Explicit production authorization flag required: `FORTRESS_ALLOW_STAFF_PASSWORD_RESET=1`.
- Password input method: hidden interactive `getpass` prompt only.
- Hashing path: app `hash_password()` helper, same bcrypt verifier used by Command Center login.
- User creation: impossible in this script.
- Scope: existing Gary `staff_users` row only.
- Metadata update: `updated_at` is updated with the password hash change.
- Session revocation: not supported by the current schema; no session table/token-version column was found.

Verification performed:

- `python3 -m py_compile fortress-guest-platform/backend/scripts/admin_reset_gary_staff_password.py`: PASS.
- Help output check: PASS.
- Non-Gary email refusal check: PASS.
- Missing authorization flag refusal check: PASS.
- Static output scan: PASS; script prints only email, user id, role, updated_at, and sessions_revoked status on success.

Password reset execution:

- NOT_PERFORMED_IN_CODEX_CHAT.

Reason:

- The only available way to feed the interactive prompt from this chat would expose the password through assistant/tool input. That would violate the hidden-prompt and no-password-printing requirements.

Current standing remains:

- Production status: `PRODUCTION_AUTONOMOUS_INTAKE_BACKEND_COMPLETE`
- Legal operations status: `LEGAL_OPS_BACKEND_INTAKE_COMPLETE_APP_VISIBILITY_PENDING`
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_COMPLETE_APP_VISIBILITY_UNVERIFIED`
- Pilot status: `BLOCKED_BY_PRODUCTION_OPERATOR_PASSWORD_RESET`

Remaining operator action:

- Run the Gary-only reset command from a real terminal attached to the production operator environment, enter the new password only at the hidden prompt, then verify Gary login and Fortress Legal UI visibility.

Superseded by current operator instruction:

- Do not reset Gary's password in this continuation unless a password hash mismatch is conclusively proven and Gary explicitly chooses that path later.
- Current next action is the verify-only hidden-prompt password check recorded above, not a reset.
- Current pilot status is `BLOCKED_BY_PRODUCTION_OPERATOR_PASSWORD_VERIFY`.

## Login Path Repair Attempt After Password Match

Timestamp: 2026-05-05T23:40:46-04:00

New verified operator evidence:

- `PASSWORD_MATCH yes`
- `USER_FOUND yes`
- `ACTIVE yes`
- `ROLE super_admin`
- `HASH_ALGORITHM_MATCH yes`
- Password reset: NOT_PERFORMED

Runtime/config diagnosis:

- Browser route: `https://crog-ai.com/login`.
- Form endpoint: same-origin `/api/auth/login`.
- BFF route: `apps/command-center/src/app/api/auth/login/route.ts`.
- Direct backend route: FastAPI `/api/auth/login`.
- Custom-domain production route: Cloudflare tunnel -> `http://127.0.0.1:3005`.
- Runtime process before repair: `crog-ai-frontend.service`, Next.js standalone on port `3005`, cwd pointed at a deleted standalone directory.
- Vercel project deployment completed but generated deployment URLs were protected by Vercel Authentication and `crog-ai.com` is served by the Cloudflare tunnel path, not directly by the protected generated URL.
- Vercel production env metadata contains `FORTRESS_BACKEND_BASE_URL`; the BFF helper previously only read `FGP_BACKEND_URL`.

Root cause classifications:

- `LOGIN_BFF_USES_WRONG_ENV_VAR` for the Vercel runtime path.
- `STALE_PRODUCTION_BUILD_OR_OLD_BFF` for the custom-domain `crog-ai.com` runtime path.
- `PASSWORD_MATCH_CONFIRMED_LOGIN_RECHECK_PENDING` remains until Gary completes a post-restart login.

Fix applied:

- `apps/command-center/src/lib/server/backend-url.ts` now accepts `FGP_BACKEND_URL` first and falls back to `FORTRESS_BACKEND_BASE_URL`.
- `apps/command-center/src/app/api/auth/login/route.ts` backend-unreachable hint now names both supported backend URL variables.
- Focused test added for backend URL variable precedence/fallback.
- Vercel production deploy completed: `dpl_4FjyAoySS7ea33dYj5QjZAH7Uk41`, URL `https://crog-ai-command-center-jy6uh35h2-cabin-rentals-of-georgia.vercel.app`.
- Custom-domain runtime restart completed: `crog-ai-frontend.service`, active/running, new PID `3236455`, cwd `/home/admin/Fortress-Prime/fortress-guest-platform/apps/command-center/.next/standalone/apps/command-center`.

Verification performed:

- Targeted backend URL unit test: PASS.
- Focused lint: PASS.
- Command Center build: PASS.
- `git diff --check`: PASS.
- Static asset smoke on `https://crog-ai.com`: PASS, representative JS and CSS returned HTTP 200.
- Login shell smoke on `https://crog-ai.com/login`: PASS, HTTP 200.
- Unauthenticated legal review route: guarded; no document contents exposed.
- Invalid-password probe: still returns HTTP 401 `Invalid email or password`, as expected.

Authenticated Gary UI verification:

- Gary login after restart: PENDING_OPERATOR_RECHECK.
- Fortress Legal review matter visibility: PENDING_AUTHENTICATED_UI.
- Document metadata visibility: PENDING_AUTHENTICATED_UI.
- Locked privileged handling: PENDING_AUTHENTICATED_UI.

Current standing:

- Production status: `PRODUCTION_AUTONOMOUS_INTAKE_BACKEND_COMPLETE`
- Legal operations status: `LEGAL_OPS_BACKEND_INTAKE_COMPLETE_APP_VISIBILITY_PENDING`
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_COMPLETE_APP_VISIBILITY_UNVERIFIED`
- Pilot status: `BLOCKED_BY_GARY_MANUAL_LOGIN_RECHECK_AFTER_BFF_RESTART`

## Autonomous Intake Document Metadata Linkage Repair

Timestamp: `2026-05-06T00:01:33-04:00`

Observed authenticated UI state before this repair:

- Gary login: SUCCESS.
- Legal Command Center: VISIBLE.
- Fortress Legal Production Review matter: VISIBLE.
- Matter detail route: `/legal/cases/fortress-legal-production-review`.
- Detail page still showed the synthetic review shell.
- Displayed synthetic execution ID: `fortress-review-20260506-011528`.
- Expected autonomous intake execution ID: `fortress-autointake-20260506-015341`.
- Displayed message: `Synthetic review shell only. No real legal documents uploaded or ingested.`

Read-only data comparison:

- UI case detail source: FastAPI legal case route using the legacy legal database.
- UI case id: `26`.
- Autonomous intake canonical case ids: `fortress_db=26`, `fortress_prod=13`.
- Runtime `fortress_shadow` `legal.vault_documents` rows for slug: `0`.
- Legacy `fortress_db` `legal.vault_documents` rows for slug: `80`.
- Production mirror `fortress_prod` `legal.vault_documents` rows for slug: `80`.
- `fortress_db` status counts: `completed=78`, `locked_privileged=2`.
- `fortress_prod` status counts: `completed=78`, `locked_privileged=2`.

Root cause classifications:

- `FRONTEND_DOCUMENT_TAB_NOT_CONNECTED`
- `DOCUMENTS_WRITTEN_TO_VAULT_TABLE_NOT_UI_DOCUMENT_TABLE`
- `DOCUMENT_API_QUERIES_WRONG_DATABASE`

Fix applied:

- Added a typed Command Center hook for `/api/internal/legal/cases/{slug}/vault/documents`.
- Updated the case detail Document tab to render autonomous intake vault-document metadata.
- Kept old case notes available under a separate Notes tab.
- Updated the backend vault-document list route to read from the same legacy legal database source as the UI-visible case detail route.
- The list response remains metadata-only and excludes content, NAS paths, file hashes, and vector IDs.
- `locked_privileged` rows render as locked/restricted metadata only.

Deploy/restart evidence:

- Source commit: `bcb54ba57` (`fix(legal): connect autonomous intake documents to review workspace`).
- Runtime-main cherry-pick: `f07bc9526`.
- `fortress-backend.service`: restarted and active.
- `crog-ai-frontend.service`: restarted and active.
- Vercel deploy: NOT_PERFORMED for this repair because `https://crog-ai.com` is served through the local Cloudflare tunnel/runtime path; the correct production runtime was restarted.

Verification performed:

- Frontend metadata rendering test: PASS.
- Backend vault-document list route test: PASS.
- Command Center typecheck: PASS.
- Targeted ESLint for changed frontend files: PASS.
- Command Center production build: PASS.
- `git diff --check`: PASS.
- Focused secret scan of changed diff: PASS.
- Full command-center lint: FAILS on pre-existing unrelated files outside this repair scope; no unrelated files were touched.
- Production root: HTTP 200.
- Representative production static asset: HTTP 200.
- Unauthenticated legal vault-documents API: HTTP 401.
- Runtime backend route direct metadata check: `total=80`, `completed=78`, `locked_privileged=2`.
- Restricted fields exposed by route: NO.

Authenticated browser verification after deploy:

- Gary refresh/reopen after restart: PENDING_OPERATOR_CONFIRMATION.
- `/legal`: PENDING_OPERATOR_CONFIRMATION.
- `/legal/cases/fortress-legal-production-review`: PENDING_OPERATOR_CONFIRMATION.
- Document metadata visible in browser: PENDING_OPERATOR_CONFIRMATION.
- Locked privileged browser handling: PENDING_OPERATOR_CONFIRMATION.

Mutation invariants:

- New document upload: NO.
- New ingest: NO.
- New document rows: NO.
- New Qdrant writes: NO.
- Metadata linkage writes: NO.
- Schema changes: NO.
- RLS/policy changes: NO.
- Document contents printed/exposed: NO.
- Secrets printed/exposed: NO.
- Unrelated dirty files touched: NO.

Current standing state:

- Production status: `PRODUCTION_OPERATOR_AUTH_REPAIRED_MATTER_VISIBLE`
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`
- Legal operations status: `LEGAL_OPS_DOCUMENT_METADATA_VISIBILITY_PENDING_OPERATOR_CONFIRMATION`
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_INGESTED_WITH_PRIVILEGED_LOCKS`
- Production legal-data status: `AUTONOMOUS_INTAKE_BACKEND_COMPLETE_UI_DOCUMENTS_DEPLOYED_PENDING_OPERATOR_CONFIRMATION`
- Pilot status: `BLOCKED_BY_AUTHENTICATED_DOCUMENT_METADATA_UI_CONFIRMATION_PENDING`

Exact next action:

- Gary/operator must refresh or reopen `/legal/cases/fortress-legal-production-review` in an authenticated production browser session and confirm the Document tab shows 80 metadata rows or UI-equivalent count with 78 completed and 2 locked/restricted privileged rows.

## Final Authenticated Document Metadata Visibility Confirmation

Timestamp: `2026-05-06T00:08:07-04:00`

Gary/operator authenticated production UI confirmation:

- Production domain: `https://crog-ai.com`.
- Login result: SUCCESS.
- Route checked: `/legal/cases/fortress-legal-production-review`.
- Matter checked: `Fortress Legal Production Review`.
- Review matter visible: YES.
- Document/Vault metadata view visible: YES.
- Document metadata list visible: YES.
- UI document count: `80`.
- UI completed count: `78`.
- UI locked count: `2`.
- Locked/restricted rows: visible as restricted metadata only.
- Locked/restricted contents exposed: NO.
- Confidential document contents pasted into evidence: NO.
- Public/unauthenticated exposure observed: NO.

Backend evidence aligned with UI confirmation:

- Execution ID: `fortress-autointake-20260506-015341`.
- PDFs selected/ingested: `80`.
- Completed: `78`.
- Locked privileged: `2`.
- Qdrant/vector points: `3,785`.
- Repair commit: `bcb54ba57` (`fix(legal): connect autonomous intake documents to review workspace`).
- Evidence commit before final confirmation: `209167f95` (`docs(legal): record document metadata visibility repair`).
- Runtime-main backend cherry-pick: `f07bc9526`.

Mutation invariants:

- New document upload: NO.
- New ingest: NO.
- New document rows: NO.
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

- Production status: `PRODUCTION_AUTONOMOUS_INTAKE_APP_VISIBLE`
- Legal readiness status: `LEGAL_READINESS_ACTIVE_FOR_AUTONOMOUS_REVIEW_SCOPE`
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_AI_ASSISTED_DOCUMENT_REVIEW`
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_INGESTED_WITH_PRIVILEGED_LOCKS`
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_COMPLETE_APP_VISIBLE`
- Pilot status: `PILOT_READY_FOR_GARY_REVIEW`

## Litigation Intelligence Layer Visibility Status

Timestamp: `2026-05-06T00:12:57-04:00`

- Litigation intelligence execution ID: `fortress-intel-20260506-041839`.
- Evidence file: `docs/operational/fortress-legal-litigation-intelligence-phase-2026-05-06.md`.
- Backend intelligence extraction: COMPLETE.
- Derived graph nodes: `448`.
- Derived graph edges: `1,227`.
- Draft chronology events: `180`.
- Contradiction/tension candidates: `14`.
- Review queue items: `20`.
- Locked/restricted documents: still restricted and metadata-only.
- Public exposure check: unauthenticated document, graph, chronology, and sanctions endpoints returned HTTP 401.
- Authenticated Gary UI confirmation of populated intelligence panels: PENDING_OPERATOR_CONFIRMATION.

Current intelligence-layer standing:

- Production status: `PRODUCTION_INTELLIGENCE_EXTRACTION_COMPLETE_UI_PENDING`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_AI_ASSISTED_LITIGATION_REVIEW`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_ANALYZED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_ANALYZED_UI_CONFIRMATION_PENDING`.
- Product status: `LITIGATION_INTELLIGENCE_BACKEND_READY_UI_PENDING`.
- Counsel status: `COUNSEL_REVIEW_REQUIRED`.

## Final Litigation Intelligence UI Visibility Confirmation

Timestamp: `2026-05-06T07:20:07-04:00`

Gary/operator authenticated production UI confirmation:

- Production route checked: `https://crog-ai.com/legal/cases/fortress-legal-production-review`.
- Matter checked: `Fortress Legal Production Review`.
- Draft posture banner: `DRAFT / COUNSEL REVIEW REQUIRED` visible.
- Panopticon / Deliberation / Vanguard / Graph Radar panels visible: YES.
- UI entity count: `448 Entities Mapped`.
- UI contradiction count: `14 Contradiction Edges`.
- Graph sync indicator: `Graph Synced: 448 Entities`.
- Master Chronology indicator: `180 events`.
- Entity Graph Pressure Map indicator: `448 Entities`, `1,227 Edges`.
- Timeline/Master Chronology populated: YES.
- Entity Graph / Graph Radar / Panopticon populated: YES.
- Contradiction candidates/edges visible: YES.
- Counsel-review posture preserved: YES.

Document/Vault baseline remains confirmed:

- Documents: `80`.
- Completed: `78`.
- Locked/restricted: `2`.
- Locked/restricted handling: metadata-only; restrictions preserved.

Product evidence aligned with UI:

- Litigation intelligence execution ID: `fortress-intel-20260506-041839`.
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

## Counsel Review Workbench Visibility Status

Timestamp: `2026-05-06T07:33:30-04:00`

- Workbench execution ID: `fortress-counsel-review-20260506-073330`.
- Source intelligence execution ID: `fortress-intel-20260506-041839`.
- Evidence file: `docs/operational/fortress-legal-counsel-review-workbench-2026-05-06.md`.
- Counsel workbench generation: COMPLETE.
- Issue matrix records: `20`.
- Evidence binder records: `17`.
- Chronology review packet: COMPLETE over `180` events.
- Contradiction triage records: `14`.
- Entity dossier records: `40`.
- Counsel questions/actions: `24`.
- Consolidated review queue items: `18`.
- Locked/restricted documents: `2`, preserved metadata-only.
- Workbench manifest: `/mnt/fortress_nas/audits/fortress-counsel-review-20260506-073330.json`.
- Backend API: `GET /api/internal/legal/cases/{slug}/counsel-workbench`.
- Frontend panel: Counsel Review Workbench in the Deliberation tab.
- Production restart: `fortress-backend.service` and `crog-ai-frontend.service` restarted and active.
- Public exposure check: unauthenticated workbench API returned HTTP `401`.
- Production matter route smoke: HTTP `200`.
- Authenticated Gary UI confirmation of counsel workbench panel: PENDING.

Current workbench-layer standing:

- Production status: `PRODUCTION_COUNSEL_WORKBENCH_BACKEND_COMPLETE_UI_PENDING`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_COUNSEL_REVIEW_WORKBENCH`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_ANALYZED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_INTELLIGENCE_AND_WORKBENCH_DEPLOYED_PENDING_UI_CONFIRMATION`.
- Product status: `COUNSEL_WORKBENCH_BACKEND_READY_UI_PENDING`.
- Counsel status: `COUNSEL_REVIEW_REQUIRED`.

## Counsel Workbench UI Mapping Repair

Timestamp: `2026-05-06T07:51:36-04:00`

- Prior authenticated UI observation: litigation intelligence was visible, but Counsel Review Workbench sections were not visible.
- Root cause classification: `COUNSEL_WORKBENCH_COMPONENT_EXISTS_NAV_HIDDEN`.
- Fix commit: `232055866`.
- Fix applied: matter page now has a first-class default `Workbench` tab.
- Visible workbench sections in deployed bundle: Issue Matrix, Evidence Binders, Contradiction Triage, Entity Dossier, Theory / Counter-Theory, Counsel Questions / Actions, Review Queue.
- Draft/counsel-review labeling preserved: YES.
- Locked/restricted metadata-only handling preserved: YES.
- Frontend restart: `crog-ai-frontend.service` restarted and active.
- Public exposure check: unauthenticated workbench API returned HTTP `401`.
- Authenticated Gary/operator post-repair UI confirmation: PENDING.

Current workbench visibility standing:

- Production status: `PRODUCTION_COUNSEL_WORKBENCH_UI_MAPPING_DEPLOYED_PENDING_OPERATOR_CONFIRMATION`.
- Legal operations status: `LEGAL_OPS_ACTIVE_FOR_COUNSEL_REVIEW_WORKBENCH`.
- Real legal data status: `AUTONOMOUS_REVIEW_DATA_ANALYZED_WITH_PRIVILEGED_LOCKS`.
- Production legal-data status: `PRODUCTION_AUTONOMOUS_INTAKE_INTELLIGENCE_AND_WORKBENCH_DEPLOYED_PENDING_UI_CONFIRMATION`.
- Product status: `COUNSEL_WORKBENCH_UI_MAPPING_DEPLOYED_PENDING_OPERATOR_CONFIRMATION`.
- Counsel status: `COUNSEL_REVIEW_REQUIRED`.
