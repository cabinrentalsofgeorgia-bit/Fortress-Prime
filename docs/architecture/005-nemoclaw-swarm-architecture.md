# 005 NemoClaw Swarm Architecture

This document is the authoritative architecture contract for NeMo Claw, sovereign swarm orchestration, evaluator routing, and asynchronous cross-agent execution inside Fortress Prime. It extends `docs/architecture/004-postgres-contract.md` and is subordinate only to the Constitution, Requirements, and sovereign doctrine.

## THE IRON LAYER: HARDWARE & MODEL TIERING

- NeMo Claw is the sovereign local orchestration layer for DGX swarm execution. It MUST run inside Fortress Prime and MUST remain subordinate to the data-sovereignty, tunnel, and Strangler Fig rules already established by sovereign law.
- NeMo Claw MUST be treated as a cluster-local control plane, not a public service. Public ingress to NeMo Claw is prohibited.
- The authoritative client boundary for NeMo Claw MUST remain config-driven through `nemoclaw_orchestrator_url`. Callers MUST NOT hardcode worker-node identity.
- This contract resolves the current mixed placement story as follows:
  - Leadership MAY float between DGX nodes operationally.
  - The authoritative control-plane identity MUST remain a single sovereign local endpoint.
  - Heavy inference execution MAY fan out across DGX workers, but orchestration authority remains logically singular.
- Tiering law:
  - Tactical Edge: FastAPI ingress, auth, queue producers, cache invalidation triggers, and human approval surfaces.
  - Heavy Iron: local DGX inference workers, local Ollama or equivalent sovereign model serving, Redis choreography, PostgreSQL state, Qdrant or equivalent vector memory, and NAS-backed artifacts.
  - Frontier Consensus: evaluator or reviewer tier for grading, critique, or consensus scoring. It is a gated tier, never the system of record.
- Frontier Consensus MUST NOT receive raw sovereign payloads. Any Tier 1 reviewer outside the core sovereign compute boundary MUST receive only masked, derived, minimum-necessary artifacts.
- Sensitive data classes including guest PII, financial records, legal evidence, raw ledgers, and private operational context MUST remain on approved local hardware.
- External evaluator use is permitted only for masked derived payloads and NEVER for raw operational state.
- Frontier Consensus is not the same thing as the legal-council consensus system. The former is an evaluator lane for operational swarms. The latter is a legal deliberation subsystem with separate semantics, evidence rules, and queue responsibilities.
- SWARM mode remains the default production execution mode. Deep or strategic escalation MUST still obey existing sovereign routing law and MUST NOT weaken local-first inference requirements.
- No architecture under this contract may imply direct public traffic from `cabin-rentals-of-georgia.com` into internal orchestration. Domain separation remains absolute.

## SOVEREIGN MEMORY & STATE MANAGEMENT

- PostgreSQL is the primary state authority for work units, approvals, audit fields, and deployment state.
- Redis is the mandatory choreography substrate for swarm coordination. Durable work handoff MUST use Redis queue semantics. Ephemeral fan-out MAY use pub/sub only for advisory notifications, never as the sole source of truth.
- NAS-backed storage remains the authority for heavy documents, vault material, extracted artifacts, model-adjacent files, and golden snapshots.
- Vector memory remains local-first and MUST store only data classes permitted by sovereign law.
- Redis payload doctrine:
  - Queue messages MUST carry references, not heavy payloads.
  - The canonical payload form is task identity plus context references, queue target, status, and metadata.
  - Raw documents, raw HTML, large JSON blobs, legal evidence bodies, and guest PII MUST NOT be embedded in queue payloads.
- The current `SwarmEventEnvelope` pattern is elevated into doctrine:
  - `task_id` identifies the unit of work.
  - `context_refs` identify the authoritative database records or artifact IDs.
  - `source_agent` and `target_queue` define provenance and routing.
  - `status` records lifecycle phase.
  - `metadata` carries only bounded, non-heavy operational context.
- All swarm state transitions MUST be replayable from authoritative storage plus queue envelopes.
- Any cache layer is derivative state only. Cache loss MUST NOT compromise authoritative workflow state.
- Edge SEO payloads, live metadata, and approval outcomes MUST be reconstructable from PostgreSQL without trusting Redis persistence.
- Sovereign data masking MUST happen before any payload exits the core local trust boundary for evaluation or review.
- Human approval artifacts MUST remain attached to authoritative records, not reconstructed from queue history alone.

## THE NERVOUS SYSTEM: ASYNCHRONOUS CHOREOGRAPHY

- Agent-to-agent HTTP is not an approved default architecture. Cross-agent coordination MUST prefer asynchronous choreography over direct peer invocation.
- FastAPI ingress may authenticate, validate, persist work, and enqueue references. It MUST NOT become a mesh of synchronous agent RPC chains.
- The current worker pattern in `backend/core/worker.py` is the reference doctrine:
  - ARQ or equivalent job workers boot first-class background consumers.
  - Long-lived Redis consumers run alongside the worker runtime.
  - Consumer crashes MUST surface as fatal operational signals, not silent degradation.
