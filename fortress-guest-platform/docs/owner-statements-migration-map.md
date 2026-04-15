# Owner Statements Migration Map

Generated 2026-04-15. Source of truth for which alembic revisions own which
owner-statement schema objects. All entries verified by reading migration files
verbatim. Execution order is determined by Alembic chain (down_revision links),
not by developer-assigned phase labels.

**Execution order in fortress_shadow** (earliest first as applied by Alembic):
`e7c3f9a1b5d2` → `c1a8f3b7e2d4` → `d1e2f3a4b5c6` → `f8e1d2c3b4a5` → `a3b5c7d9e1f2`
→ `c9e2f4a7b1d3` → `f1e2d3c4b5a6` → `e5merge01` → `e5a1b2c3d4f5` → `e5b2c3d4e5f6`
→ `e6a1b2c3d4f5`

---

## Phase E — Infrastructure (executes FIRST in chain)

### `e7c3f9a1b5d2` — `e7c3f9a1b5d2_owner_statement_infrastructure.py`

**down_revision:** `b2c4d6e8f0a1`  
**Phase label:** E (owner statement infrastructure — Area 2 gap-remediation Phase 1 + 1.5)

**Creates / Alters:**

| Operation | Object | Detail |
|---|---|---|
| `ALTER TABLE` | `owner_payout_accounts` | `DELETE FROM owner_payout_accounts` (clears prior test rows) |
| `ALTER TABLE` | `owner_payout_accounts.commission_rate` | `NUMERIC(5,4) NOT NULL` — fraction, e.g. 0.3000 = 30% |
| `ALTER TABLE` | `owner_payout_accounts.streamline_owner_id` | `INTEGER NULL` — Streamline integer owner ID |
| `ADD CONSTRAINT` | `owner_payout_accounts.chk_opa_commission_rate` | `CHECK (commission_rate >= 0 AND commission_rate <= 0.5000)` |
| `CREATE INDEX` | `ix_opa_streamline_owner_id` | `ON owner_payout_accounts (streamline_owner_id)` |
| `CREATE TABLE` | `owner_statement_sends` | Audit table — full column list below |

**`owner_statement_sends` columns:**

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | BIGSERIAL | NOT NULL | — | PK |
| `owner_payout_account_id` | BIGINT | NOT NULL | — | FK → owner_payout_accounts(id) ON DELETE RESTRICT |
| `property_id` | UUID | NOT NULL | — | FK → properties(id) ON DELETE RESTRICT |
| `statement_period_start` | DATE | NOT NULL | — | |
| `statement_period_end` | DATE | NOT NULL | — | |
| `sent_at` | TIMESTAMPTZ | NULL | — | |
| `sent_to_email` | VARCHAR(255) | NULL | — | |
| `crog_total_amount` | NUMERIC(12,2) | NULL | — | |
| `streamline_total_amount` | NUMERIC(12,2) | NULL | — | |
| `source_used` | VARCHAR(20) | NULL | — | CHECK IN ('crog', 'streamline', 'failed') |
| `comparison_status` | VARCHAR(30) | NULL | — | CHECK IN ('match', 'mismatch', 'streamline_unavailable', 'not_compared') |
| `comparison_diff_cents` | INTEGER | NULL | — | |
| `email_message_id` | VARCHAR(255) | NULL | — | |
| `error_message` | TEXT | NULL | — | |
| `is_test` | BOOLEAN | NOT NULL | false | Rows from send-test endpoint |
| `created_at` | TIMESTAMPTZ | NOT NULL | now() | |

**Indexes on `owner_statement_sends`:**
- `ix_oss_owner_payout_account_id` ON (owner_payout_account_id)
- `ix_oss_property_id` ON (property_id)
- `ix_oss_period` ON (statement_period_start, statement_period_end)
- `ix_oss_sent_at` ON (sent_at)

---

### `c1a8f3b7e2d4` — `c1a8f3b7e2d4_add_commission_rate_to_magic_tokens.py`

**down_revision:** `e7c3f9a1b5d2`  
**Phase label:** E (infrastructure, grouped with Phase 1.5)  
**Audit script classification:** `no_op` (raw SQL; parser limitation)

Adds `commission_rate` to `owner_magic_tokens` so that the commission rate the
owner agreed to at invite time is captured and copied to `owner_payout_accounts`
on invite acceptance. Exact DDL: `ALTER TABLE owner_magic_tokens ADD COLUMN commission_rate NUMERIC(5,4)`.

---

## Phase A — Ledger Foundation

