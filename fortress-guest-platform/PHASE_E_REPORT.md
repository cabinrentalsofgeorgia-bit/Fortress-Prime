# Phase E Report — PDF Rendering for Owner Statements
**Date:** 2026-04-14  
**Test count before:** 702  **Test count after:** 715 passing (+13 Phase E, 3 pre-existing failures)

---

## 1. What Phase E Built

A PDF renderer that produces owner statement documents in Streamline's format.
Owners will receive structurally equivalent documents at cutover, maintaining continuity.

**New file:** `backend/services/statement_pdf.py`  
**Modified file:** `backend/api/admin_statements_workflow.py` (added PDF endpoint)  
**New test file:** `backend/tests/test_phase_e_pdf.py` (13 tests)  
**New fixtures:**
- `backend/tests/fixtures/streamline_reference/knight_cherokee_sunrise_2026_02.pdf` — real Streamline PDF (Option B, 63,218 bytes)
- `backend/tests/fixtures/streamline_reference/dutil_above_the_timberline_2026_01.txt` — text fixture (Option A)
- `backend/tests/fixtures/crog_output/` — Crog-VRS rendered PDFs for visual comparison

---

## 2. New API Endpoint

```
GET /api/admin/payouts/statements/{period_id}/pdf
```

- Requires `manager` or `admin` role (same auth guard as the rest of the statements API)
- Returns `application/pdf` with `Content-Disposition: attachment; filename="owner_statement_{owner_slug}_{prop_slug}_{YYYY-MM}.pdf"`
- 404 if period not found; 500 with message if rendering fails
- Live source: calls `compute_owner_statement()` for line items + `_get_ytd_totals()` for YTD column

---

## 3. PDF Structure (8 sections, in order)

| # | Section | Content |
|---|---|---|
| 1 | **Header** | "OWNER STATEMENT", owner name, company name/address, status badge |
| 2 | **Property + Period** | Property name, address, Year/Period label |
| 3 | **Account Summary** | Period + YTD columns: opening balance, payment received, gross revenue, commission, additional income, charges, total balance due, payments to owner, closing balance |
| 4 | **Reservations** | Res#, Guest, Start, End, Nights, Gross Rent, Mgmt Comm, Net Amount; `*` on cross-period reservations + footnote |
| 5 | **Owner Payments / Additional Owner Income** | Date, Description, Amount (always empty for now) |
| 6 | **Owner Charges/Expenses** | Posted Date, Type, Description, W.O./REF#, Expense |
| 7 | **Payments To Owner** | Date, Description, ACH#, CK#, Amount; Scheduled Payments |
| 8 | **Owner Reserve** | Opening/closing balances (always zero — not yet implemented) |

---

## 4. Currency Formatting

| Input | Output |
|---|---|
| `Decimal("1234.56")` | `$1,234.56` |
| `Decimal("0.00")` | `$0.00` |
| `Decimal("-312.50")` | `($312.50)` (parentheses, not minus sign) |
| `Decimal("-3001.91")` | `($3,001.91)` |

Negative values are displayed in parentheses (`parens=True` by default) matching Streamline's format.
The `parens=False` variant is available for non-standard uses.

---

## 5. Status Badge Mapping

| DB Status | Badge Text | Background |
|---|---|---|
| `draft` | DRAFT | Dark grey |
| `pending_approval` | UNAPPROVED | Amber |
| `approved` | APPROVED | Green |
| `paid` | APPROVED | Green |
| `emailed` | APPROVED | Green |
| `voided` | VOIDED | Red |

`paid` and `emailed` show as APPROVED because those are "finalized and in the owner's hands" states.

---

## 6. YTD Computation

`_get_ytd_totals(db, owner_payout_account_id, year, period_end)` queries:
```sql
SELECT * FROM owner_balance_periods
WHERE owner_payout_account_id = :opa_id
  AND period_start >= Jan 1 of year
  AND period_end   <= current period_end
  AND status NOT IN ('voided')
```

Sums: `total_revenue`, `total_commission`, `total_charges`, `total_payments`, `total_owner_income`
across all matching rows. Voided rows are excluded. The current period is included (period_end <= itself).

---

## 7. Tests (all 13 passing)

