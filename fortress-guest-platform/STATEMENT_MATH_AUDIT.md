# Statement Math Audit
**Date:** 2026-04-14  
**Method:** Read-only. No code was modified. All findings are from reading source
files and running SELECT queries against the live `fortress_shadow` database.

---

## Question 1 — Cancellation Filter

### Which table and what WHERE clauses?

Reservations are pulled from the single `reservations` table. In
`backend/services/statement_computation.py`, the exact query is:

```python
select(Reservation)
.where(and_(
    Reservation.property_id == property_uuid,
    Reservation.check_in_date >= period_start,
    Reservation.check_in_date <= period_end,
    Reservation.status.in_(["confirmed", "checked_in", "checked_out", "completed"]),
))
```

There is an explicit status filter. Only reservations with status `confirmed`,
`checked_in`, `checked_out`, or `completed` are included. Everything else is
excluded.

### What status values actually exist in the database?

Running `SELECT status, COUNT(*) FROM reservations WHERE check_in_date >= NOW() - INTERVAL '12 months' GROUP BY status`:

| Status | Count | Total Amount |
|---|---|---|
| `confirmed` | 40 | $107,127.67 |
| `cancelled` | 17 | $25,345.82 |

Only two statuses exist. No `checked_in`, `checked_out`, or `completed`
reservations have been recorded in the past 12 months. Every non-cancelled
booking is simply `confirmed`.

Cancelled reservations have real money attached to them — amounts range from
$0.00 to $5,005.65, totalling $25,345.82 across 17 cancellations.

### Is the cancellation filter correct?

**Yes.** Cancelled reservations are excluded. The filter is working as intended.

### Trace: $2,500 confirmed + $3,000 cancelled in the same month

`compute_owner_statement` runs the query above. It finds the $2,500 confirmed
reservation (status=`confirmed`, included) and skips the $3,000 cancelled
reservation (status=`cancelled`, excluded). The function processes only the
confirmed reservation and returns a statement based on $2,500 gross. The $3,000
never appears anywhere in the output.

---

## Question 2 — Commission Base (Rent vs Total)

### How items are built from a reservation

The function `_bucketed_items_from_reservation` (in
`backend/services/statement_computation.py`) converts a database reservation
row into a list of line items. Here is exactly what it does:

```
nightly_rate = res.nightly_rate (or 0 if NULL)
nights       = res.nights_count  (or calculated from check_out - check_in)

IF nightly_rate > 0:
    rent = nightly_rate × nights        ← Base Rent item (commissionable)
ELSE:
    rent = res.total_amount             ← FALLBACK: entire total becomes rent (see below)

Then adds separate items for:
    cleaning_fee       → Cleaning Fee item
    pet_fee            → Pet Fee item
    damage_waiver_fee  → Accidental Damage Waiver item
    service_fee        → Processing Fee item
    tax_amount         → Taxes item
```

Each item is then passed to `_is_pass_through()` which decides whether it
enters the commission base or is excluded.

### What columns exist on the reservations table?

The Reservation model has these financial columns:

| Column | Type | Present in real data? |
|---|---|---|
| `nightly_rate` | DECIMAL(10,2) | Yes (35 of 40 confirmed reservations) |
| `nights_count` | Integer | Sometimes NULL (code falls back to date diff) |
| `total_amount` | DECIMAL(10,2) | Yes — includes everything |
| `cleaning_fee` | DECIMAL(10,2) | Sometimes populated |
| `pet_fee` | DECIMAL(10,2) | Exists, usually $0.00 |
| `damage_waiver_fee` | DECIMAL(10,2) | Always NULL in current data |
| `service_fee` | DECIMAL(10,2) | Sometimes populated (see note below) |
| `tax_amount` | DECIMAL(10,2) | Sometimes populated |
| `security_deposit_amount` | Numeric(12,2) | Exists, separate from `total_amount` |
| `price_breakdown` | JSONB | Rich line_items for local-ledger bookings |
| `tax_breakdown` | JSONB | Present for some bookings |
| `streamline_financial_detail` | JSONB | **Empty for all rows** (see Question 4) |

