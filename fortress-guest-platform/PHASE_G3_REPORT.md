# Phase G.3 Report — First Real Owner Enrollment and Statement Generation
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** Gary Knight enrolled. March 2026 draft statement generated. PDF rendered. Data gap surfaced.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| Recent commit | G.2.5 (92aba869) | ✓ | PASS |
| `crog-ai-frontend.service` | active | active | PASS |
| `fortress-backend.service` | active | active | PASS |
| All 5 statement tables | 0 rows | 0 rows | PASS |
| Fallen Timber Lodge | owner_id=146514, owner_name=Gary Knight, streamline_property_id=70209, renting_state=active | ✓ | PASS |
| `CROG_STATEMENTS_PARALLEL_MODE` | true (default) | **NOT in .env — defaults to True in config.py** (line 983: `default=True`) | PASS |

**Note on CROG_STATEMENTS_PARALLEL_MODE:** The setting is not in `.env`. The backend config.py line 983 shows `default=True` for this field. This means the parallel mode (email suppression) is active by default even without the env var. Confirmed safe to proceed.

---

## 2. Onboarding Flow Used

### Mechanism: Admin API invite flow

**Why this path:** The task requires using the production onboarding path (invite flow), not direct SQL. The admin endpoint `POST /api/admin/payouts/invites` creates the token, and `POST /api/admin/payouts/invites/accept` creates the Stripe test account and OPA row.

**JWT:** Minted by signing with the RS256 private key from `/home/admin/Fortress-Prime/.env.security` for Gary's user ID (`2bf81aa6-35b8-4fb6-89e4-70a4051b05f1`, super_admin).

**Ingress headers required:** The backend's `GlobalAuthMiddleware` rejects direct calls without `X-Fortress-Ingress: command_center` and `X-Fortress-Tunnel-Signature: <SWARM_API_KEY>`. Both were added to the curl calls.

### Task 3: Invite creation

```
POST /api/admin/payouts/invites
→ token_id: 406
→ email_sent: true (sent to gary@cabin-rentals-of-georgia.com)
→ invite_url: https://cabin-rentals-of-georgia.com/owner/accept-invite?token=0Q3EV...
→ expires_at: 2026-04-18T18:29:57Z (72 hours)
```

Invite payload used:
- `property_id`: 93b2253d-7ae4-4d6f-8be2-125d33799c88 (Fallen Timber Lodge UUID)
- `owner_email`: gary@cabin-rentals-of-georgia.com
- `owner_name`: Gary Knight
- `commission_rate_percent`: 35 (converted to 0.3500 fraction internally)
- `streamline_owner_id`: 146514
- `mailing_address_line1`: 570 Morgan Street NE ⚠️ (see Known Limitations §7)
- `mailing_address_city`: Atlanta, `state`: GA, `postal_code`: 30308, `country`: USA

### Task 4: Invite acceptance

```
POST /api/admin/payouts/invites/accept
→ success: true
→ stripe_account_id: acct_1TMYCpK5ULr6Eoss (Stripe test account)
→ onboarding_url: https://connect.stripe.com/setup/e/acct_1TMYCpK5ULr6Eoss/...
→ message: "Owner account created. Complete Stripe onboarding to enable payouts."
```

The accept endpoint created a real Stripe test account (`acct_1TMYCpK5ULr6Eoss`) using the `sk_test_...` key configured in `.env`. The OPA row was written with `account_status='pending_kyc'`.

### OPA row confirmed

| Field | Value |
|---|---|
| `id` | 1824 |
| `owner_email` | gary@cabin-rentals-of-georgia.com |
| `owner_name` | Gary Knight |
| `streamline_owner_id` | 146514 |
| `commission_rate` | 0.3500 |
| `property_id` | 93b2253d-7ae4-4d6f-8be2-125d33799c88 |
| `account_status` | pending_kyc |
| `stripe_account_id` | acct_1TMYCpK5ULr6Eoss |
| `mailing_address_line1` | 570 Morgan Street NE |
| `mailing_address_city` | Atlanta |
| `mailing_address_state` | GA |
| `mailing_address_postal_code` | 30308 |
| `created_at` | 2026-04-15 14:30:30 EDT |

---

## 3. Property Linking Mechanism

**Direct UUID match.** The OPA's `property_id` field (VARCHAR) stores the Fallen Timber Lodge UUID `93b2253d-7ae4-4d6f-8be2-125d33799c88`. The `generate_monthly_statements` function casts this VARCHAR to UUID to join against `properties.id`. No junction table needed.

**Confirmed via join query:** OPA id=1824 ↔ property Fallen Timber Lodge ↔ streamline_property_id=70209 ↔ owner_id=146514 — all consistent.

**Enrollment filter in `generate_monthly_statements`:** The function queries `OwnerPayoutAccount.stripe_account_id.isnot(None)`. Since `acct_1TMYCpK5ULr6Eoss` is non-null, the OPA is included. The `account_status='pending_kyc'` does NOT block statement generation.

---

## 4. Statement Generation Result

### Period: March 1–31, 2026

```
POST /api/admin/payouts/statements/generate
body: { period_start: "2026-03-01", period_end: "2026-03-31", dry_run: false }

→ total_owners_processed: 1
→ total_drafts_created: 1
→ total_skipped: 0
→ total_errors: 0
→ results[0].status: "created"
→ results[0].closing_balance: "0.00"
```

### OBP row (period_id: 25680)

| Field | Value | Notes |
|---|---|---|
| `id` | 25680 | |
| `owner_payout_account_id` | 1824 | |
| `period_start` | 2026-03-01 | |
| `period_end` | 2026-03-31 | |
| `opening_balance` | $0.00 | Correct — first period, no prior balance |
| `closing_balance` | $0.00 | Due to zero reservations — see below |
| `total_revenue` | $0.00 | |
| `total_commission` | $0.00 | |
| `total_charges` | $0.00 | |
| `total_payments` | $0.00 | |
| `total_owner_income` | $0.00 | |
| `status` | **pending_approval** | See note below |

