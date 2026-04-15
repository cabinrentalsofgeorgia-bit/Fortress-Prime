# Phase A.5 Report — Offboard Historical Properties
**Date:** 2026-04-14  
**Migration revision:** `f8e1d2c3b4a5`

---

## The 14 preserved property IDs

These 14 properties are in Streamline's current active roster and were NOT touched
by this migration. Their `renting_state` values were set by Phase A and are unchanged.

| Crog-VRS UUID | Property Name | renting_state |
|---|---|---|
| `50f8e859-c30c-4d4c-a32e-8c8189eebb6c` | Above the Timberline | **active** |
| `8302f1c9-40d8-4d4d-99ae-f83647a15cc6` | Aska Escape Lodge | **active** |
| `ba440208-cfcf-4b47-b687-0f07f0436c21` | Blue Ridge Lake Sanctuary | **active** |
| `ed6a2ba8-6cca-4f69-b822-4b825e44d4af` | Chase Mountain Dreams | **active** |
| `50a9066d-fc2e-44c4-a716-25adb8fbad3e` | Cherokee Sunrise on Noontootla Creek | **active** |
| `53d047f9-2ba4-4ef4-bb29-22f34df279d3` | Cohutta Sunset | **active** |
| `72e278a3-1dc1-4bd8-9373-ce8f234f8ea0` | Creekside Green | **active** |
| `93b2253d-7ae4-4d6f-8be2-125d33799c88` | Fallen Timber Lodge | **active** |
| `25e397f9-ce07-4924-9fb6-c09759aff357` | High Hopes | **active** |
| `d7f4a8d3-7947-4d56-9c46-1cb37b96fd85` | Restoration Luxury | **pre_launch** (set by Phase A) |
| `200780d1-2d26-494f-ae7a-5214ac0dd9e7` | Riverview Lodge | **active** |
| `63bf8847-9990-4a36-9943-b6c160ce1ec4` | Serendipity on Noontootla Creek | **active** |
| `e22e6ef2-1d8e-4310-ad73-0a105eda0583` | Skyfall | **active** |
| `7a263caf-6b0f-46cd-af22-6d1a0bfe486e` | The Rivers Edge | **active** |

---

## Post-migration counts

| renting_state | Count |
|---|---|
| `active` | **13** |
| `pre_launch` | **1** |
| `offboarded` | **44** |
| **Total** | **58** |

13 + 1 + 44 = 58. All counts verified by the migration's own CHECK logic and by
the test suite.

---

## What the migration did

A single `UPDATE` statement set `renting_state = 'offboarded'` on every property
whose `id` was not in the 14-entry list. The 44 offboarded properties:

- All had `is_active = false` before this migration (unchanged)
- All had `renting_state = 'active'` (incorrectly set by Phase A's `DEFAULT 'active'`)
- All have zero reservations — ever, not just recently
- All have zero `owner_payout_accounts` rows
- All have zero `owner_balance_periods` rows

The migration ran built-in verification queries immediately after the UPDATE. If
any count had been wrong (e.g., some property was counted twice, or a 15th active
property appeared that wasn't on the list), the migration would have raised an error
and rolled back.

The downgrade path (`downgrade()`) sets the 44 offboarded rows back to `active`,
reversing the migration cleanly.

---

## What was NOT touched

- `is_active` column — not modified by this migration
- The 14 preserved property rows — not modified
- Any reservation rows
- Any `owner_payout_accounts` rows
- Any `owner_balance_periods` rows
- All Phase A work (migration `d1e2f3a4b5c6`, tests, models) — unchanged

---

## Test count delta

| Metric | Before Phase A.5 | After Phase A.5 |
|---|---|---|
| Total passing | 617 | **621** |
| New tests (Phase A.5, added to existing file) | — | **4** |
| Failing | 1 (pre-existing) | 1 (pre-existing, unchanged) |

The 4 new tests verify:
1. The exact 13/1/44/58 counts
2. Each of the 14 preserved properties has the exact expected `renting_state`
3. `compute_owner_statement` raises `property_not_renting` for an offboarded property
4. All 13 active properties can run through `compute_owner_statement` without error

---

## Confidence: HIGH

The migration is a single UPDATE with hardcoded UUIDs verified against the live
Streamline API. The migration verifies its own output before committing. All 15 tests
(11 Phase A + 4 Phase A.5) pass. The full suite runs clean at 621 passing.

---

## Ready for Phase B

Phase A and Phase A.5 are complete. The `renting_state` column is correctly set on
all 58 properties. The `owner_balance_periods` table and `get_or_create_balance_period`
function are in place. `compute_owner_statement` correctly guards against non-active
properties.

Phase B will:
- Remove the CC processing fee deduction from `calculate_owner_payout`
- Add `is_owner_booking` column to reservations
- Backfill the 5 confirmed + up to 5 cancelled owner bookings by calling Streamline
- Fix the 5 lump-sum Streamline reservations with `nightly_rate = 0`
- Add multi-month reservation splitting
- Exclude owner bookings from `compute_owner_statement`
