# Owner Booking Audit
**Date:** 2026-04-14  
**Method:** Read-only. No code was modified. Findings are from reading source
files, running SELECT queries against the live `fortress_shadow` database, and
calling the Streamline API against the confirmed reservation numbers.

---

## Question 1 — What Does Streamline Return for an Owner Booking?

**API method used:** `GetReservationInfo` with `confirmation_id=54049` (one of
the Eby reservations). The call includes all enrichment flags:
`return_flags=1`, `show_commission_information=1`, `show_owner_charges=1`,
`show_taxes_and_fees=1`, `show_payments_folio_history=1`.

**Yes — Streamline does expose owner-booking information.** It is explicit and
unambiguous. The full Streamline response for reservation 54049 is below (personal
address information redacted; all field names kept intact):

```json
{
  "reservation": {
    "id": 47118623,
    "confirmation_id": 54049,
    "madetype_id": 5,
    "maketype_name": "O",
    "maketype_description": "Owner Reservation",
    "type_name": "OWN",
    "status_code": 2,
    "status_id": 4,
    "owning_id": 443731,
    "first_name": "Dale & Denise",
    "last_name": "Eby",
    "email": "daledeby@netscape.net",
    "email1": "deniseanddale@yahoo.com",
    "price_nightly": 0,
    "price_total": 212,
    "price_paidsum": 212,
    "price_common": 212,
    "price_balance": 0,
    "unit_id": 419022,
    "unit_name": "Blue Ridge Lake Sanctuary",
    "hear_about_name": "Ring Central",
    "flags": {
      "flag": [
        { "id": 2,    "name": "R",         "description": "Repeat Reservation" },
        { "id": 2635, "name": "OWNER RES", "description": "Owner Reservation"  }
      ]
    },
    ...
  },
  "taxes_and_fees": {
    "tax_fee": [
      { "name": "Arrival/Departure Clean", "id": 39468, "value": 200, ... },
      { "name": "County Tax",              "id": 39470, "value": 12,  ... }
    ]
  },
  "commission_information": {
    "management_commission_percent": 35,
    "owner_commission_percent": 65,
    "owner_commission_disburse_date": []
  },
  "payments_folio_history": {
    "record": [
      {
        "type": "Charge Owner",
        "description": "Transaction by Eby Dale & Denise",
        "amount": "-$212.00",
        "payment_description": "Arrival/Departure Clean"
      }
    ]
  }
}
```

**Fields that unambiguously identify this as an owner booking:**

| Field | Value | Meaning |
|---|---|---|
| `maketype_name` | `"O"` | Single-letter code for Owner |
| `maketype_description` | `"Owner Reservation"` | Human-readable description |
| `type_name` | `"OWN"` | Three-letter reservation type code |
| `madetype_id` | `5` | Numeric ID for the Owner reservation type |
| `flags[].name` | `"OWNER RES"` | Explicit flag attached to the reservation |
| `payments_folio_history[].type` | `"Charge Owner"` | The $212 is a charge TO the owner, not revenue from a guest |

Note also: `commission_information.management_commission_percent` is `35` and
`owner_commission_percent` is `65` — but these are the **property's general
commission rates**, not a statement that commission applies to this booking.
The `payments_folio_history` tells the real story: the $212 is money charged
*to* the owner for cleaning, not money received from a guest booking.

The `taxes_and_fees` breakdown confirms the total: $200 cleaning + $12 county
tax on the cleaning = $212. This is exactly the cleaning fee.

**Streamline also exposes this information on `GetReservations` (the list
endpoint).** The `_map_reservation` function in the sync code shows that
`maketype_name` and `maketype_description` are returned in the full list
response under the key `maketype_name`. This means the owner-booking flag
is available at sync time, not just on individual reservation lookups.

---

## Question 2 — Does the Sync Code Read Those Fields?

The function `_map_reservation` in `backend/integrations/streamline_vrs.py`
defines the field mapping from the Streamline API response to Crog-VRS. Here
is the complete field mapping:

