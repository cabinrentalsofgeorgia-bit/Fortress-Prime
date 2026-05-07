# Operational Memory Architecture - 2026-05-06

## Classification

`MACHINE_READABLE_OPERATIONAL_COGNITION_ARCHITECTURE`

## Purpose

Operational memory turns Fortress Legal's current state, capabilities, governance boundaries, evidence lineage, remediation posture, wiki/app knowledge, and reviewer feedback posture into deterministic artifacts that humans, reviewers, operators, and AI agents can consume without relying on prose-only docs or chat memory.

## Principles

- Registries describe operational state; they do not create legal authority.
- Registries are read-only operational memory unless a future phase separately approves governed write paths.
- Registries must preserve `COUNSEL_SIGNOFF_PENDING`, `NOT_AUTHORIZED`, `NOT FINAL LEGAL ADVICE`, unresolved-source exclusion, metadata-only restricted handling, and human review requirements.
- Registries must not contain confidential legal text, privileged content, locked/restricted content, auth state, cookies, tokens, passwords, headers, database URLs, service keys, or raw source excerpts.
- Registries must not infer counsel signoff, final legal conclusions, external submission authority, source resolution, or reviewer authority.
- Registry consumers must treat registry contents as operational state and routing context, not as legal advice or filing authority.

## Registry Types

- `operational-state`: standing labels, checker state, verifier state, blockers, hard stops.
- `capability-registry`: maturity and limitations of canonicalized platform phases.
- `governance-registry`: hard boundaries, forbidden operations, required labels, hard stops.
- `evidence-registry`: evidence directories, validation summaries, rollback references.
- `remediation-registry`: unresolved-source posture, queue state, human review requirement.
- `reviewer-feedback-ledger`: structured feedback/disposition schema and empty/synthetic entries only.
- `wiki-knowledge-index`: docs/wiki/evidence entries with category, freshness, and source path.

## Ownership And Update Cadence

- Platform integrator owns registry schema changes.
- Evidence owner updates evidence references after each governed phase.
- Review operations owner updates remediation and feedback categories.
- Governance owner updates forbidden operations and standing labels.
- Registries should be regenerated or curated at the end of each phase and validated before PR.

## Consumers

- AI agents: consume registries to determine current branch stack, standing labels, evidence paths, known blockers, and forbidden operations.
- Reviewers: consume summaries to understand queue posture, feedback categories, and human review boundaries.
- Operators: consume state/evidence/rollback references for deployment and incident response.
- Governance reviewers: consume machine-readable boundary checks and validation reports.

## Validation

Operational memory validation must check:

- JSON parse and required field presence.
- Standing labels present and conservative.
- No signoff/final/external authority states.
- No `.auth` paths or secret-shaped values.
- No confidential/privileged content markers.
- Unresolved-source exclusions preserved.
- Reviewer ledger entries contain no freeform legal text or forbidden content.

## Rollback Model

Registry changes are git-revertable. If runtime visibility changes are deployed, rollback uses the previous frontend/backend artifacts plus git revert. Registry rollback must never alter legal evidence, source issue status, reviewer authority, or counsel signoff state.

## Security And Privacy Model

Operational memory is metadata-only. It may include counts, paths to repo docs/evidence, commit hashes, status labels, validation booleans, and safe categories. It must never include legal document body text, locked/restricted content, secrets, or auth/session material.

## Explicit Non-Authority

Operational memory does not:

- record counsel signoff;
- create final legal conclusions;
- authorize filing, service, sending, email, or external submission;
- override unresolved-source exclusions;
- authorize reviewer assignments or dispositions;
- mutate production data;
- change schema/RLS/policies.

## Result

`OPERATIONAL_MEMORY_DESIGNED_AS_QUERYABLE_GOVERNED_STATE_NOT_LEGAL_AUTHORITY`
