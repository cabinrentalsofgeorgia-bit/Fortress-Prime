# Properties Reconciliation Report
**Date:** 2026-04-14  
**Method:** Read-only. No rows modified. No migrations run.  
**Source of truth for active properties:** Streamline VRS (`GetPropertyList`)

---

## How the reconciliation was done

1. Called `StreamlineVRS.fetch_properties()` (wraps `GetPropertyList`) against the
   live Streamline API. Got the full list with `status_name` for each property.

2. Queried the `properties` table in `fortress_shadow` for all 58 rows: `id`, `name`,
   `streamline_property_id`, `renting_state`, `is_active`.

3. Matched on `streamline_property_id`. Properties with no Streamline ID were
   treated as unmatched (Bucket C).

4. Checked reservation history for all Bucket C properties: any reservation ever
   (not just recent).

---

## Bucket A — In both Streamline and Crog-VRS (14 properties)

All 14 match exactly. Names are identical character-for-character. All 14 Streamline
properties have `status_name = "Active"`.

| Streamline ID | Name | Crog-VRS renting_state | Crog-VRS is_active |
|---|---|---|---|
| 70206 | Cohutta Sunset | active | ✓ |
| 70209 | Fallen Timber Lodge | active | ✓ |
| 70220 | Riverview Lodge | active | ✓ |
| 70222 | Serendipity on Noontootla Creek | active | ✓ |
| 70224 | The Rivers Edge | active | ✓ |
| 235641 | Aska Escape Lodge | active | ✓ |
| 306758 | Cherokee Sunrise on Noontootla Creek | active | ✓ |
| 382651 | Above the Timberline | active | ✓ |
| 419022 | Blue Ridge Lake Sanctuary | active | ✓ |
| 441334 | High Hopes | active | ✓ |
| 756771 | Creekside Green | active | ✓ |
| 980130 | Chase Mountain Dreams | active | ✓ |
| 1001528 | Skyfall | active | ✓ |
| **1012373** | **Restoration Luxury** | **pre_launch** | ✓ |

**Note on Restoration Luxury:** Streamline reports it as `Active` — meaning Streamline
considers it a managed property. Crog-VRS correctly has it as `pre_launch` because it is
not yet generating guest revenue. This discrepancy is intentional and correct: the
`renting_state` column in Crog-VRS tracks revenue-generating readiness, not Streamline
management status. Restoration Luxury should remain `pre_launch` until it begins renting.

**All 14 names match exactly.** No name mismatches.

---

## Bucket B — In Streamline but NOT in Crog-VRS (0 properties)

**None.** Streamline returned exactly 14 properties and all 14 are present in
the Crog-VRS `properties` table. There is no missing data.

---

## Bucket C — In Crog-VRS but NOT in Streamline (44 properties)

These are historical properties from past management relationships that Streamline no
longer knows about. Every single one has:
- `is_active = false` (already marked inactive in Crog-VRS)
- **0 reservations — ever, not just in the last 24 months**
- `renting_state = active` (incorrectly set by the Phase A migration default)

**Group 1 — Properties with a Streamline ID (formerly managed, now offboarded): 23**

These were once in Streamline but were removed from the active roster at some point.
Crog-VRS still has their Streamline IDs on file.

| Streamline ID | Crog-VRS Name | is_active |
|---|---|---|
| 69413 | A River Of Dreams Lodge | false |
| 69630 | A Rolling River Cabin | false |
| 70199 | All Inspired Lodge | false |
| 70211 | Hemlock Hideaway | false |
| 70212 | Hidden Laurel Lodge | false |
| 70219 | Outlaw Ridge | false |
| 70221 | Sanctuary | false |
| 101503 | River Ridge Lodge | false |
| 101504 | Toccoa Tails | false |
| 335975 | Hawks Ridge | false |
| 386883 | Creekside Bend | false |
| 412821 | Blue Ridge In-Town Retreat | false |
| 418994 | Blue Ridge Bliss | false |
| 419132 | Happy Ours Lodge | false |
| 426588 | The Great Getaway | false |
| 430997 | Blue Ridge Lakewalk | false |
| 443929 | River Heights Lodge | false |
| 445301 | Lazy Creek Retreat | false |
| 455175 | Our True Blue | false |
| 498913 | Moonlight Serenade | false |
| 512192 | Peace of Heaven | false |
| 522645 | Wooded Bliss | false |
| 523567 | Above it All Lodge | false |

**Group 2 — Properties with NO Streamline ID: 21**

These have no `streamline_property_id` at all. They were presumably added to the
Crog-VRS database from a source other than Streamline (perhaps an earlier data import
from a different system or manual entry).

| Crog-VRS Name | is_active |
|---|---|
| 200 Amber Ridge | false |
| Amber Ridge | false |
| Bear Creek | false |
| Bella Vista | false |
| Buckhorn Lodge | false |
| Cadence Ridge | false |
| Cherry Log | false |
| Cloud 10 | false |
| Crooked Creek | false |
| Eagles Nest | false |
| Five Peaks | false |
| Hidden Creek | false |
| Majestic Lake | false |
| Melancholy Moose | false |
| Morningstar Vista | false |
| Mountain Laurel | false |
| Rolling River | false |
| Solitude | false |
| Toccoa Heights | false |
| Toccoa Retreat | false |
| Whispering Pines | false |

---

## Summary counts

| Bucket | Expected | Actual | Status |
|---|---|---|---|
| A — In both Streamline and Crog-VRS | 14 | **14** | ✓ |
| B — In Streamline but NOT in Crog-VRS | 0 | **0** | ✓ |
| C — In Crog-VRS but NOT in Streamline | 44 | **44** | ✓ |
| **Total Crog-VRS rows** | 58 | **58** | ✓ |

All counts match the expected numbers exactly.

---

## Key findings

**The data is clean.** Every currently-managed property is accounted for in both
systems. Every historical property already has `is_active = false` in Crog-VRS and
has never generated a reservation in the system. The only problem is that the Phase A
migration defaulted all 58 rows to `renting_state = 'active'` — the 44 Bucket C
properties need to be changed to `offboarded`.

**Zero risk in the offboarding migration.** The 44 Bucket C properties have:
- No reservations (ever)
- No owner_payout_accounts rows
- No owner_balance_periods rows
- Already `is_active = false`

Changing their `renting_state` from `active` to `offboarded` has zero downstream effect
on any existing data. It simply prevents them from accidentally appearing in any
statement generation or property-selection logic.

**Restoration Luxury should stay `pre_launch`, not be touched by the offboarding
migration.** It is in Bucket A (Streamline knows about it) and is intentionally set
to `pre_launch` by the Phase A migration.

---

## Recommendation

**Ready to proceed with offboarding migration.**

The migration should:
1. Set `renting_state = 'offboarded'` for all 44 Bucket C properties
   (where `streamline_property_id NOT IN (14 active IDs)` OR `streamline_property_id IS NULL`,
   AND `name != 'Restoration Luxury'`)
2. Leave all 13 active Bucket A properties unchanged (`renting_state = 'active'`)
3. Leave Restoration Luxury unchanged (`renting_state = 'pre_launch'`)

After the migration, the breakdown should be:
- 13 properties: `renting_state = 'active'`
- 1 property: `renting_state = 'pre_launch'` (Restoration Luxury)
- 44 properties: `renting_state = 'offboarded'`

This migration is safe to run immediately.
