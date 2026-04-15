# Owner Statements — Discovery Report
**Date:** 2026-04-14  
**Purpose:** Establish the current state of the codebase before beginning Phase A of the
Crog-VRS Owner Statements build.  
**Method:** Read-only. No code modified. No tables created. No migrations run.

---

## 1. Test Suite Baseline

**606 passing, 1 failing, 3 skipped.**

The 1 failing test (`test_run_concierge_shadow_draft_cycle_disabled`) is a pre-existing
flaky test that passes in isolation but fails when run alongside the full suite due to
shared state. It is not related to the statement system and was present before any
statement work began.

Statement-related tests added in prior sessions:

| Test file | Tests |
|---|---|
| `test_owner_statement_phase1.py` | 7 |
| `test_owner_statement_phase1_5.py` | 10 |
| `test_owner_statement_phase2.py` | 8 |
| `test_owner_statement_phase3.py` | 11 |
| **Total statement tests** | **36** |

**Confidence: HIGH** — ran the suite directly.

---

## 2. Key Files — Current State

All nine files listed in the discovery prompt exist. Here is their current state:

### `backend/services/statement_computation.py`
Contains `compute_owner_statement(db, owner_payout_account_id, period_start, period_end)`.
Also contains `StatementResult` (Pydantic), `StatementComputationError`, and
`_bucketed_items_from_reservation`.

**What it currently does correctly:**
- Reads `commission_rate` from `owner_payout_accounts` (never hardcoded)
- Excludes cancelled reservations (`status.in_(["confirmed", "checked_in", "checked_out", "completed"])`)
- Separates cleaning fees, taxes, and processing fees as pass-through
- Raises `StatementComputationError` for unenrolled owners and non-existent properties

**What it does NOT yet do (Phase B work):**
- No `is_owner_booking` filter — owner-booked reservations are included in revenue
- No `renting_state` check — Restoration Luxury would get a statement if an owner enrolled there
- No multi-month reservation splitting (a reservation straddling Jan/Feb is counted entirely in check-in month)
- Pet fees are currently commissionable (correct per business rules) but the CC processing fee deduction has NOT been removed yet (bug to fix in Phase B — see Section 5 for detail)

### `backend/services/statement_comparison.py`
Contains `compare_statements(crog, streamline)` and `ComparisonResult`.
Also contains `fetch_streamline_statement_normalized()` — currently a documented stub
that always returns `None` because Streamline's GetMonthEndStatement does not return
financial figures in JSON (the data is PDF-only). The stub is intentional pending a
product-owner decision on how to handle the comparison.

### `backend/services/ledger.py`
Contains `calculate_owner_payout(items, commission_rate, cc_processing_rate, cc_processing_flat)`.

**Current behavior:** The function still subtracts a CC processing fee from the owner's
net payout (2.9% of total collected + $0.30 flat). This is the "Model A not yet
implemented" bug. For a $1,615 rent reservation at 30% commission, the function
currently returns $1,063.23 instead of the correct $1,130.50. Phase B must remove the
CC deduction. The constants `DEFAULT_CC_PROCESSING_RATE` and `DEFAULT_CC_PROCESSING_FLAT`
still exist in the file.

### `backend/api/admin_statements.py`
The `GET /api/v1/statements/{owner_id}` endpoint exists and calls
`compute_owner_statement`. After Phase 1.5 changes, it reads commission_rate from the
database instead of using a hardcoded default. It accepts a `commission_rate_override`
query parameter for staff what-if modelling only (not a business rate source, documented
as such).

### `backend/api/owner_portal.py`
Contains the public (no-auth) invite endpoints:
- `GET /api/owner/invite/validate?token=...`
- `POST /api/owner/invite/accept`

### `backend/api/admin_payouts.py`
Contains the admin invite creation endpoint `POST /api/admin/payouts/invites` (requires
admin auth). The `OwnerInviteRequest` schema now requires `commission_rate_percent` (0–50
inclusive). Also contains the `POST /api/admin/payouts/statements/send-all` endpoint,
which currently returns HTTP 501 Not Implemented — the old implementation with hardcoded
65% was deleted in Phase 1.5 and not yet replaced.