**Important note about `service_fee`:** This column is a lump sum combining
multiple fees. For the booking CRG-SNDNN, the `price_breakdown.line_items`
shows three separate items that all got combined into `service_fee`:
- Accidental Damage Waiver: $65.00
- DOT Tax: $25.00
- Processing Fee: $111.90
- **Total stored in `service_fee` column: $201.90**

The code treats `service_fee` as one "Processing Fee" item with `bucket=ADMIN`,
which correctly makes it pass-through regardless of what it actually contains.

### Which items enter the commission base?

The function `_is_pass_through()` (in `backend/services/ledger.py`) decides
this. Here is what it does for each item type:

| Item | Item type | Bucket | Pass-through? | Why |
|---|---|---|---|---|
| Base Rent | `rent` | LODGING | **No → commissionable** | Not in any pass-through set |
| Cleaning Fee | `fee` | LODGING | **Yes → pass-through** | Name contains "clean" (special override) |
| Pet Fee | `fee` | LODGING | **No → commissionable** | Not in any pass-through set |
| ADW | `fee` | ADMIN | **Yes → pass-through** | ADMIN bucket is pass-through |
| Processing Fee | `fee` | ADMIN | **Yes → pass-through** | ADMIN bucket is pass-through |
| Taxes | `tax` | LODGING | **Yes → pass-through** | "tax" type is pass-through |

**Pet fees are currently treated as commissionable.** The product owner says
commission applies to rent only. This is a bug.

### Real data sample: reservation CRG-SNDNN

Confirmed booking for Cohutta Sunset, check-in May 13 2026 (5 nights).

| Field | Value |
|---|---|
| nightly_rate | $323.00 |
| nights | 5 (calculated from dates) |
| rent computed | $1,615.00 |
| cleaning_fee | $250.00 |
| pet_fee | $0.00 |
| damage_waiver_fee | NULL ($0) |
| service_fee | $201.90 (ADW + DOT + Processing combined) |
| tax_amount | $242.45 |
| **total_amount** | **$2,309.35** |

### What `calculate_owner_payout` would return at 30% commission

Following the code exactly:

```
gross_revenue       = $1,615.00  (rent only — commissionable)
pass_through_total  = $694.35    (cleaning $250 + service $201.90 + tax $242.45)
commission (30%)    = $1,615.00 × 30% = $484.50
total_collected     = $2,309.35  (all money)
cc_processing_fee   = $2,309.35 × 2.9% + $0.30 = $67.27
net_owner_payout    = $1,615.00 - $484.50 - $67.27 = $1,063.23
```

**The product owner's stated expectation: rent only at 30% = $1,615 × 70% = $1,130.50.**

The gap between $1,063.23 (what the code returns today) and $1,130.50 (the stated
intention) is $67.27 — exactly the CC processing fee deduction. The code applies an
additional deduction of 2.9% of the total collected amount plus $0.30 flat. This CC
processing fee deduction is applied to the owner's net. Whether this is intended
behavior needs to be confirmed separately.

### The lump-sum problem: 5 reservations with no nightly rate

Five confirmed reservations in the past 12 months have `nightly_rate = 0`. These
are all Streamline-synced bookings where Streamline returned only `price_common`
(a total) with no `price_nightly`. For these, the code does:

```python
rent = res.total_amount  # fallback: entire total becomes "Base Rent"
```

This means the entire reservation total — which likely includes cleaning fees and
taxes we cannot separate — is classified as commissionable rent.

The five reservations:

| Confirmation | total_amount | nights | Streamline price_nightly |
|---|---|---|---|
| 54048 | $291.50 | 3 | NULL |
| 54049 | $212.00 | 6 | NULL |
| 54047 | $371.00 | 5 | NULL |
| 53887 | $212.00 | 25 | NULL |
| 53868 | $212.00 | 8 | NULL |

