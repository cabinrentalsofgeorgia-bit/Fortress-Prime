# Decision 0001: Operational Memory And Agent Boundaries

Date: 2026-05-07

Status: accepted

## Context

Fortress Legal work has depended too heavily on chat context and scattered operational notes. Future agents need a permanent, repo-native memory layer that records canonical topology, runtime lineage, promotion gates, auth boundaries, database classification, audit findings, and operating rules.

## Decision

Create and maintain these durable operational memory files in the canonical repo:

- `docs/architecture/system-topology.md`
- `docs/production/runtime-lineage.md`
- `docs/deployment/promotion-gates.md`
- `docs/auth/auth-boundaries.md`
- `docs/database/supabase-classification.md`
- `docs/audit/readonly-system-discovery.md`
- `docs/decisions/0001-operational-memory-and-agent-boundaries.md`
- `docs/runbooks/cli-agent-operating-rules.md`

Every future agent must update these files as facts are discovered or changed.

## Boundaries

Without explicit operator approval, agents must not:

- deploy,
- mutate production,
- alter Supabase, RLS, storage, auth, DNS, Cloudflare, or Vercel production state,
- ingest real legal documents,
- expose secrets,
- edit `.auth`,
- touch CROG-VRS, Hedge Fund, or Market Club systems,
- perform broad cleanup or unrelated lint fixes.

## Consequences

- Chat context is no longer the operational source of truth.
- Topology changes require docs changes in the same PR.
- Read-only discovery comes before build work.
- Production mutation requires a fresh promotion gate and explicit approval.
