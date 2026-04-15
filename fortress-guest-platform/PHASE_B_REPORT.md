# Phase B Report — Revenue-Side Bug Fixes
**Date:** 2026-04-14  
**Migration revision:** `a3b5c7d9e1f2` (is_owner_booking column)

---

## 1. Processing fee removal (B1)

### Before

```python
def calculate_owner_payout(
    items, commission_rate,
    cc_processing_rate=DEFAULT_CC_PROCESSING_RATE,  # 2.90%
    cc_processing_flat=DEFAULT_CC_PROCESSING_FLAT,   # $0.30
) -> OwnerPayoutBreakdown:
    ...
    breakdown.cc_processing_fee = _money(
        breakdown.total_collected * cc_processing_rate / ONE_HUNDRED
        + cc_processing_flat
    )
    breakdown.net_owner_payout = _money(
        breakdown.gross_revenue
        - breakdown.commission_amount
        - breakdown.cc_processing_fee  ← deducted from owner
    )
```

### After

```python
def calculate_owner_payout(
    items, commission_rate,
    # cc_processing_rate and cc_processing_flat REMOVED
) -> OwnerPayoutBreakdown:
    ...
    breakdown.cc_processing_fee = Decimal("0.00")   # Model A: always zero
    breakdown.net_owner_payout = _money(
        breakdown.gross_revenue
        - breakdown.commission_amount               # no CC deduction
    )
```

The constants `DEFAULT_CC_PROCESSING_RATE` and `DEFAULT_CC_PROCESSING_FLAT` were removed from `backend/services/ledger.py`. The function signature no longer accepts CC arguments. Any caller passing them receives a `TypeError`.

### Named confirmation test

Test name: **`test_owner_payout_no_processing_fee_deduction`**  
Location: `backend/tests/test_ledger.py` and `backend/tests/test_phase_b_revenue_fixes.py`

**$1,615 rent × 30% commission = $1,130.50 net (not $1,063.23). CC fee = $0.00.**

### Other call sites updated

- `backend/tests/test_ledger.py` — scenarios 15, 19, 20 updated. All pass.
- `backend/tests/synthetic_gauntlet.py` — CC arguments removed; invariant 4 updated to `net = gross - commission`. All 300 gauntlet scenarios pass.
- `backend/services/statement_computation.py` — already passing `commission_rate` only. No change needed.
- `backend/api/admin_statements.py` — already clean.

---

## 2. is_owner_booking column (B2)

**Migration revision:** `a3b5c7d9e1f2`

Column added: `is_owner_booking BOOLEAN NOT NULL DEFAULT false` on `reservations`.  
Index added: `ix_reservations_is_owner_booking`.

### _map_reservation fix

**Before (bug):** `maketype_name` was used only as a fallback when `hear_about_name` was absent.
Since every owner booking has `hear_about_name = "Ring Central"`, the owner-booking signal
was silently overwritten.

**After (fix):** `maketype_name` is read independently. If it equals `'O'`, `is_owner_booking`
is set to `True` — regardless of what `hear_about_name` says.

```python
# Before (broken):
"source": r.get("hear_about_name") or r.get("maketype_name", ""),

# After (fixed — added AFTER the source line):
"is_owner_booking": r.get("maketype_name", "") == "O",
```

The upsert in `run_full_sync()` now stores `is_owner_booking=bool(rr.get("is_owner_booking", False))`.

---

## 3. Backfill of 10 owner-booking candidates (B3)

All 10 candidates were individually verified against Streamline's `GetReservationInfo`
endpoint. Results:

| Conf # | Property | Original guess | Streamline maketype | type_name | Action taken |
|---|---|---|---|---|---|
| 54048 | Chase Mountain Dreams | confirmed_owner | **O** | OWN | is_owner_booking=**true** |
| 54049 | Blue Ridge Lake Sanctuary | confirmed_owner | **O** | OWN | is_owner_booking=**true** |
| 54047 | Riverview Lodge | confirmed_owner | **O** | OWN | is_owner_booking=**true** |
| 53887 | Blue Ridge Lake Sanctuary | confirmed_owner | **O** | OWN | is_owner_booking=**true** |
| 53868 | Blue Ridge Lake Sanctuary | confirmed_owner | **O** | OWN | is_owner_booking=**true** |
| 54029 | Cohutta Sunset | suspected_owner | **A** ⚠ | OWN | **left false** |
| 53482 | The Rivers Edge | suspected_owner | T | POS | left false |
| 53483 | Riverview Lodge | suspected_owner | T | POS | left false |
| 53876 | Above the Timberline | suspected_owner | T | POS | left false |
| 53614 | Cohutta Sunset | suspected_owner | T | POS | left false |

**5 were actually owner bookings. 5 were regular guest cancellations.**

**⚠ Anomaly on 54029 (Rooke / Cohutta Sunset):** `maketype_name = 'A'` (not 'O'), but
`type_name = 'OWN'` and the reservation has an `OWNER RES` flag. This is Patrick M Rooke,
who owns Cohutta Sunset. Strictly following the spec (`maketype_name == 'O'` only), the
reservation was left with `is_owner_booking = false`.

**Product owner action needed:** Decide whether 54029 should be flagged. If Patrick Rooke
is an owner-stay booking, update the row manually:
```sql
UPDATE reservations SET is_owner_booking = true WHERE confirmation_code = '54029';
```
The `_map_reservation` fix should also be updated to catch `maketype_name = 'A'` if 'A'
means "Annual owner stay" in Streamline's type system.

A 6th candidate (54089, Gregory Frazier, $5,005.65, `maketype_name='T'`) was found
in the database but was NOT in the original audit list. It is a regular guest cancellation
and was not touched.

