# Cross-Division Flow: Council Retrieval

Last updated: 2026-04-26

## Summary

Council deliberation freezes context from Qdrant for a given case before invoking the persona panel. PR G (#214) made this **privilege-aware** and **cross-matter aware**: deliberation pulls from BOTH the work-product collection AND the privileged collection (when `COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL=true`), and expands retrieval to every slug in the case's `legal.cases.related_matters` JSONB (when `COUNCIL_INCLUDE_RELATED_MATTERS=true`). Both env vars are read **at deliberation time**, not at backend startup, so emergency containment doesn't require a restart.

This flow consumes Fortress Legal data and produces structured deliberation output that any division (or operator) can consume — though today only Fortress Legal exposes it via the command-center UI.

## Path

```
[ Fortress Legal ]                [ Council ]                       [ Deliberation output ]
   │                                  │                                     │
   │   case_slug + related_matters    │                                     │
   ├──────────────────────────────►   │                                     │
   │                                  │                                     │
   │                                  ├─ resolve related_matters slugs      │
   │                                  │  (one-hop only)                     │
   │                                  │                                     │
   │   freeze_context(case_slug)      │                                     │
   ├──►  legal_ediscovery     ◄────── │                                     │
   │                                  │                                     │
   │   freeze_privileged_context()    │                                     │
   ├──►  legal_privileged_comms ◄──── │                                     │
   │                                  │                                     │
   │                                  ├─ frozen_context (with [PRIVILEGED]  │
   │                                  │   tags preserved)                   │
   │                                  │                                     │
   │                                  ├─ persona panel (Architect /         │
   │                                  │   Sovereign / Counselor / etc.)    │
   │                                  │                                     │
   │                                  ├─ contains_privileged: true/false   │
   │                                  ├─ FOR YOUR EYES ONLY warning        │
   │                                  │                                     │
   │                                  └────────────────────────────────────►│
                                                                            │
                                                                            ├─ command-center UI
                                                                            │   (FYEO Card if privileged)
                                                                            │
                                                                            └─ PDF export / SSE stream
                                                                                (FYEO text in-band)
```

## Trigger

Operator-initiated via command-center "Council Deliberation" UI, which calls `POST /api/internal/legal/cases/{slug}/deliberate`.

## Steps

1. UI sends POST with case_slug + question
2. Handler resolves alias if needed (`_resolve_case_slug`)
3. Reads `_council_retrieval_flags()` (env vars at call time)
4. Resolves `related_matters` (if flag enabled)
5. For each (case_slug + related slugs):
   - Calls `freeze_context()` against `legal_ediscovery`
   - If privileged retrieval enabled: also calls `freeze_privileged_context()` against `legal_privileged_communications`
6. Merges frozen context with `=== PRIVILEGED COMMUNICATIONS ===` separator
7. Runs persona panel
8. Streams SSE events with `contains_privileged: bool`
9. Final result: `consensus_summary` (with FYEO warning appended if any privileged chunk was retrieved), `vector_ids` for traceability

## Failure modes

| Failure | Detection | Recovery |
|---|---|---|
| Qdrant unreachable | `freeze_context()` returns `([], [])` | deliberation continues with empty context; persona warns operator |
| Privileged collection empty | `freeze_privileged_context()` returns `([], [])` | no FYEO warning emitted; deliberation continues |
| Case_slug doesn't exist | alias resolver returns original slug | normal 404 from handler |
| `related_matters` JSONB malformed | `_resolve_related_matters_slugs()` returns `[]` | retrieval scoped to primary case only |
| Operator wants to disable privileged retrieval mid-incident | `COUNCIL_INCLUDE_PRIVILEGED_RETRIEVAL=false` env var (no restart needed) | next deliberation skips privileged track |

## Authoritative source-of-truth

- Privilege architecture: [`../../runbooks/legal-privilege-architecture.md`](../../runbooks/legal-privilege-architecture.md)
- FYEO wording: `legal_council.FOR_YOUR_EYES_ONLY_WARNING` constant — **do not paraphrase**
- Code: `backend/services/legal_council.py`
- UI: `apps/command-center/src/lib/use-council-stream.ts` (state reducer)

## Cross-references

- Source division: [`../divisions/fortress-legal.md`](../divisions/fortress-legal.md)
- Shared service: [`../shared/council-deliberation.md`](../shared/council-deliberation.md)
- Qdrant: [`../shared/qdrant-collections.md`](../shared/qdrant-collections.md)

Last updated: 2026-04-26
