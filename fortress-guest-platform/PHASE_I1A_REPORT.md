# Phase I.1a Report — Vendor + Markup on Owner Charges
**Date:** 2026-04-16  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** COMPLETE. Migration applied, vendor + markup end-to-end validated on Fallen Timber Lodge.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| Latest commit | I.1 (e325bb09) | e325bb09 | PASS |
| `fortress-backend.service` | active | active | PASS |
| `crog-ai-frontend.service` | active | active | PASS |
| Charge 354 | voided | voided_at set | PASS |
| OBP 25680 opening/closing | $500,702.41 / $504,738.26 | ✓ | PASS |
| Vendors (active) | 216 | 216 | PASS |
| Distinct trades | 4 | hvac, plumbing, electrical, general | PASS |

---

## 2. Migration Applied

**File:** `backend/alembic/versions/i1a2_add_vendor_and_markup.py`  
**Revision:** `i1a2_add_vendor_and_markup` → `i1a1_add_owner_charge_types`  
**Note:** First attempt used ID `i1a2_add_vendor_and_markup_to_owner_charges` (44 chars > VARCHAR(32) limit on `alembic_version`). Rolled back cleanly; retried with `i1a2_add_vendor_and_markup` (26 chars). ✓

**Columns added:**

| Column | Type | Nullable | Default |
|---|---|---|---|
| `vendor_id` | UUID FK → vendors.id (SET NULL) | YES | — |
| `markup_percentage` | NUMERIC(5,2) | NO | 0.00 |
| `vendor_amount` | NUMERIC(12,2) | YES | — |

Index: `ix_owner_charges_vendor_id` created.  
Existing rows: `markup_percentage=0.00`, `vendor_id=NULL`, `vendor_amount=NULL` — no disruption.

---

## 3. Model + Schema Changes

### `backend/models/owner_charge.py`
- Added `vendor_id`, `markup_percentage`, `vendor_amount` columns
- Added `vendor = relationship("Vendor", ...)` (lazy-loaded)

### `backend/api/admin_charges.py`
- Added `from backend.models.vendor import Vendor` import
- `OwnerChargeCreateRequest`:
  - `amount` made optional (required only when no vendor)
  - `vendor_id`, `markup_percentage`, `vendor_amount` added
  - Cross-field validation: `vendor_id → vendor_amount required`, `markup_percentage 0–100`
  - `computed_amount()` method: `vendor_amount × (1 + markup/100)` rounded to cents
- `OwnerChargePatchRequest`: added `markup_percentage`, `vendor_amount`
- `_enrich()`: now returns `(owner_name, property_name, vendor_name)` — looks up vendor by FK
- `_charge_dict()`: includes `vendor_id`, `vendor_name`, `markup_percentage`, `vendor_amount`
- `create_charge`: validates vendor active; uses `computed_amount()` when vendor set; persists 3 new fields
- `update_charge`: recomputes `amount` when `vendor_amount` or `markup_percentage` updated
- All `_enrich` call sites updated to unpack 3 values

### `backend/services/statement_computation.py`
- `OwnerChargeLineItem`: added `vendor_name: Optional[str] = None`
- `_fetch_charges()`: resolves vendor name via `db.get(Vendor, ch.vendor_id)` when `vendor_id` set

### `backend/services/statement_pdf.py`
- Owner Charges section: appends `— {vendor.name[:16]}` to truncated description when vendor linked
- Description format: `"{desc[:20]}…"` + ` — {vendor[:16]}` when vendor; `desc[:40]` otherwise

---

## 4. Frontend UI Changes

### `apps/command-center/src/lib/types.ts`
- `OwnerCharge`: added `vendor_id`, `vendor_name`, `markup_percentage`, `vendor_amount`
- `CreateOwnerChargeRequest`: `amount` made optional; added `vendor_id`, `markup_percentage`, `vendor_amount`

### `apps/command-center/src/lib/hooks.ts`
- Added `Vendor`, `VendorListResponse` interfaces
- Added `useVendors(activeOnly=true)` hook → `GET /api/vendors`

### `apps/command-center/src/app/(dashboard)/admin/owner-charges/page.tsx`
- Import: added `useVendors`, `Vendor`, `useMemo`, `ChevronDown`, `ChevronUp`
- `ChargeModal`: collapsible **Vendor & Markup** section:
  - Trade dropdown (client-side filtered from 216 vendors)
  - Vendor dropdown (filtered by selected trade)
  - Vendor Amount field
  - Markup % field (0–100)
  - Computed Owner Amount (read-only, live-updated)
  - Vendor name → PDF reminder shown in description field
  - When no vendor: existing direct Amount flow unchanged
- Table: added **Vendor** column showing `vendor_name` or "—"
- TypeScript: zero errors (`npx tsc --noEmit` clean)

---

## 5. End-to-End Validation Results

**Test charge:** OPA 1824 (Fallen Timber Lodge), 2026-03-15, Maintenance  
**Vendor:** ActiveV_0b2a98 (trade=plumbing, id=f1aafea6-4c53-4941-a4ef-f266c866e94c)

| Step | Check | Expected | Result |
|---|---|---|---|
| a | Charge posted | id=356 created | ✓ |
| b | DB: vendor_amount | $100.00 | ✓ |
| b | DB: markup_percentage | 20.00 | ✓ |
| b | DB: amount (owner) | $120.00 | ✓ ($100 × 1.20 = $120 ✓) |
| c | PDF generated | 5.2 KB | ✓ |
| d | Vendor name on PDF | "… — ActiveV_0b2a98" | ✓ |
| d | Owner amount on PDF | $120.00 | ✓ |
| e | Void charge | status=voided | ✓ |

All 7 checks: **PASS**.

---

## 6. PDF for Visual Review

```
backend/scripts/i1a_crog_with_vendor.pdf   (5.2 KB, gitignored)
```

Shows: Gary Knight / Fallen Timber Lodge / March 2026 / Owner Charges section with  
"Test charge for I.1a… — ActiveV_0b2a98 | Maintenance | $120.00".

---

## 7. Confidence Rating

| Item | Confidence |
|---|---|
| Migration applied cleanly | **CERTAIN** — 3 columns in information_schema, existing row 354 has markup=0.00, vendor=NULL |
| `amount = vendor_amount × (1 + markup/100)` | **CERTAIN** — $100 × 1.20 = $120.00 verified in DB |
| Vendor name on PDF | **CERTAIN** — pdftotext shows "… — ActiveV_0b2a98" |
| TypeScript zero errors | **CERTAIN** — `tsc --noEmit` clean |
| Build clean | **CERTAIN** — `next build` succeeded |
| No regression on existing charges | **CERTAIN** — charge 354 (voided, no vendor) unaffected |

---

## 8. Recommended Next Phase

**I.1b — Email-on-save** (deferred from I.1): send owner a copy of the statement PDF when a charge is posted.

**I.4 — Event-driven OBP recompute**: close the architectural gap where posting a charge doesn't automatically update `owner_balance_periods.closing_balance`. Options:
- Emit an event from `create_charge` / `void_charge` that triggers `generate_monthly_statements` for the affected OPA+period
- Or a lightweight `recompute_obp(db, opa_id, period_start, period_end)` helper called inline

**I.5 — Real vendor names**: the 216 active vendors in DB have synthetic names (ActiveV_*, HVAC_*, Plumber_*, etc.) from the sync script. Before using the vendor attribution feature in production, Gary/Barbara will need to run a vendor name cleanup sync from Streamline.
