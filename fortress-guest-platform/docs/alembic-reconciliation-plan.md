# Alembic Reconciliation Plan

**Current as of 2026-04-15.** This document replaces the deprecated
`alembic-reconciliation-plan.deprecated-2026-04-15.md` which described
a pre-Phase-A-F target of `e8b1c4d7f9a2`. All claims below are sourced
from live DB queries or verbatim code references.

See also:
- `docs/alembic-reconciliation-report.md` — machine-generated per-revision audit
- `docs/owner-statements-migration-map.md` — Phase A-F DDL reference
- `SYSTEM_ORIENTATION.md` — full system context

---

## 1. Current State

### Live alembic heads

```sql
-- fortress_shadow (runtime DB, migrated via fortress_admin)
SELECT version_num FROM alembic_version;
-- Result: e6a1b2c3d4f5
```

```sql
-- fortress_guest (legacy/secondary DB, migrated via fgp_app on its own branch)
-- Connect: psql "postgresql://fgp_app:...@localhost:5432/fortress_guest"
SELECT version_num FROM alembic_version;
-- Result: c4a8f1e2b9d0
```

Both results verified live on 2026-04-15.

### Which DB the FastAPI runtime uses

`backend/core/config.py` (lines 199–206):
```python
@property
def database_url(self) -> str:
    runtime_uri = self._require_database_uri(
        self.postgres_api_uri,
        expected_role="fortress_api",
        env_var="POSTGRES_API_URI",
    )
    return self._rewrite_database_driver(runtime_uri, async_driver=True)
```

`POSTGRES_API_URI` = `postgresql+asyncpg://fortress_api:fortress@127.0.0.1:5432/fortress_shadow`

So `settings.database_url` → **fortress_shadow**. Every `get_db()` session writes to fortress_shadow.

### Which DB Alembic migrates

`backend/alembic.ini` line 88 (comment):
```
# database URL. env.py rewrites this from POSTGRES_ADMIN_URI at runtime so
# Alembic always migrates through the fortress_admin lane.
```

`POSTGRES_ADMIN_URI` = `postgresql+asyncpg://fortress_admin:fortress@127.0.0.1:5432/fortress_shadow`

Alembic migrates **fortress_shadow** only. fortress_guest manages its own Alembic branch independently.

### Why DATABASE_URL pointing at fortress_guest is inert

`backend/core/config.py` (line 18):
```python
ALLOWED_POSTGRES_DATABASES = frozenset({"fortress_prod", "fortress_shadow", "fortress_db"})
```

The validator at lines 110–136 rejects any database name not in that set. `fortress_guest`
is not in the set, so even if `DATABASE_URL` is set and exported, the runtime would raise
`ValueError` when instantiating `Settings`. The `.env` value is a legacy artefact that is
effectively silenced by the validator. It is NOT used by the FastAPI application.

### Single alembic head confirmed

```bash
cd fortress-guest-platform
python3 -m alembic -c backend/alembic.ini heads
# Output: e6a1b2c3d4f5 (parity_audit, offline_buffer, property_tax_geo) (head)
```

One head. No divergent branches requiring merge. The Phase A-F migrations
extend the chain and terminate at `e6a1b2c3d4f5`.

---

## 2. Two-Database Model Summary

### fortress_shadow (primary runtime DB)

| Property | Value |
|---|---|
| DB name | `fortress_shadow` |
| Runtime user | `fortress_api` |
| Alembic user | `fortress_admin` |
| Alembic head | `e6a1b2c3d4f5` |
| Tables (public + core) | ~120 |
| Active connections | 26 idle (as of 2026-04-15) |
| All Phase A-F tables | Present |

Row counts for Phase A-F tables (queried 2026-04-15):

```sql
SELECT 'owner_balance_periods', COUNT(*) FROM owner_balance_periods  -- 17692
UNION ALL SELECT 'owner_payout_accounts', COUNT(*) FROM owner_payout_accounts  -- 1261
UNION ALL SELECT 'owner_charges', COUNT(*) FROM owner_charges  -- 311
UNION ALL SELECT 'owner_statement_sends', COUNT(*) FROM owner_statement_sends  -- 55
UNION ALL SELECT 'owner_magic_tokens', COUNT(*) FROM owner_magic_tokens;  -- 401
```

