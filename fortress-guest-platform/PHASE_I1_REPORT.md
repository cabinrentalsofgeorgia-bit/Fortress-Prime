# Phase I.1 Report — Owner Charges UI + Transaction Code Taxonomy
**Date:** 2026-04-16  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** COMPLETE. UI built, 21 codes taxonomized, E2E validation passed on Fallen Timber Lodge.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| Latest commit | H.2 (8c3444af) | 8c3444af | PASS |
| `fortress-backend.service` | active | active | PASS |
| `crog-ai-frontend.service` | active | active | PASS |
| OBP 25680 opening | $500,702.41 | $500,702.41 | PASS |
| OBP 25680 closing | $504,738.26 | $504,738.26 | PASS |
| `owner_charges` table | exists | exists, 0 rows | PASS |
| `transaction_type` column | exists | USER-DEFINED enum | PASS |

---

## 2. Transaction Code Taxonomy

**Scenario A — partial match (17 of 22 codes already in backend).**

The backend had `OwnerChargeType` enum in `backend/models/owner_charge.py` with 17 values.

### Missing from backend (4 codes + 1 UI-only placeholder)

| Missing code | Action |
|---|---|
| Statement Marker | Added `STATEMENT_MARKER = "statement_marker"` |
| Room Revenue | Added `ROOM_REVENUE = "room_revenue"` |
| Hacienda Tax | Added `HACIENDA_TAX = "hacienda_tax"` |
| Charge Expired Owner | Added `CHARGE_EXPIRED_OWNER = "charge_expired_owner"` |
| "(Select Transaction Code)" | UI placeholder only — no DB enum value needed |

### Decision: extend existing enum (Scenario A path)

**Files changed:**
- `backend/models/owner_charge.py`: added 4 enum values + display names  
- `backend/alembic/versions/i1a1_add_owner_charge_types.py`: `ALTER TYPE owner_charge_type_enum ADD VALUE IF NOT EXISTS` for each new value  
- `apps/command-center/src/lib/owner-charge-codes.ts`: TS constant mirroring all 21 values in Streamline canonical order

**Migration run:** `g6a1_add_owner_middle_name → i1a1_add_owner_charge_types` ✓ (21 values in DB confirmed)

---

## 3. New Page: `/admin/owner-charges`

**File:** `apps/command-center/src/app/(dashboard)/admin/owner-charges/page.tsx`

### Structure

| Section | Implementation |
|---|---|
| Header | "Owner Charges" title + subtitle + "Post Charge" button |
| Filters bar | Owner dropdown (OPA), Transaction Type dropdown, Date From/To, Show/Hide Voided toggle, Clear button |
| Table | 8 columns: Posted Date, Owner, Property, Transaction Type, Description, Amount, Status, Actions |
| Empty state | "No charges posted. Click Post Charge to get started." |
| Post Charge modal | OPA dropdown, Transaction Type, Description, Posted Date, Amount, W.O./REF# (optional) |
| Edit modal | Description, Posted Date, Amount, W.O./REF# editable; type locked |
| Void modal | Prompts for void reason, calls `useVoidOwnerCharge` |

**Hooks used:** `useAdminCharges`, `useCreateOwnerCharge`, `useUpdateOwnerCharge`, `useVoidOwnerCharge`, `useAdminOPAs` (new)

**TypeScript:** zero errors (`npx tsc --noEmit` clean)  
**Build:** clean (`next build` succeeded, page compiled at `/(dashboard)/admin/owner-charges/page.js`)

### New hook added to hooks.ts

`useAdminOPAs()` → `GET /api/admin/payouts/accounts` → returns `AdminOPA[]` for UI dropdowns.

### New backend endpoint

`GET /api/admin/payouts/accounts` added to `admin_statements_workflow.py`.  
Returns all OPAs with resolved property names. Used exclusively by the owner-charges UI dropdown.

---

## 4. Navigation Entries

**File:** `apps/command-center/src/config/navigation.ts`

| Sector | Entry added |
|---|---|
| SHADOW OPS | "Owner Charges" → `/admin/owner-charges`, `allowedRoles: COMMAND_ROLES` |
| STAKEHOLDERS | "Owner Charges" → `/admin/owner-charges`, `allowedRoles: ["super_admin", "ops_manager"]` |

