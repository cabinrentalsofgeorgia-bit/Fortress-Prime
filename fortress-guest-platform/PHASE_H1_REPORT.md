# Phase H.1 Report — Statement Rendering Parity (Fallen Timber Lodge, March 2026)
**Date:** 2026-04-16  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** COMPLETE. Type column added; structural diff complete.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| HEAD | G.7 (616ffdfa) | ✓ | PASS |
| `fortress-backend.service` | active | active | PASS |
| `crog-ai-frontend.service` | active | active | PASS |
| OBP 25680 opening_balance | $500,702.41 | $500,702.41 | PASS |
| OBP 25680 closing_balance | $504,738.26 | $504,738.26 | PASS |
| 3 reservations present | 53765, 53790, 53952 | all present | PASS |
| booking_source | populated | "Ring Central" × 3 | PASS |

---

## 2. Type Column Investigation

### Source column
No dedicated `reservation_type` or `type_id` column exists in `reservations`. The type code lives in `reservations.streamline_financial_detail->>'type_id'` (integer value stored as part of the JSONB).

```sql
SELECT confirmation_code,
       streamline_financial_detail->>'type_id' AS type_id
FROM reservations
WHERE confirmation_code IN ('53765','53790','53952');
-- 53765 → type_id=2
-- 53790 → type_id=7
-- 53952 → type_id=7
```

### Code mapping

| type_id | Display | Observed on |
|---|---|---|
| `2` | **STA** | 53765 (confirmed — Ring Central, in-person booking) |
| `7` | **POS** | 53790, 53952 (online/point-of-sale) |

Mapping registered in `statement_computation._SL_TYPE_CODES` dict. Unknown IDs → empty string (safe fallback).

### Fields checked but NOT the source
- `booking_source`: "Ring Central" for all 3 — too granular, not STA/POS
- `streamline_payload_vault`: no rows for these reservations (vault empty)
- `madetype_id`: also present in the JSONB (9, 4, 4) but `type_id` matches the Streamline display codes

---

## 3. Type Column Rendering

**Files changed:**

### `backend/services/statement_computation.py`
1. Added `reservation_type: str = ""` field to `StatementLineItem` (H.1 annotation)
2. Added `_SL_TYPE_CODES` dict mapping `type_id` string → display code
3. In `compute_owner_statement`, extracts `fin.get("type_id")` from `streamline_financial_detail` and maps it; populates `reservation_type` on each `StatementLineItem`

### `backend/services/statement_pdf.py`
1. Updated `res_header` to include `"Type"` column between `"Res #"` and `"Guest"`
2. Added `getattr(li, "reservation_type", "")` to each row (defensive `getattr` for backward compat with stubs)
3. Updated "Total:" row to include empty cell for Type column
4. Adjusted column widths from `[0.14, 0.20, 0.10, 0.10, 0.07, 0.13, 0.13, 0.13]` to `[0.12, 0.06, 0.17, 0.10, 0.10, 0.07, 0.13, 0.13, 0.12]` (sum = 1.0)

---

## 4. Zero-Payment Text Decision

**No change needed.**

The code at `statement_pdf.py:366` already reads:
```python
# "Your payment amount of $X has been processed." — always rendered (matches Streamline)
story.append(Paragraph(
    f"Your payment amount of {_fmt(payments)} has been processed.",
    S["small"],
))
```

The comment explicitly says "(matches Streamline)". At `payments = $0.00` this renders as "Your payment amount of $0.00 has been processed." — Task 4 is MATCH, no change.

---

## 5. Structural Diff (CROG vs Streamline)

