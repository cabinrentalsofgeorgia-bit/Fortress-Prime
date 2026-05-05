# Fortress Legal Production Approval Packet

Date: 2026-05-05
Status: TARGET VERIFIED BY OPERATOR; DEPLOY BLOCKED PENDING BACKUP / ROLLBACK / ADVISORY / LEGAL GATES

## Current Certified State

- Staging authenticated-session UI certification commit: `cb3d1a202`
- Staging password-login E2E certification commit: `74806ee7c`
- Staging UI classification: `STAGING_AUTHENTICATED_UI_CERTIFIED`
- Password-login E2E: `PASSWORD_LOGIN_E2E_CERTIFIED`
- Backend legal safety: `PASS`
- Legal readiness: `NOT_READY_BY_DESIGN`
- Production: `BLOCKED`

## Required Production Target Identity

Production approval must identify all production targets before any deploy or mutation:

- Production domain: OPERATOR-VERIFIED; exact value not recorded in local evidence.
- Deployment provider/target: Vercel project `crog-ai-command-center` observed in read-only local project metadata.
- Vercel project id: `prj_u90XAUhroRxPGIXKYCowt0uqULDg`.
- Vercel org/team id: `team_yGxCOcECYMqhFKB3Yve2wRVi`.
- Production app URL: not recorded in local evidence; `VERCEL_URL` is empty in the local production env snapshot.
- Production API URL: `FORTRESS_BACKEND_BASE_URL` key observed in Vercel production env metadata; value redacted and not recorded.
- Production Supabase project ref: UNKNOWN in this packet.
- Production database host/ref: UNKNOWN in this packet.
- Production Qdrant endpoint and collection names: UNKNOWN in this packet.
- Production NAS/evidence mount or storage target: UNKNOWN in this packet.
- Production environment variable source: Vercel production env metadata observed locally at `apps/command-center/.vercel/.env.production.local`; values redacted and not printed.
- Production branch/tag/commit: expected release branch `safety/foundation-audit-snapshot`, commit `e8b1bd358` or later gate-closure commit.

Operator standing classification: `PRODUCTION_TARGET_VERIFIED_DEPLOY_BLOCKED_PENDING_BACKUP_ROLLBACK_ADVISORY_LEGAL_GATES`.
Staging targets must not be reused or inferred as production targets.

## Required Operator Authorization

Production approval must be explicit and scoped:

- Operator name: not recorded in this packet.
- Operator role/authority: production target verification acknowledged by operator in thread; deploy authorization not granted.
- Approval timestamp: 2026-05-05 thread acknowledgement.
- Authorized deployment scope: NONE YET.
- Authorized mutation scope, if any: NONE.
- Explicit deploy authorization: `NO`
- Explicit DB migration authorization: `NO`
- Explicit legal evidence mutation authorization: `NO`
- Explicit Qdrant mutation authorization: `NO`
- Explicit NAS/evidence mutation authorization: `NO`

Default scope is UI/backend deployment only. Legal evidence ingest, promotion, privilege clearance, Qdrant vector movement, and resolution application require separate legal/operator authorization.

## Required Backup / Snapshot Evidence

Before production deploy or mutation, attach evidence for:

- Current production DB backup/snapshot:
- Backup timestamp:
- Backup project/ref:
- Backup type:
- Backup creator/system:
- Restore procedure reference:
- Previous deployment ID/artifact:
- Current production environment snapshot reference, secrets redacted:
- Current production image/static artifact reference:

If this evidence is missing, production remains blocked. The backup gate also requires the production Supabase/project ref or production DB target to be recorded before any backup command may run.

## Dependency Advisory Disposition

Before production deploy, every high/critical advisory must be resolved or formally dispositioned:

| Package | Severity | Affected Version | Fixed Version | Reachable In Production | Disposition | Owner | Expiry |
| --- | --- | --- | --- | --- | --- | --- | --- |

Allowed dispositions: `FIXED`, `NOT_REACHABLE`, `ACCEPTED_WITH_EXPIRY`, `BLOCKING`.

## Legal / Compliance Gate

Fortress Legal remains fail-closed until legal/operator decisions are explicit.

Required confirmations:

- Legal readiness result:
- Current blocker count:
- HOLD policy reviewed: `YES/NO`
- Privilege inference prohibited: `YES/NO`
- Dry-run/read-only controls verified: `YES/NO`
- Qdrant collection allowlist verified: `YES/NO`
- UI does not claim production ready while legal readiness is `NOT_READY`: `YES/NO`
- Legal operations scope accepted while readiness is `NOT_READY`: `YES/NO`

If full legal-data production readiness is required, unresolved HOLD/blocker decisions remain a production blocker.

## Rollback Requirements

A production rollback plan must reference:

- Rollback owner/operator:
- Rollback trigger conditions:
- Previous deploy/artifact ID:
- Previous environment snapshot reference:
- App rollback command sequence:
- DB rollback strategy or `not touched`:
- Qdrant rollback strategy or `not touched`:
- NAS/evidence rollback strategy or `not touched`:
- Auth rollback strategy or `not touched`:
- Post-rollback verification commands:

No legal evidence rollback may rely on guesswork. No deletion is allowed without explicit approval.

## Approval Decision

Production may proceed only after this section is completed and signed.

- Decision: `APPROVED / BLOCKED`
- Approved production scope:
- Blocked reason, if any:
- Operator signature:
- Timestamp:
