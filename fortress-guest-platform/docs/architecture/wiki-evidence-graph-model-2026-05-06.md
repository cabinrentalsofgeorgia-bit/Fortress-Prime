# Fortress Legal Wiki and Evidence Graph Model

Date: 2026-05-06

## Purpose

The wiki and evidence graph turns operational documentation, validation evidence, runbooks, and architecture audits into traversable operational cognition. It indexes paths, categories, freshness, and relationships, not confidential legal content.

## Nodes

- architecture documents
- operational runbooks
- evidence summaries
- validation evidence bundles
- wiki decisions
- wiki audits
- context packs

## Edges

- `references`: wiki or architecture node references an operational phase.
- `supports`: evidence bundle supports a capability or phase.
- `validated_by`: phase is validated by a checker, verifier, simulation, or registry validation.
- `generated_from`: graph index node derives from the wiki knowledge index.

## Boundaries

The graph never stores document body text, restricted content, secrets, or privileged legal content. It is an index of operational memory relationships.
