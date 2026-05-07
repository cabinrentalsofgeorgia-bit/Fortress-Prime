# Fortress Legal Operational Memory

Machine-readable operational memory for Fortress Legal.

These registries are operational state, not legal authority. They do not record counsel signoff, create final legal conclusions, authorize external submission, resolve source issues, mutate evidence, or grant reviewer authority.

## Directories

- `schemas/`: JSON schema definitions for registry shape.
- `registries/`: curated initial operational memory registries.

## Safety Rules

- No confidential legal text.
- No privileged/locked/restricted content.
- No auth state, cookies, tokens, passwords, headers, service keys, DB URLs, or session values.
- No source promotion.
- No signoff/final/external authority states.
- No schema/RLS/policy mutation.

## Validation

Run:

```bash
node fortress-guest-platform/scripts/operational-memory/validate-operational-memory.mjs
node fortress-guest-platform/scripts/operational-memory/summarize-operational-memory.mjs
```

Optional index regeneration:

```bash
node fortress-guest-platform/scripts/operational-memory/build-wiki-knowledge-index.mjs
```