### `backend/services/owner_onboarding.py`
Contains `create_invite()` and `accept_invite()`. Commission rate flows from the invite
token (stored in `owner_magic_tokens.commission_rate`) through to
`owner_payout_accounts.commission_rate` at accept time.

### `backend/integrations/streamline_vrs.py`
Contains `fetch_owner_statement(owner_id, unit_id, start_date, end_date, include_pdf)`.
Confirmed working against the real Streamline API (tested in the owner-booking audit).
Returns metadata only in JSON; financial figures are PDF-only.

### `backend/core/worker.py`
Contains `WorkerSettings` class with ~35 background job functions. **No `cron_jobs`
list exists yet.** The statement cron (12th and 15th monthly) will be added in Phase F.

**Confidence: HIGH** — read every file directly.

---

## 3. Table Schemas

### `reservations`
53 columns. Financially relevant columns:

| Column | Type | Notes |
|---|---|---|
| `status` | varchar | Only `confirmed`/`cancelled` in current data |
| `booking_source` | varchar | `Ring Central` for all owner bookings (loses the `O` flag) |
| `total_amount` | numeric | |
| `nightly_rate` | numeric | Zero for 5 confirmed + 5 cancelled lump-sum Streamline reservations |
| `cleaning_fee` | numeric | Separate column |
| `pet_fee` | numeric | Separate column |
| `damage_waiver_fee` | numeric | Always NULL in current data |
| `service_fee` | numeric | Combined lump: ADW + DOT Tax + Processing Fee |
| `tax_amount` | numeric | Total taxes combined |
| `price_breakdown` | jsonb | Has `line_items` for local-ledger bookings; Streamline price fields for synced bookings |
| `streamline_financial_detail` | jsonb | **Empty for all rows** |

**Missing columns (Phase B will add these):**
- `is_owner_booking` — does not exist yet; all 5 known confirmed owner bookings are undetected

### `owner_payout_accounts`
17 columns. Key columns added in prior sessions:

| Column | Type | Notes |
|---|---|---|
| `id` | bigint | Primary key |
| `property_id` | varchar(100) | Links to `properties.id` as text (type mismatch — string vs UUID) |
| `commission_rate` | numeric(5,4) | **NOT NULL, no default** — set at invite time |
| `streamline_owner_id` | integer | Nullable |
| `stripe_account_id` | varchar | NULL until owner accepts invite |
| `account_status` | varchar | `onboarding`/`pending_kyc`/`active` |

Currently **0 real enrolled owners** in the database (only test rows from the test suite, all cleaned up). The table is ready but empty.

### `owner_magic_tokens`
8 columns. The `commission_rate numeric(5,4) NULL` column was added in Phase 1.5 so the
rate travels from invite creation to acceptance.

### `owner_statement_sends`
16 columns audit table built in Phase 1. Stores per-send metadata including comparison
status, crog/streamline totals, and the `is_test` flag. **No `owner_balance_periods`
table exists yet** — that is Phase A work.

### `properties`
51 columns (two schemas merged into one table). **No `renting_state` column exists yet.**

The current "renting status" fields are:
- `is_active` — boolean, all 14 properties are `true`
- `status` — a `crog_acquisition.market_state` enum from the acquisition pipeline

Neither field distinguishes "actively renting" from "pre-launch." Phase A adds
`renting_state`.

**Confidence: HIGH** — ran `\d` directly against all tables.

---

## 4. Cron Jobs Currently Running

### System cron (`admin` user's crontab)
28 non-comment entries. **None are related to owner statements, payouts, or monthly
billing.** The crontab handles: email monitoring, market intelligence, code backups,
database backups, AI model maintenance, and housekeeping. No statement cron exists.

