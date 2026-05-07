# Fortress Legal Queryable Governance Model

Date: 2026-05-06

## Purpose

Queryable governance makes Fortress Legal boundaries traversable without turning operational memory into legal authority. The model answers operational questions about standing labels, evidence lineage, remediation exclusion, validation status, and rollback posture.

## Query Classes

- `governance`: list boundaries and nodes governed by them.
- `remediation`: list unresolved-source nodes and exclusion edges.
- `evidence`: list evidence bundles and validations they support.
- `deployment`: list deployment and rollback lineage.
- `operational_state`: list current standing labels, blockers, and validating checks.

## Required Query Guarantees

- No confidential legal text.
- No restricted-content body text.
- No secrets or auth state.
- No final legal conclusion status.
- No counsel signoff authority.
- No external submission authority.
- No unresolved-source promotion.

## Current Query Tooling

- `query-knowledge-graph.mjs governance`
- `query-knowledge-graph.mjs remediation`
- `query-knowledge-graph.mjs evidence`
- `query-knowledge-graph.mjs deployment`
- `query-knowledge-graph.mjs operational_state`

All query output is metadata-only and safe for operational evidence.