### `d1e2f3a4b5c6` — `d1e2f3a4b5c6_phase_a_owner_ledger_foundation.py`

**down_revision:** `c1a8f3b7e2d4`  
**Phase label:** A  
**Audit script classification:** `no_op` (raw SQL via op.execute; parser limitation)

**Creates / Alters:**

| Operation | Object | Detail |
|---|---|---|
| `CREATE TYPE` | `property_renting_state` | ENUM('active', 'pre_launch', 'paused', 'offboarded') |
| `ALTER TABLE` | `properties.renting_state` | `property_renting_state NOT NULL DEFAULT 'active'` |
| `UPDATE` | `properties` | Sets `renting_state = 'pre_launch'` WHERE name = 'Restoration Luxury' |
| `CREATE INDEX` | `ix_properties_renting_state` | `ON properties (renting_state)` |
| `CREATE TYPE` | `statement_period_status` | ENUM('draft', 'pending_approval', 'approved', 'paid', 'emailed', 'voided') |
| `CREATE TABLE` | `owner_balance_periods` | Full column list below |

**`owner_balance_periods` columns:**

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | BIGSERIAL | NOT NULL | — | PK |
| `owner_payout_account_id` | BIGINT | NOT NULL | — | FK → owner_payout_accounts(id) ON DELETE RESTRICT |
| `period_start` | DATE | NOT NULL | — | |
| `period_end` | DATE | NOT NULL | — | |
| `opening_balance` | NUMERIC(12,2) | NOT NULL | — | |
| `closing_balance` | NUMERIC(12,2) | NOT NULL | — | |
| `total_revenue` | NUMERIC(12,2) | NOT NULL | 0 | |
| `total_commission` | NUMERIC(12,2) | NOT NULL | 0 | |
| `total_charges` | NUMERIC(12,2) | NOT NULL | 0 | |
| `total_payments` | NUMERIC(12,2) | NOT NULL | 0 | |
| `total_owner_income` | NUMERIC(12,2) | NOT NULL | 0 | |
| `status` | statement_period_status | NOT NULL | 'draft' | |
| `created_at` | TIMESTAMPTZ | NOT NULL | now() | |
| `updated_at` | TIMESTAMPTZ | NOT NULL | now() | |
| `approved_at` | TIMESTAMPTZ | NULL | — | |
| `approved_by` | VARCHAR(255) | NULL | — | |
| `paid_at` | TIMESTAMPTZ | NULL | — | |
| `emailed_at` | TIMESTAMPTZ | NULL | — | |
| `notes` | TEXT | NULL | — | |

**Constraints on `owner_balance_periods`:**
- `uq_obp_owner_period` UNIQUE (owner_payout_account_id, period_start, period_end)
- `chk_obp_period_order` CHECK (period_end > period_start)
- `chk_obp_ledger_equation` CHECK (closing = opening + revenue − commission − charges − payments + owner_income)

**Indexes:**
- `ix_obp_owner_period` ON (owner_payout_account_id, period_start)
- `ix_obp_status` ON (status)

---

## Phase A.5 — Offboard Historical Properties (data migration)

### `f8e1d2c3b4a5` — `f8e1d2c3b4a5_phase_a5_offboard_historical_properties.py`

**down_revision:** `d1e2f3a4b5c6`  
**Phase label:** A.5  
**Audit script classification:** `no_op` (data migration only; no DDL)

**Changes:**

| Operation | Object | Detail |
|---|---|---|
| `UPDATE` | `properties` | Sets `renting_state = 'offboarded'` WHERE id NOT IN (14 active UUIDs) |

No tables created, no columns added. Post-migration state verified by migration:
13 active, 1 pre_launch, 44 offboarded, 58 total.

---

## Phase B — Owner Booking Flag

### `a3b5c7d9e1f2` — `a3b5c7d9e1f2_add_is_owner_booking_to_reservations.py`

**down_revision:** `f8e1d2c3b4a5`  
**Phase label:** B  
**Audit script classification:** `no_op` (raw SQL; parser limitation)

**Creates / Alters:**

| Operation | Object | Detail |
|---|---|---|
| `ALTER TABLE` | `reservations.is_owner_booking` | `BOOLEAN NOT NULL DEFAULT false` |
| `CREATE INDEX` | `ix_reservations_is_owner_booking` | `ON reservations (is_owner_booking)` |

---

## Phase C — Owner Charges

### `c9e2f4a7b1d3` — `c9e2f4a7b1d3_add_owner_charges_table.py`

**down_revision:** `a3b5c7d9e1f2`  
**Phase label:** C  
**Audit script classification:** `no_op` (raw SQL; parser limitation)