**Warning:** As of 2026-04-15, fortress_shadow contains significant test data
from Phase A-F development: 1,047 owner_payout_accounts with `@test.com` emails,
17,492 owner_balance_periods with `period_start >= 2050`. Slated for cleanup in Phase G.1.5.

### fortress_guest (legacy/secondary DB)

| Property | Value |
|---|---|
| DB name | `fortress_guest` |
| Runtime user | `fgp_app` |
| Alembic head | `c4a8f1e2b9d0` (own branch, not shared with fortress_shadow) |
| Tables (public) | ~105 |
| Active connections | 1 idle (as of 2026-04-15) |
| Phase A-F tables | Absent |
| Owner statements | 0 rows (owner_payout_accounts empty) |
| Real reservations | 2,665 rows (NOT mirrored to fortress_shadow) |

fortress_guest appears to be the pre-migration operational database that is no longer
receiving application writes. The reservation and guest data there represents a historical
record not yet migrated to fortress_shadow.

### Open question for Gary

Is fortress_guest being wound down, kept as a read-only archive, or should its
historical reservation data be migrated to fortress_shadow? This determines whether
the statement computation system (which reads `reservations` from fortress_shadow) has
access to the full booking history. Currently it does not.

---

## 3. Phase A-F Additions

The migrations that landed in fortress_shadow since the deprecated plan was written.
Full DDL reference: `docs/owner-statements-migration-map.md`.

| Revision | Phase | What it adds |
|---|---|---|
| `e7c3f9a1b5d2` | E (infrastructure) | `owner_payout_accounts.commission_rate` NOT NULL, `streamline_owner_id`; creates `owner_statement_sends` |
| `c1a8f3b7e2d4` | E (infrastructure) | `owner_magic_tokens.commission_rate` (no-op per parser — raw SQL) |
| `d1e2f3a4b5c6` | A | `properties.renting_state` ENUM column; creates `owner_balance_periods` table |
| `f8e1d2c3b4a5` | A.5 | Data migration: sets 44 historical properties to `renting_state='offboarded'` |
| `a3b5c7d9e1f2` | B | `reservations.is_owner_booking` BOOLEAN |
| `c9e2f4a7b1d3` | C | Creates `owner_charges` table + `owner_charge_type_enum` |
| `f1e2d3c4b5a6` | D | `owner_balance_periods.voided_at`, `voided_by`, `paid_by` |
| `e5merge01` | E (merge) | No schema changes — merge point |
| `e5a1b2c3d4f5` | E.5a | 6 mailing address columns on `owner_payout_accounts`; `properties.property_group` |
| `e5b2c3d4e5f6` | E.5b | 6 mailing address columns on `owner_magic_tokens` |
| `e6a1b2c3d4f5` | E.6 | `properties.city`, `state`, `postal_code` |

---

## 4. Watchlist Tables (Updated)

All original 7 watchlist tables are now **present** in fortress_shadow.

```sql
-- Verification query
SELECT table_name,
  CASE WHEN to_regclass('public.' || table_name) IS NOT NULL THEN 'present' ELSE 'missing' END
FROM (VALUES
  ('owner_property_map'), ('management_splits'), ('owner_markup_rules'),
  ('capex_staging'), ('marketing_attribution'), ('owner_marketing_preferences'),
  ('owner_magic_tokens'), ('owner_balance_periods'), ('owner_charges'),
  ('owner_statement_sends'), ('owner_payout_accounts')
) AS t(table_name);
-- All 11 rows: present (verified 2026-04-15)
```

| Table | Status | Created by |
|---|---|---|
| `owner_property_map` | **present** | `d1f4e8c2b7a9` (pre-Phase-A) |
| `management_splits` | **present** | `d1f4e8c2b7a9` |
| `owner_markup_rules` | **present** | `d1f4e8c2b7a9` |
| `capex_staging` | **present** | `d1f4e8c2b7a9` |
| `marketing_attribution` | **present** | `d1f4e8c2b7a9` |
| `owner_marketing_preferences` | **present** | `d1f4e8c2b7a9` |
| `owner_magic_tokens` | **present** | `d1f4e8c2b7a9` |
| `owner_balance_periods` | **present** | `d1e2f3a4b5c6` (Phase A) |
| `owner_charges` | **present** | `c9e2f4a7b1d3` (Phase C) |
| `owner_statement_sends` | **present** | `e7c3f9a1b5d2` (Phase E infra) |
| `owner_payout_accounts` | **present** | pre-existing; new columns in `e7c3f9a1b5d2` and `e5a1b2c3d4f5` |

