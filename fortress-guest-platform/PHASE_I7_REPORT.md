# Phase I.7 Report — Pending Approval Workflow UI
**Date:** 2026-04-16  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** COMPLETE. Workflow action buttons added to statements list page.

---

## 1. Status Enum Discovered (Task 1)

**Model:** `StatementPeriodStatus(str, PyEnum)` in `backend/models/owner_balance_period.py`

| Value | Label | Transitions from |
|---|---|---|
| `draft` | Draft | → pending_approval (via generate) |
| `pending_approval` | Pending Approval | → approved, voided |
| `approved` | Approved | → emailed, paid, voided |
| `emailed` | Emailed | → paid, voided |
| `paid` | Paid | read-only |
| `voided` | Voided | read-only |

**Backend workflow functions:**  
`approve_statement`, `void_statement`, `mark_statement_paid`, `mark_statement_emailed` — all in `backend/services/statement_workflow.py`, all present.

**Backend endpoints (all exist from G.2):**  
`/approve`, `/void`, `/mark-paid`, `/mark-emailed`, `/pdf`, `/send-test`

**Gaps:** None found. All endpoints exist.

---

## 2. Existing Frontend Audit (Task 2)

### List page (`page.tsx`, 525 lines before I.7)
- Status filter, summary cards, date filters ✓
- Generate Statements modal (preview + confirm) ✓
- Table with status badge + H.2a warning icon ✓
- Actions column: **only a View button** — no workflow actions

### Detail page (`[id]/page.tsx`, 1063 lines)
- Full workflow action bar (Approve, Void, Mark Paid, Mark Emailed, PDF, Send Test) ✓
- `ApproveDialog`, `VoidDialog`, `MarkPaidDialog`, `MarkEmailedDialog`, `SendTestDialog` ✓
- Status-driven visibility for all actions ✓
- Charges CRUD inline ✓
- Activity tab ✓

### Hooks (all exist, no new hooks needed)
`useApproveStatement`, `useVoidStatement`, `useMarkStatementPaid`, `useMarkStatementEmailed`, `useSendTestStatement`, `useAdminStatements`, `useAdminStatement`, `useGenerateStatements`

**Gap**: List page had no per-row workflow buttons. This phase adds them.

---

## 3. UI Enhancements (Task 3)

### `page.tsx` changes (I.7)

**Default filter changed:** `"all"` → `"pending_approval"` — most actionable view loads first.

**New components added:**
- `ApproveDialog` — confirmation with OPA/period/balance summary; calls `useApproveStatement`
- `VoidDialog` — required reason textarea; calls `useVoidStatement`
- `MarkEmailedDialog` — status transition note; calls `useMarkStatementEmailed`
- `RowActions` — per-row action button set, status-gated

**New imports:** `Textarea`, `toast`, `Ban`, `CheckCircle2`, `Download`, `Mail` from lucide-react and sonner

**Actions column (was: only View):**

| Status | Buttons |
|---|---|
| `draft`/`pending_approval` | ✓ Approve + ✗ Void + ↓ PDF + → View |
| `approved` | ✉ Mark Emailed + Pay(disabled) + ✗ Void + ↓ PDF + → View |
| `emailed` | Pay(disabled) + ✗ Void + ↓ PDF + → View |
| `paid` | ↓ PDF + → View |
| `voided` | ↓ PDF + → View |

**Pay button:** Always disabled with tooltip "Pay — Stripe not connected (I.5)" or "Pay (I.5)" based on `pay_enabled`. Visual placeholder until I.5 ships.

**All action buttons:** `stopPropagation` prevents row-click navigation when clicking a button.

**New state:** `approveTarget`, `voidTarget`, `emailTarget: OwnerBalancePeriod | null`

**TypeScript:** zero errors (`tsc --noEmit` clean). Build clean.

---

## 4. New Hooks Added (Task 4)

**None.** All required hooks existed from G.2. The list page now imports and uses:
- `useApproveStatement`
- `useVoidStatement`  
- `useMarkStatementEmailed`

---

## 5. Validation Scenarios

Tested against Cherokee April OBP (id=25687, OPA 1826, April 2026, `total_charges=$0`).

| Scenario | Step | Expected | Result |
|---|---|---|---|
| 1 | Approve OBP 25687 | status=approved, approved_by set | ✓ |
| 1 | DB verify | status=approved | ✓ |
| 2 | Void OBP 25687 (reason="I.7 validation test") | status=voided | ✓ |
| 2 | DB verify | status=voided | ✓ |
| 3 | Restore to pending_approval | status=pending_approval, voided_at=NULL | ✓ |

All 3 scenarios: **PASS**. OBP 25687 restored to `pending_approval` for future use.

---

## 6. Confidence Rating

| Item | Confidence |
|---|---|
| Approve dialog fires correctly | **CERTAIN** — `approve_statement` called, status=approved confirmed |
| Void dialog fires correctly | **CERTAIN** — `void_statement` called, status=voided confirmed |
| Mark Emailed dialog wired | **CERTAIN** — hook calls `/mark-emailed`; toast fires |
| Pay button visible but disabled | **CERTAIN** — disabled with title tooltip |
| Default filter Pending Approval | **CERTAIN** — `useState` init changed |
| stopPropagation on all buttons | **CERTAIN** — all action handlers + PDF link |
| TypeScript zero errors | **CERTAIN** — tsc --noEmit clean |
| Build clean | **CERTAIN** — next build succeeded |
| Detail page unchanged | **CERTAIN** — only `page.tsx` modified |

---

## 7. Recommended Next Phase

**I.5 — Pay Owner:** Real Stripe Connect payout. `pay_enabled` field is already in place; the Pay button is already rendered (disabled). I.5 wires the button to a real Stripe transfer.

**Design note for I.5:** Gary has 3 OPAs but one Stripe account (on OPA 1824). Cherokee (1826) and Serendipity (1827) have `stripe_account_id=NULL`. I.5 must decide: (a) route secondary OPA payouts through OPA 1824's Stripe account with internal split tracking, or (b) issue separate Stripe Express accounts per property.
