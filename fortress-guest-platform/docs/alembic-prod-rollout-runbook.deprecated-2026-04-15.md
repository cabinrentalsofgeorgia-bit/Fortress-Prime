> **DEPRECATED 2026-04-15.** This document predates Phase A-F (owner statement system).
> It describes a target head of e8b1c4d7f9a2; the live database fortress_shadow is
> already at e6a1b2c3d4f5. Preserved for historical reference. See current
> docs/alembic-reconciliation-plan.md and docs/alembic-reconciliation-report.md.

---

# Alembic Production Rollout Runbook

This runbook advances the live Fortress Prime database from legacy-stamped
revision `c7d8e9f0a1b2` to merged repo head `e8b1c4d7f9a2` without replaying
already-materialized branches or reapplying the manual Hunter hotfix.

## Live Facts Verified

- Live `alembic_version`: `c7d8e9f0a1b2`
- Repo head: `e8b1c4d7f9a2`
- `public.agent_queue.delivery_channel` exists in prod as:
  - `varchar`
  - `NOT NULL`
  - default `'email'::character varying`
- The canonical tables introduced by `d1f4e8c2b7a9` are all absent in prod:
  - `public.owner_property_map`
  - `public.management_splits`
  - `public.owner_markup_rules`
  - `public.capex_staging`
  - `public.marketing_attribution`
  - `public.owner_marketing_preferences`
  - `public.owner_magic_tokens`

## Decision Matrix

| Revision / Object | Live Status | Action | Why |
|---|---|---|---|
| `c7d8e9f0a1b2` | stamped and present | keep | This is the current production lineage anchor. |
| `9b3e8218df41` | schema-equivalent | stamp only | `agent_queue.delivery_channel` was already added manually in prod. |
| `f2a6b8c4d1e9` | schema-equivalent branch merge | stamp only | Prior audit shows its ancestry is already materially present or no-op. |
| `d1f4e8c2b7a9` | missing | run migration | This revision creates seven real missing tables in prod. |
| `e8b1c4d7f9a2` | missing merge node | run via upgrade | This is the no-op repo convergence point after branch state is aligned. |

## Canonical Table Classification

| Table | Live Status | Classification | Operator Action |
|---|---|---|---|
| `owner_property_map` | absent | safe-to-run | create via `d1f4e8c2b7a9` |
| `management_splits` | absent | safe-to-run | create via `d1f4e8c2b7a9` |
| `owner_markup_rules` | absent | safe-to-run | create via `d1f4e8c2b7a9` |
| `capex_staging` | absent | safe-to-run | create via `d1f4e8c2b7a9` |
| `marketing_attribution` | absent | safe-to-run | create via `d1f4e8c2b7a9` |
| `owner_marketing_preferences` | absent | safe-to-run | create via `d1f4e8c2b7a9` |
| `owner_magic_tokens` | absent | safe-to-run | create via `d1f4e8c2b7a9` |

## Why Not Run `alembic upgrade head` Immediately

Do not jump directly from `c7d8e9f0a1b2` to `e8b1c4d7f9a2` without pre-stamping.

Reasons:

1. The queue branch revision `9b3e8218df41` would try to add
   `agent_queue.delivery_channel` again even though the column already exists.
2. The sovereign branch converged at `f2a6b8c4d1e9`, but production is not
   stamped there even though the branch ancestry is already materially present.
3. The only branch that should execute real DDL in prod is `d1f4e8c2b7a9`.

## Preflight Snapshot

Run these before any stamp or upgrade:

```sql
SELECT version_num FROM alembic_version ORDER BY version_num;
```

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'owner_property_map',
    'management_splits',
    'owner_markup_rules',
    'capex_staging',
    'marketing_attribution',
    'owner_marketing_preferences',
    'owner_magic_tokens'
  )
ORDER BY table_name;
```

```sql
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'agent_queue'
  AND column_name = 'delivery_channel';
```

## Rollout Sequence

Run from `fortress-guest-platform/backend`.

1. Confirm the preflight snapshot still matches this runbook.
2. Stamp the already-equivalent branches so Alembic does not replay them:

```bash
alembic stamp c7d8e9f0a1b2 9b3e8218df41 f2a6b8c4d1e9
```

3. Upgrade to the merged repo head:

```bash
alembic upgrade e8b1c4d7f9a2
```

Expected effect:

- `d1f4e8c2b7a9` runs and creates the seven missing canonical tables.
- `e8b1c4d7f9a2` records branch convergence with no schema change.

## Post-Upgrade Verification

Check version state:

```sql
SELECT version_num FROM alembic_version ORDER BY version_num;
```

Expected result:

- one row: `e8b1c4d7f9a2`

Check tables:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'owner_property_map',
    'management_splits',
    'owner_markup_rules',
    'capex_staging',
    'marketing_attribution',
    'owner_marketing_preferences',
    'owner_magic_tokens'
  )
ORDER BY table_name;
```

Expected result:

- all seven tables present

## Smoke Checks

After schema convergence, verify these flows:

1. owner magic link request and verify endpoints
2. owner portal pending CapEx listing and approve/reject endpoints
3. admin split update and markup update endpoints
4. admin marketing attribution write endpoint
5. management contract generation path
6. Hunter queue read path to confirm the prior `delivery_channel` hotfix remains intact

## Abort Conditions

Stop immediately if any of these are true:

- `agent_queue.delivery_channel` is no longer `NOT NULL DEFAULT 'email'`
- any of the seven canonical tables already exists unexpectedly
- `alembic stamp` produces multiple unexpected live versions beyond the three intended branch anchors
- `alembic upgrade e8b1c4d7f9a2` emits DDL outside `d1f4e8c2b7a9`

## Recovery Note

If rollout stops after the multi-head stamp but before the final upgrade:

- do not purge `alembic_version` blindly
- inspect current rows in `alembic_version`
- compare them to the intended branch anchors:
  - `c7d8e9f0a1b2`
  - `9b3e8218df41`
  - `f2a6b8c4d1e9`
- resume only after confirming that no partial DDL from `d1f4e8c2b7a9` ran
