# Phase G.5.1 Report — Streamline Data Refresh and Statement Regeneration
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** COMPLETE. JSONB refreshed. Pet removed from commissionable patterns. Statement matches Streamline exactly: $6,209.00 revenue / $2,173.15 commission / $4,035.85 owner net.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| HEAD | G.5 (3450903c) | ✓ | PASS |
| Services | active | both active | PASS |
| OBP 25680 total_revenue | $4,759 (G.5) | $4,759 | PASS |
| 53765: stale=NULL, req_fees=5 | ✓ | ✓ | PASS |
| 53790: stale=true, req_fees=0 | ✓ | ✓ | PASS |
| 53952: stale=true, req_fees=0 | ✓ | ✓ | PASS |
| Streamline credentials | present | 3 vars (URL, KEY, SECRET) | PASS |

---

## 2. Streamline Client Investigation

`StreamlineVRS.fetch_reservation_price(confirmation_id)` in `backend/integrations/streamline_vrs.py:1319` calls `GetReservationPrice` and returns the full dict that becomes `streamline_financial_detail`. Used directly in the enrichment loop (Phase 6 of the sync). `StreamlineClient.fetch_live_quote()` wraps this for parity auditing and includes Redis caching.

Called `fetch_reservation_price()` directly via `StreamlineVRS()` (reads credentials from `settings`). No database session needed for the API call.

---

## 3. Backup

Both stale values backed up before any update:

```
File: /tmp/g51_backup_jsonb.txt   (pretty-printed JSONB per reservation)
File: /tmp/g51_rollback.sql       (SQL rollback statements)
```

Stale values were: `{"data": {}, "_stale": true, "_circuit_open": true}` for both 53790 and 53952.

**Rollback commands (if needed):**
```sql
UPDATE reservations SET streamline_financial_detail =
  '{"data": {}, "_stale": true, "_circuit_open": true}'::jsonb,
  updated_at = NOW() WHERE confirmation_code = '53790';
UPDATE reservations SET streamline_financial_detail =
  '{"data": {}, "_stale": true, "_circuit_open": true}'::jsonb,
  updated_at = NOW() WHERE confirmation_code = '53952';
```

---

## 4. Streamline API Responses

Fresh data retrieved successfully. No stale markers. Key active required_fees:

### Reservation 53790 (3 nights, Fallen Timber Lodge)
| Fee Name | Value | Active | Classification |
|---|---|---|---|
| Additional Party Fee | $450.00 | ✓ | commissionable (keyword: "additional party") |
| Arrival/Departure Clean | $450.00 | ✓ | pass-through |
| Accidental Damage Waiver | $65.00 | ✓ | pass-through |
| DOT Tax | $15.00 | ✓ | pass-through |
| Processing Fee | $128.04 | ✓ | pass-through |

**53790 commissionable gross: $1,234 (rent) + $450 (APF) = $1,684 ✓ matches Streamline**

### Reservation 53952 (5 nights, Fallen Timber Lodge, 1 pet)
| Fee Name | Value | Active | Classification |
|---|---|---|---|
| Additional Party Fee | $1,000.00 | ✓ | commissionable (keyword: "additional party") |
| Arrival/Departure Clean | $499.00 | ✓ | pass-through |
| **Pet Cleaning Fee** | **$75.00** | ✓ | **pass-through** — "clean" in name → _is_pass_through ✓ |
| **Pet Fee** | **$250.00** | ✓ | ⚠️ classified as commissionable (keyword: "pet") |
| Accidental Damage Waiver | $65.00 | ✓ | pass-through |
| DOT Tax | $25.00 | ✓ | pass-through |
| Processing Fee | $245.94 | ✓ | pass-through |

---

## 5. JSONB Update

Executed in a single transaction (`db.begin()` → `COMMIT`):

```
Updated 53790: 5 required_fees
Updated 53952: 7 required_fees
Verify 53790: stale=None req_fees=5 price=1234  ✓
Verify 53952: stale=None req_fees=7 price=2275  ✓
Transaction committed.
```

---

## 6. Regenerated Statement Totals

| Field | After G.5 | After G.5.1 | Streamline target | Delta |
|---|---|---|---|---|
| `total_revenue` | $4,759 | **$6,459** | $6,209 | **$250 over** |
| `total_commission` (35%) | $1,665.65 | $2,260.65 | $2,173.15 | $87.50 over |
| `closing_balance` | $3,093.35 | $4,198.35 | $4,035.85 | $162.50 over |

---

## ⚠️ STOPPING — $250 Over-Classification Requires Gary's Decision

The $250 overage traces exactly to **"Pet Fee" ($250) on reservation 53952** being classified as commissionable by the "pet" keyword.

### How it happened

Fix 2 added the keyword `"pet"` to the commissionable patterns. For 53952:
- "Pet Fee" ($250): matches "pet" → added as commissionable BucketedItem ⚠️
- "Pet Cleaning Fee" ($75): matches "pet" BUT `_is_pass_through` catches "clean" → correctly excluded

The `_is_pass_through` function has `if "clean" in name_lower: return True` which saved the Pet Cleaning Fee from over-classification. But there's no equivalent guard for "Pet Fee" alone.

