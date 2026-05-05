# Fortress Legal Production Legal / Compliance Gate

Date: 2026-05-05
Status: PASS FOR UI/BACKEND SCOPE; LEGAL OPS NOT READY BY DESIGN

## Scope

This gate evaluates whether a production UI/backend deployment may proceed while legal evidence operations remain fail-closed. It does not approve legal evidence ingest, promotion, privilege clearance, Qdrant movement, NAS/evidence movement, or resolution application.

## Legal Readiness State

Observed standing state from certified staging and prior legal-readiness work:

- Legal readiness: `NOT_READY_BY_DESIGN`.
- Drift blockers remain unresolved unless explicit operator/legal decisions are recorded.
- Duplicate filename/hash conflicts remain unresolved unless explicit operator/legal decisions are recorded.
- HOLD decisions remain authoritative where confirmation is absent.

## Privilege Policy

Standing policy:

- `ALL_PRIVILEGED_ZERO_DISCOVERY` default: `HOLD`.
- Upgrade to `ACCEPT_PRIVILEGED_COLLECTION` only with explicit, scoped legal/operator confirmation.
- No privilege inference from metadata, domains, filenames, or vector placement.
- No batch clearance without explicit scope and authority.

## Evidence Controls

The production UI/backend scope must preserve:

- No evidence ingest without authorization.
- No promotion without authorization.
- No privilege clearance without authorization.
- No email body ingestion without authorization.
- No Qdrant vector movement without authorization.
- No NAS/evidence movement, copy, rename, delete, overwrite, or audit rewrite without authorization.
- No legal resolution application without authorization.

## UI Behavior Requirements

The Command Center/Fortress Legal UI must:

- Display legal readiness as `NOT_READY` while unresolved blockers remain.
- Not claim legal `PRODUCTION_READY` unless backend/legal readiness says so.
- Avoid exposing mutation actions that can ingest, promote, clear privilege, move vectors, or apply resolutions without explicit authorization.
- Preserve read-only certification behavior for `/dashboard` and `/legal`.

## Gate Result

- Legal/compliance gate for UI/backend deployment scope: `PASS_FOR_UI_BACKEND_SCOPE`.
- Full legal-data operations readiness: `BLOCKED_PENDING_OPERATOR_DECISIONS`.
- Legal operations classification: `LEGAL_OPS_NOT_READY_BY_DESIGN`.

## Required Next Action For Full Legal Ops

Resolve or explicitly scope every drift and duplicate blocker through the authorized operator/legal resolution model. HOLD remains the correct state where confirmation is absent.
