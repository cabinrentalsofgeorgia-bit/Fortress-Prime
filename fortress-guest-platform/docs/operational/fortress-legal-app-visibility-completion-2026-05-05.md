# Fortress Legal App Visibility Completion Evidence

Date: 2026-05-05
Continuation timestamp: 2026-05-05T23:09:12-04:00

## Current Classification

Final classification: `PRODUCTION_OPERATOR_AUTH_BLOCKER_PRECISE_APP_VISIBILITY_PENDING`

Gary Knight's production staff account exists and the backend review data is present, but this continuation did not complete normal authenticated UI verification because Gary's observed login attempt returned `Invalid email or password`.

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
