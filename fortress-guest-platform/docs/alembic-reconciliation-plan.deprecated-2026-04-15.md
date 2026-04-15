> **DEPRECATED 2026-04-15.** This document predates Phase A-F (owner statement system).
> It describes a target head of e8b1c4d7f9a2; the live database fortress_shadow is
> already at e6a1b2c3d4f5. Preserved for historical reference. See current
> docs/alembic-reconciliation-plan.md and docs/alembic-reconciliation-report.md.

---

# Alembic Reconciliation Plan

This document records the current Alembic / live-schema mismatch discovered while
attempting to run `alembic upgrade head(s)` against the live Fortress Prime
database.

## Current State

Execution runbook:

- `docs/alembic-prod-rollout-runbook.md`

### Live `alembic_version`

The live database is stamped at:

- `c7d8e9f0a1b2`

That revision was missing from the current repository checkout and has now been
restored into `backend/alembic/versions/` together with a compatibility anchor:

- `a9c1e4f8b2d0_legacy_branch_anchor.py`
- `c7d8e9f0a1b2_create_ai_insights_table.py`

This allows Alembic to resolve the live lineage safely again.

### Local Alembic Graph

The repository now has a formal no-op merge revision:

- `e8b1c4d7f9a2`

That merge revision converges the three previously active heads:

- `9b3e8218df41`
- `c7d8e9f0a1b2`
- `d1f4e8c2b7a9`

This normalizes the repo graph, but it does **not** make the live database safe
to upgrade blindly. The production database is still stamped at the legacy head
`c7d8e9f0a1b2` and still lacks several canonical owner/admin tables.

### Live Schema Snapshot

Observed in the live database:

Present:

- `public.ai_insights`
- `public.agent_queue`
- `public.vrs_automation_events`
- `public.staff_users`
- `public.guests`
- `public.properties`
- `public.reservations`
- `public.messages`
- `public.trust_balance`
- `core.deliberation_logs`
- `public.accounts`
- `public.journal_entries`
- `public.journal_line_items`

Missing:

- `public.owner_property_map`
- `public.management_splits`
- `public.owner_markup_rules`
- `public.capex_staging`
- `public.marketing_attribution`
- `public.owner_marketing_preferences`
- `public.owner_magic_tokens`

### Live Patch Already Applied

Because the Hunter runtime depended on it, the following schema delta was applied
manually to the live database:

```sql
ALTER TABLE public.agent_queue
ADD COLUMN IF NOT EXISTS delivery_channel VARCHAR(20) NOT NULL DEFAULT 'email';
```

This fixed the live Hunter queue/runtime path without requiring a full Alembic
branch merge.

## Why `alembic upgrade heads` Is Not Safe Yet

Running `alembic upgrade heads` is unsafe because:

1. the live DB is stamped to a legacy head (`c7d8e9f0a1b2`)
2. the sovereign branch head (`f2a6b8c4d1e9`) is not stamped
3. some sovereign-branch tables already exist in live schema
4. other sovereign-branch tables are still missing

That means a blanket upgrade could:

- try to recreate already-present structures
- fail mid-branch on duplicate DDL
- leave the branch only partially applied

## Safe Recovery Strategy

### Phase 1: Preserve Operability

Done:

- restored missing legacy Alembic files into the repo
- applied the minimal `agent_queue.delivery_channel` runtime fix manually
- verified Hunter backend/BFF endpoints return `200`

### Phase 2: Reconcile the Sovereign Branch

Recommended next steps:

1. Build a table-by-table branch audit.
   For each sovereign-branch revision, determine whether the target schema object:
   - already exists and matches intent
   - exists but differs
   - is absent

2. Group revisions into:
   - safe-to-stamp (schema already equivalent)
   - safe-to-run (objects absent, no conflicts expected)
   - manual-repair-required

3. Create one explicit reconciliation revision or runbook, rather than
   improvising stamps in production.

