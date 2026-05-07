# Fortress Legal Canonical Operational Knowledge Index

## Purpose

This is the current operational index for humans, AI sessions, reviewers, operators, and future engineers. It routes readers to the active systems, workflows, governance boundaries, evidence paths, and remaining blockers for Fortress Legal.

## Current Standing Labels

- Production status: `PRODUCTION_CAPABILITY_AUDIT_COMPLETE_PENDING_REVIEW`
- Counsel status: `COUNSEL_SIGNOFF_PENDING`
- External submission authority: `NOT_AUTHORIZED`
- Final legal conclusions: `NOT_CREATED`
- Legal advice status: `NOT FINAL LEGAL ADVICE`
- Schema/RLS/policy mutation: `NOT_PERFORMED`

## Canonical Source

- Canonical repo: `/home/admin/Fortress-Prime`
- Current phase worktree: `/home/admin/Fortress-Prime-capability-audit`
- Production domain: `https://crog-ai.com`
- Matter slug: `fortress-legal-production-review`
- Wiki repo: `/home/admin/fortress-legal-production-work/fortress-legal-wiki`

## Verification Systems

- Authenticated UI checker: `scripts/verification/check-crog-fortress-ui.mjs`
- Deployment verifier: `scripts/verification/verify-production-deployment.mjs`
- Controlled pilot simulation verifier: `scripts/verification/run-controlled-pilot-simulation.mjs`
- Internal reviewer tabletop verifier: `scripts/verification/run-internal-reviewer-tabletop.mjs`
- Checker usage guide: `scripts/verification/README.md`

## Core Legal Review Systems

- Counsel Review Workbench: `legal_counsel_workbench.py`, `counsel-review-workbench.tsx`
- Counsel Validation Workflow: `counsel-validation-workflow.tsx`
- Counsel Signoff Strategy Packet: `counsel-signoff-strategy-packet.tsx`
- Counsel Signoff Decision Workflow: `legal_counsel_signoff_decision.py`, `counsel-signoff-decision-workflow.tsx`
- Draft Work Product: `legal_draft_work_product.py`, `draft-work-product-panel.tsx`
- Autonomous Learning: `legal_autonomous_learning_loop.py`, `autonomous-learning-loop-panel.tsx`

## Source And Remediation Systems

- Source Integrity Validation: `legal_source_integrity_validation.py`, `source-integrity-validation-panel.tsx`
- Source Remediation: `legal_source_remediation.py`, `source-remediation-panel.tsx`
- Source Link Repair: `source-link-repair-panel.tsx`
- Targeted Source Completion: `targeted-source-completion-panel.tsx`
- Limited Signoff Candidate Packet: `limited-signoff-candidate-panel.tsx`
- Remediation Maturity / Review Queue: `legal_remediation_maturity.py`, `remediation-maturity-panel.tsx`, `review-operations-panel.tsx`

## Review Operations Systems

- Review queue maturity: `review-queue-maturity-model.md`
- Reviewer assignment framework: `reviewer-assignment-framework.md`
- Reviewer workload balancing: `reviewer-workload-balancing-model.md`
- Queue aging/SLA: `queue-aging-sla-model.md`
- Review analytics: `review-analytics-model.md`
- Contradiction review: `contradiction-review-model.md`
- Evidence lineage: `evidence-lineage-model.md`
- Human operations maturity: `human-operations-maturity-index.md`

## Governance Systems

- Governance enforcement: `governance-enforcement-verification.md`
- Pilot governance certification: `pilot-governance-certification-framework.md`
- Governance exceptions: `governance-exception-handling-2026-05-06.md`
- Reviewer onboarding governance: `reviewer-onboarding-governance-model.md`
- Operational feedback model: `operational-feedback-capture-model.md`
- Operational drift detection: `operational-drift-detection-model.md`
- AI behavior boundaries in wiki: `wiki/legal-domain/ai-behavior-boundaries.md`
- Legal boundaries in wiki: `wiki/legal-domain/legal-boundaries.md`

