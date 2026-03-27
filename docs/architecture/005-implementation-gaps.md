# 005 Implementation Gaps

Strict audit of the reviewed Swarm surfaces against `docs/architecture/005-nemoclaw-swarm-architecture.md`.

## Nervous System

- RESOLVED: `fortress-guest-platform/backend/vrs/infrastructure/seo_event_bus.py` no longer embeds full rewrite feedback JSON inside Redis queue payloads. Rewrite requests now travel as reference-only envelopes and the worker hydrates state from Postgres.
- RESOLVED: `fortress-guest-platform/backend/vrs/infrastructure/seo_event_bus.py` no longer LPUSHes arbitrary remap JSON to `fortress:seo:remap_grade_requests`. The remap publish path now emits a canonical reference envelope keyed by the queue row UUID.
- RESOLVED: `fortress-guest-platform/backend/services/seo_grading_service.py` no longer copies raw malformed queue payloads into DLQ metadata. DLQ routing now stores only bounded diagnostic fields and the authoritative context reference.
- COMPLIANT: `fortress-guest-platform/backend/vrs/infrastructure/seo_event_bus.py` physically defines both `fortress:seo:dlq` and `fortress:swarm:dlq`, and `publish_swarm_dlq()` actively routes failures into both queues.
- COMPLIANT: `fortress-guest-platform/backend/services/seo_grading_service.py` actively routes malformed messages, missing patch or rubric state, null-score outcomes, and exhausted rewrite attempts into the swarm DLQ.
- COMPLIANT: `fortress-guest-platform/backend/core/worker.py` boots long-lived SEO BRPOP consumers alongside the ARQ worker, which matches the `005` asynchronous choreography doctrine.

## Tool Binding & Security Boundaries

- RESOLVED: `fortress-guest-platform/backend/api/seo_patches.py` now enforces strict `verify_swarm_token` on Swarm ingestion and evaluator routes. Human review surfaces remain on staff JWT dependencies.
- RESOLVED: `fortress-guest-platform/backend/api/seo_remaps.py` now enforces strict `verify_swarm_token` on machine grade-result ingestion instead of dual-mode auth.
- RESOLVED: `fortress-guest-platform/backend/core/security_swarm.py` remains the strict `X-Swarm-Token` validator for M2M routes, and the legacy dual-mode dependency is no longer used on audited Swarm ingress surfaces.
- RESOLVED: `fortress-guest-platform/backend/services/seo_grading_service.py` now sends an allowlisted rubric contract, summarized JSON-LD, and scrubbed text through the cloud grading lane, and it fails closed to the local grading route if property identifiers survive masking.
- COMPLIANT: `fortress-guest-platform/backend/core/security_swarm.py` does implement `X-Swarm-Token` validation via `verify_swarm_token()` with constant-time comparison and sovereign-configured keys.
- COMPLIANT: `fortress-guest-platform/backend/api/seo_patches.py` keeps human review and approval routes on staff JWT boundaries via `get_current_user`.

## Reviewed Surface Summary

- RESOLVED: Queue payload discipline is now aligned for the audited rewrite, remap, and malformed-message DLQ flows. Redis carries reference envelopes rather than heavy workflow payloads on those surfaces.
- RESOLVED: M2M boundary enforcement is now aligned for the audited Swarm ingress routes. Reviewed machine endpoints require `X-Swarm-Token` and fail closed without it.
- RESOLVED: Frontier grading now follows a masked, minimum-necessary payload contract with a local-only safety fallback when external payload scrubbing cannot prove compliance.