| Streamline field | → | Crog-VRS column / key | Stored? |
|---|---|---|---|
| `confirmation_id` | → | `streamline_reservation_id` | ✅ |
| `unit_id` | → | used to look up `property_id` | ✅ |
| `status_code` | → | `status` (via status_map) | ✅ |
| `startdate` | → | `check_in_date` | ✅ |
| `enddate` | → | `check_out_date` | ✅ |
| `occupants` | → | `num_adults` | ✅ |
| `occupants_small` | → | `num_children` | ✅ |
| `occupants + occupants_small` | → | `num_guests` | ✅ |
| `pets` | → | `num_pets` | ✅ |
| `price_total` | → | `total_amount` | ✅ |
| `price_paidsum` | → | `paid_amount` | ✅ |
| `price_balance` | → | `balance_due` | ✅ |
| `price_nightly` | → | `nightly_rate` | ✅ |
| `days_number` | → | `nights_count` | ✅ |
| `price_nightly/common/paidsum/etc.` | → | `price_breakdown` (JSONB) | ✅ |
| `kabacode` | → | `access_code` | ✅ |
| `client_comments` | → | `special_requests` | ✅ |
| `hear_about_name` OR `maketype_name` | → | `source` key (then → `booking_source`) | ✅ (but see below) |
| `first_name`, `last_name` | → | used to create/find guest record | ✅ |
| `email` | → | `guest_email` | ✅ |
| `phone`, `mobile_phone` | → | `guest_phone` | ✅ |
| **`maketype_name`** | → | **`booking_source` (as fallback when `hear_about_name` is present)** | ⚠️ |
| **`maketype_description`** | → | **DROPPED** | ❌ |
| **`type_name`**  | → | **DROPPED** | ❌ |
| **`madetype_id`** | → | **DROPPED** | ❌ |
| **`flags` (OWNER RES flag)** | → | **DROPPED** | ❌ |

**The owner-booking flag is being dropped.** The sync code does this:

```python
"source": r.get("hear_about_name") or r.get("maketype_name", ""),
```

This line uses `hear_about_name` as the primary source for `booking_source`,
and falls back to `maketype_name` only when `hear_about_name` is absent.
For the Eby reservations, `hear_about_name` is `"Ring Central"` — so
`maketype_name` ("O" / "Owner Reservation") is never stored. `booking_source`
ends up as `"Ring Central"`, which tells us nothing about owner vs guest.

The `flags` array (which contains the explicit `"OWNER RES"` flag), `type_name`
("OWN"), and `maketype_description` ("Owner Reservation") are all discarded at
the `_map_reservation` stage. There is no `is_owner_booking` column, no
`reservation_type` column, and the JSONB `price_breakdown` that gets stored
contains only price fields — none of the reservation-type metadata.

---

## Question 3 — Does the Database Currently Store the Flag Anywhere?

**Full reservations table schema (53 columns):**

| Column | Type | Owner-booking relevant? |
|---|---|---|
| `id` | uuid | |
| `confirmation_code` | varchar | |
| `guest_id` | uuid | |
| `property_id` | uuid | |
| `guest_email` | varchar | |
| `guest_name` | varchar | Guest name is blank for all 3 Eby rows |
| `guest_phone` | varchar | |
| `check_in_date` | date | |
| `check_out_date` | date | |
| `num_guests` | integer | |
| `num_adults` | integer | |
| `num_children` | integer | |
| `num_pets` | integer | |
| `special_requests` | text | |
| `status` | varchar | Confirmed/cancelled — doesn't distinguish owner |
| `access_code` | varchar | |
| `access_code_valid_from/until` | timestamptz | |
| **`booking_source`** | **varchar** | **Stores "Ring Central" — loses "O"/owner info** |
| `total_amount` | numeric | |
| `paid_amount` | numeric | |
| `balance_due` | numeric | |
| `nightly_rate` | numeric | 0.00 for all 3 Eby rows |
| `cleaning_fee` | numeric | NULL for all 3 Eby rows |
| `pet_fee` | numeric | NULL for all 3 Eby rows |
| `damage_waiver_fee` | numeric | NULL for all 3 Eby rows |
| `service_fee` | numeric | NULL for all 3 Eby rows |
| `tax_amount` | numeric | NULL for all 3 Eby rows |
| `nights_count` | integer | |
| `price_breakdown` | jsonb | Stores Streamline price fields — no type info |
| `currency` | varchar | |
| `digital_guide_sent` | boolean | |
| `pre_arrival_sent` | boolean | |
| `access_info_sent` | boolean | |
| `mid_stay_checkin_sent` | boolean | |
| `checkout_reminder_sent` | boolean | |
| `post_stay_followup_sent` | boolean | |
| `guest_rating` | integer | |
| `guest_feedback` | text | |
| `internal_notes` | text | |
| `streamline_notes` | jsonb | NULL for all 3 Eby rows |
| `streamline_financial_detail` | jsonb | NULL for all rows in DB |
| `qdrant_point_id` | uuid | |
| `security_deposit_required` | boolean | |
| `security_deposit_amount` | numeric | |
| `security_deposit_status` | varchar | |
| `security_deposit_stripe_pi` | varchar | |
| `security_deposit_updated_at` | timestamptz | |
| `streamline_reservation_id` | varchar | |
| `created_at` / `updated_at` | timestamptz | |
| `tax_breakdown` | jsonb | NULL for all 3 Eby rows |
| `security_deposit_payment_method_id` | varchar | |