None of these have `price_breakdown.line_items` — there is no record of what
portion is rent vs cleaning vs tax. For these 5 reservations, the commission base
is wrong (over-counted) and the data needed to fix it is not currently stored.

---

## Question 3 — Pass-Through Accounting

### Is the concept implemented?

**Yes — the pass-through framework is fully implemented and wired up.**

In `backend/services/ledger.py`, the classification system is:

```python
# Items in these buckets are pass-through
PASS_THROUGH_BUCKETS = frozenset({TaxBucket.ADMIN, TaxBucket.EXEMPT})
PASS_THROUGH_TYPES   = frozenset({"tax", "deposit"})
```

The `_is_pass_through()` function runs four checks in order:
1. Is the item type "tax" or "deposit"? → pass-through
2. Is the bucket ADMIN or EXEMPT? → pass-through
3. Does `classify_item()` return ADMIN or EXEMPT? → pass-through
4. Does the name contain "clean"? → pass-through

This is called from `calculate_owner_payout()` for every line item before it
decides whether to add it to `gross_revenue` (commissionable) or
`pass_through_total`.

The `classify_item()` function uses a regex priority system:

| Pattern | Bucket | Pass-through? |
|---|---|---|
| deposit, refund | EXEMPT | Yes |
| waiver, damage, adw, processing, admin | EXEMPT | Yes |
| check-in/out, early arrival, late departure | EXEMPT | Yes |
| firewood | GOODS | No (commissionable) |
| fish guide, concierge | SERVICE | No (commissionable) |
| clean, pet, extra guest | LODGING | No for "pet" (bug); "clean" caught by name check |

### What about the $0.00 on the Hermes parity dashboard?

The Hermes parity dashboard shows "commissionable" and "pass-through" buckets that
display $0.00. This is **not a hardcoded placeholder and not unimplemented**. The
code in `backend/api/telemetry.py` reads from the `ParityAudit` table and sums up
items from `local_breakdown` — classifying `type=rent` as commissionable and
everything else as pass-through.

The $0.00 values appear because no `ParityAudit` records with populated
`local_breakdown.items` exist in the database yet. The pipeline is wired; there
is simply no data flowing through it.

---

## Question 4 — What the Streamline Integration Already Knows

### What does Streamline return when syncing reservations?

The basic `GetReservations` call returns these financial fields per reservation:
- `price_total` — the total reservation amount (stored in `total_amount`)
- `price_nightly` — nightly rate (stored in `nightly_rate`)
- `price_common` — a "common" price (same as total for most Streamline bookings)
- `price_paidsum` — amount paid
- `price_balance` — balance due

**No separate cleaning fee, tax, or deposit fields.** Streamline's basic
reservation sync does not break down the total into components.

### What is stored in `streamline_financial_detail`?