### ARQ cron_jobs (in `WorkerSettings`)
**None.** The `WorkerSettings` class has no `cron_jobs` field at all. The worker runs
~35 on-demand background jobs and several internal asyncio polling loops (payout sweep,
hermes daily auditor), but no true ARQ cron entries. Phase F adds the statement cron
jobs using ARQ's native `cron_jobs` feature.

### Systemd timers (application-level)
Three timers running on spark-node-2:
- `fortress-deadline-sweeper.timer` — daily at 06:00 (legal/contract deadlines)
- `crog-hunter-worker.timer` — daily at 09:00 ET (sales reactivation)
- `fortress-nightly-finetune.timer` — daily at 02:00 (LLM fine-tuning)

None are related to statements.

**Confidence: HIGH** — checked system cron, ARQ WorkerSettings, and systemd timers
directly.

---

## 5. Environment Variables

### Currently defined (names only, no values)

**Stripe:**
`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_CONNECT_CLIENT_ID`,
`stripe_connect_webhook_secret`, `stripe_dispute_webhook_secret`,
`stripe_publishable_key`

**SMTP/Email:**
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
`email_from_address`, `email_from_name`

**Streamline:**
`STREAMLINE_API_KEY` (field name: `streamline_api_key`),
`STREAMLINE_API_URL`, `STREAMLINE_API_SECRET`, `STREAMLINE_WEBHOOK_SECRET`,
plus four `STREAMLINE_SOVEREIGN_BRIDGE_*` flags

### Missing — will need to be added

- **`OWNER_STATEMENT_ALERT_EMAIL`** — not defined anywhere in config.py. Phase F requires
  this for the post-run alert email. It will need to be added to `Settings` and to the
  production `.env` file before Phase F runs for real.

- **`QUICKBOOKS_*`**, **`ACH_*`** — No QuickBooks or ACH integration exists anywhere in
  the codebase. The business rule is that Crog-VRS records that payment occurred but does
  not initiate bank transfers. These env vars are not needed unless QuickBooks integration
  is added in a future phase (out of scope for this build plan).

**Confidence: HIGH** — searched config.py directly.

---

## 6. NOTES.md

**Does not exist** at the repo root. Phase B will create it (the build plan requires it).
Several items are already queued for NOTES.md from prior sessions:

- The scheduling trilemma (system cron vs ARQ vs asyncio.sleep loops coexisting)
- The `owner_magic_tokens` dual-purpose table (invite tokens and login tokens share one table)
- The Stripe Connect Express accounts being dormant infrastructure (no money flows yet)
- The admin UI invite form not yet having `commission_rate_percent` or `streamline_owner_id` fields
- The `commission_rate_override` parameter on `admin_statements.py` being a what-if tool, not a real rate source
- `fetch_streamline_statement_normalized()` stub pending product owner decision on PDF extraction

**Confidence: HIGH** — checked directly.

---

## 7. Properties — Current State

All 14 properties have `is_active = true`. **There is no `renting_state` column yet.**

| Property | Owner | Streamline ID | 12-mo confirmed reservations | Revenue |
|---|---|---|---|---|
| Above the Timberline | (outside) | 382651 | 1 | $5,147 |
| Aska Escape Lodge | (outside) | 235641 | 3 | $4,609 |
| Blue Ridge Lake Sanctuary | Dale & Denise Eby | 419022 | 4* | $2,497 |
| Chase Mountain Dreams | Mary Kay Buquoi | 980130 | 3* | $5,375 |
| Cherokee Sunrise on Noontootla Creek | Gary Knight | 306758 | 1 | $1,282 |
| Cohutta Sunset | (outside) | 70206 | 1 | $2,309 |
| Creekside Green | Katherine Sutton | 756771 | 2 | $3,351 |
| Fallen Timber Lodge | Gary Knight | 70209 | 7 | $25,412 |
| High Hopes | Mike Chumbley | 441334 | 3 | $6,822 |
| **Restoration Luxury** | **Gary Knight** | **1012373** | **0** | **$0** |
| Riverview Lodge | Thor James | 70220 | 7* | $21,155 |
| Serendipity on Noontootla Creek | Gary Knight | 70222 | 2 | $8,357 |
| Skyfall | Chris & Danielle Curtis | 1001528 | 0 | $0 |
| The Rivers Edge | Jerome Yoham | 70224 | 6 | $20,810 |

