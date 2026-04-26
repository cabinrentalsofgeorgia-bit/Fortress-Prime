# Fortress Prime Architecture Documentation

This directory is the navigable map of the Fortress Prime estate. It complements `fortress_atlas.yaml` (the runtime sector routing config) and `CONSTITUTION.md` (the governing doctrine) with human-readable documentation: who owns what, how the divisions connect, and where the shared services sit.

## How to use this directory

Read in this order on first encounter:

1. [`system-map.md`](system-map.md) — visual ASCII layout of divisions + shared services + data flows
2. [`divisions/`](divisions/) — one document per business division
3. [`shared/`](shared/) — one document per cross-cutting service (Captain, Council, Sentinel, Postgres, Qdrant, etc.)
4. [`cross-division/`](cross-division/) — flows that span two or more divisions

## Discipline

**Every PR that touches a division MUST update its doc** — owner field, last-updated date, any new data stores or services. The doc is the contract; the code is the implementation.

**Stub-then-fill pattern** for unknown divisions. When a division surfaces in an operator conversation that we don't yet have grounded knowledge of, write a stub immediately:

```markdown
Status: planned, requires operator input

Open questions:
- ...
- ...
```

Don't fabricate facts. A stub with honest open questions is more useful than confident-but-wrong prose.

## Cross-references to existing docs

These pre-existing artifacts remain authoritative for their topic. The architecture docs link to them rather than duplicate:

- [`../runbooks/legal-vault-documents.md`](../runbooks/legal-vault-documents.md) — `legal.vault_documents` schema + state machine
- [`../runbooks/legal-vault-ingest.md`](../runbooks/legal-vault-ingest.md) — vault ingestion script (PR D)
- [`../runbooks/legal-privilege-architecture.md`](../runbooks/legal-privilege-architecture.md) — privilege track + FYEO + cross-matter retrieval (PR G)
- [`../runbooks/legal-email-backfill.md`](../runbooks/legal-email-backfill.md) — case-aware email backfill (PR I)
- [`../CHANGELOG.md`](../CHANGELOG.md) — dated PR ledger
- [`../../CONSTITUTION.md`](../../CONSTITUTION.md) — sovereign doctrine
- [`../../fortress_atlas.yaml`](../../fortress_atlas.yaml) — runtime sector routing config
- [`../../CODEBASE_OVERVIEW.md`](../../CODEBASE_OVERVIEW.md) — codebase tour

Existing files in this directory (predate the foundation refactor and remain in place):

- `004-postgres-contract.md`
- `005-implementation-gaps.md`
- `005-nemoclaw-swarm-architecture.md`
- `006-nemoclaw-ray-deployment.md`
- `redirect-vanguard.md`
- `sovereign-intent-engine-boundaries.md`
- `sovereign_quote_paths.md`

## Contributing

- New division surface: copy `divisions/_template.md`, fill what you know, list questions for the rest. Open a PR.
- New shared service: add a doc under `shared/` with the four required sections (overview, consumers, contract, code paths).
- New cross-division flow: copy `cross-division/_template.md`.

Last updated: 2026-04-26 (architecture foundation PR)