**There is no `is_owner_booking` column, no `reservation_type` column, no
`guest_type` column, and no `owner_stay` column.** No separate `owner_bookings`
table exists — the database has `owner_magic_tokens`, `owner_payout_accounts`,
`owner_statement_sends`, and a few others, but nothing for owner-stay bookings.

The `booking_source` column is the closest thing — but for the Eby reservations
it contains `"Ring Central"` (the how-they-heard value) rather than any
owner-booking indicator.

---

## Question 4 — Complete Rows for the Three Eby Reservations

All three reservations share the same `guest_id` (`905b95be-c181-4eb2-a119-edf6db2f0af6`)
and the same `property_id` (`ba440208-cfcf-4b47-b687-0f07f0436c21` = Blue Ridge Lake Sanctuary,
Streamline unit 419022).

**Reservation 54049** (June 4–10, 2026, 6 nights):
```
confirmation_code:           54049
guest_name:                  (empty string)
guest_email:                 (empty string)
property:                    Blue Ridge Lake Sanctuary
check_in_date:               2026-06-04
check_out_date:              2026-06-10
num_guests:                  2, num_adults: 2, num_children: 0, num_pets: 0
status:                      confirmed
booking_source:              Ring Central
total_amount:                212.00
paid_amount:                 212.00
balance_due:                 0.00
nightly_rate:                0.00
nights_count:                6
cleaning_fee / pet_fee / damage_waiver_fee / service_fee / tax_amount: all NULL
price_breakdown:             {"tax_exempt":0, "days_number":6, "price_total":"212",
                              "price_common":"212", "price_paidsum":"212",
                              "price_nightly":null, "pricing_model":1, ...}
streamline_notes:            NULL
streamline_financial_detail: NULL
internal_notes:              NULL
streamline_reservation_id:   54049
created_at:                  2026-04-10T17:41:05
```

**Reservation 53887** (June 24 – July 19, 2026, 25 nights):
```
confirmation_code:           53887
guest_name:                  (empty string)
guest_email:                 (empty string)
property:                    Blue Ridge Lake Sanctuary
check_in_date:               2026-06-24
check_out_date:              2026-07-19
num_guests:                  2, num_adults: 2
status:                      confirmed
booking_source:              Ring Central
total_amount:                212.00
paid_amount:                 212.00
nights_count:                25
nightly_rate:                0.00
All fee columns:             NULL
price_breakdown:             same structure as above, price_total: "212"
streamline_reservation_id:   53887
created_at:                  2026-04-08T12:21:38
```

**Reservation 53868** (August 9–17, 2026, 8 nights):
```
confirmation_code:           53868
property:                    Blue Ridge Lake Sanctuary
check_in_date:               2026-08-09
check_out_date:              2026-08-17
num_guests:                  2, num_adults: 2
status:                      confirmed
booking_source:              Ring Central
total_amount:                212.00
paid_amount:                 212.00
nights_count:                8
nightly_rate:                0.00
All fee columns:             NULL
streamline_reservation_id:   53868
created_at:                  2026-04-05T13:54:09
```