**Creates / Alters:**

| Operation | Object | Detail |
|---|---|---|
| `CREATE TYPE` | `owner_charge_type_enum` | 17 values — see file for full list |
| `CREATE TABLE` | `owner_charges` | Full column list below |

**`owner_charges` columns:**

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | BIGSERIAL | NOT NULL | — | PK |
| `owner_payout_account_id` | BIGINT | NOT NULL | — | FK → owner_payout_accounts(id) ON DELETE RESTRICT |
| `posting_date` | DATE | NOT NULL | — | |
| `transaction_type` | owner_charge_type_enum | NOT NULL | — | |
| `description` | VARCHAR(500) | NOT NULL | — | CHECK (description != '') |
| `amount` | NUMERIC(12,2) | NOT NULL | — | CHECK (amount != 0) |
| `reference_id` | VARCHAR(100) | NULL | — | |
| `originating_work_order_id` | BIGINT | NULL | — | |
| `created_at` | TIMESTAMPTZ | NOT NULL | now() | |
| `created_by` | VARCHAR(255) | NOT NULL | — | |
| `voided_at` | TIMESTAMPTZ | NULL | — | Must pair with voided_by |
| `voided_by` | VARCHAR(255) | NULL | — | Must pair with voided_at |
| `void_reason` | TEXT | NULL | — | |

**Constraints:** `chk_oc_amount_not_zero`, `chk_oc_description_not_empty`, `chk_oc_void_pair`

**Indexes:**
- `ix_oc_owner_date` ON (owner_payout_account_id, posting_date)
- `ix_oc_transaction_type` ON (transaction_type)
- `ix_oc_active` ON (owner_payout_account_id, posting_date) WHERE voided_at IS NULL

**`owner_charge_type_enum` values:**
`cleaning_fee`, `maintenance`, `management_fee`, `supplies`, `landscaping`, `linen`,
`electric_bill`, `housekeeper_pay`, `advertising_fee`, `third_party_ota_commission`,
`travel_agent_fee`, `credit_card_dispute`, `federal_tax_withholding`,
`adjust_owner_revenue`, `credit_from_management`, `pay_to_old_owner`, `misc_guest_charges`

---

## Phase D — Balance Period Lifecycle Columns

### `f1e2d3c4b5a6` — `f1e2d3c4b5a6_add_voided_paid_by_to_balance_periods.py`

**down_revision:** `c9e2f4a7b1d3`  
**Phase label:** D  
**Audit script classification:** `no_op` (raw SQL; parser limitation)

**Creates / Alters:**

| Operation | Object | Detail |
|---|---|---|
| `ALTER TABLE` | `owner_balance_periods.voided_at` | TIMESTAMPTZ NULL |
| `ALTER TABLE` | `owner_balance_periods.voided_by` | VARCHAR(255) NULL |
| `ALTER TABLE` | `owner_balance_periods.paid_by` | VARCHAR(255) NULL |

---

## Phase E — Merge Point

### `e5merge01` — `e5merge01_merge_phase_d_and_fees_for_e5.py`

**down_revision:** `('f1e2d3c4b5a6', 'k6f7a8b9c0d1')`  
**Phase label:** E (merge)

No schema changes. Converges the owner-statement branch (f1e2d3c4b5a6) and the
fees/other branch (k6f7a8b9c0d1) into a single head before E.5 additions.

---

## Phase E.5a — Owner Mailing Address + Property Group

### `e5a1b2c3d4f5` — `e5a1_add_owner_address_and_property_group.py`

**down_revision:** `e5merge01`  
**Phase label:** E.5a

**Creates / Alters:**

| Operation | Object | Detail |
|---|---|---|
| `ADD COLUMN` | `owner_payout_accounts.mailing_address_line1` | VARCHAR(255) NULL |
| `ADD COLUMN` | `owner_payout_accounts.mailing_address_line2` | VARCHAR(255) NULL |
| `ADD COLUMN` | `owner_payout_accounts.mailing_address_city` | VARCHAR(100) NULL |
| `ADD COLUMN` | `owner_payout_accounts.mailing_address_state` | VARCHAR(50) NULL |
| `ADD COLUMN` | `owner_payout_accounts.mailing_address_postal_code` | VARCHAR(20) NULL |
| `ADD COLUMN` | `owner_payout_accounts.mailing_address_country` | VARCHAR(50) NULL DEFAULT 'USA' |
| `ADD COLUMN` | `properties.property_group` | VARCHAR(100) NULL |

---

## Phase E.5b — Owner Magic Token Mailing Address

