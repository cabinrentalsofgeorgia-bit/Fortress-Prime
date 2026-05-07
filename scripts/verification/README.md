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
- `featureAlignmentOk`: `ok` plus Source Integrity / Validation, Workbench, Draft Work Product, Autonomous Learning, Remediation Maturity, and Controlled Review Operations visibility.
- Remediation maturity visibility is included in `featureAlignmentOk` after the review-maturity phase. It checks for Remediation Maturity, Review Confidence, Evidence Lineage, and unresolved-source exclusion labels.
- Review operations visibility is included after the controlled-review-operations phase. It checks for Controlled Review Operations, Review Queue Operations, Contradiction Review, Evidence Navigator, Review Analytics, Controlled Pilot Readiness, and unresolved-source exclusion labels.
- Review scaling visibility is included after the controlled-review-scaling phase. It checks for Reviewer Assignment, Workload Balancing, Queue Aging / SLA, Escalation & Incident Readiness, and explicit forbidden counsel-signoff/external-submission labels.
- Operational certification visibility is included after the controlled-pilot certification phase. It checks for Operational Readiness Certification, Pilot Governance, Reviewer Onboarding Governance, Rollback Certification, Governance Enforcement Verification, Operational Safety Certification, and explicit no-public-launch / no-auto-signoff limits.
- Internal pilot visibility is included after the controlled-internal-pilot phase. It checks for Controlled Internal Pilot Operations, allowed/forbidden pilot exercises, Pilot Throughput Metrics, Pilot Simulation / Drills, no production writes, and forbidden legal-signoff/external-submission labels.
- Human operations visibility is included after the controlled-human-operations phase. It checks for Controlled Human Operations, Reviewer Onboarding Governance, Operational Feedback Capture, Governance Exception Handling, Operational Drift Detection, Human Incident Rehearsal, and explicit halt/no-write/no-source-promotion boundaries.
- Operational memory visibility is included after the machine-readable cognition phase. It checks for Operational Memory / Machine-Readable Cognition, Governance Registry, Remediation Registry, Evidence Registry, Capability Registry, Wiki / App / Evidence Knowledge Index, and Reviewer Feedback Ledger Foundation.
- Operational graph visibility is included after the queryable-governance phase. It checks for Operational Knowledge Graph / Queryable Governance, graph entities, graph relationships, governance graph, evidence graph, remediation graph, and graph validation labels.
- Governance query engine visibility is included after the agent-context phase. It checks for Governance Query Engine / Agent Operating Context, safe next actions, forbidden actions, signoff blockers, launch blockers, and agent context labels.

For Fortress Legal production feature alignment, expected target values are:

```json
{
  "ok": true,
  "featureAlignmentOk": true,
  "checks": {
    "draftWorkProduct": true,
    "learning": true,
    "remediationMaturity": true,
    "reviewOperations": true,
    "reviewScaling": true,
    "operationalCertification": true,
    "internalPilot": true,
    "humanOperations": true,
    "feedbackCapture": true,
    "reviewerOnboarding": true,
    "governanceExceptions": true,
    "driftDetection": true,
    "humanEscalation": true,
    "operationalMemory": true,
    "governanceRegistry": true,
    "remediationRegistry": true,
    "evidenceRegistry": true,
    "wikiKnowledgeIndex": true,
    "reviewerLedgerFoundation": true,
    "operationalGraph": true,
    "governanceGraph": true,
    "evidenceGraph": true,
    "remediationGraph": true,
    "graphValidation": true,
    "governanceQueryEngine": true,
    "agentContext": true,
    "safeNextActionsVisible": true,
    "forbiddenActionsVisible": true,
    "signoffBlockersVisible": true,
    "launchBlockersVisible": true
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

## Internal Reviewer Tabletop

`run-internal-reviewer-tabletop.mjs` validates the controlled internal reviewer tabletop phase without using auth state or legal document content:

```bash
node scripts/verification/run-internal-reviewer-tabletop.mjs
```

It checks required pilot docs, prior sanitized pilot evidence, public route reachability, unauthenticated legal API guards, aggregate throughput counts, and standing governance labels. It does not inspect document body text, locked/restricted content, auth storage state, cookies, tokens, passwords, headers, or secrets.
