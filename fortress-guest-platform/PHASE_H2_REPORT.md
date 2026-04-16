# Phase H.2 Report — Opening Balance Backfill (Cherokee Sunrise & Serendipity)
**Date:** 2026-04-16  
**Branch:** `fix/storefront-quote-light-mode`  
**Status:** COMPLETE. Three OBPs seeded; all PDFs verified.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| OBP 25680 opening | $500,702.41 | $500,702.41 | PASS |
| OBP 25680 closing | $504,738.26 | $504,738.26 | PASS |
| Active Gary properties | 3 | 3 (Fallen Timber, Cherokee, Serendipity) | PASS |
| Cherokee API vs DB delta | $0 | $0 | PASS |
| Serendipity API vs DB delta | < $100 | $2,347.30 → STOPPED | Resolved per §3 |

---

## 2. Option C Outcome (GetMonthEndStatement)

**Result: unavailable for both properties.**

- `GetMonthEndStatement(owner_id=146514, unit_id=306758, Feb 2026)` → E0191
- `GetMonthEndStatement(owner_id=146514, unit_id=70222, Feb 2026)` → E0191
- Owner-only Feb 2026 call returned one statement: **"Restoration Luxury"** (sl_property 1012373) — a 4th Gary property (owner_balance=$0, no OPA) that was not in scope for H.2.

Cherokee and Serendipity have no Streamline-generated owner statements for February or March 2026 (no Streamline-tracked billing activity triggered statement generation for those periods).

---

## 3. Authoritative Opening Balances (Gary's Streamline March 2026 Statements)

Gary confirmed March 2026 Streamline statements for all three properties, delivered via email and NAS-archived (via cpanel). These are the authoritative source for all future parity work.

| Property | March 1 Opening | March 31 Closing | Source |
|---|---|---|---|
| Fallen Timber Lodge | $500,702.41 | $504,738.26 | G.7 (already seeded) |
| Cherokee Sunrise | **$64,822.71** | $64,822.71 | NAS-archived Streamline PDF |
| Serendipity | **$306,170.38** | **$308,517.68** | NAS-archived Streamline PDF |

**Serendipity delta explained:** The live API balance ($308,517.68) was the March 31 *closing* balance, not the March 1 opening. The DB cache ($306,170.38) was synced after March began but before March reservations posted, making it the accurate March 1 opening. CROG-computed March net = $2,347.30 → closing = $306,170.38 + $2,347.30 = **$308,517.68** ✓

---

## 4. New Type Code (type_id 40)

**Source:** Serendipity March 2026 reservations 53870, 54020 (HAFamOLB per Streamline PDF).

| type_id | Display code | Added |
|---|---|---|
| `40` | **HAFamOLB** | H.2, 2026-04-16 |

**Files changed:**
- `backend/services/statement_computation.py` — `_SL_TYPE_CODES`: added `"40": "HAFamOLB"`
- `OPERATIONAL_TRUTH.md` — type codes table + Serendipity observations

pdftotext smoke: `HAFamOLB` appears on 53870 and 54020 in Serendipity PDF ✓

---

## 5. OPA Architecture Discovery

**One-OPA-per-property model confirmed.** `owner_payout_accounts.property_id` is a unique VARCHAR column — each property requires its own OPA row.

**Stripe unique constraint:** `uq_owner_payout_accounts_stripe_account_id` prevents multiple OPA rows sharing the same Stripe account. Gary has one Stripe Connect account (`acct_1TMYCpK5ULr6Eoss`) on OPA 1824. New OPAs created with `stripe_account_id = NULL`.

**Implication for statement generation:** `generate_monthly_statements` filters `WHERE stripe_account_id IS NOT NULL`. New OPAs bypass this via:
- `h2_generate_obps.py`: queries by `streamline_owner_id = 146514`
- `compute_owner_statement` + `render_owner_statement_pdf`: new `require_stripe_enrollment` kwarg (default `True`; backfill uses `False`)

---

## 6. Code Changes

### `backend/services/statement_computation.py`
1. `_SL_TYPE_CODES`: added `"40": "HAFamOLB"` (H.2 type code)
2. `compute_owner_statement`: added `require_stripe_enrollment: bool = True` keyword argument. When `False`, skips the `stripe_account_id IS NULL` check. Default remains `True` — existing callers (API endpoints, `generate_monthly_statements`) are unaffected.

### `backend/services/statement_pdf.py`
1. `render_owner_statement_pdf`: passes `require_stripe_enrollment=False` to `compute_owner_statement` — allows rendering PDFs for multi-property owners with secondary OPAs that have `stripe_account_id = NULL`.

### `OPERATIONAL_TRUTH.md`
1. Type codes table: added type_id 40 row
2. Added Serendipity observation block (H.2, 2026-04-16)
3. Verification grep updated to include `HAFamOLB`

---

## 7. New OPAs Created

Script: `backend/scripts/h2_opa_insert.sql` (COMMITTED)

| OPA id | Property | UUID | stripe_account_id | commission |
|---|---|---|---|---|
| 1826 | Cherokee Sunrise on Noontootla Creek | 50a9066d-fc2e-44c4-a716-25adb8fbad3e | NULL | 35% |
| 1827 | Serendipity on Noontootla Creek | 63bf8847-9990-4a36-9943-b6c160ce1ec4 | NULL | 35% |

Both: owner=Gary Knight / Mitchell, email=gary@cabin-rentals-of-georgia.com, sl_owner=146514, PO Box 982 Morganton GA 30560.

---

## 8. OBP Generation

Script: `backend/scripts/h2_generate_obps.py`

