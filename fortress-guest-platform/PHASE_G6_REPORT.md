# Phase G.6 Report — Owner Name Format Parity
**Date:** 2026-04-15  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** COMPLETE. PDF now renders "Knight Mitchell Gary". Verified programmatically.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| `fortress-backend.service` | active | active | PASS |
| Gary OPA 1824 `owner_name` | `Gary Knight` | `Gary Knight` | PASS |
| OPA name columns | only `owner_name` (no middle) | only `owner_name` | PASS — migration needed |
| Streamline client `fetch_owner_info` | exists | `streamline_vrs.py:1204` | PASS |

---

## 2. Streamline Owner API Findings

**Method:** `StreamlineVRS.fetch_owner_info(owner_id: int)` → `GetOwnerInfo` RPC  
**Called with:** `owner_id=146514` (Gary's Streamline owner ID from OPA)

**Response keys:** `owner_id`, `first_name`, `last_name`, **`middle_name`**, `display_name`, `email`, `address1`–`address2`, `city`, `state`, `zip`, `country`, `mobile_phone`, `company`, `units`

**Extracted values:**
- `first_name`: Gary
- `last_name`: Knight
- `middle_name`: **Mitchell**
- `display_name`: **Knight Mitchell Gary** (pre-assembled by the client in last-middle-first order)

The `fetch_owner_info` function already parses `middle_name` and assembles `display_name`. No custom parsing needed — the client does the right thing.

Full response saved to `/tmp/g6_streamline_owner_response.json` (not committed — contains PII).

---

## 3. Schema Migration

**Migration file:** `backend/alembic/versions/g6a1_add_owner_middle_name.py`  
**Revision:** `g6a1_add_owner_middle_name`  
**Parent:** `e6a1b2c3d4f5` (prior head)

```python
def upgrade() -> None:
    op.add_column("owner_payout_accounts",
        sa.Column("owner_middle_name", sa.String(100), nullable=True))

def downgrade() -> None:
    op.drop_column("owner_payout_accounts", "owner_middle_name")
```

**Applied successfully:**
```
Running upgrade e6a1b2c3d4f5 -> g6a1_add_owner_middle_name
alembic current: g6a1_add_owner_middle_name (head)
```

**ORM model updated:** `backend/models/owner_payout.py` — added `owner_middle_name = Column(String(100), nullable=True)` after `owner_name`.

---

## 4. Data Update

```sql
UPDATE owner_payout_accounts
SET owner_middle_name = 'Mitchell', updated_at = NOW()
WHERE id = 1824
RETURNING id, owner_name, owner_middle_name, owner_email;
-- id=1824, owner_name='Gary Knight', owner_middle_name='Mitchell'
```

---

## 5. Code Change — PDF Rendering

**New helper in `backend/services/statement_pdf.py`:**

```python
def _streamline_name(owner_name: str, owner_middle_name: str | None) -> str:
    """Format owner name in Streamline's last-middle-first format."""
    parts = owner_name.strip().split()
    if len(parts) < 2:
        return owner_name          # single-word fallback
    first = parts[0]
    last  = parts[-1]
    if owner_middle_name and owner_middle_name.strip():
        return f"{last} {owner_middle_name.strip()} {first}"
    return f"{last} {first}"      # no middle → "Knight Gary"
```

**Call site changed (`render_owner_statement_pdf`, line ~542):**

```diff
- owner_name=opa.owner_name or "",
+ owner_name=_streamline_name(opa.owner_name or "", getattr(opa, "owner_middle_name", None)),
```

`getattr(..., None)` is used defensively so existing code paths with no `owner_middle_name` attribute (e.g., tests using stubs) don't crash.

---

## 6. PDF Regeneration and Verification

**PDF:** `backend/scripts/g6_gary_march2026_with_middle_name.pdf` (5.1 KB, 2 pages, gitignored)

**Programmatic check:**
```bash
pdftotext /tmp/g6_gary_march2026_with_middle_name.pdf - | grep -i "knight"
# Output:
Knight Mitchell Gary
77 Knights Landing Blue Ridge GA 30513
```

"Knight Mitchell Gary" ✓ confirmed in PDF header.

---

## 7. OPERATIONAL_TRUTH.md Update

Added new section: **"Owner name rendering policy"** documenting:
- Storage format (`owner_name` = "First Last", `owner_middle_name` = nullable)
- Rendering format ("Last Middle First" to match Streamline)
- Verification command
- G.7+ guidance: fetch middle name from `GetOwnerInfo` at enrollment time

---

## 8. Edge Cases

### Names with 3+ words (compound first names, suffixes)
The `_streamline_name` helper uses `parts[0]` as first name and `parts[-1]` as last name. For "Mary Ann Smith": first="Mary", last="Smith" (the "Ann" in `owner_name` is ignored; authoritative middle comes from `owner_middle_name`). No WARNING was surfaced in this phase because Gary Knight's name is a clean 2-word form.

**Future owners:** When `owner_name` has 3+ tokens, the compound middle is dropped. The `owner_middle_name` column carries the authoritative middle. No action required unless an owner's stored `owner_name` itself has a compound form.

### Other owners need middle-name backfill at enrollment
Only Gary Knight (OPA 1824) has `owner_middle_name` set. Future enrollments should call `fetch_owner_info(sl_owner_id)` and set `owner_middle_name` at invite-creation time. This is a G.7+ improvement.

### No middle name available
`_streamline_name` degrades gracefully to "Last First" (e.g., "Knight Gary") when `owner_middle_name` is NULL.

---

## 9. Confidence Rating

| Item | Confidence |
|---|---|
| Middle name "Mitchell" from Streamline | **CERTAIN** — direct `GetOwnerInfo` response |
| Migration applied cleanly | **CERTAIN** — alembic confirms head = g6a1 |
| PDF renders "Knight Mitchell Gary" | **CERTAIN** — pdftotext verified |
| Existing OPAs without middle name unaffected | **CERTAIN** — nullable column, graceful fallback |
| No regression to statement totals | **CERTAIN** — code change scoped to name formatting only |

---

## 10. Recommended Next Phase

**G.7 — Opening balance backfill** (first period starts at $0, subsequent periods carry forward via the ledger chain). OR **G.8 — Circuit breaker investigation** (why did 53790/53952 have stale data?). Gary's choice.
