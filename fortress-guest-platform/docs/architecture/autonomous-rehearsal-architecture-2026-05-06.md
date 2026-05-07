# Fortress Legal Autonomous Rehearsal Architecture

Date: 2026-05-06
Status: ACTIVE FOR GOVERNED DRY-RUNS

## Purpose

Autonomous rehearsal exercises Fortress Legal agent orchestration without granting autonomy over legal operations. It validates that agents can plan, simulate, block, trace, replay, and report governed work while preserving hard stops, rollback, evidence lineage, and human review.

## Dry-Run Lifecycle

1. Select a dry-run category.
2. Load the existing agent plan or generate a metadata-only plan.
3. Validate allowed and forbidden actions.
4. Simulate execution states without production mutation.
5. Stop on hard-stop triggers.
6. Record blocked actions and validation gates.
7. Write a non-sensitive execution trace.
8. Replay the trace to confirm deterministic governance behavior.
9. Produce evidence and rollback references.
10. Preserve human review and standing labels.

## Execution Trace Lifecycle

Execution traces record only operational metadata:

- dry-run ID;
- category;
- plan ID;
- decisions taken;
- simulated states;
- blocked actions;
- hard stops triggered;
- validation gates;
- evidence refs;
- rollback refs;
- governance assertions.

Traces must not contain secrets, auth state, confidential legal text, restricted-content, legal conclusions, signoff statements, external submission instructions, or source-promotion outcomes.

## Replay Lifecycle

Replay re-checks:

- allowed category;
- forbidden category;
- blocked actions;
- hard-stop decisions;
- standing labels;
- governance assertions;
- validation gates;
- rollback refs.

Replay is non-destructive and must not execute real production operations.

## Safe Dry-Run Categories

- validation-only;
- governance-query;
- evidence-summary;
- registry-update-simulation;
- remediation-triage-simulation;
- contradiction-review-simulation;
- queue-navigation-simulation;
- deployment-verification-simulation;
- rollback-tabletop;
- incident-tabletop;
- reviewer-guidance-simulation;
- context-generation;
- checker-verification;
- documentation-generation.

## Forbidden Dry-Run Categories

- legal signoff;
- final legal conclusion;
- external submission;
- public launch;
- restricted-content inspection;
- confidential text output;
- schema mutation;
- RLS mutation;
- source promotion;
- production data mutation;
- unrestricted reviewer assignment;
- auth bypass.

## Human Approval Boundaries

Dry-runs can recommend next steps but cannot approve counsel signoff, final legal advice, external launch, filing, service, email, source promotion, restricted-content review, schema/RLS/policy mutation, ingestion, vector writes, or unrestricted reviewer authority.

## Rollback

Rollback is git-revertable. Dry-run traces and replays are file-backed evidence and may be deleted or superseded by reverting this phase. No production legal data, vectors, document rows, schema, RLS, or policies are modified.

## Standing Labels

- Counsel status: `COUNSEL_SIGNOFF_PENDING`
- External submission authority: `NOT_AUTHORIZED`
- Final legal conclusions: `NOT_CREATED`
- Legal advice status: `NOT FINAL LEGAL ADVICE`
- Schema/RLS/policy mutation: `NOT_PERFORMED`
