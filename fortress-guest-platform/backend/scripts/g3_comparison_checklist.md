# G.3 Manual Comparison Checklist
**Purpose:** Gary compares the CROG-generated March 2026 statement PDF against the Streamline statement for the same period.

**CROG PDF:** `backend/scripts/g3_gary_march2026_draft.pdf` (NOT committed — private financial data)  
**Property:** Fallen Timber Lodge (Streamline unit 70209)  
**Owner:** Gary Knight (Streamline owner 146514)  
**Period:** March 1–31, 2026  
**Statement status:** pending_approval (draft — not yet approved or sent)

---

## ⚠️ Important Context Before Comparison

The CROG statement will show **$0.00 for all totals** because fortress_shadow currently has **zero reservations for Fallen Timber Lodge in March 2026**. fortress_shadow only has ~100 synced reservations (recent activity) while the full historical record lives in fortress_guest (2,665 reservations). The Streamline statement for March 2026 will show the real reservation data.

This comparison therefore has two purposes:
1. Verify the CROG PDF **structure, formatting, and owner/property data** is correct (even with zero amounts)
2. **Expose the reservation data gap** — the amounts will not match until fortress_shadow has the historical data

---

## Checklist

### Owner Information
| Item | Streamline | CROG PDF | Match? |
|---|---|---|---|
| Owner full name | Gary Knight | | ☐ |
| Owner email | gary@cabin-rentals-of-georgia.com | | ☐ |
| Mailing address line 1 | 570 Morgan Street NE (verify with Gary) | | ☐ |
| Mailing address city | Atlanta | | ☐ |
| Mailing address state | GA | | ☐ |
| Mailing address postal code | 30308 | | ☐ |
| Commission rate | 35% | | ☐ |

### Property Information
| Item | Streamline | CROG PDF | Match? |
|---|---|---|---|
| Property name | Fallen Timber Lodge | | ☐ |
| Property address | (from Streamline) | | ☐ |
| Streamline property ID | 70209 | | ☐ |

### Statement Period
| Item | Expected | CROG PDF | Match? |
|---|---|---|---|
| Period start | March 1, 2026 | | ☐ |
| Period end | March 31, 2026 | | ☐ |

### Financial Figures (expected to be $0 in CROG due to data gap)
| Item | Streamline March 2026 | CROG PDF | Match? | Note if gap |
|---|---|---|---|---|
| Opening balance | | $0.00 | — | CROG always starts at 0 for first period |
| Reservation count | | 0 | ✗ expected | Data gap — see context above |
| Total gross revenue | | $0.00 | ✗ expected | Data gap |
| Total commission (35%) | | $0.00 | ✗ expected | Data gap |
| Total charges/fees | | $0.00 | ✗ expected | Data gap |
| Net owner income | | $0.00 | ✗ expected | Data gap |
| Closing balance | | $0.00 | ✗ expected | Data gap |

### Reservation Line Items
| Item | Streamline | CROG PDF | Match? |
|---|---|---|---|
| Number of reservations in period | (from Streamline) | 0 | ✗ (data gap) |
| Each confirmation code present | N/A | N/A | — |
| Each check-in date correct | N/A | N/A | — |
| Each gross amount correct | N/A | N/A | — |
| Each commission amount correct | N/A | N/A | — |

### PDF Formatting and Branding
| Item | Expected | Actual | Pass? |
|---|---|---|---|
| PDF opens without error | yes | | ☐ |
| Cabin Rentals of Georgia branding/logo visible | yes | | ☐ |
| Owner name formatted correctly | "Gary Knight" | | ☐ |
| Property name formatted correctly | "Fallen Timber Lodge" | | ☐ |
| Period dates displayed correctly | "March 1 – March 31, 2026" or similar | | ☐ |
| Commission rate shown (35%) | yes | | ☐ |
| Opening balance shows $0.00 for first period | yes | | ☐ |
| "No reservations" or empty table when 0 reservations | yes | | ☐ |
| Page layout renders clearly | yes | | ☐ |
| Contact info / footer present | yes | | ☐ |

---

## Action Items After Comparison

### If PDF structure is correct (formatting, owner/property info matches):
- [ ] Confirm mailing address street is correct (570 Morgan Street NE)
- [ ] Document as "structure verified, amounts not comparable due to data gap"
- [ ] File issue: populate fortress_shadow with historical reservation data (G.4 scope)
- [ ] When data is available: re-generate and re-compare for the same March 2026 period

### If PDF structure has issues (wrong name, wrong address, formatting broken):
- [ ] Document each issue
- [ ] Fix in statement_pdf.py (backend service) — no OBP or OPA changes needed
- [ ] Re-generate PDF after fix
- [ ] Re-compare

### Data gap remediation options (Gary decision):
1. **Option A (preferred):** Sync fortress_shadow with historical Streamline reservations for all 14 active properties, going back to at least Jan 2026. This unblocks statement computation with real data.
2. **Option B:** Generate statements against fortress_guest instead of fortress_shadow — requires architectural change (two-DB model change).
3. **Option C:** Leave fortress_shadow as current-data-only; generate first "real" statement for April 2026 (when fortress_shadow will have the data).

---

## Notes / Gary's Findings
_(Gary fills this in during manual comparison)_

```
Date of comparison:
Streamline statement accessed at:
PDF structure verdict:
Financial figures verdict:
Issues found:
Decision on data gap remediation:
```
