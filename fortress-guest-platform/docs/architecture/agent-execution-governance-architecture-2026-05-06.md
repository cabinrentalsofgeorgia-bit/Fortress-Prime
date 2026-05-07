# Fortress Legal Agent Execution Governance Architecture

Date: 2026-05-06
Status: ACTIVE FOR GOVERNED OPERATIONS DESIGN

## Purpose

Agent execution governance makes Fortress Legal operationally usable by AI agents without granting legal authority. The system can classify requested work, produce bounded task plans, validate hard-stop policies, and record evidence-backed execution reports. It is an operations-control layer, not autonomous legal practice.

## Scope

The scope is limited to metadata-only orchestration over operational memory, the operational knowledge graph, governance registries, checker/verifier tooling, evidence references, and safe documentation or validation work.

Allowed orchestration includes:

- reading operational state;
- reading governance registries;
- reading the operational graph;
- generating context packs;
- summarizing evidence references;
- running validators and checkers;
- creating governance docs and evidence summaries;
- generating plans and reports;
- proposing pull requests;
- updating nonlegal machine-readable status registries when safe and reviewable.

Forbidden orchestration includes:

- counsel signoff;
- final legal conclusions;
- filing, service, email, or external submission;
- public launch authorization;
- document upload or intake;
- ingestion reruns;
- vector writes;
- schema/RLS/policy mutation;
- restricted-content inspection;
- confidential text exposure;
- unresolved-source promotion;
- auth bypass;
- secret printing;
- uncontrolled reviewer authority escalation.

## Agent Roles

- `agent_governance`: interprets governance boundaries and hard stops.
- `task_schema`: validates task, plan, report, and evidence structure.
- `risk_classifier`: maps task requests to risk classes.
- `task_planner`: creates validation-gated task plans.
- `execution_reporter`: records actions attempted, skipped, blocked, and validated.
- `evidence_agent`: links reports to evidence directories.
- `checker_agent`: verifies production visibility without exposing auth state.

All roles are subordinate to standing labels and human review. No role may infer counsel signoff, final advice, external authority, source promotion, or schema authority.

## Execution Lifecycle

1. Query operational state and governance context.
2. Classify requested actions.
3. Reject hard-stop actions.
4. Generate a bounded plan with allowed actions only.
5. Attach validation gates and evidence requirements.
6. Execute only read-only or explicitly safe-write tasks.
7. Record skipped and blocked actions.
8. Run validators/checkers.
9. Produce an execution report.
10. Preserve rollback and human-review requirements.

## Risk Classes

- `safe_read_only`
- `safe_docs_only`
- `safe_validation_only`
- `safe_governance_update`
- `safe_read_only_ui`
- `guarded_code_change`
- `requires_human_approval`
- `hard_stop`

Risk classification is conservative. If a task requests any forbidden action, the classifier returns `hard_stop` or `requires_human_approval` and records the blocking policy.

## Hard Stops

Hard stops trigger before execution. The task runner must stop on:

- secrets or auth material exposure risk;
- confidential or privileged content exposure risk;
- restricted-content boundary violation;
- schema/RLS/policy mutation requirement;
- production instability risk;
- rollback impossibility;
- unresolved auth failure;
- uncontrolled reviewer authority risk;
- uncontrolled legal automation risk;
- legal signoff, final legal advice, external submission, ingestion/upload, vector writes, source promotion, or restricted-content inspection.

## Validation Gates

Required gates include:

- orchestration registry validation;
- operational memory validation;
- knowledge graph validation;
- governance query smoke tests;
- checker/verifier execution when production UI is affected;
- no-secret and no-auth scans;
- no-confidential-text scans;
- no authority-state scans;
- `git diff --check`;
- focused tests for touched UI/API/scripts.

## Evidence Requirements

Every task report must include:

- task ID;
- risk class;
- allowed actions;
- forbidden actions;
- hard stops evaluated;
- validations run;
- evidence refs;
- rollback refs;
- standing labels;
- human review requirement.

Evidence must not contain document body text, secrets, auth state, restricted content, final legal advice, counsel signoff, external authority, or unresolved-source promotion.

## Relationship to Existing Systems

- Governance query engine: provides current standing, blockers, safe actions, forbidden actions, evidence refs, and phase recommendations.
- Operational graph: links capabilities, evidence, governance boundaries, remediation posture, validations, and rollback lineage.
- Agent context packs: provide deterministic read-first context for future Codex sessions and operators.
- Checker/verifier systems: prove UI/API visibility and auth boundaries without exposing credentials.

## Authority Boundaries

Agents cannot sign off, create final legal conclusions, authorize external submission, inspect restricted content, promote unresolved sources, mutate schema/RLS/policies, bypass auth, or override the governance registry.

Standing labels remain:

- Counsel status: `COUNSEL_SIGNOFF_PENDING`
- External submission authority: `NOT_AUTHORIZED`
- Final legal conclusions: `NOT_CREATED`
- Legal advice status: `NOT FINAL LEGAL ADVICE`
- Schema/RLS/policy mutation: `NOT_PERFORMED`

## Rollback

All changes in this phase are git-revertable. Generated plans and reports are file-backed operational evidence and may be deleted or superseded by reverting the relevant commit. No production legal data, document rows, vector points, schema, RLS, or policies are modified.