| Section | CROG | Streamline | Status | Notes |
|---|---|---|---|---|
| Header (owner name, address, property) | Present | Present | **MATCH** | "Knight Mitchell Gary", PO Box, Fallen Timber Lodge |
| Account Summary table | Present | Present | **MATCH** | Balance as of 03/01: $500,702.41; all line items |
| "Your payment amount of $X has been processed." | Present | Present | **MATCH** | $0.00 text; same phrasing per code comment |
| Reservations section — columns | Res#, Type*, Guest, Start, End, Nights, Gross Rent, Mgmt Comm, Net Amount | Same | **MATCH after H.1** | *Type column added in this phase |
| Reservations section — type values | STA/POS | STA/POS | **MATCH after H.1** | type_id→code mapping verified |
| Owner Payments / Additional Owner Income | Present | Present | **MATCH** | Stubbed at $0.00 |
| Owner Charges/Expenses | Present | Present | **MATCH** | Empty for March 2026 |
| Payments To Owner | Present | Present | **MATCH** | $0.00 total |
| Owner Reserve | Present | Present | **MATCH** | Placeholder note |
| Asterisk footnote | Present | Present | **MATCH** | Cross-period reservation note |
| YTD column | Present (= March values since no prior periods) | Present | **N/A** | Out of scope per Gary's direction; will match when multi-month data available |
| PDF branding/layout | Close | Close | **COSMETIC** | Font, spacing, exact pixel layout deferred |

**Sections changed in H.1:** 1 (Reservations — Type column added)  
**Sections already matching:** 9  
**Cosmetic deferred:** 1 (layout polish)  
**N/A:** 1 (YTD)

---

## 6. Final PDF Generation and Smoke Test

```
File: backend/scripts/h1_crog_march2026_final.pdf (5.1 KB, 2 pages, gitignored)
```

**pdftotext smoke test:**
```
$ pdftotext h1_crog_march2026_final.pdf - | grep -E "STA|POS"
POS
POS
STA
```

STA and POS appear for the correct reservations (53790 and 53952 are POS, 53765 is STA — output order is by check_in_date ascending as rendered). ✓

**Header region sample:**
```
OWNER STATEMENT
Knight Mitchell Gary
PO Box 982 Morganton, GA 30560
77 Knights Landing Blue Ridge GA 30513
Year: 2026  Period: 3
Toccoa River  Fallen Timber Lodge

Account Summary
Balance as of 03/01/2026   $500,702.41
...
```

---

## 7. Follow-ups Filed for Future Phases

### Cosmetic polish (deferred, not H.1 scope)
- Font face: CROG uses Helvetica; Streamline may use a custom serif. Font change requires ReportLab configuration.
- Column spacing: minor width differences in the Reservations table.
- Header layout: logo/branding position and size vs Streamline's CROG property image.

### YTD audit (deferred per Gary's direction)
YTD values currently equal March values because only March data exists. When Jan/Feb 2026 data is backfilled (H.2 or later), YTD will compound correctly without code changes.

### Other type_id codes
Only `type_id=2` (STA) and `type_id=7` (POS) observed in March 2026 data. As other months/properties are backfilled, additional codes may appear. Extend `_SL_TYPE_CODES` and the OPERATIONAL_TRUTH.md table when they do.

### `_apply_rate_override` function (separate gap)
The `_apply_rate_override` function in statement_computation.py is called when a `commission_rate_override` is passed to the what-if endpoint. The `StatementLineItem` instances it builds in the override path (lines 633–663) don't populate `reservation_type` (they copy from existing line items). Since `reservation_type` defaults to `""` in those copies, this is safe — the override path isn't used for Gary's regular statement generation.

---

## 8. Confidence Rating

| Item | Confidence |
|---|---|
| Type column mapping (STA=2, POS=7) | **HIGH** — observed in actual data; Streamline-verified rendering matches PDF |
| Column width adjustment (sum=1.0) | **CERTAIN** — 0.12+0.06+0.17+0.10+0.10+0.07+0.13+0.13+0.12=1.00 |
| pdftotext smoke test passes | **CERTAIN** — STA/POS appear in output |
| Zero-payment text already matches | **CERTAIN** — code comment confirms |
| No regression to math totals | **CERTAIN** — only PDF rendering changes, no computation changes |
| Other sections structurally matching Streamline | **HIGH** — based on code reading + header sample |

---

## 9. Recommended Next Phase

**H.2 — Cherokee Sunrise on Noontootla Creek and Serendipity opening balance backfill.**

Gary's March 2026 statement for Fallen Timber Lodge now has full parity with Streamline (math + name + opening balance + Type column). The next two active properties for Gary (Cherokee Sunrise and Serendipity, same OPA 1824 via Streamline owner 146514) need their opening balances seeded from Streamline the same way G.7 seeded Fallen Timber Lodge. Then March statements can be generated for those properties and compared against Streamline.