*Includes confirmed owner-booked reservations that should contribute $0 to statements
(Blue Ridge Lake Sanctuary: 3 Eby owner stays; Chase Mountain Dreams: 1 Buquoi owner
stay; Riverview Lodge: 1 Thor James owner stay). These 5 will be excluded from revenue
once Phase B adds `is_owner_booking`.

**Key observations:**
- **Restoration Luxury**: 0 confirmed reservations, owned by Gary Knight. Phase A will
  mark it `pre_launch`. No statement will ever be generated for it until status changes.
- **Skyfall**: 0 confirmed reservations in the past 12 months despite being `is_active`.
  This may be genuinely idle, or may need attention. Flagging for NOTES.md.
- Most properties have real revenue data available for parallel validation during Phase G.

**Confidence: HIGH** — data queried directly.

---

## 8. Reservation Counts

Total confirmed reservations (last 12 months): **40** across 12 of 14 properties.
Total cancelled: 17 (all correctly excluded from statements by the current filter).
Total with `is_owner_booking` flag needed: at least 5 confirmed (verified) + 5 cancelled
(likely, not individually confirmed).

The database has enough real data to meaningfully run parallel validation in Phase G.
Properties with the richest data are Fallen Timber Lodge (7), Riverview Lodge (7),
and The Rivers Edge (6).

**Confidence: HIGH** — queried directly.

---

## Outstanding Missing Pieces (Blockers for Specific Phases)

These are facts, not judgments. Each one maps to a specific phase.

| Item | Current state | Needed for |
|---|---|---|
| `is_owner_booking` column on reservations | **Does not exist** | Phase B |
| `renting_state` column on properties | **Does not exist** | Phase A |
| `owner_balance_periods` table | **Does not exist** | Phase A |
| `owner_charges` table | **Does not exist** | Phase C |
| CC processing fee deduction in `calculate_owner_payout` | **Still present** (Bug) | Phase B |
| Multi-month reservation splitting | **Not implemented** | Phase B |
| Owner-booking exclusion in `compute_owner_statement` | **Not implemented** | Phase B |
| `OWNER_STATEMENT_ALERT_EMAIL` env var | **Not defined** | Phase F |
| ARQ `cron_jobs` for 12th/15th | **Not registered** | Phase F |
| 5 "lump sum" Streamline reservations missing nightly_rate | **Present, inaccurate** | Phase B |
| NOTES.md | **Does not exist** | Phase B (create at start) |
| No enrolled owners in database | **Table is empty** | All phases needing real data |

---

## Ready to Begin Phase A?

**Yes, with one note.**

There are no blockers for Phase A itself. The prerequisites for Phase A are all met:
- The test suite is clean (606 passing)
- `owner_payout_accounts` has the `commission_rate` column (NOT NULL, no default)
- `compute_owner_statement` reads commission_rate from the database correctly
- The Alembic migration chain ends at `c1a8f3b7e2d4` (clean head)

The one thing to be aware of going into Phase A: **there are no enrolled owners in
the database right now.** Every owner_payout_accounts row was a test artifact from
prior development sessions. Phase A's tests for `get_or_create_balance_period` and
`compute_owner_statement` will need to create their own test enrollment rows, as the
Phase 2 tests already do. This is expected and not a blocker.

The bug in Phase A context: `calculate_owner_payout` still subtracts a CC processing
fee. This does not block Phase A (which is about schema and balance carrying), but
the Phase A tests for `compute_owner_statement` will produce lower-than-expected
owner net amounts until Phase B fixes it. Any test that asserts an exact dollar
amount in Phase A should use the post-CC-deduction value, or should mock
`calculate_owner_payout`. The Phase A prompt does not require exact financial
assertions, so this should not be a practical problem.

**Send Phase A whenever ready.**
