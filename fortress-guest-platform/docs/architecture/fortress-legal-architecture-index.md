# Fortress Legal Canonical Architecture Index

Last updated: `2026-05-06`

## Canonical Platform

- Canonical repository: `/home/admin/Fortress-Prime`
- Canonical branch: `release/fortress-legal-canonicalization`
- Production domain: `https://crog-ai.com`
- Matter: Fortress Legal Production Review
- Matter slug: `fortress-legal-production-review`

This index maps the canonical Fortress Legal production architecture without exposing legal document contents, auth state, secrets, or locked/restricted content.

## Frontend Surfaces

Command Center app:

- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/page.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/page.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/case-detail-shell.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/counsel-review-workbench.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/counsel-validation-workflow.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/counsel-signoff-strategy-packet.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/counsel-signoff-decision-workflow.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/source-integrity-validation-panel.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/source-remediation-panel.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/source-link-repair-panel.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/targeted-source-completion-panel.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/limited-signoff-candidate-panel.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/autonomous-learning-loop-panel.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/draft-work-product-panel.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/document-viewer.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/master-timeline.tsx`
- `fortress-guest-platform/apps/command-center/src/app/(dashboard)/legal/cases/[slug]/_components/graph-snapshot-card.tsx`

Shared frontend data contracts:

- `fortress-guest-platform/apps/command-center/src/lib/legal-hooks.ts`
- `fortress-guest-platform/apps/command-center/src/lib/legal-types.ts`

## Backend Services

Core legal workflow services:

- `fortress-guest-platform/backend/services/legal_counsel_workbench.py`
- `fortress-guest-platform/backend/services/legal_counsel_validation.py`
- `fortress-guest-platform/backend/services/legal_counsel_signoff_packet.py`
- `fortress-guest-platform/backend/services/legal_counsel_signoff_decision.py`
- `fortress-guest-platform/backend/services/legal_source_integrity_validation.py`
- `fortress-guest-platform/backend/services/legal_source_remediation.py`
- `fortress-guest-platform/backend/services/legal_source_link_repair.py`
- `fortress-guest-platform/backend/services/legal_targeted_source_completion.py`
- `fortress-guest-platform/backend/services/legal_limited_signoff_candidate_packet.py`
- `fortress-guest-platform/backend/services/legal_autonomous_learning_loop.py`
- `fortress-guest-platform/backend/services/legal_draft_work_product.py`

Supporting legal services:

- `legal_ediscovery.py`
- `legal_vector_sync.py`
- `legal_case_graph.py`
- `legal_chronology.py`
- `legal_drafter.py`
- `legal_docgen.py`
- `legal_motion_drafter.py`
- `legal_deposition_engine.py`
- `legal_deposition_outline_engine.py`
- `legal_deposition_prep.py`
- `legal_discovery_engine.py`
- `legal_discovery_validator.py`
- `legal_sanctions_tripwire.py`
- `legal_mail_ingester.py`
- `legal_email_intake.py`
- `legal_dispatcher.py`
- `legal_council.py`
- `legal_agent_orchestrator.py`
- `legal_hive_mind.py`
- `legal_search_engine.py`
- `legal/cite_verifier.py`

## API Routes

Legal API modules:

- `fortress-guest-platform/backend/api/legal_cases.py`
- `fortress-guest-platform/backend/api/legal_workbench.py`
- `fortress-guest-platform/backend/api/legal_graph.py`
- `fortress-guest-platform/backend/api/legal_discovery.py`
- `fortress-guest-platform/backend/api/legal_deposition.py`
- `fortress-guest-platform/backend/api/legal_sanctions.py`
- `fortress-guest-platform/backend/api/legal_tactical.py`
- `fortress-guest-platform/backend/api/legal_hold.py`
- `fortress-guest-platform/backend/api/legal_docgen.py`
- `fortress-guest-platform/backend/api/legal_agent.py`
- `fortress-guest-platform/backend/api/legal_council.py`
- `fortress-guest-platform/backend/api/legal_email_intake_api.py`

Workbench API surface includes read-only loaders and governed action endpoints for:

- Counsel workbench.
- Counsel validation.
- Counsel signoff packet.
- Source integrity/remediation/link repair.
- Targeted source completion.
- Limited signoff candidate packet.
- Counsel signoff decision workflow.
- Autonomous learning feedback.
- Draft work product.

## Scripts

Governed production-review scripts:

- `fortress-guest-platform/backend/scripts/fortress_counsel_review_workbench.py`
- `fortress-guest-platform/backend/scripts/fortress_counsel_validation_workflow.py`
- `fortress-guest-platform/backend/scripts/fortress_counsel_signoff_packet.py`
- `fortress-guest-platform/backend/scripts/fortress_counsel_signoff_decision_workflow.py`
- `fortress-guest-platform/backend/scripts/fortress_source_integrity_validation.py`
- `fortress-guest-platform/backend/scripts/fortress_source_remediation.py`
- `fortress-guest-platform/backend/scripts/fortress_source_link_repair.py`
- `fortress-guest-platform/backend/scripts/fortress_targeted_source_completion.py`
- `fortress-guest-platform/backend/scripts/fortress_limited_signoff_candidate_packet.py`
- `fortress-guest-platform/backend/scripts/fortress_autonomous_learning_loop.py`
- `fortress-guest-platform/backend/scripts/fortress_draft_work_product.py`

Verification infrastructure:

- `scripts/verification/check-crog-fortress-ui.mjs`
- `scripts/verification/README.md`

## Evidence And Manifests

Primary file-backed audit location:

- `/mnt/fortress_nas/audits`

Representative manifest prefixes:

- `fortress-counsel-review-*`
- `fortress-validation-*`
- `fortress-signoff-packet-*`
- `fortress-source-integrity-*`
- `fortress-source-remediation-*`
- `fortress-source-link-repair-*`
- `fortress-targeted-source-completion-*`
- `fortress-limited-signoff-candidate-*`
- `fortress-signoff-decision-*`
- `fortress-learning-loop-*`
- `fortress-draft-work-product-*`

Operational docs:

- `fortress-guest-platform/docs/operational/fortress-legal-*.md`

## Retrieval And Source Remediation Systems

Retrieval and source review are bounded by existing ingested data and existing source metadata:

- Source Integrity Validation classifies material items.
- Source Remediation refines unresolved blocker categories.
- Source Link Repair validates existing non-locked source routing.
- Targeted Source Completion expands verified subsets without ingestion or vector creation.
- Limited Signoff Candidate Packet scopes review-ready material.

Forbidden during these workflows:

- New document upload or ingestion.
- New Qdrant/vector points.
- Locked/restricted content inspection.
- Schema/RLS/policy mutation.

## Draft Work Product System

Draft work product is generated from the limited source-verified subset only:

- Backend: `legal_draft_work_product.py`
- Script: `fortress_draft_work_product.py`
- UI: `draft-work-product-panel.tsx`
- Evidence: `fortress-legal-draft-work-product-2026-05-06.md`

Required labels:

- `DRAFT / COUNSEL REVIEW REQUIRED`
- `NOT FINAL LEGAL ADVICE`
- `NOT AUTHORIZED FOR FILING, SERVICE, SENDING, EMAIL, OR EXTERNAL SUBMISSION`
- `SOURCE-VERIFIED SUBSET ONLY`
- `COUNSEL_SIGNOFF_PENDING`

## Counsel Validation And Signoff System

Counsel signoff is explicit-action only:

- Operator acknowledgment is not counsel signoff.
- Counsel signoff is scoped to approved items/sections/packet.
- No workflow may infer signoff.
- No workflow may create final legal conclusions.
- No workflow may authorize external submission.

## Autonomous Learning System

Autonomous learning is bounded and auditable:

- Observes metadata/manifests.
- Runs evaluation checks.
- Generates improvement proposals.
- Gates safe auto-apply.
- Captures feedback.
- Preserves human/counsel gates.
- Does not train external models on confidential legal data.

## Known Open Blockers

- 232 source issues remain unresolved and excluded from relied-upon draft sections.
- Counsel signoff remains pending.
- Production checker currently reports Draft Work Product and Autonomous Learning panels not visible.
- Fortress-Prime remote fetch/push from this host currently fails by SSH public-key denial.
- Unrelated dirty files exist in the worktree and must not be staged.
- `fortress-legal-app` is not feature-equivalent and should not be treated as production source without a deliberate migration project.

## Standing Labels

- Production status: `PRODUCTION_SOURCE_OF_TRUTH_CANONICALIZATION_IN_PROGRESS`
- Product status: `FORTRESS_PRIME_CANONICAL_LEGAL_PRODUCTION_REPO`
- Counsel status: `COUNSEL_SIGNOFF_PENDING`
- External submission authority: `NOT_AUTHORIZED`
- Final legal conclusions: `NOT_CREATED`
- Schema/RLS/policy mutation: `NOT_PERFORMED`
