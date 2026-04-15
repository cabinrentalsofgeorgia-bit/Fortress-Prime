# Fortress Prime — Known Issues and Deferred Work
Last updated: 2026-04-14

This file records items that were deliberately deferred, known issues with
low urgency, and decisions that need to be traceable. If you find a bug while
working on a feature, add it here rather than fixing it out of scope.

---

## Owner Statement Cron (Phase F)

### DO NOT set CROG_STATEMENTS_PARALLEL_MODE=false until Phase G completes
The owner statement send cron job (15th of month, 09:30 ET) is gated by
`CROG_STATEMENTS_PARALLEL_MODE`. Default is `true` which suppresses all real
email sends. The generation job (12th of month, 06:00 ET) runs unconditionally
and creates drafts for the previous month. Set the flag to `false` only after
Phase G validation has completed and the product owner has explicitly approved
the production cutover. Document the date of the decision here.

### OWNER_STATEMENT_ALERT_EMAIL must be set before the next 12th
The cron jobs send a run-summary email to `OWNER_STATEMENT_ALERT_EMAIL` after
every fire. If the env var is unset, the job logs a loud error but continues.
Set it in production `.env` and restart `fortress-arq-worker.service` before
the 15th of any month to receive monitoring emails. Priority: HIGH.

---

## Phase G Prerequisites (from Phase E.5)

### Property group backfill may become stale before Phase G
`properties.property_group` was populated for all 14 active properties from
Streamline's `GetPropertyList` (`location_area_name`) on 2026-04-14. Phase G
reconciliation will compare Crog-VRS statement totals against Streamline PDFs.
If Streamline reclassifies a property into a different location area, the backfill
becomes stale and statements will show the wrong group prefix.
Before beginning Phase G, re-run `backfill_property_groups_from_streamline()` from
`backend/services/statement_backfill.py` to confirm the data is current.
Priority: LOW (property groups change rarely).

### Real enrolled OPAs are required before Phase G can run meaningful reconciliation
Phase G compares Crog-VRS statement totals against Streamline's GetMonthEndStatement
API by matching on `owner_payout_accounts.streamline_owner_id`. As of 2026-04-14,
all 870 OPA rows in the DB are test rows — none have a real `streamline_owner_id`.
Phase G reconciliation cannot produce useful output until at least one real owner
invitation has been sent and accepted via the production invite flow. The invite form
now captures the Streamline owner ID (`streamline_owner_id` field in
`OwnerInviteRequest`). Ensure this is populated for every real invite.
Priority: HIGH — blocks Phase G entirely.

### 870 test rows in owner_payout_accounts must be cleaned before Phase G validation
The test suite creates an OPA row per test via `ON CONFLICT (property_id) DO UPDATE`
using unique fake property IDs. These accumulate indefinitely because `fortress_api`
lacks DELETE permission on `owner_payout_accounts`. Before Phase G validation begins,
the database must either be reset (fresh test run) or the test rows must be removed
via a superuser DELETE. Only rows with real `streamline_owner_id` values (the actual
CROG property owners) should remain.
Priority: HIGH — Phase G prerequisite (see item above).

### owner_payout_accounts address NOT NULL constraint deferred (Phase G prerequisite)
Phase E.5 added six mailing address columns as nullable. A follow-up migration to
tighten `mailing_address_line1`, `city`, `state`, and `postal_code` to NOT NULL was
deferred because all 870 current rows are test rows with NULL addresses. The
application layer enforces the requirement at invite-creation time (Pydantic
validation), but the database itself does not. Before Phase G validation, clean the
test rows (see previous item) then apply the NOT NULL tighten migration.
Priority: HIGH — Phase G prerequisite.

---

## Architecture