Both entries positioned immediately after "Owner Statements" in their respective sectors.

---

## 5. End-to-End Validation Results (Fallen Timber Lodge, OPA 1824)

| Step | Check | Expected | Result |
|---|---|---|---|
| a | Post $100 Maintenance charge, 2026-03-15 | charge_id created | ✓ id=354 |
| b | Charge in DB | row present, voided_at=NULL | ✓ |
| c | Regenerate PDF with charge | PDF generated | ✓ 5.2 KB |
| d | Charge appears in PDF | "Maintenance", "Test charge for I.1", $100.00 | ✓ |
| e | OBP closing balance after recompute | $504,638.26 (= $504,738.26 − $100) | ✓ |
| f | Void charge | status=voided, void_reason recorded | ✓ |
| g | Post-void PDF | charge absent (`charges=0` in log) | ✓ |

**Gap surfaced:** The OBP `total_charges` and `closing_balance` columns do NOT auto-update when a charge is posted. The PDF endpoint always recomputes live (correct). The stored OBP balance only updates when `generate_monthly_statements` is re-run. Filed as follow-up (§7).

All 7 checks: **PASS**.

---

## 6. PDF for Visual Review

```
backend/scripts/i1_crog_march2026_with_charge.pdf   (5.2 KB, gitignored)
```

Contains: Gary Knight / Fallen Timber Lodge / March 2026 / with $100 Maintenance charge visible in Owner Charges / Expenses section.

---

## 7. Follow-ups Filed

### OBP auto-recompute on charge post (I.2+)
Posting a charge does not automatically update `owner_balance_periods.total_charges` / `closing_balance`. Staff must re-run statement generation to sync the stored balance. Options:
- Trigger `generate_monthly_statements` for the affected OPA+period on charge create/void/update
- Or add a DB trigger / event hook
- Or document that the "Regenerate" button in the statements UI covers this

### File attachments for charges (deferred)
The charge form has no file attachment support. Adding it requires:
- Storage backend (S3-compatible or local NAS bucket)
- Security design (signed URLs, access control)
- New `owner_charge_attachments` table or JSONB column
- Deferred to I.3 or later.

### Stripe multi-property: Cherokee/Serendipity charge posting
OPAs 1826 and 1827 have `stripe_account_id=NULL`. The `POST /charges` endpoint rejects them (422). For Barbara to post charges to Cherokee/Serendipity, either:
- Extend `require_stripe_enrollment` bypass to the charges API (like we did for PDF/computation)
- Or document that charges to these properties use a workaround until Stripe is wired up

---

## 8. Confidence Rating

| Item | Confidence |
|---|---|
| 21 transaction codes in DB | **CERTAIN** — `SELECT enum_range(NULL::owner_charge_type_enum)` confirms all 21 |
| Page builds clean | **CERTAIN** — `next build` clean, `tsc --noEmit` zero errors |
| Charge appears in PDF | **CERTAIN** — pdftotext shows Maintenance / $100 / description text |
| Void removes charge from PDF | **CERTAIN** — `charges=0` in log, grep returns empty |
| OBP closing moves by $100 | **CERTAIN** — $504,638.26 after recompute |
| OBP restoration | **CERTAIN** — $504,738.26 after void + recompute |
| Navigation entries added | **CERTAIN** — grep confirms both SHADOW OPS and STAKEHOLDERS |

---

## 9. Recommended Next Phase

**I.2 — Receive Owner Payment:** Record a payment from owner to management (trust reconciliation).  
**I.3 — Credit Owner Account:** Record a credit back to the owner (e.g., overpayment return).  
**I.4 — Auto-recompute OBP on charge events:** Trigger `generate_monthly_statements` when a charge is posted/voided/edited for the affected period, so `closing_balance` stays current without manual regeneration.  
**I.5 — Pay Owner:** Full payout flow trigger (Stripe transfer initiation from the UI).  
**H.3 — Serendipity/Cherokee parity audit:** Line-by-line comparison of CROG PDFs vs NAS-archived Streamline PDFs.
