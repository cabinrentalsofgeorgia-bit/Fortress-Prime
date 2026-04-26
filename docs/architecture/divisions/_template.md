# Division: <Name>

Owner: <person or role>
Status: <active | closed | planned | scaffolding>
Spark allocation:
- **Current:** <Spark N (status) — what's hosted here today>
- **Target:** <Spark N (status) — final home per ADR-001; Same if not migrating>
Last updated: <YYYY-MM-DD>

> **Allowable exception — multi-purpose Spark pattern.** ADR-001 locks
> "one spark per division" as the default rule. ADR-002 (LOCKED 2026-04-26)
> introduced a recognized exception: a single spark may host **one shared
> service + two or more intermittent divisions** when the workload-
> compatibility argument is genuine.
>
> Live instance of this pattern: **Spark 4** hosts Council (bursty cross-
> division LLM deliberation) + Acquisitions (intermittent deal-pipeline
> analysis) + Wealth (lower-frequency intelligence). None of the three
> sustains continuous load, so co-tenancy avoids hardware sprawl without
> contention risk.
>
> Spark 2 is the other multi-purpose spark — hosting CROG-VRS + Captain +
> Sentinel — though that pairing is "control-plane shared services + a
> high-traffic division" rather than the Spark 4 pattern.
>
> If you're documenting a division that maps to a multi-purpose spark
> (Spark 4 today), call out the multi-purpose context explicitly in the
> "Spark allocation" block. The default for any new division remains
> "one spark per division."

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

## Inference consumers

Per [ADR-003](../cross-division/_architectural-decisions.md) LOCKED 2026-04-26, the inference plane (LLM + embedding) is a shared cluster-wide resource routed through the LiteLLM proxy on Spark 2. Each division documents what inference workloads it generates so the cluster can be sized.

Document for this division:

- **LLM workloads** — what calls does this division make? Examples: classification, summarization, parsing, deliberation. Estimate volume (per day / per case / per booking).
- **Embedding workloads** — what gets embedded? Vault uploads, NAS walks, search index updates. Estimate volume (chunks per day).
- **Tier preference** — does this division need TITAN/BRAIN tier (deep reasoning), SWARM tier (fast routing), or either?
- **Latency budget** — synchronous (user is waiting) vs. async (queueable via ADR-003 Phase 2 embedding queue)?
- **Per-division accounting tag** — what LiteLLM virtual key does this division use? (ADR-003 Phase 4)

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