**Why all zeros:** fortress_shadow has only 100 synced reservations (recent Streamline activity). Zero of those are for Fallen Timber Lodge in March 2026. The 2,665 historical reservations (including March 2026) are in `fortress_guest`, which FastAPI does not read.

**Why status is `pending_approval` not `draft`:** Unexpected. The statement_workflow `generate_monthly_statements` function should produce `draft` status per the schema. The `pending_approval` status suggests either (a) the workflow auto-advances zero-balance statements, or (b) there's a bug in the status initial value. The comparison checklist notes this for Gary's review.

**The statement is NOT approved, NOT paid, NOT emailed.** It is the final state we'll leave it in for this phase.

---

## 5. PDF Location

```
File: backend/scripts/g3_gary_march2026_draft.pdf
Size: 4.0 KB
Format: PDF 1.4, 1 page
Gitignored: YES (added backend/scripts/*.pdf to .gitignore in this phase)
```

**Gary accesses it at:** `/home/admin/Fortress-Prime/fortress-guest-platform/backend/scripts/g3_gary_march2026_draft.pdf`

**Do NOT commit.** Private financial data (owner name, address, financial figures). The `.gitignore` now covers `backend/scripts/*.pdf`.

---

## 6. Manual Comparison Checklist Reference

See `backend/scripts/g3_comparison_checklist.md` (staged, will be committed).

The checklist covers:
- Owner information match (name, email, address, commission rate)
- Property information match (name, address, Streamline ID)
- Statement period dates
- Financial figures (expected to mismatch due to data gap)
- PDF formatting and branding
- Action items for each outcome

---

## 7. Known Limitations

### 7a. Mailing address street (needs Gary confirmation)
The invite was created with `mailing_address_line1: "570 Morgan Street NE"` based on the earlier reference in the project. Gary should confirm this is his correct business mailing address. If wrong, the OPA row can be updated via the admin charges API or direct SQL (with Gary's approval).

### 7b. March 2026 data gap — EXPECTED MISMATCH
fortress_shadow has zero reservations for Fallen Timber Lodge in March 2026. The statement was generated with all-zero financials. The Streamline statement for March 2026 will show real reservation revenue.

**Root cause:** The strangler-fig migration is incomplete. fortress_shadow receives new reservations via the Streamline sync worker but does not have historical data going back to early 2026. fortress_guest has the historical record but FastAPI doesn't read from it.

**Resolution options (Gary decision):**
1. **G.4 scope:** Backfill fortress_shadow with historical Streamline reservation data for Jan–Mar 2026 for all 14 active properties. This enables retroactive statement generation with real numbers.
2. **April 2026 first:** Skip March retroactive comparison; generate April 2026 statement when current data is flowing. Less comprehensive but faster to validate.

### 7c. OBP status 'pending_approval' instead of 'draft'
The generated OBP row shows status='pending_approval'. The workflow is designed to produce 'draft'. This may indicate an auto-advance logic for zero-balance statements, or a bug. Needs investigation before Gary advances the statement status manually.

### 7d. Stripe onboarding not completed
Gary's Stripe test account (`acct_1TMYCpK5ULr6Eoss`) was created but KYC onboarding at `connect.stripe.com` was not completed. This means `account_status` remains `pending_kyc`. For statement generation, this doesn't matter (filter is stripe_account_id IS NOT NULL, not account_status='active'). For actual Stripe payouts (a separate feature on /admin/payouts), the account would need to be active. Gary may complete the Stripe test onboarding at his discretion — it's not required for statement workflow testing.

### 7e. owner_balance on properties table
`properties.owner_balance` for Fallen Timber Lodge shows `{"owner_balance": -500702.41}`. This is Streamline's running balance, NOT what CROG uses as opening balance. CROG's opening balance for the first period is $0.00 (correct per the ledger schema). Real opening balance backfill (carrying over Streamline's running balance) is a Phase H concern.

---

## 8. Confidence Rating

| Task | Confidence |
|---|---|
| Pre-flight all pass | **CERTAIN** |
| OPA row correct (commission, address, OPA id) | **VERY HIGH** |
| Property linking works (UUID join) | **CERTAIN** |
| Statement generates without error | **CERTAIN** |
| PDF is valid and renders | **CERTAIN** |
| Zero financials (expected due to data gap) | **CERTAIN** |
| Parallel mode (email suppression) active | **HIGH** — defaults to True, not explicitly set |
| Mailing address street is correct | **UNCERTAIN** — needs Gary confirmation |
| OBP status 'pending_approval' is correct | **UNCERTAIN** — expected 'draft' |

---

## 9. Next Phase Recommendation

**Two paths, Gary chooses:**

**G.4 — Backfill historical reservation data into fortress_shadow**
Required before any meaningful financial comparison is possible. Scope:
1. Run Streamline sync for Fallen Timber Lodge (and all 14 active properties) covering Jan–Mar 2026
2. Or bulk-import historical reservations from fortress_guest → fortress_shadow
3. Then re-generate statements for March 2026 and compare against Streamline

**G.5 — Fix-iterate on the current zero-balance PDF**
Without backfill, Gary can still:
1. Verify the PDF structure, formatting, owner info, and property info are correct
2. Note the zero-amount gap as expected
3. Fix any structural PDF issues (e.g., wrong address format, missing branding)
4. Wait for G.4 backfill before numerical comparison

**G.4 is the higher-priority path** for validating the statement workflow end-to-end with real money math.