## Deployment, Rollback, And Observability

- Observability map: `fortress-legal-observability-map.md`
- Deployment repeatability: `deployment-repeatability-plan-2026-05-06.md`
- Service health hardening: `service-health-hardening-2026-05-06.md`
- Rollback certification: `rollback-certification-2026-05-06.md`
- Production error audit: `production-error-audit-2026-05-06.md`
- Operational safety certification: `operational-safety-certification-2026-05-06.md`

## Pilot And Human Operations

- Controlled pilot readiness: `controlled-review-pilot-readiness-2026-05-06.md`
- Controlled review scaling readiness: `controlled-review-scaling-pilot-readiness-2026-05-06.md`
- Controlled internal pilot plan: `controlled-internal-pilot-execution-plan-2026-05-06.md`
- Internal pilot workload model: `internal-pilot-workload-model.md`
- Internal pilot drills: `internal-pilot-incident-and-rollback-drill-2026-05-06.md`
- Internal reviewer tabletop: `internal-reviewer-tabletop-operational-validation-2026-05-06.md`
- Human operations audit: `human-operations-readiness-audit-2026-05-06.md`
- Human incident rehearsal: `human-operations-incident-rehearsal-2026-05-06.md`

## Capability And Cognition Audits

- Full platform capability audit: `full-platform-capability-audit-2026-05-06.md`
- Wiki knowledge-plane audit: `wiki-knowledge-plane-audit-2026-05-06.md`
- AI-assisted operations audit: `ai-assisted-operations-audit-2026-05-06.md`
- Governance maturity audit: `governance-maturity-audit-2026-05-06.md`
- World-class future state architecture: `world-class-future-state-architecture-2026-05-06.md`

## Active Evidence Roots

- Canonicalization: `docs/operational/evidence/2026-05-06-canonicalization/`
- Feature alignment: `docs/operational/evidence/2026-05-06-feature-alignment/`
- Operational hardening: `docs/operational/evidence/2026-05-06-operational-hardening/`
- Remediation maturity: `docs/operational/evidence/2026-05-06-remediation-maturity/`
- Review operations: `docs/operational/evidence/2026-05-06-review-operations/`
- Review scaling: `docs/operational/evidence/2026-05-06-review-scaling/`
- Operational certification: `docs/operational/evidence/2026-05-06-operational-certification/`
- Internal pilot: `docs/operational/evidence/2026-05-06-internal-pilot/`
- Internal reviewer tabletop: `docs/operational/evidence/2026-05-06-internal-reviewer-tabletop/`
- Human operations: `docs/operational/evidence/2026-05-06-human-operations/`
- Capability audit: `docs/operational/evidence/2026-05-06-capability-audit/`

## Open Blockers

- 232 unresolved source issues remain excluded from relied-upon sections.
- Counsel signoff remains pending.
- Public launch remains forbidden.
- External legal operations remain forbidden.
- Persistent reviewer assignment writes remain deferred.
- Wiki/app operational memory is not yet unified into machine-readable registries.
- Durable reviewer feedback/disposition/exception ledgers are not implemented.

## Future Engineering Priorities

1. Create a machine-readable operational state registry.
2. Add durable reviewer onboarding acknowledgments.
3. Add structured review feedback/disposition ledger with no confidential text.
4. Add governance exception register defaulting to deny.
5. Build source-remediation graph for unresolved source issues.
6. Generate AI session start packs from repo/wiki/evidence state.
7. Replace text-selector-only verification with semantic route/API contracts where feasible.

## Hard Boundaries

Any future phase must preserve:

- `COUNSEL_SIGNOFF_PENDING`
- `NOT_AUTHORIZED`
- `NOT_CREATED`
- `NOT FINAL LEGAL ADVICE`
- unresolved-source exclusion
- metadata-only restricted handling
- no schema/RLS/policy mutation unless separately approved
- no secrets/auth state/document body text in evidence