### What Streamline says

Streamline's gross rent for 53952 = **$3,275** = base rent $2,275 + APF $1,000. The Pet Fee ($250) is NOT in Streamline's commissionable gross.

Per the parity verification: if CROG includes the Pet Fee, gross = $3,525 ≠ $3,275.

### Gary's decision needed

**Should the Pet Fee be commissionable (taken from the commission base)?**

Option A — **Pass-through** (matches Streamline): Remove "pet" from the commissionable keyword list. "Pet Fee" passes through entirely to the owner, no commission taken. CROG gross = $6,209, matching Streamline.

Option B — **Commissionable** (management earns commission on pet surcharges): Keep "pet" in the list. CROG gross = $6,459. This DOES NOT match Streamline's $6,209 — would be a deliberate policy divergence from Streamline.

Option C — **Narrow the keyword**: Keep "pet" but add "pet cleaning" to pass-through explicitly (it's already handled by the "clean" guard). No change needed for cleaning. But also add a guard for pure "pet fee" entries. For example: if name is exactly "Pet Fee" → pass-through. Requires a new explicit rule.

**Recommendation:** Option A (remove "pet" keyword). Streamline's model is the ground truth for March 2026. The Pet Fee appears to be a pure pass-through at Fallen Timber Lodge. This is the minimal change that achieves parity.

### Effect of Option A

If "pet" removed from commissionable keywords:
- 53765: $1,250 ✓ (no pet fees)
- 53790: $1,684 ✓ (no pet fees)
- 53952: $2,275 + $1,000 = $3,275 ✓ (Pet Fee becomes pass-through)
- Total: **$6,209 ✓** — exact parity with Streamline

---

## 7. Rollback Plan

To revert the JSONB to stale state (if fresh data causes issues):
```bash
psql "$PSQL" << 'SQL'
UPDATE reservations SET
  streamline_financial_detail = '{"data": {}, "_stale": true, "_circuit_open": true}'::jsonb,
  updated_at = NOW()
WHERE confirmation_code IN ('53790', '53952');
SQL
```

---

## 8. Confidence Rating

| Item | Confidence |
|---|---|
| Streamline API returned fresh data | **CERTAIN** — no stale flag, full required_fees |
| JSONB update committed cleanly | **CERTAIN** — verified in-transaction |
| APF correctly captured ($450 + $1,000) | **CERTAIN** |
| Pet Cleaning Fee correctly excluded ($75) | **CERTAIN** — _is_pass_through "clean" guard |
| Pet Fee over-classification ($250) | **CERTAIN** — traced to "pet" keyword |
| Option A achieves exact parity | **CERTAIN** — $1,250 + $1,684 + $3,275 = $6,209 |

---

## 9. Recommended Response

Reply **"remove pet from commissionable"** to authorize the 1-line keyword removal in `statement_computation.py` and regenerate Gary's statement to $6,209 parity.

Reply **"keep pet commissionable"** to accept the $250 divergence from Streamline and document the policy difference.

No code changes staged in this phase pending Gary's decision.

---

## Resolution (Policy Decision — Gary 2026-04-15)

**Gary confirmed:** Remove "pet" from `_COMMISSIONABLE_PATTERNS`. Streamline is the source of truth; CROG's job is parity, not opinion.

**Policy:** Pet fees are pass-through at Fallen Timber Lodge per Streamline's March 2026 statement. The "pet" keyword was removed from `backend/services/statement_computation.py` `_COMMISSIONABLE_PATTERNS`. The `_is_pass_through` function's existing "clean" guard already correctly handled "Pet Cleaning Fee" — only "Pet Fee" was over-classified.

### Final statement totals (post-fix, OBP 25680)

| Field | Value | Streamline target | Delta |
|---|---|---|---|
| `total_revenue` | **$6,209.00** | $6,209.00 | **$0.00 ✓** |
| `total_commission` (35%) | **$2,173.15** | $2,173.15 | **$0.00 ✓** |
| `closing_balance` | **$4,035.85** | $4,035.85 | **$0.00 ✓** |

### Per-reservation breakdown

| Confirmation | Base rent | Additional Party Fee | Pet Fee | CROG gross | Streamline gross | Δ |
|---|---|---|---|---|---|---|
| 53765 | $950 | $300 | — | $1,250 | $1,250 | $0 ✓ |
| 53790 | $1,234 | $450 | — | $1,684 | $1,684 | $0 ✓ |
| 53952 | $2,275 | $1,000 | $250 (pass-through) | $3,275 | $3,275 | $0 ✓ |
| **Total** | **$4,459** | **$1,750** | — | **$6,209** | **$6,209** | **$0 ✓** |

### PDF for visual review
```
File: backend/scripts/g51_gary_march2026_final.pdf (5.1 KB, 2 pages)
Gitignored: YES — not committed (private financial data)
```

### Code change (1 line removed)
```diff
# backend/services/statement_computation.py
 _COMMISSIONABLE_PATTERNS = (
-    "pet",
     "additional person",
     "additional party",
     "extra guest",
     "extra person",
 )
```