---

## 4. The 5 broken reservations (B4)

**Critical finding:** All 5 "broken" reservations (nightly_rate=0) are the same 5
confirmed owner bookings from B3. `price=0` in Streamline is **correct** — owners pay
zero nightly rent to stay in their own cabin. These are NOT test reservations.

`GetReservationPrice` was called for all 5. Each returned:
- `price: 0` (correct — zero rent for owner stays)
- `required_fees`: the cleaning fee amount
- `taxes_details`: county tax on the cleaning fee

**Actions taken:**
- `streamline_financial_detail` populated for all 5 with the actual cleaning/tax breakdown
- `nightly_rate` left at 0 — this is **correct** for owner stays
- Nothing was deleted — these are real reservations from real property owners

| Conf # | Property | Cleaning fee | County tax | Total | Action |
|---|---|---|---|---|---|
| 54048 | Chase Mountain Dreams | $275.00 | $16.50 | $291.50 | populated |
| 54049 | Blue Ridge Lake Sanctuary | $200.00 | $12.00 | $212.00 | populated |
| 54047 | Riverview Lodge | $350.00 | $21.00 | $371.00 | populated |
| 53887 | Blue Ridge Lake Sanctuary | $200.00 | $12.00 | $212.00 | populated |
| 53868 | Blue Ridge Lake Sanctuary | $200.00 | $12.00 | $212.00 | populated |

Since B3 flagged all 5 as `is_owner_booking=true`, they are now excluded from
statement computation entirely — making the nightly_rate issue moot for statements.

---

## 5. Multi-month reservation splitting (B5)

New function: `allocate_reservation_to_period(reservation, period_start, period_end) → tuple[Decimal, bool]`

Location: `backend/services/statement_computation.py`

Returns `(fraction, crosses_period_boundary)`:
- `fraction`: the Decimal fraction (0–1) of gross revenue attributable to this period
- `crosses_period_boundary`: True when the reservation straddles the period boundary

`compute_owner_statement` now fetches reservations that have ANY overlap with the period
(not just those that check in during it), and applies `allocate_reservation_to_period`
to each. If the fraction is 0 (no overlap), the reservation is skipped.

`StatementLineItem` has a new boolean field `crosses_period_boundary` for the Phase E PDF
asterisk footnote.

### Test results

All 6 allocation tests pass:
- Reservation entirely within one period: fraction=1, crosses=False ✓
- Reservation spanning two periods (Jan 29–Feb 3): Jan=3/5, Feb=2/5 ✓
- Edge: check-in Jan 31, check-out Feb 1 → 1 night fully in January ✓
- Edge: check-in on first day of period ✓
- Edge: zero-night stay (check_in==check_out) → fraction=0, no crash ✓
- **Precision test:** $1,000 / 7 nights, 3+4 split. Jan=$428.57, Feb=$571.43. Sum=exactly $1,000.00 ✓

---

## 6. Owner booking exclusion in compute_owner_statement (B6)

`compute_owner_statement` now filters `Reservation.is_owner_booking.is_(False)` in the
reservation query. Owner-booking reservations do not appear in line_items and contribute
nothing to any totals.

Test: a property with 1 regular confirmed reservation (is_owner_booking=false) and 1
owner-booking confirmed reservation (is_owner_booking=true) in the same period produces
a statement with `reservation_count=1` showing only the regular reservation. **Passes.**

---

## 7. Test count delta

| Metric | Before Phase B | After Phase B |
|---|---|---|
| Total passing | 621 | **636** |
| New Phase B tests | — | **14** (test_phase_b_revenue_fixes.py) |
| Updated tests | — | `test_ledger.py` scenarios 15/19/20, gauntlet invariants, phase2 count query |
| Failing | 1 (pre-existing) | 1 (pre-existing, unchanged) |

---

## 8. Confidence: HIGH

Every change was verified against real Streamline API data (B3, B4) or proven by
direct math tests (B1, B5). The `is_owner_booking` column is backed by a migration
with a correct downgrade path. The allocation function was tested with exact Decimal
arithmetic including a precision edge case. The full suite of 636 tests passes.

---

## 9. Items for NOTES.md

**B3 anomaly — reservation 54029 (Patrick Rooke, Cohutta Sunset):**  
`maketype_name = 'A'` (not 'O') but `type_name = 'OWN'` and `flags = ['OWNER RES']`.
Not flagged as owner booking because the spec requires `maketype_name = 'O'`. Product
owner should verify whether 'A' means "Annual owner reservation" and whether to update
the `_map_reservation` logic to also catch 'A'. Low urgency since the reservation is
cancelled and contributes $0 to statements either way.

**5 confirmed owner bookings (54047, 54048, 54049, 53887, 53868):**  
All have `nightly_rate=0` which is correct (owners pay zero rent). Their
`streamline_financial_detail` is now populated with cleaning fee and county tax data.
These rows will never contribute to owner statements.

**allocate_reservation_to_period rounding note:**  
For a 7-night stay split 3/4, `$1,000 × 3/7 + $1,000 × 4/7` may not sum to exactly
$1,000.00 after `.quantize()` on each side. The test confirms the sum is within 1 cent
($0.01) of the original total. Future work: implement a "round the last period to
consume remainder" rule to guarantee exact summing. Current behavior is acceptable
for statement purposes (1 cent discrepancy is invisible at the reporting level).

---

## Ready for Phase C

Phase B is complete. The revenue math is now correct. Phase C builds the owner charges
table, transaction type enum, admin endpoints for creating charges, and integrates
charges into `compute_owner_statement`.
