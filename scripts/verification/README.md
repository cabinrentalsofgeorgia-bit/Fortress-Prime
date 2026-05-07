# Fortress Legal Verification Scripts

## Authenticated Production UI Checker

`check-crog-fortress-ui.mjs` verifies the authenticated production Fortress Legal matter page at `https://crog-ai.com/legal/cases/fortress-legal-production-review`.

The checker requires an externally provisioned Playwright storage state file. By default it looks for:

```text
.auth/crog-ai-gary.json
```

Operational rules:

- `.auth/` must remain untracked and ignored.
- The storage state file must remain local-only and mode `600`.
- Do not print, commit, copy, or upload auth storage state.
- Do not print cookies, tokens, passwords, auth headers, or session values.
- The checker is evidence for authenticated UI visibility only.
- The checker does not record counsel signoff.
- The checker does not create final legal conclusions.
- The checker does not authorize filing, service, email, sending, or external submission.

Run from the repository root after provisioning auth state:

```bash
node scripts/verification/check-crog-fortress-ui.mjs
```

To reuse an auth state from another governed local worktree without copying it:

```bash
CROG_AUTH_STATE=/path/to/.auth/crog-ai-gary.json node scripts/verification/check-crog-fortress-ui.mjs
```

The checker suppresses page text samples by default to avoid exposing legal content in logs. Set `FORTRESS_CHECKER_INCLUDE_TEXT_SAMPLE=1` only for an explicitly authorized local diagnostic run.

## Feature Alignment Assertions

The checker reports two top-level outcomes:

- `ok`: authenticated matter baseline is intact, `COUNSEL_SIGNOFF_PENDING` is visible, no login error is present, and the page does not expose final-advice or external-submission authority labels.
- `featureAlignmentOk`: `ok` plus Source Integrity / Validation, Workbench, Draft Work Product, and Autonomous Learning visibility.
- Remediation maturity visibility is included in `featureAlignmentOk` after the review-maturity phase. It checks for Remediation Maturity, Review Confidence, Evidence Lineage, and unresolved-source exclusion labels.

For Fortress Legal production feature alignment, expected target values are:

```json
{
  "ok": true,
  "featureAlignmentOk": true,
  "checks": {
    "draftWorkProduct": true,
    "learning": true,
    "remediationMaturity": true
  }
}
```

`featureAlignmentOk` is still not counsel signoff. It only proves authenticated production UI visibility for the governed review workflow. It preserves:

- `COUNSEL_SIGNOFF_PENDING`
- `DRAFT / COUNSEL REVIEW REQUIRED`
- `NOT FINAL LEGAL ADVICE`
- `NOT_AUTHORIZED` / no external submission authority
- locked/restricted metadata-only handling

## Operational Hardening Assertions

The checker also records non-sensitive production error evidence:

- `checkedAt`
- `responseUrl`
- `xRequestId`, when the app shell provides it
- `httpErrors[]` with sanitized URL, status, method, resource type, and classification
- `requestFailures[]` with sanitized URL and failure class
- `errorSummary` counts by class

The checker must not print auth state, cookies, tokens, passwords, authorization headers, session values, or document body text.

Error classifications are operational only:

- `missing_asset`
- `missing_route`
- `missing_api_route_or_manifest`
- `backend_or_bff_failure`
- `runtime_failure`
- `auth_guard`

## Deployment Verification

`verify-production-deployment.mjs` runs a repeatable, non-mutating production smoke:

```bash
CROG_AUTH_STATE=/path/to/.auth/crog-ai-gary.json node scripts/verification/verify-production-deployment.mjs
```

It verifies public route reachability, unauthenticated API guards, local service activity, and the authenticated checker when `CROG_AUTH_STATE` is present.

Deployment evidence should include only non-sensitive fields:

- `checkedAt`
- service/unit status
- HTTP status codes
- sanitized route paths
- checker booleans
- error classifications

Deployment evidence never records counsel signoff, final legal conclusions, or external submission authority.