**What Crog-VRS currently knows about these three reservations:**

- That they exist and are confirmed ✓
- Their dates and night counts ✓
- That they are for Blue Ridge Lake Sanctuary ✓
- That the total for each is $212.00 (the cleaning fee) ✓
- That they came through "Ring Central" ✓
- **That they are owner bookings: NO** ✗
- The guest name (Dale & Denise Eby): NOT STORED (empty string) ✗

The guest name being blank is a direct consequence of the sync treating this
like any other Streamline reservation — the name fields are populated by
`_map_reservation`, but since the resulting guest record has an empty name,
there is no human-readable indication in the local database of whose booking
this is, let alone that it's the property owner.

---

## Question 5 — Other Potential Owner Bookings

### Confirmed owner bookings (verified via Streamline API)

Sampling two additional Ring Central / zero-nightly-rate confirmed reservations
against the Streamline API confirmed they are also marked as owner bookings:

| Confirmation | Owner | Property | Dates | Amount |
|---|---|---|---|---|
| **54049** | Dale & Denise Eby | Blue Ridge Lake Sanctuary | Jun 4–10, 2026 | $212 |
| **53887** | Dale & Denise Eby | Blue Ridge Lake Sanctuary | Jun 24 – Jul 19, 2026 | $212 |
| **53868** | Dale & Denise Eby | Blue Ridge Lake Sanctuary | Aug 9–17, 2026 | $212 |
| **54048** | Mary Kay Buquoi | Chase Mountain Dreams | May 22–25, 2026 | $291.50 |
| **54047** | Thor James | Riverview Lodge | Jun 11–16, 2026 | $371 |

All five confirmed reservations have:
- `maketype_name = "O"` (Owner)
- `maketype_description = "Owner Reservation"`
- `type_name = "OWN"`
- `flags` containing `"OWNER RES"`
- No guest name or email stored locally
- `nightly_rate = 0`, total = cleaning fee only

### Other Ring Central / zero-nightly-rate reservations (not yet verified)

The database has 10 Ring Central reservations with `nightly_rate = 0`:

| Confirmation | Status | Property | Dates | Amount |
|---|---|---|---|---|
| 54048 | confirmed | Chase Mountain Dreams | May 22–25 | $291.50 |
| 54049 | confirmed | Blue Ridge Lake Sanctuary | Jun 4–10 | $212 |
| 54047 | confirmed | Riverview Lodge | Jun 11–16 | $371 |
| 53887 | confirmed | Blue Ridge Lake Sanctuary | Jun 24–Jul 19 | $212 |
| 53868 | confirmed | Blue Ridge Lake Sanctuary | Aug 9–17 | $212 |
| 54029 | cancelled | Cohutta Sunset | May 31–Dec 31 | $238.50 |
| 53482 | cancelled | The Rivers Edge | Jun 18–21 | $0 |
| 53483 | cancelled | Riverview Lodge | Jun 18–21 | $0 |
| 53876 | cancelled | Above the Timberline | Jun 19–22 | $0 |
| 53614 | cancelled | Cohutta Sunset | Oct 14–20 | $0 |