### Three scheduling systems on the same machine
spark-node-2 has ~25 system cron jobs (in the `admin` user's crontab), ARQ
cron_jobs (newly introduced in Phase F of the owner statement build), and a
hand-rolled `asyncio.sleep` loop in the existing payout sweep. Future work:
consolidate to one scheduler. Owner: not assigned. Priority: LOW.

### owner_magic_tokens dual purpose
This table holds both invite tokens (72h lifetime, from `create_invite()`) and
magic-link login tokens (24h lifetime, from `auth.py`). There is no column to
distinguish them. The `create_invite()` function wipes all unused tokens for an
email on invite creation, which can cancel an active login token. Low impact
today (rare overlap), but should be fixed by adding a `token_type` column.
Priority: MEDIUM.

---

## Owner Statements

### Monthly statement cron not yet wired (Phase F)
`send_all_monthly_statements` was deleted in Phase 1.5 (hardcoded 65% rate).
The replacement cron job (ARQ, fires 12th at 06:00 ET to generate drafts, 15th
at 09:30 ET to send approved statements) will be added in Phase F. The trigger
endpoint `POST /api/admin/payouts/statements/send-all` returns HTTP 501 until
Phase F is complete.

### Streamline GetMonthEndStatement returns no financial data in JSON
GetMonthEndStatement's JSON response contains only statement metadata (ID, location
name, period, count). Financial figures are in the PDF attachment only. The
`fetch_streamline_statement_normalized()` function in
`backend/services/statement_comparison.py` currently returns None for all calls.
Pending product owner decision on how to extract financial data:
  Option A: Parse the base64 PDF (complex, brittle)
  Option B: Sum GetReservations data as a proxy
  Option C: Accept 'streamline_unavailable' for all runs (current)

### Owner Charges admin UI form not yet built
The backend endpoints for owner charges exist at `POST/GET/PATCH /api/admin/payouts/charges`.
The frontend admin form (transaction type dropdown, description, posting date, amount,
optional reference, owner/property selector) does NOT exist yet. It should mirror
Streamline's owner charge form. Until it is built, staff must use curl or Postman.
Owner: not assigned. Priority: HIGH — needed before real charges can be entered
through the UI.

### Owner charge transaction types are a starter set
The `owner_charge_type_enum` contains 17 values from Streamline's full list.
Deliberately excluded: Hacienda Tax (unused by CROG), Statement Marker, Room Revenue,
and Charge Expired Owner (serve different purposes in Streamline). Add new types only
when the product owner identifies a real workflow that needs them. Adding a type
requires a new Alembic migration to extend the enum.

### Owner Reserve sub-account not yet implemented
The owner statement PDF format (Phase E) includes an "Owner Reserve" section showing
a balance. This feature is not yet implemented — it will display as zero until built.

### admin_statements.py commission_rate_override is a what-if tool
The `commission_rate_override` query parameter on `GET /api/v1/statements/{owner_id}`
is for staff what-if modelling only. It does NOT change any stored rate. The
authoritative rate always comes from `owner_payout_accounts.commission_rate`.
Responses using this override are tagged `source='crog_what_if'`.

### synthetic_gauntlet.py uses GAUNTLET_COMMISSION_RATE = 25%
This test file uses a 25% rate for math stress-testing purposes only. It does NOT
exercise the real business rates (30% and 35%). Future enhancement: add gauntlet
scenarios at 30% and 35% to mirror the actual owner distribution.

---

## Commission Rates

### Admin UI invite form missing commission_rate_percent and streamline_owner_id fields
The backend invite creation endpoint (`POST /api/admin/payouts/invites`) requires
`commission_rate_percent` (0–50) and optionally accepts `streamline_owner_id`. The
admin frontend form does NOT yet send these fields. Real owner invitations cannot be
sent through the UI until this is fixed. These fields were added in Phase 1.5
(2026-04-14). Priority: HIGH.

---

## Owner Bookings

### Reservation 54029 (Rooke / Cohutta Sunset) — calendar block, unusual maketype_name
Reservation 54029 has `maketype_name='A'` (not 'O') but `type_name='OWN'` and
flags=['OWNER RES']. It is a **calendar placeholder block** — not an actual owner
stay — created to prevent guest bookings on Cohutta Sunset between now and Pat
Rooke's program departure at end of May 2026. Pat is not staying at the cabin for
seven months; the reservation exists purely to block the calendar.

`is_owner_booking` was set to True (Phase B.5, 2026-04-14), which produces the
correct practical effect: no revenue, no commission, no statement line item. The
`detect_owner_booking()` helper catches it via `type_name='OWN'`. The 'A'
maketype_name code meaning in Streamline is unknown (possibly "Annual block").

### $238.50 on reservation 54029 — auto-generated cleaning fee, no action needed
The $238.50 is an auto-generated cleaning fee that Streamline attaches to every
owner reservation at creation time. It is **not** a real expense Pat Rooke owes.
When the placeholder reservation is cancelled at Pat's program departure date (end
of May 2026), Streamline will automatically reverse the cleaning fee. No Crog-VRS
`owner_charges` entry should be created for this amount.

---

## Reservation Modeling

### Placeholder / calendar-block reservations are modeled as owner bookings
Crog-VRS does not currently have a `reservation_purpose` field. Reservation 54029
(Rooke / Cohutta Sunset) is a calendar block, not an owner stay — but both map to
`is_owner_booking = true` because both produce the same practical effect: excluded
from statement revenue, commission, and line items.