### Still missing from fortress_shadow (audit report 2026-04-15)

| Table | Revision that creates it | Status |
|---|---|---|
| `str_signals` | `d3a7c1b9e4f2` | **missing** — revision in graph, table absent |
| `channex_webhook_events` | `f4c2b7d9e1a0` | **missing** — revision in graph, table absent |
| `parcels`, `owners`, `owner_contacts`, `acquisition_pipeline`, `intel_events` | `b6f0a2c4d8e1` (partial) | **missing** — properties present but siblings absent |

These are not owner-statement tables and do not affect statement workflow.
The acquisition/channex tables are out of scope for G.1.5.

---

## 5. Known Issues

### 5.1 Test data contamination in fortress_shadow

Phase A-F test suites wrote fixtures directly to fortress_shadow (the production DB)
without transaction isolation. Current contamination:

- `owner_payout_accounts`: 1,047 rows with `@test.com` emails; 92 real rows
- `owner_balance_periods`: 17,492 rows with `period_start >= 2050`; 200 real rows
- `owner_charges`: 311 rows (mix; needs per-row audit)
- `owner_statement_sends`: 55 rows (mix; needs per-row audit)

**Slated for cleanup:** Phase G.1.5. Cleanup must run as `fortress_admin` or a role
with DELETE on these tables (`fortress_api` lacks DELETE on `owner_magic_tokens`).

### 5.2 Conftest does not isolate the test DB

The test suite (`backend/tests/conftest.py` and related fixtures) uses fortress_shadow
without transactional rollback isolation. Every test run that writes fixtures permanently
pollutes the production schema. This is the root cause of issue 5.1.

**Recommended fix (G.1.5):** Wrap test DB access in a transaction that is rolled back
after each test, or point the test suite at a dedicated `fortress_test` database.

### 5.3 admin_statements.py has no role-level auth guard

`backend/api/admin_statements.py` defines `router = APIRouter()` with no
`dependencies=[Depends(require_manager_or_admin)]`. The route
`GET /api/v1/admin/statements/{owner_id}` is therefore JWT-authenticated only
(any valid staff token works) with no role check. This is inconsistent with the
other statement endpoints (all gated by `require_manager_or_admin`).

**Recommended fix:** Add `dependencies=[Depends(require_manager_or_admin)]` to the router
in `admin_statements.py` and add to `docs/permission-matrix.md`.

---

## 6. Operator Guidance

### Do not run `alembic upgrade heads` blindly

The policy from the deprecated plan remains valid as a general principle.
Although fortress_shadow now has a single clean head (`e6a1b2c3d4f5`), the
graph contains revisions referencing missing tables
(`str_signals`, `channex_webhook_events`) and an acquisition table set that
is only partially present. A blanket `upgrade heads` might attempt to apply
revisions for tables that already exist or produce partial states.

**Safe upgrade procedure:**
```bash
# 1. Check current state
python3 -m alembic -c backend/alembic.ini current
# 2. Check what would run
python3 -m alembic -c backend/alembic.ini upgrade head --sql  # dry-run DDL
# 3. Apply only after reviewing the DDL
python3 -m alembic -c backend/alembic.ini upgrade head
```

### Adding a new migration

Migrations land in **fortress_shadow only**. fortress_guest is separately managed
and does not run the same Alembic chain. Do not assume a migration applied to
fortress_shadow is also applied to fortress_guest.

The command `alembic revision --autogenerate -m "description"` compares models
against fortress_shadow (via fortress_admin). Inspect the generated file before
applying — autogenerate sometimes detects phantom differences from partial table states.

---

## 7. Recommended Next Phase

See `SYSTEM_ORIENTATION.md` Section 11 — "Recommended Next Phase" — for the
full G.1.5 scope. In brief: clean test data from fortress_shadow's owner-statement
tables, fix conftest isolation, then proceed to G.2 (admin statement UI).
