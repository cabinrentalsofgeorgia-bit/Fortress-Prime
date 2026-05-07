# AI-Assisted Operations Audit - 2026-05-06

## Classification

`AI_OPERATIONAL_COGNITION_AUDIT`

## Executive Finding

Fortress Legal has become an AI-assisted operational system more than a conventional legal app. AI agents plan, inspect, patch, validate, document, deploy, capture evidence, and open PRs. The strongest safety property is that AI work is repeatedly bounded by explicit governance labels, authenticated checkers, non-sensitive evidence, and git-revertable commits. The weakest property is that much operational cognition still exists in long prompts and chat history instead of structured, queryable operational memory.

## AI Interaction Surfaces

- Codex phase prompts define mission, boundaries, hard stops, branch strategy, evidence, and final labels.
- Verification scripts turn UI and API behavior into machine-readable evidence.
- Operational docs encode phase outcomes and decision boundaries.
- PR bodies function as governance capsules.
- Evidence JSON preserves non-sensitive runtime truth.
- Agents perform parallel read-only exploration while one integrator stages/commits.

## Deterministic Elements

- Authenticated checker booleans.
- Deployment verifier route/API/service checks.
- Pilot simulation verifier booleans.
- Git commit history and PR branches.
- Evidence directories.
- Standing governance labels.
- No-auth/no-secret scans.

## Fragile Elements

- Long-context prompt memory carries operational facts that are not fully codified.
- Branch ancestry is inferred by the operator/agent rather than generated from a live state manifest.
- Checker text selectors can break from UI copy changes.
- Evidence is searchable but not indexed as a graph.
- AI agents must remember not to inspect confidential/locked content instead of relying on systemic guardrails in every tool.
- Backend pytest environment blockers are understood socially, not encoded as machine-readable expected blockers.

## Operational Cognition That Exists Mostly In Prompts

- "Use the clean phase worktree, not the dirty canonical root."
- "Authenticated checker replaces manual Gary/operator confirmation."
- "Do not treat operator acknowledgment as counsel signoff."
- "Persistent reviewer assignment writes are deferred."
- "Human operations are read-only/synthetic unless separately approved."
- "PRs are governance PRs, not feature-sprawl PRs."

## What Should Become Structured

- Phase registry: phase name, branch, PR, base, evidence path, verifier status.
- Governance invariant manifest: all standing labels and forbidden operations.
- Expected environment blockers: backend pytest requiring local `POSTGRES_API_URI`.
- Worktree registry: clean/current/dirty/unrelated status.
- Checker assertion registry: UI text, API guard, negative controls, evidence output.
- Source-blocker registry: unresolved counts, categories, review lanes, age, owner role hint.
- AI session start packet: current branch stack, latest PRs, dirty-file warnings, evidence paths.

## AI Operational Maturity

| Capability | Current Maturity | Gap |
| --- | --- | --- |
| Agent planning | High | Still prompt-heavy |
| Safe coding | High | Depends on branch hygiene |
| Evidence capture | High | Fragmented indexing |
| Runtime verification | High | Text-selector fragility |
| Governance preservation | High | Needs machine-readable policy registry |
| Knowledge retrieval | Medium | Wiki/app split |
| Long-term memory | Medium-low | Chat memory not structured |
| Reviewer assistance | Medium | No durable feedback/disposition ledger |

## Audit Result

`AI_ASSISTANCE_IS_OPERATIONALLY_POWERFUL_BUT_NEEDS_STRUCTURED_MEMORY_AND_POLICY_MANIFESTS`
