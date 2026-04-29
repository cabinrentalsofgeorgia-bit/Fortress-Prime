# Incident 2026-04-29 — Ollama Removal Without Caller Audit

**Severity:** Production regression, ~10 minutes
**Detection:** Operator endpoint audit ~5 min after removal
**Recovery:** Atomic rollback, no data loss
**Status:** RESOLVED 2026-04-29

## What happened

Spark-3 + spark-4 audits classified ollama as "redundant — spark-2 is canonical." Operator approved removal. Removal executed. Production callers (`fortress-guest-platform/.env` + 3 hardcoded Python URLs + `fortress_atlas.yaml`) referenced the removed endpoints. Rolled back within 10 minutes.

### Timeline

| Time (EDT) | Event |
|---|---|
| ~17:00 | Spark-3 + spark-4 audits ran (read-only) |
| ~17:15 | Operator approved "delete ollama on spark-3 + spark-4 — spark-2 is canonical" |
| ~17:18 | Spark-3 ollama container stopped + removed |
| ~17:20 | Spark-4 ollama.service stopped + disabled |
| ~17:25 | Endpoint audit (operator-driven) revealed live callers pointing at the removed endpoints |
| ~17:30 | EMERGENCY ROLLBACK initiated |
| 17:22:30 | Spark-4 ollama.service restored (Active: running) |
| ~17:24 | Spark-3 ollama container redeployed from cached image (5.49 GB local) |
| ~17:27 | qwen2.5:7b re-pulled to spark-3 (4.7 GB; was in unmounted ollama_data volume as fallback) |
| ~17:30 | Both endpoints reachable, 4 models on spark-3, 6 models on spark-4 |
| Total | ~10 min downtime spark-4, ~7 min downtime spark-3 |

## Root cause

Two stories about ollama topology were out of sync:

| Story source | Said |
|---|---|
| Doc story (`CLAUDE.md` DEFCON 5/SWARM section, infrastructure.md, qdrant-collections.md) | "spark-2 is the canonical SWARM tier" |
| Config story (`.env`, `fortress_atlas.yaml`, hardcoded Python URLs) | "spark-3 = vision-specialist ollama at 192.168.0.105:11434, spark-4 = SWARM ollama at 192.168.0.106:11434" |

Audit + remediation acted on the doc story. Production references the config story. They diverged because config evolved without doc updates.

## Principles captured (durable)

### Principle 1 — Audit callers BEFORE removing any service

No service is "redundant" without a caller-side audit. Required before any service stop/removal:

```bash
# Find every reference to the endpoint
grep -rn "PORT_OR_URL_PATTERN" \
  --include="*.py" \
  --include="*.yaml" \
  --include="*.env*" \
  --include="*.sh" \
  --include="*.md" \
  --exclude-dir=node_modules \
  --exclude-dir=venv \
  ~/Fortress-Prime
```

If grep returns ANY hit, do not remove. File a migration plan first.

### Principle 2 — Config story trumps doc story

Production runs config, not docs. When the two diverge, config is reality. Doc updates trail; config drives.

This means: when an audit finding contradicts what's in `.env` / `fortress_atlas.yaml` / hardcoded URLs, the audit is the suspect, not the config.

### Principle 3 — "Doc-only PR" is not a license to skip caller validation

Even when the action is just "stop a service" with no code change, every service has a caller surface. The caller surface is part of what the action affects.

### Principle 4 — Cached images are an undocumented backup

Spark-3 ollama image was still cached when the container was removed. That cache made redeploy a `docker run` away. The unmounted `ollama_data` volume held qwen2.5:7b weights as a second-line backup. Both saved this incident.

Codified as policy: do NOT remove cached images during cleanup. They cost storage but enable instant recovery.

### Principle 5 — Rollback first, blame later

When production breaks, restore baseline first. Investigate causes after. The "audit before remediating" rule is for prevention; the "rollback first" rule is for response. They're different rules and they don't conflict.

## Action items (post-incident)

1. **fortress_atlas.yaml + CLAUDE.md reconciliation** — update docs to match reality (spark-3/4 ollama is part of SWARM tier, not redundant). Filed P3.
2. **Add "log callers" step to all future service-removal briefs.** Hard constraint, not best practice.
3. **Ollama consolidation migration brief** — if/when consolidation is desired, requires caller migration first. Filed P4. Not urgent.
4. **Master plan §4.4 discipline rules** — add "audit callers before removing any service" as anti-pattern.

## What worked

- Rollback within 10 minutes — atomic, clean
- Cached image on spark-3 (5.49 GB) made redeploy instant
- ollama_data volume on spark-3 (13 GB) preserved qwen2.5:7b weights as fallback
- No `.env`, `.py`, or `fortress_atlas.yaml` was modified during incident — clean rollback surface
- Operator endpoint audit caught divergence quickly

## What to do differently

- Add `grep -rn "<endpoint>"` step to every audit checklist
- Default policy: when in doubt, retain. Removal is the harder operation.
- When operator approves a removal based on an audit finding, the operator is trusting the audit's caller-coverage. Make caller-coverage explicit in every audit's findings table.

## Cross-references

- ADR-004 amendment v2 (this PR) — `docs/architecture/cross-division/ADR-004-app-vs-inference-boundary.md` § Amendment 2026-04-29
- Retained-state record + caller surface — `docs/operational/spark-3-4-retained-state-2026-04-29.md`
- Original wipe-and-rebuild brief (superseded, header-noted) — `docs/operational/briefs/spark-3-4-wipe-and-rebuild-2026-04-29.md`
- MASTER-PLAN.md §4.4 discipline-rules + §9 anti-patterns updates — this PR
