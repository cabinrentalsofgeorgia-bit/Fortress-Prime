# Fortress Legal Production Approval Packet

Date: 2026-05-05
Status: BLOCKED PENDING EXPLICIT PRODUCTION AUTHORIZATION

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

- Production domain:
- Deployment provider/target:
- Production app URL:
- Production API URL:
- Production Supabase project ref:
- Production database host/ref:
- Production Qdrant endpoint and collection names:
- Production NAS/evidence mount or storage target:
- Production environment variable source:
- Production branch/tag/commit:

Staging targets must not be reused or inferred as production targets.

## Required Operator Authorization

Production approval must be explicit and scoped:

- Operator name:
- Operator role/authority:
- Approval timestamp:
- Authorized deployment scope:
- Authorized mutation scope, if any:
- Explicit deploy authorization: `YES/NO`
- Explicit DB migration authorization: `YES/NO`
- Explicit legal evidence mutation authorization: `YES/NO`
- Explicit Qdrant mutation authorization: `YES/NO`
- Explicit NAS/evidence mutation authorization: `YES/NO`

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

If this evidence is missing, production remains blocked.

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