A future enhancement could add a `reservation_purpose` enum to the `reservations`
table with values such as `guest_stay`, `owner_stay`, `placeholder_block` to model
this distinction more precisely. This is LOW priority: there is currently only one
example of a placeholder block in the production data, and `is_owner_booking = true`
handles it correctly for statement purposes. A migration and corresponding
`detect_owner_booking()` logic update would be needed.

---

## Stripe Connect

### Stripe Connect Express accounts are dormant infrastructure
Built in April 2026. Owner Stripe accounts exist and are stored in
`owner_payout_accounts.stripe_account_id`, but no money flows through them.
Owner payouts continue via QuickBooks ACH. The Connect infrastructure activates
when CROG cuts the cord from Streamline as merchant of record.

### Old admin POST /api/admin/payouts/invites/accept endpoint
This endpoint is still in the codebase. It requires manager/admin auth — owners
clicking email links cannot use it. The public owner invite endpoint is
`POST /api/owner/invite/accept`. The admin version was kept for staff testing only.
Its docstring was stale (said "called from the owner portal frontend") — this is
no longer true. Decision recorded here for traceability (2026-04-14).

---

## Data Quality

### Skyfall property has 0 confirmed reservations in 12 months
Skyfall is marked `renting_state='active'` and `is_active=true` but has no
confirmed reservations in the past 12 months. This may be a genuinely idle
property or may need investigation. Consider whether it should be `paused`.
Owner: not assigned.

---

## Properties

### Statement workflow admin UI not yet built (Phase D)
The statement lifecycle endpoints exist at `/api/admin/payouts/statements/*`.
The admin UI (statement list, approve button, mark-paid form, void form) does NOT
exist yet and is a follow-up task. Until it is built, the workflow is driven via
curl, Postman, or admin scripts. Priority: HIGH — required for the first real
statement run.

### Auto-generated charges from Streamline not yet modeled
Streamline may attach auto-generated charges to owner reservations (e.g., the
cleaning fee on reservation 54029 that gets reversed on cancellation). Crog-VRS
does not currently detect or replicate these. Phase G's reconciliation is the
discovery mechanism: by comparing Crog-VRS totals against Streamline's PDFs we
will identify discrepancies, and Phase G.5 (if needed) will add models to capture
them. Do NOT try to anticipate these in Phase D or Phase E.

### Payments To Owner table body empty until owner_payments table is built
The Payments To Owner table header row has columns: Date, Description, ACH #, CK #, Amount.
The body rows (individual disbursements) are empty because the `owner_payments` table does
not yet exist. Phase D's `mark_statement_paid()` stores only a text reference in `notes`.
The owner_payments table is required before per-payment line items (date, ACH number,
check number, description) can populate this section. Deferred to Phase F.5 or later.
Priority: MEDIUM — cosmetic gap at cutover; total amount is already correct.

### PDF closing balance label: "(includes minimum required balance)" is cosmetic
The PDF statement's closing balance row label reads:
  "Balance as of MM/DD/YYYY (includes minimum required balance)"
This text is hardcoded to match Streamline's format for cutover continuity.
Crog-VRS does NOT actually enforce a minimum required balance. The label is purely
cosmetic. Remove when CROG designs its own reserve/holdback policy (out of scope
for the Streamline migration phases).

### Owner mailing address NOT NULL migration deferred
The Phase E.5 design called for tightening `mailing_address_line1`, `city`, `state`,
and `postal_code` to NOT NULL after backfill. At time of Phase E.5, all 769 OPAs
in the DB are test rows with no real owners (no Streamline owner ID set). Running
ALTER COLUMN SET NOT NULL would fail on these test rows. Deferred until:
  (a) Real owner invitations are sent with addresses (invite form now requires them), OR
  (b) A clean test database is used
Add this migration when the first real owner is enrolled via the invite flow.

### PDF payments-to-owner section shows period total only
The "Payments To Owner" section total comes from `owner_balance_periods.total_payments`.
Individual disbursement rows (date, ACH number, check number) are not yet tracked
as line items in the DB. Add structured disbursement tracking in Phase F when the
payout pipeline is built.

### 44 historical properties marked offboarded
44 properties in the `properties` table were from past management relationships.
All have `is_active=false` and zero reservations. They were set to
`renting_state='offboarded'` in Phase A.5 migration `f8e1d2c3b4a5`. They cannot
generate owner statements, charges, or balance periods.