All 5 confirmed ones were verified as owner bookings via the Streamline API.
The 5 cancelled ones were not individually verified, but the pattern strongly
suggests they are also owner bookings (same `booking_source`, same zero
nightly rate, same structural pattern in Streamline's data).

### Gary Knight reservations

Three reservations exist under the name "Gary Knight" / "G KNight":

| Confirmation | Property | Dates | Amount | Status | Source |
|---|---|---|---|---|---|
| CRG-EUT97 | (not one of Gary's 4 properties) | Apr 7–9 | $2,580.72 | **cancelled** | storefront_checkout |
| CRG-ZC6Z4 | Fallen Timber Lodge | Apr 7–9 | $1.00 | **cancelled** | storefront_checkout |
| CRG-SNDNN | Cohutta Sunset | May 13–18 | $2,309.35 | confirmed | direct |

**Important:** CRG-SNDNN is a booking by the product owner (Gary Knight) for
**Cohutta Sunset**, which is NOT one of the 4 properties Gary owns (his
properties are Serendipity on Noontootla Creek, Fallen Timber Lodge, Cherokee
Sunrise on Noontootla Creek, and Restoration Luxury). This means CRG-SNDNN is
a **guest booking by the property manager at another owner's cabin**, not an
owner-stay booking. It has a full nightly rate ($323/night), real line-item
breakdown, and was placed through the storefront checkout path.

CRG-ZC6Z4 ($1.00 at Fallen Timber Lodge) and CRG-EUT97 ($2,580.72 at a
different property) are both cancelled storefront-checkout bookings — these
appear to be test bookings from the development process. Neither is an
owner-booking in the Streamline sense.

**None of Gary's 4 owned properties have any confirmed reservations with
the owner-booking pattern (zero nightly rate, Ring Central source) in the
current database.**

---

## Summary and Recommendation

### Does Streamline expose owner-booking information at all?

**Yes, clearly and unambiguously.** Streamline returns at least five separate
signals on every owner-booking reservation:

1. `maketype_name = "O"` (single-letter code)
2. `maketype_description = "Owner Reservation"` (human-readable)
3. `type_name = "OWN"` (three-letter code)
4. `madetype_id = 5` (numeric ID)
5. A flag named `"OWNER RES"` in the `flags` array

All of these are present in the `GetReservationInfo` response. The
`GetReservations` list endpoint also returns `maketype_name` (shown in the
`_map_reservation` comment: "maketype_name, hear_about_name").

### Is that information currently being lost at sync time?

**Yes, completely.** The sync code reads `maketype_name` but only uses it as
a fallback for `booking_source` when `hear_about_name` is absent. Since all
owner bookings have `hear_about_name = "Ring Central"`, the `maketype_name`
value of `"O"` (Owner) is never recorded. `maketype_description`, `type_name`,
`madetype_id`, and the entire `flags` array are discarded.

The result: all 5 confirmed owner bookings in the database look
indistinguishable from regular guest reservations, except that they have no
guest name, no nightly rate, and a suspiciously round total (the cleaning fee).

### Can Crog-VRS reliably identify owner bookings today?

**No.** There is no stored field that identifies an owner booking. The only
available heuristics are:

1. `booking_source = "Ring Central"` AND `nightly_rate = 0` — this catches
   all known owner bookings but may also catch non-owner Streamline bookings
   with unusual pricing.
2. `total_amount` equals a round cleaning-fee-like number — fragile and
   property-specific.
3. No guest name or email — consistent with owner bookings, but not definitive.

None of these are reliable enough to base automated statement logic on without
risk of false positives or false negatives.

**What needs to change:** The sync code needs to read and store at least one
of the owner-booking indicators. The cleanest option is:

- Add a boolean column `is_owner_booking` to the `reservations` table.
- In `_map_reservation`, set it to `True` when `maketype_name == "O"` or
  `type_name == "OWN"`.
- This requires a migration and a one-line change to `_map_reservation`.

Alternatively, storing `maketype_name` or `type_name` verbatim in
`price_breakdown` or `streamline_notes` would also work and requires no
migration — but would be harder to filter on.

### How many total reservations look like they might be owner bookings?

**5 confirmed** owner bookings with high confidence (all verified via
Streamline API: three Eby at Blue Ridge Lake Sanctuary, one Buquoi at Chase
Mountain Dreams, one Thor James at Riverview Lodge).

**5 cancelled** reservations with the same pattern (Ring Central,
nightly_rate = 0) that are very likely also owner bookings — not individually
verified against the API.

**Total: approximately 10 reservations**, all from the past few months of
sync data.

The pattern is distinctive enough that a retroactive backfill is possible
once the `is_owner_booking` column is added: any confirmed reservation with
`booking_source = 'Ring Central'` and `nightly_rate = 0` from the Streamline
sync can be investigated case by case.