4. Only after equivalence is proven:
   - stamp branch heads that are already materially present
   - run the truly missing migrations

### Phase 3: Normalize the Graph

Done in-repo:

1. created canonical revision `d1f4e8c2b7a9` for the missing owner/admin ops tables
2. created merge revision `e8b1c4d7f9a2` to collapse the three active heads into one

Still required for live rollout:

1. prove live schema equivalence for each canonical table
2. decide per structure whether prod should `upgrade`, `stamp`, or receive one-time
   manual SQL alignment first
3. document the exact production procedure before any `alembic upgrade`

## Operator Guidance

Until reconciliation is complete:

- do **not** run `alembic upgrade heads` blindly against production
- do **not** stamp sovereign branch heads without verifying corresponding schema
- prefer minimal surgical SQL for urgent runtime fixes only when the change is
  obvious, isolated, and reversible

## Immediate Next Candidate

The best next execution step is a production rollout runbook anchored on the new
merged head `e8b1c4d7f9a2`:

1. verify live shape for each table introduced in `d1f4e8c2b7a9`
2. for tables that already match, prefer stamping via controlled branch
   reconciliation rather than recreating them
3. for tables that are absent, allow the canonical migration path to create them
4. for tables that differ materially, write one-time repair SQL before advancing
   the Alembic stamp

That turns the remaining work from “graph repair” into a deterministic live
schema rollout.

## Recommended Live Rollout Sequence

Assuming the repo head remains `e8b1c4d7f9a2`, the safest operator sequence is:

1. snapshot `alembic_version`, `pg_tables`, `information_schema.columns`, and all
   relevant indexes/constraints for the canonical tables
2. compare prod definitions against the intended shapes in `d1f4e8c2b7a9`
3. classify each table:
   - `equivalent`
   - `missing`
   - `conflicting`
4. if any table is `conflicting`, stop and write explicit repair SQL first
5. if all canonical tables are either `equivalent` or `missing`, advance prod in
   controlled order:
   - keep legacy lineage reachable from `c7d8e9f0a1b2`
   - run only the canonical DDL still truly missing
   - stamp/advance into `e8b1c4d7f9a2` only after schema state matches branch intent
6. run post-upgrade smoke checks for:
   - owner magic link auth
   - owner portal CapEx approval endpoints
   - admin split / markup / marketing endpoints
   - contract generation

## Watchlist Recommendations

Based on the current live-schema audit and repository usage:

### Should Become Canonical Migration

These tables are referenced directly by active backend application code and should
not remain implicit external dependencies long-term:

- `public.owner_property_map`
  - used by admin ops, owner auth/login resolution, contracts, and owner portal

- `public.management_splits`
  - used by admin ops and contract generation

- `public.owner_markup_rules`
  - used by admin ops and contract generation

- `public.capex_staging`
  - used by admin ops, owner portal, and Stripe webhook reconciliation

- `public.marketing_attribution`
  - used by admin ops and owner portal reporting

- `public.owner_marketing_preferences`
  - used by admin ops and owner portal reporting

- `public.owner_magic_tokens`
  - used by owner magic-link login and owner onboarding flows

Recommended direction:

1. create canonical Alembic revisions for these structures in the current branch
2. verify live schema shape vs intended shape
3. stamp or migrate only after shape equivalence is proven

### Should Remain External / Legacy Dependency

These present tables are important to runtime behavior but are not necessarily
owned by the current reconciliation branch:

- `public.trust_balance`
- `public.accounts`
- `public.journal_entries`
- `public.journal_line_items`

Recommended direction:

1. document them as required legacy/finance infrastructure when appropriate
2. avoid implicitly assuming Alembic in this repo fully owns them unless that is
   an intentional future migration goal

### Should Be Removed From App Expectations

None identified in the current watchlist.

Every missing table in the watchlist is actively referenced by application code,
so removal would require feature deprecation or refactoring rather than simple
cleanup.
