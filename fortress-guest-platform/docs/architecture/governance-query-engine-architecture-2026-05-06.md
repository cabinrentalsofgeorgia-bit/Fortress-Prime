# Fortress Legal Governance Query Engine Architecture

Date: 2026-05-06

## Purpose

The governance query engine turns operational memory and the operational knowledge graph into deterministic, read-only operating guidance for agents, reviewers, operators, deployment verification, remediation planning, governance review, and controlled next-action selection.

The query engine is operational guidance. It is not legal authority.

## Inputs

- `operational-memory/registries/operational-state.json`
- `operational-memory/registries/capability-registry.json`
- `operational-memory/registries/governance-registry.json`
- `operational-memory/registries/evidence-registry.json`
- `operational-memory/registries/remediation-registry.json`
- `operational-memory/registries/reviewer-feedback-ledger.json`
- `operational-memory/registries/wiki-knowledge-index.json`
- `operational-memory/graph/graph.json`
- `operational-memory/graph/graph-validation-report.json`

## Outputs

Allowed outputs are metadata-only:

- standing labels
- current capabilities
- blockers
- evidence references
- validation references
- governance boundaries
- safe next actions
- forbidden actions
- human-review requirements
- recommended next phase
- files/docs/evidence a new AI session should read first

Forbidden outputs:

- confidential legal text
- restricted-content body text
- secrets, auth state, cookies, tokens, passwords, headers, service keys, database URLs
- counsel signoff
- final legal conclusions
- filing, service, sending, email, or external submission authority
- source promotion
- autonomous governance overrides

## Query Categories

- standing state
- current capabilities
- current blockers
- signoff blockers
- external launch blockers
- evidence for phase or capability
- validation for capability
- governance boundaries
- safe next actions
- forbidden actions
- agent operating context
- reviewer operating context
- remediation status
- unresolved-source boundary
- deployment readiness
- rollback readiness
- human review requirements
- phase progression

## Authority Boundaries

The query engine must always preserve:

- `COUNSEL_SIGNOFF_PENDING`
- `NOT_AUTHORIZED`
- `NOT_CREATED`
- `NOT FINAL LEGAL ADVICE`
- `Schema/RLS/policy mutation: NOT_PERFORMED`

It may recommend operational next actions. It may not create legal decisions, signoff, final conclusions, external authority, production data mutation, or source promotion.

## Agent Usage Model

Agents may use query output as deterministic starting context:

- read the listed docs first
- respect hard stops
- run listed validators/checkers
- keep changes scoped to the recommended phase
- preserve evidence and rollback requirements

Agents must not treat query output as permission to bypass human review, counsel review, authentication, restricted-content boundaries, or deployment governance.

## Reviewer / Operator Usage Model

Reviewers and operators may use query output to understand current posture, blockers, evidence support, and safe next actions. They still need human/counsel review for legal interpretation, signoff, source acceptance, and external-use decisions.

## Rollback

The query engine is file-backed and git-revertable. Runtime visibility is read-only. Rollback is git revert plus runtime artifact restore if deployed.