| OBP id | OPA | Property | Revenue | Commission | Net |
|---|---|---|---|---|---|
| 25680 | 1824 | Fallen Timber Lodge | $6,209.00 | $2,173.15 | $4,035.85 |
| 25681 | 1826 | Cherokee Sunrise | $0.00 | $0.00 | $0.00 |
| 25682 | 1827 | Serendipity | $3,611.22 | $1,263.92 | $2,347.30 |

Fallen Timber OBP 25680: opening_balance=500702.41 **preserved** (get_or_create returned existing row unchanged).

---

## 9. Opening Balance Backfill

Scripts: `h2_opening_balance_dryrun.sql` → verified → `h2_opening_balance_commit.sql`

### Dry-run output (complete)

```
PRE-UPDATE STATE:
  25681 | Cherokee Sunrise | opening=0.00     | closing=0.00     | rev=0      | comm=0
  25680 | Fallen Timber    | opening=500702.41| closing=504738.26| rev=6209   | comm=2173.15  ← UNTOUCHED
  25682 | Serendipity      | opening=0.00     | closing=2347.30  | rev=3611.22| comm=1263.92

POST-UPDATE STATE:
  25681 | Cherokee Sunrise | opening=64822.71  | closing=64822.71  ✓
  25680 | Fallen Timber    | opening=500702.41 | closing=504738.26 ✓ (UNCHANGED)
  25682 | Serendipity      | opening=306170.38 | closing=308517.68 ✓

LEDGER CHECKS: all within_one_cent = t
SERENDIPITY PARITY: delta vs Streamline = $0.00
FALLEN TIMBER SENTINEL: opening_correct=t, closing_correct=t

ROLLBACK
```

Commit: same output, ended with `COMMIT` + `LEDGER CHECK: all OBPs satisfy closing_balance equation — OK`.

---

## 10. PDF Smoke Tests

| PDF | Key values | Type codes | Result |
|---|---|---|---|
| h2_fallen_timber_march2026.pdf (5.1 KB) | Balance 03/01: $500,702.41 / 03/31: $504,738.26 | POS, POS, STA | PASS |
| h2_cherokee_march2026.pdf (4.0 KB) | Balance 03/01: $64,822.71 / 03/31: $64,822.71 | (no reservations) | PASS |
| h2_serendipity_march2026.pdf (5.1 KB) | Balance 03/01: $306,170.38 / 03/31: $308,517.68 | HAFamOLB, STA, HAFamOLB | PASS |

All 3 PDFs: owner = "Knight Mitchell Gary" ✓, property group + name ✓, Year 2026 Period 3 ✓.

---

## 11. Backup

```
File: /home/admin/fortress-snapshot-h2-20260416_073335.sql
Size: 35 MB
Exit: 0 (clean)
```

---

## 12. Confidence Rating

| Item | Confidence |
|---|---|
| Cherokee opening $64,822.71 | **CERTAIN** — API=DB=same value; Streamline PDF confirms |
| Serendipity opening $306,170.38 | **CERTAIN** — Gary confirmed from NAS-archived Streamline PDF |
| Serendipity closing $308,517.68 | **CERTAIN** — CROG net=$2,347.30; opening+net=closing; delta vs Streamline=$0.00 |
| HAFamOLB = type_id 40 | **CERTAIN** — observed in Serendipity March data; Streamline PDF confirms |
| Fallen Timber OBP 25680 untouched | **CERTAIN** — sentinel checks pass; opening/closing unchanged |
| Ledger CHECK constraint passes | **CERTAIN** — all 3 OBPs pass within_one_cent |
| PDF renders type_id 40 as "HAFamOLB" | **CERTAIN** — pdftotext shows HAFamOLB on 53870 and 54020 |

---

## 13. Notes for Future Phases

### 4th Gary property: Restoration Luxury (sl_property 1012373)
Discovered via owner-only GetMonthEndStatement call. Has a February 2026 Streamline statement. `owner_balance=$0` in DB. No OPA. Not in scope for H.2.

### NAS-archived Streamline statements
All 3 active Gary properties have March 2026 statements on NAS (cpanel). Future parity phases should reference NAS PDFs rather than calling the Streamline API for historical data. A future phase (H.3 or later) could ingest/index these for automated parity comparison.

### Stripe multi-property architecture
Current: one Stripe Connect account per OPA row (unique constraint). Gary's secondary OPAs (Cherokee, Serendipity) have `stripe_account_id=NULL`. For actual Stripe payouts from these properties, a future migration options:
- (a) Relax unique constraint to allow shared Stripe accounts across OPAs for same owner
- (b) Issue per-property Stripe Express accounts
- (c) Route all payouts through OPA 1824's account with internal split tracking

### Cherokee March 2026: no reservations
Cherokee had no March 2026 reservations in fortress_shadow. The statement renders correctly with $0 revenue and opening=closing=$64,822.71. When Cherokee reservations are backfilled (future phase), the statement will need to be regenerated.

---

## 14. Recommended Next Phase

**H.3 — Parity audit: compare CROG Serendipity and Cherokee PDFs against NAS-archived Streamline PDFs.**

The Serendipity March 2026 statement is ready for line-by-line comparison against the Streamline original. Key items to verify:
- Reservation rows: amounts, type codes (HAFamOLB/STA), gross rent, commission, net
- Account summary section balances
- Any owner charges or payments not yet in fortress_shadow

Or: **G.8 — Circuit breaker root cause** (why 53790/53952 had `_circuit_open: true` in G.5.1, and whether the Serendipity/Cherokee fetches might trip it).

Or: **Restoration Luxury OPA enrollment** — Gary's 4th property has a Streamline statement but no CROG statement infrastructure.