- Redis queue naming is part of architectural law. Existing queue names remain canonical:
  - `fortress:seo:grade_requests`
  - `fortress:seo:rewrite_requests`
  - `fortress:seo:deploy_events`
  - `fortress:seo:dlq`
  - `fortress:swarm:dlq`
- New swarm domains MUST follow the same namespacing pattern:
  - `fortress:<domain>:<action>`
  - `fortress:<domain>:dlq`
- `fortress:swarm:dlq` is the cross-swarm dead-letter standard. Domain-local DLQs MAY mirror into it, but the cross-swarm DLQ is mandatory.
- LPUSH and BRPOP style durable queue semantics are the approved baseline for at-least-once delivery. If another Redis primitive is introduced, it MUST preserve durability, bounded retry policy, and replay visibility.
- The SEOPatch swarm-to-edge flow is the current reference implementation:
  - draft patch
  - enqueue grade request
  - evaluator returns pass or critique
  - enqueue rewrite request if needed
  - escalate to human review
  - approve or reject
  - publish deploy event
  - revalidate edge caches
- Human-in-the-loop remains mandatory for public output that changes deployed guest-facing content, legal posture, financial consequence, or irreversible workflow state.
- The Strangler Fig rule applies to swarm choreography:
  - New swarm lanes MUST be additive.
  - Legacy bridges MAY remain until the new asynchronous lane is proven.
  - Cutover MUST NOT break SEO continuity, booking continuity, or audit traceability.

## TOOL BINDING & SECURITY BOUNDARIES

- All tool binding MUST respect zero-trust boundaries.
- Machine-to-machine swarm ingress MUST authenticate with `X-Swarm-Token` or a stricter sovereign replacement. This header pattern is now contractual for swarm M2M boundaries.
- Human staff access MUST continue to authenticate separately through staff JWT boundaries. Swarm auth and human auth MUST NOT be conflated.
- NeMo Claw clients MUST use config-defined endpoints and sovereign credentials only. Clients MUST NOT bypass the configured control-plane boundary.
- Any NeMo Claw or swarm service carrying inference prompts across nodes MUST remain inside the approved local network boundary unless the payload is masked and expressly permitted by sovereign law.
- Cloudflare Tunnels remain the only sanctioned public ingress path. No doctrine under this contract authorizes opening raw orchestration ports to the public internet.
- Public storefront traffic and internal command traffic MUST remain domain-separated:
  - `cabin-rentals-of-georgia.com` serves public guest experiences.
  - `crog-ai.com` serves staff and agent infrastructure.
  - No direct orchestration tooling may be exposed through the public storefront domain.
- Tool binding doctrine:
  - Tools MUST execute against local FastAPI, local PostgreSQL, local Redis, local NAS, and local model runtimes by default.
  - Tools MUST request only the minimum data required for a task.
  - Tools MUST write auditable state transitions before triggering downstream execution where the workflow is durable.
- Frontier Consensus boundary law:
  - Frontier Consensus MUST consume masked derived artifacts only.
  - It MUST NOT receive direct database credentials.
  - It MUST NOT receive unrestricted tool access into sovereign stores.
  - It MUST NOT be described as or reused as the legal-council system.
- The legal-council subsystem remains a separate sovereign deliberation mechanism and MUST keep its own terminology, approval semantics, and evidence controls.

## FAILURE DOMAINS & DEAD LETTER QUEUES (DLQ)

- Every swarm lane MUST define its own failure domain and bounded retry policy.
- No consumer may retry indefinitely.
- Every exhausted retry path MUST terminate in a DLQ record with enough metadata to reconstruct the failure.
- `fortress:swarm:dlq` is mandatory for cross-swarm dead lettering.
- Domain-local DLQs such as `fortress:seo:dlq` MUST remain permitted and SHOULD mirror into `fortress:swarm:dlq` when the failure has cross-domain operational relevance.
- A DLQ payload MUST include, at minimum:
  - `task_id`
  - `source_agent`
  - `failed_queue`
  - `context_refs`
  - bounded error summary
  - bounded terminal trace metadata
- DLQ payloads MUST remain reference-based and MUST NOT become raw artifact dumps.
- DLQ handling MUST preserve human control:
  - Operators MUST be able to inspect failed work without replaying heavy payloads.
  - Replay MUST be explicit and auditable.
  - Poison messages MUST be isolatable without draining healthy queues.
- Failure isolation law:
  - A grading consumer failure MUST NOT take down deploy consumers.
  - A rewrite consumer failure MUST NOT corrupt already-approved state.
  - A frontier evaluator outage MUST degrade to queued backlog or human escalation, not silent data loss.
  - A cache invalidation failure MUST NOT roll back authoritative approval state.
- If an external evaluator lane is unavailable, the system MUST fail closed on sensitive review routing and MUST keep authoritative work local.
- If NeMo Claw leadership changes nodes, queue identity and state authority MUST survive the transition through Redis and PostgreSQL, not process-local memory.
- Golden Snapshot doctrine remains in force for destructive recovery or legal-schema repair. This architecture does not waive any snapshot requirement from sovereign law.
