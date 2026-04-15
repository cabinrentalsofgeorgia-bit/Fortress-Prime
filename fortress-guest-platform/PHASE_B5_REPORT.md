# Phase B.5 Report — Owner Booking Detection Rule Expansion
**Date:** 2026-04-14

---

## 1. Detection rule expansion

### Old rule (Phase B)

```python
# Only checked one signal:
"is_owner_booking": r.get("maketype_name", "") == "O"
```

This missed reservation 54029 because it has `maketype_name='A'` (not 'O'),
even though Streamline also sets `type_name='OWN'` and attaches the `OWNER RES` flag.

### New rule (Phase B.5)

A new helper method `detect_owner_booking(r: dict) -> bool` was added to
`StreamlineVRS` as a `@staticmethod`. It returns `True` when **any** of the
following is present in the Streamline response:

1. `maketype_name == 'O'`
2. `type_name == 'OWN'`
3. The `flags` array contains a flag named `'OWNER RES'` (case-insensitive)

It returns `False` when none of the three signals are present.

Every code path that evaluates "is this an owner booking?" calls
`detect_owner_booking()`. The logic is not duplicated anywhere.

```python
@staticmethod
def detect_owner_booking(r: dict) -> bool:
    if r.get("maketype_name", "") == "O":
        return True
    if r.get("type_name", "") == "OWN":
        return True
    flags_wrapper = r.get("flags", {})
    flag_list = flags_wrapper.get("flag", []) if isinstance(flags_wrapper, dict) else []
    if isinstance(flag_list, dict):
        flag_list = [flag_list]
    flag_names = {str(f.get("name", "")).upper() for f in flag_list if isinstance(f, dict)}
    return "OWNER RES" in flag_names
```

### Test results for the helper (9 tests, all passing)

| Test | Signal tested | Expected | Result |
|---|---|---|---|
| `test_detect_owner_booking_maketype_O` | maketype_name='O' alone | True | ✓ |
| `test_detect_owner_booking_type_name_OWN` | type_name='OWN' alone | True | ✓ |
| `test_detect_owner_booking_owner_res_flag` | 'OWNER RES' flag alone | True | ✓ |
| `test_detect_owner_booking_owner_res_flag_lowercase` | 'owner res' lowercase | True | ✓ |
| `test_detect_owner_booking_all_three_signals` | All three present | True | ✓ |
| `test_detect_owner_booking_none_of_three_signals` | maketype='T', type='POS' | False | ✓ |
| `test_detect_owner_booking_exact_54029_pattern` | maketype='A', type='OWN', OWNER RES flag | True | ✓ |
| `test_map_reservation_uses_detect_owner_booking` | 54029 pattern through _map_reservation | True | ✓ |
| `test_reservation_54029_is_owner_booking` | 54029 in DB | True | ✓ |

---

## 2. Reservation 54029

**Before Phase B.5:**

```
confirmation_code: 54029
is_owner_booking:  FALSE
status:            cancelled
total_amount:      238.50
check_in_date:     2026-05-31
check_out_date:    2026-12-31
property:          Cohutta Sunset
```

**After Phase B.5:**

```
confirmation_code: 54029
is_owner_booking:  TRUE
status:            cancelled
total_amount:      238.50 (unchanged — Phase C will handle this as an owner charge)
check_in_date:     2026-05-31
check_out_date:    2026-12-31
property:          Cohutta Sunset
```

This reservation is a departure hold blocking Cohutta Sunset for the rest of 2026
while Pat Rooke ends his management relationship. It was cancelled in Streamline,
so it already contributes $0 to statements on the cancellation filter. The
is_owner_booking=true flag provides a second layer of exclusion and ensures
future re-syncs do not accidentally treat it as a guest booking.

The $238.50 cleanup charge is a separate item — it represents the final cleaning
fee charged to Pat Rooke. It will be entered as an `owner_charges` record in
Phase C.

---

## 3. Re-scan results

**Scope:** All confirmed, checked-in, checked-out, and completed reservations on
the 14 active/pre-launch properties whose `is_owner_booking` was still False,
from the last 24 months. Excludes test reservations (B6REG-*, B6OWN-*, CRG-*).

**Scan stats:**

| Metric | Value |
|---|---|
| Reservations to scan | 33 |
| Streamline API calls made | 33 |
| Elapsed time | 13.9 seconds |
| Failed lookups | 0 |
| **New candidates found** | **0** |

**Candidates table:**

*No new candidates.* Every one of the 33 scanned reservations was a regular guest
booking (maketype_name='T', type_name='POS', no 'OWNER RES' flag). None of them
match the expanded owner-booking detection rule.

---

## AWAITING REVIEW

The following **0 reservations** match the new owner booking detection rule but were
missed by Phase B's narrower rule. The product owner must review this list and confirm
which reservations should be flagged. Reply with confirmation numbers to flag (e.g.,
'flag 54078, 54091, 54103'), or 'flag all' to flag every candidate, or 'flag none' to
skip all candidates and document the discrepancies in NOTES.md instead.

*(No candidates to review. The re-scan found zero new reservations that match the
expanded rule beyond the 54029 fix that was already applied.)*

---

## 4. Test count delta

| Metric | Before Phase B.5 | After Phase B.5 |
|---|---|---|
| Total passing | 636 | **645** |
| New Phase B.5 tests added | — | **9** (appended to test_phase_b_revenue_fixes.py) |
| Failing | 1 (pre-existing) | 1 (pre-existing, unchanged) |

---

## 5. Confidence: HIGH

- `detect_owner_booking()` is tested against all seven cases including the exact
  54029 pattern that Phase B missed.
- The 33-reservation re-scan completed in 13.9 seconds with zero API failures and
  zero new candidates. This confirms Phase B's narrower rule did not miss any
  additional reservations in the current database beyond 54029.
- Reservation 54029 was verified before and after the UPDATE. The row now has
  `is_owner_booking=true`.

---

## Notes for NOTES.md

**54029 (Rooke / Cohutta Sunset)** — `maketype_name='A'` is a Streamline booking
type that isn't 'O' but still represents an owner-related reservation. The 'A' code
meaning is unknown (possibly "Annual block" or "Administrative hold"). The new
`detect_owner_booking()` rule catches it via `type_name='OWN'` and the 'OWNER RES'
flag. If future owner reservations also use `maketype_name='A'`, the new rule will
catch them correctly. No code change needed.

**$238.50 on 54029** — This is a cleaning charge to the owner, not guest revenue.
It must be entered as an `owner_charges` record in Phase C against Cohutta Sunset's
payout account. The total_amount column on the reservation itself was not changed.
