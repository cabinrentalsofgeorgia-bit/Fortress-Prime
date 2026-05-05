# Fortress Legal Production Rollback Plan

Date: 2026-05-05
Status: READY AS A PLAN; EXECUTION BLOCKED UNTIL PRODUCTION DEPLOY IS AUTHORIZED

## Scope

The expected release scope is UI/backend deployment only.

This plan does not authorize:

- Production DB migrations.
- Legal DB table mutation.
- Qdrant writes or vector movement.
- NAS/evidence movement, copy, rename, delete, or overwrite.
- Evidence ingest or promotion.
- Privilege clearance.
- Resolution application.

## Rollback Triggers

Rollback or stop-the-line review is required if any of the following are observed:

- Production smoke failure.
- Authentication failure or unsafe auth bypass.
- Service-role key or private credential exposure.
- Wrong Supabase ref or wrong backend target.
- UI shows legal `PRODUCTION_READY` while backend/legal readiness is `NOT_READY`.
- Legal API critical 4xx/5xx failure after authenticated access.
- Browser calls localhost from production.
- Unexpected production mutation.
- Any legal DB, Qdrant, NAS/evidence, ingest, promotion, privilege, or resolution mutation.

## Rollback Prerequisites

Before deployment, the operator must record:

- Verified production target.
- Previous deployment ID or artifact.
- Current deployment ID.
- Current production DB backup/snapshot evidence.
- Redacted production environment snapshot.
- Rollback owner/operator.
- Explicit rollback authorization scope.

## Application Rollback

Provider observed from local metadata: Vercel project `crog-ai-command-center`.

Provider-specific rollback command is REQUIRED before deployment. Do not invent it at incident time. The production approval packet must record one of:

- Vercel rollback to previous deployment ID.
- Re-deploy previous known-good commit.
- Provider dashboard rollback action with operator and timestamp.

Required placeholders:

```text
ROLLBACK_PROVIDER=Vercel
PREVIOUS_DEPLOYMENT_ID=<required-before-deploy>
CURRENT_DEPLOYMENT_ID=<required-after-deploy>
ROLLBACK_COMMAND=<required-before-deploy>
ROLLBACK_OPERATOR=<required-before-deploy>
```


## Backup Evidence Reference

Current production DB backup/snapshot evidence is recorded in `docs/operational/fortress-legal-production-backup-snapshot-gate-2026-05-05.md`.

- Evidence method: provider-native Supabase backup listing.
- Production project: `Fortress Legal Production`.
- Production ref: `hms...liap` partial-safe.
- Latest completed physical backup timestamp: `2026-05-05T11:09:03.536Z`.
- Restore path: provider-native Supabase restore for the verified production project, requiring explicit production restore approval.
- Restore verification checklist: documented in the backup/snapshot gate and mirrored by this rollback plan's post-rollback verification steps.

## Data Rollback Policy

For this UI/backend-only scope:

- DB rollback strategy: not touched.
- Qdrant rollback strategy: not touched.
- NAS/evidence rollback strategy: not touched.
- Auth rollback strategy: not touched unless production auth metadata-write smoke is separately authorized.

If a future approved scope includes data mutation, data rollback must be deterministic and tied to snapshot IDs. No DB rollback, Qdrant rollback, NAS deletion, evidence overwrite, privilege rewrite, or audit rewrite may rely on guesswork.

## Post-Rollback Verification

After rollback:

- Root route loads.
- Login shell loads.
- Protected routes require auth.
- Dashboard either loads safely or redirects safely.
- Fortress Legal route either loads safely or redirects safely.
- Readiness is not falsely `PRODUCTION_READY`.
- No privileged server credential or private credential appears in browser/static output.
- No wrong Supabase ref appears.
- No token patterns, DB/Qdrant credentials, or NAS/evidence paths appear in browser/static output.
- No legal DB/Qdrant/NAS/evidence mutation occurred.
- No ingest, promotion, privilege clearance, or resolution application occurred.

## Current Gate Result

Rollback plan: `PASS_AS_PLAN`. Backup evidence reference: `PRESENT`.

Execution remains blocked until production deploy authorization and required deployment IDs are present.
