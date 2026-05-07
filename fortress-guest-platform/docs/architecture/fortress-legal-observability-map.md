# Fortress Legal Observability Map

## Purpose

This map defines the minimum operational visibility required for Fortress Legal production hardening without expanding legal workflow scope.

## Health Surfaces

- Public frontend route: `https://crog-ai.com/`
- Authenticated matter route: `/legal/cases/fortress-legal-production-review`
- Public backend health: `/health`
- Staff system health BFF: `/api/system-health`
- Internal backend health: `/internal/health`
- Authenticated production checker: `scripts/verification/check-crog-fortress-ui.mjs`
- Deployment verifier: `scripts/verification/verify-production-deployment.mjs`

## Non-Sensitive Fingerprints

Health and checker evidence may include:

- `checkedAt`
- service/unit name
- HTTP status
- request duration
- deployment `git_sha`
- deployment `started_at_utc`
- service version
- sanitized URL path
- error classification

Health and checker evidence must not include:

- cookies, tokens, passwords, auth headers, or storage state;
- document body text;
- locked/restricted content;
- final legal conclusions;
- counsel signoff records unless explicitly recorded by a human in a later phase.

## Error Classes

- `missing_asset`
- `missing_route`
- `missing_api_route_or_manifest`
- `backend_or_bff_failure`
- `runtime_failure`
- `auth_guard`
- `request_failed`

## Governance Invariants

- Counsel status remains `COUNSEL_SIGNOFF_PENDING`.
- External submission authority remains `NOT_AUTHORIZED`.
- Legal advice status remains `NOT FINAL LEGAL ADVICE`.
- Locked/restricted documents remain metadata-only.
- Schema/RLS/policy mutation is not part of observability hardening.