### `e5b2c3d4e5f6` — `e5b2_add_address_to_owner_magic_tokens.py`

**down_revision:** `e5a1b2c3d4f5`  
**Phase label:** E.5b

**Creates / Alters:**

| Operation | Object | Detail |
|---|---|---|
| `ADD COLUMN` | `owner_magic_tokens.mailing_address_line1` | VARCHAR(255) NULL |
| `ADD COLUMN` | `owner_magic_tokens.mailing_address_line2` | VARCHAR(255) NULL |
| `ADD COLUMN` | `owner_magic_tokens.mailing_address_city` | VARCHAR(100) NULL |
| `ADD COLUMN` | `owner_magic_tokens.mailing_address_state` | VARCHAR(50) NULL |
| `ADD COLUMN` | `owner_magic_tokens.mailing_address_postal_code` | VARCHAR(20) NULL |
| `ADD COLUMN` | `owner_magic_tokens.mailing_address_country` | VARCHAR(50) NULL DEFAULT 'USA' |

---

## Phase E.6 — Property Address Fields (HEAD)

### `e6a1b2c3d4f5` — `e6a1_add_property_address_city_state_postal.py`

**down_revision:** `e5b2c3d4e5f6`  
**Phase label:** E.6  
**Status:** Current HEAD as of 2026-04-15

**Creates / Alters:**

| Operation | Object | Detail |
|---|---|---|
| `ADD COLUMN` | `properties.city` | VARCHAR(100) NULL |
| `ADD COLUMN` | `properties.state` | VARCHAR(50) NULL |
| `ADD COLUMN` | `properties.postal_code` | VARCHAR(20) NULL |

---

## Phase F — Email Cron (no schema changes)

Phase F implemented the automated statement email cron job. No Alembic migrations
were produced by Phase F — all schema was already present from Phases A–E.

Phase F code: `backend/services/statement_workflow.py` and the cron integration.

---

## Cross-Table Summary

### `owner_balance_periods`

| Column | Added by |
|---|---|
| id, owner_payout_account_id, period_start, period_end, opening_balance, closing_balance, total_revenue, total_commission, total_charges, total_payments, total_owner_income, status, created_at, updated_at, approved_at, approved_by, paid_at, emailed_at, notes | `d1e2f3a4b5c6` (Phase A) |
| voided_at, voided_by, paid_by | `f1e2d3c4b5a6` (Phase D) |

### `owner_charges`

| Column | Added by |
|---|---|
| All columns | `c9e2f4a7b1d3` (Phase C) |

### `owner_statement_sends`

| Column | Added by |
|---|---|
| All columns | `e7c3f9a1b5d2` (Phase E infrastructure) |

### `owner_payout_accounts` (new columns only — table pre-existed)

| Column | Added by |
|---|---|
| `commission_rate`, `streamline_owner_id` | `e7c3f9a1b5d2` (Phase E infrastructure) |
| `mailing_address_line1–6` | `e5a1b2c3d4f5` (Phase E.5a) |

### `owner_magic_tokens` (new columns only — table pre-existed)

| Column | Added by |
|---|---|
| `commission_rate` | `c1a8f3b7e2d4` (Phase E infrastructure) |
| `mailing_address_line1–6` | `e5b2c3d4e5f6` (Phase E.5b) |

### `properties` (new columns only — table pre-existed)

| Column | Added by |
|---|---|
| `renting_state` | `d1e2f3a4b5c6` (Phase A) |
| `property_group` | `e5a1b2c3d4f5` (Phase E.5a) |
| `city`, `state`, `postal_code` | `e6a1b2c3d4f5` (Phase E.6 — HEAD) |

### `reservations` (new column only — table pre-existed)

| Column | Added by |
|---|---|
| `is_owner_booking` | `a3b5c7d9e1f2` (Phase B) |

---

## Audit Script Limitation Note

The script at `backend/scripts/audit_alembic_reconciliation.py` uses a lightweight
regex parser. It only detects `op.create_table("tablename"...)` and
`op.add_column("tablename"...)` call patterns. Phase A-F migrations issue DDL via
`op.execute(sa.text("CREATE TABLE ..."))` which the parser classifies as `no_op`.

All Phase A-F revisions classified as `no_op` by the audit script ARE in fact
fully applied to fortress_shadow. The tables and columns listed in this document
are all present. To verify any specific object:

```sql
-- Table presence
SELECT to_regclass('public.owner_balance_periods');  -- returns OID if present

-- Column presence
SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'owner_balance_periods'
ORDER BY ordinal_position;
```