Nothing. The `streamline_financial_detail` column (which was meant to store
results from Streamline's separate `GetReservationPrice` endpoint) is **empty
for every row** in the database. That endpoint was never called and the results
were never stored.

The comment in the model says: `# Full price/payment detail from GetReservationPrice`.
The field exists but has never been populated.

### What does `price_breakdown` actually contain?

Two different shapes appear depending on where the booking originated:

**Shape 1 — Local-ledger / Storefront bookings** (e.g., CRG-SNDNN, CRG-JLJ44):
These have rich `line_items` arrays:

```json
{
  "rent": "1615.00",
  "cleaning": "250.00",
  "taxes": "242.45",
  "total": "2309.35",
  "line_items": [
    {"type": "rent",   "amount": "1615.00", "description": "5 night stay @ $323.00 / night"},
    {"type": "fee",    "amount": "65.00",   "description": "Accidental Damage Waiver"},
    {"type": "fee",    "amount": "250.00",  "description": "Cleaning Fee - cohutta-sunset"},
    {"type": "fee",    "amount": "25.00",   "description": "DOT Tax"},
    {"type": "fee",    "amount": "111.90",  "description": "Processing Fee"},
    {"type": "tax",    "amount": "111.90",  "description": "County Tax"},
    {"type": "tax",    "amount": "130.55",  "description": "State Tax"}
  ]
}
```

For these bookings, the rent amount is explicitly known and stored.

**Shape 2 — Streamline-synced bookings** (e.g., 53944, 54048):
Only the Streamline price fields, no line_items:

```json
{
  "tax_exempt": 0,
  "days_number": 2,
  "price_total": "1348.75",
  "price_common": "1348.75",
  "price_nightly": "900",
  "price_paidsum": "674.38",
  "price_balance": "674.37"
}
```

For `nightly_rate > 0` Streamline bookings, the rent can be computed as
`price_nightly × days`. For `nightly_rate = 0` Streamline bookings, there is
no breakdown available at all.

---

## What This Means

### Is the commission base currently correct (rent only)?

**Mostly, but with two problems:**

**Problem 1 — Pet fees are commissionable (wrong).**
The `pet_fee` column is a separate column on the reservation and the data is
there to fix this. The only change needed is to classify pet fees as pass-through
instead of commissionable. In the current dataset, pet_fee = $0.00 on all
confirmed reservations, so this bug has had no financial impact yet. It will
matter once a pet-fee reservation is processed.

**Problem 2 — 5 reservations have no nightly rate (lump sum fallback).**
For 5 of the 40 confirmed reservations in the last 12 months, `nightly_rate = 0`
and the code uses `total_amount` as the commission base. This overstates the
commission base because it includes cleaning fees and taxes that Streamline
bundled together with rent and sent as a single number. The data to fix this
does not exist in the database — `streamline_financial_detail` was never
populated and `price_breakdown.line_items` is absent for these bookings.
Fixing it would require either calling Streamline's `GetReservationPrice`
endpoint retroactively or accepting that these 5 reservations will have an
approximate commission base. The 5 reservations total $1,298.50 in amounts;
at 30% commission the overstatement is at most a few hundred dollars depending
on how much of each total is actually rent vs fees.

### Is the cancellation filter currently correct?

**Yes.** The filter is explicitly coded and working.

### CC processing fee deduction — needs separate confirmation

The `calculate_owner_payout` function applies a CC processing fee deduction
of 2.9% of total collected + $0.30 from the owner's net payout. This is a
separate deduction on top of the commission. The product owner did not mention
this in the business rules description. Confirmation is needed on whether the
owner's net should be:

- Option A: `rent × (1 - commission_rate)` — pure rent minus commission
- Option B: `rent × (1 - commission_rate) - cc_processing_fee` — also deducting a
  credit card processing charge

For the CRG-SNDNN reservation at 30% commission, these produce:
- Option A: $1,130.50
- Option B: $1,063.23 (current code behavior — $67.27 less)

### What data is available to fix these issues?

| Issue | Fix needed | Data available? |
|---|---|---|
| Pet fees commissionable | Classify `pet_fee` as pass-through | Yes — separate column exists |
| Lump-sum nightly rate=0 | Know actual rent portion | **No** — not stored for these 5 bookings |
| CC processing fee policy | Confirm whether deduction is intended | Needs product owner decision |
| `service_fee` is a combined lump | Already pass-through (ADMIN bucket), so OK as-is | N/A |

### Summary judgment

The commission math is **structurally correct** for the majority of reservations
(rent is separated from cleaning, taxes, and fees via the pass-through framework).
Two concrete bugs exist:

1. **Pet fees** — small, fixable in one line of code, no financial impact in current
   data but will be wrong once a pet reservation is processed.
2. **Lump-sum Streamline reservations** — 5 reservations where the entire total is
   treated as rent. The data needed to fix this retroactively does not exist.

The cancellation filter is correct and working.