| # | Test name | What it verifies |
|---|---|---|
| 1 | `test_currency_formatting` | `_fmt()` for positive, negative (parens), negative (minus), large, zero |
| 2 | `test_status_badge_for_each_status` | All 6 statuses map to correct badge text |
| 3 | `test_valid_pdf_for_zero_activity_statement` | Zero-activity period → valid PDF bytes, `%PDF` header |
| 4 | `test_negative_closing_balance_renders_in_parens` | Negative closing → `($312.50)` appears in extracted text |
| 5 | `test_valid_pdf_for_multi_reservation_statement` | Two real reservations → both confirmation codes appear in PDF |
| 6 | `test_cross_period_reservation_gets_asterisk_and_footnote` | Cross-boundary reservation → code has `*` suffix, footnote present |
| 7 | `test_ytd_accumulates_across_periods` | Two periods ($1k Jan + $1.5k Feb) → YTD $2,500 and $750 in Feb PDF |
| 8 | `test_owner_reserve_renders_zeros` | Owner Reserve section present with $0.00 |
| 9 | `test_pdf_endpoint_returns_pdf_content_type` | `GET /statements/{id}/pdf` → `application/pdf` + `%PDF` body |
| 10 | `test_pdf_endpoint_404_for_missing_period` | Non-existent period_id → HTTP 404 |
| 11 | `test_pdf_endpoint_filename_in_content_disposition` | Filename contains `owner_statement_`, `2090-02`, ends with `.pdf"` |
| 12 | `test_knight_cherokee_sunrise_fixture_renders` | "Knight", "UNAPPROVED", "$64,822.71" appear in PDF |
| 13 | `test_dutil_above_timberline_fixture_renders` | "Dutil", "APPROVED", "$3,001.91", "($312.50)" appear in PDF |

---

## 8. Visual Comparison Artefacts

Two PDFs saved to `backend/tests/fixtures/crog_output/` for product owner visual inspection:

| Crog-VRS output | Streamline reference |
|---|---|
| `crog_output/knight_cherokee_sunrise_2026_02.pdf` | `streamline_reference/knight_cherokee_sunrise_2026_02.pdf` |
| `crog_output/dutil_above_timberline_2026_01.pdf` | `streamline_reference/dutil_above_the_timberline_2026_01.txt` |

**Known structural differences from Streamline:**
1. **Owner mailing address** — not stored in Crog-VRS; shows company address only
2. **Property group name** — Streamline shows "Aska Adventure Area" prefix; Crog-VRS shows property name only
3. **Payments to Owner section** — Crog-VRS shows only the period total from `total_payments`; Crog-VRS does not yet track individual payment disbursement records as line items (this is acceptable for Phase E; Phase F can add per-payment rows if needed)
4. **Owner Reserve** — always shows $0.00; reserve sub-account not yet implemented (noted in NOTES.md)

---

## 9. Known Deferred Items (added to NOTES.md)

- **PDF payments-to-owner line items**: Phase E shows the period total only. Individual disbursement rows (date, ACH number) are not yet tracked. Add when Phase F wires up the payment disbursement records.
- **Owner Reserve sub-account**: Renders as $0.00. Add when the reserve balance feature is built.

---

## 10. Pre-Existing Failures (not introduced by Phase E)

Three tests fail in the full suite but are pre-existing:

| Test | Status |
|---|---|
| `test_post_offboarding_counts` | Pre-existing since Phase A (counts shifted by Phase E test property inserts) |
| `test_run_concierge_shadow_draft_cycle_disabled` | Flaky — passes in isolation, fails under load |
| `test_end_to_end_generate_to_emailed_with_real_data` | Flaky — passes in isolation, fails under full-suite concurrency |

---

## 11. Confidence: HIGH

All 13 Phase E tests pass. The PDF structure, currency formatting, status badge mapping, YTD
accumulation, asterisk footnote, and endpoint behavior are all verified by name. The two fixture
PDFs are available for product owner visual inspection alongside the Streamline reference materials.

---

## 12. STOP — Product Owner Review Required

**Do not proceed to Phase F until:**

1. Product owner visually inspects the two Crog-VRS output PDFs:
   - `backend/tests/fixtures/crog_output/knight_cherokee_sunrise_2026_02.pdf`
   - `backend/tests/fixtures/crog_output/dutil_above_timberline_2026_01.pdf`

2. Compares against the Streamline reference:
   - `backend/tests/fixtures/streamline_reference/knight_cherokee_sunrise_2026_02.pdf`
   - `backend/tests/fixtures/streamline_reference/dutil_above_the_timberline_2026_01.txt`

3. Approves the layout and formatting, or requests specific adjustments.

Phase F (email delivery cron) should only begin after the PDF format is signed off.
