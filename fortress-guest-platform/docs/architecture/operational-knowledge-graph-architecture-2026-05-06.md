# Fortress Legal Operational Knowledge Graph Architecture

Date: 2026-05-06

## Purpose

The operational knowledge graph makes Fortress Legal operational cognition relationship-aware and queryable. It links operational state, capabilities, governance boundaries, evidence, remediation posture, deployment lineage, rollback posture, review queues, reviewer feedback categories, incidents, validation runs, checker runs, wiki knowledge nodes, and operational phases.

The graph is operational memory. It is not legal authority.

## Hard Boundaries

- The graph is not counsel signoff authority.
- The graph does not create final legal conclusions.
- The graph does not authorize filing, service, sending, email, or external submission.
- The graph does not override unresolved-source exclusions.
- The graph does not inspect, expose, or store confidential legal text.
- The graph does not inspect, expose, or store restricted document content.
- The graph does not store auth state, cookies, tokens, passwords, headers, database URLs, or service keys.
- The graph does not create autonomous legal decisions or governance overrides.
- The graph is read-only operational cognition unless a future governed write path is separately approved.

## Entity Types

- `operational_state`
- `capability`
- `governance_boundary`
- `evidence_bundle`
- `remediation_issue`
- `contradiction_cluster`
- `deployment`
- `rollback_event`
- `review_queue`
- `reviewer_feedback`
- `incident`
- `validation_run`
- `checker_run`
- `wiki_knowledge_node`
- `operational_phase`

## Relationship Types

- `supports`
- `blocks`
- `derives_from`
- `validated_by`
- `governed_by`
- `escalated_to`
- `linked_to`
- `supersedes`
- `references`
- `generated_from`
- `excluded_by`
- `observed_in`
- `mitigated_by`

## Governance Metadata

Every node and edge must carry enough metadata to support audit and rollback:

- `id`
- `type`
- `label`
- `standingLabels`
- `governanceBoundaries`
- `evidenceRefs`
- `validationRefs`
- `rollbackRefs`
- `noSecrets: true`
- `noConfidentialText: true`
- `humanReviewRequired` when the node or edge touches review, remediation, contradiction, or governance state
- `unresolvedSourceBoundary` when an entity or edge relates to unresolved sources

## Registry Relationship

The graph derives from the existing machine-readable registries:

- operational-state registry
- capability registry
- governance registry
- evidence registry
- remediation registry
- reviewer feedback ledger
- wiki knowledge index
- validation reports

Registries remain the deterministic state source. The graph expresses traversal relationships among those registries.

## Query Boundaries

Allowed query classes:

- Which governance boundaries govern a capability?
- Which evidence bundles validate an operational phase?
- Which remediation issues remain excluded?
- Which deployments and rollback events support current runtime state?
- Which reviewer feedback categories are allowed?
- Which wiki nodes describe a capability, evidence bundle, or governance boundary?

Forbidden query outcomes:

- counsel signoff
- final legal conclusion
- filing/service/email/external submission authority
- unrestricted reviewer authority
- source promotion
- restricted-content access
- confidential legal text exposure

## Rollback Model

The graph is file-backed and git-revertable. Runtime visibility is read-only. Rollback consists of reverting graph commits, restoring prior runtime operational-memory artifacts if deployed, and rerunning checker/deployment/pilot simulation verification.

## AI Agent Relationship

AI agents may consume the graph for deterministic operational context, but the graph does not grant legal authority. Agents must treat `governance_boundary`, `remediation_issue`, and `humanReviewRequired` metadata as hard constraints.
