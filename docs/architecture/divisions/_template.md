# Division: <Name>

Owner: <person or role>
Status: <active | closed | planned>
Last updated: <YYYY-MM-DD>

## Purpose

One paragraph. What does this division do? Why does it exist? Who is the operator?

## Key data stores

- **Postgres schemas / tables:** `<schema>.<table>` (one per line; cross-link to `shared/postgres-schemas.md` if shared)
- **Qdrant collections:** `<collection>` (cross-link to `shared/qdrant-collections.md`)
- **NAS folders:** `/mnt/fortress_nas/<path>` (one per line)

## Key services consumed

Bulleted list. Each entry: service name + how this division uses it. Cross-link to `shared/<service>.md`.

- [Captain](../shared/captain-email-intake.md) — for inbound email capture
- [Council](../shared/council-deliberation.md) — for case-aware deliberation
- [Sentinel](../shared/sentinel-nas-walker.md) — for NAS document indexing

## Key services exposed

Bulleted list. What other divisions or external systems consume this division's output?

## Open questions for operator

Bulleted list. Specific things that, if answered, would let us fill in the unknowns above.

- ?

## Cross-references

- Recent merged PRs: #N, #N
- Related runbooks: `../../runbooks/<name>.md`
- Related issues: #N

Last updated: <YYYY-MM-DD>
