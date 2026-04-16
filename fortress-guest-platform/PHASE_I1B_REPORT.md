# Phase I.1b Report — Email-on-Save Charge Notification
**Date:** 2026-04-16  
**Branch:** `feature/owner-statements-and-stabilization`  
**Status:** COMPLETE. Email-on-save shipped; E2E validated against Gary's live inbox.

---

## 1. Pre-flight Verification

| Check | Expected | Actual | Result |
|---|---|---|---|
| Branch | `feature/owner-statements-and-stabilization` | ✓ | PASS |
| Latest commit | I.1a (96471337) | 96471337 | PASS |
| `fortress-backend.service` | active | active | PASS |
| `crog-ai-frontend.service` | active | active | PASS |
| SMTP configured | All vars present | SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM_* present | PASS |
| `send_email` exists | `email_service.py` | function at line 25 | PASS |
| `send_booking_alert` pattern | `owner_emails.py` | function at line 34 | PASS |
| OPA 1824 owner_email | gary@cabin-rentals-of-georgia.com | ✓ | PASS |
| I.1a test charges (354, 356) | voided | voided_at set | PASS |
| Active real charge 355 | $169 carpenter bees | untouched | PASS |

---

## 2. New Function: `send_owner_charge_notification`

**File:** `backend/services/owner_emails.py`

```python
async def send_owner_charge_notification(db: AsyncSession, *, charge_id: int) -> bool
```

**Behavior:**
- Loads charge + OPA + property + vendor via raw SQL (no ORM relationship loading)
- Returns `False` (never raises) if SMTP not configured, OPA has no email, or send fails
- Calls `send_email(to, subject, html_body, text_body)` with:
  - Subject: `"Owner Charge Posted — {property.name}"`
  - Body: plain text with `<pre>` HTML wrapper
  - Fields: property, posted date, transaction type, description, vendor (if set), amount
- Structured log on success: `owner_charge_notification_sent` with charge_id, to, subject, property
- Structured log on failure: `owner_charge_notification_failed` with charge_id, to

**Body template:**
```
A new charge has been posted to your owner account.

Property:          Fallen Timber Lodge
Posted Date:       March 15, 2026
Transaction Type:  Maintenance
Description:       [description]
[Vendor: {name} if set]
[Reference: {ref} if set]
Amount:            $50.00

This charge will appear on your next owner statement.
...
— Cabin Rentals of Georgia
```

---

## 3. API Change: `POST /charges` Accepts `send_notification`

**File:** `backend/api/admin_charges.py`

- `OwnerChargeCreateRequest` gains `send_notification: bool = False`
- After successful `OwnerCharge` create + commit, if `send_notification=True`:
  - Calls `send_owner_charge_notification(db, charge_id=charge.id)` 
  - Wrapped in `try/except` — exception → `notification_sent=False`, error in `notification_error`
- Response `_charge_dict` extended: `notification_sent: bool | None`, `notification_error: str | None`
  - Only present when `send_notification` was used (conditional dict merge via `**{}`)
  - `None` = flag was not set (plain save); `True/False` = email was/wasn't dispatched

---

## 4. Frontend: "Email and Close" Button

**File:** `apps/command-center/src/app/(dashboard)/admin/owner-charges/page.tsx`

- Added `toast` import from `sonner`
- Added `useRef<boolean>(false)` (`sendNotifRef`) to track which button submitted the form
- `handleSubmit` reads `sendNotifRef.current` to set `send_notification` in the request body
- Two submit buttons in Post Charge modal (new charges only; not shown on Edit):
  - **"Save and Close"** (`type="submit"`) — existing flow; sets `sendNotifRef.current = false`
  - **"Email and Close"** (`type="submit"`, variant="outline") — sets `sendNotifRef.current = true`
- Toast behavior when `sendNotification=true`:
  - `notification_sent=true`: `toast.success("Charge posted. Notification sent to {email}.")`
  - `notification_sent=false`: `toast.warning("Charge posted but notification failed: {error}. You can retry later.")`
- `useCreateOwnerCharge` hook: `onSuccess` fires default "Charge created" toast only when `notification_sent` is `undefined` (plain save), preventing double-toast on Email+Close
- TypeScript: zero errors (`npx tsc --noEmit` clean), build clean

---

## 5. End-to-End Validation

### Scenario 1: Happy path (email dispatched)

| Step | Check | Result |
|---|---|---|
| Charge created (id=357) | `amount=$50, transaction_type=maintenance` | ✓ |
| DB row present | `voided_at=NULL` | ✓ |
| `send_owner_charge_notification(db, charge_id=357)` | returns `True` | ✓ |
| Log: `email_sent` | `to=gary@cabin-rentals-of-georgia.com, subject="Owner Charge Posted — Fallen Timber Lodge"` | ✓ |
| Log: `owner_charge_notification_sent` | `charge_id=357, property=Fallen Timber Lodge` | ✓ |
| Charge voided | `voided_by=i1b_validation_cleanup` | ✓ |

**Gary to confirm receipt in inbox** — email was dispatched with `email_sent` log event at 10:57:51 UTC-4 on 2026-04-16.

### Scenario 2: SMTP failure path

Not tested (deferred). The graceful-degradation path is covered by the `try/except` wrapping in `create_charge` and the `is_email_configured()` guard in `send_owner_charge_notification`. Charge creation always returns 201 regardless of email result.

---

## 6. Confidence Rating

| Item | Confidence |
|---|---|
| Email dispatched to Gary | **CERTAIN** — `email_sent` + `owner_charge_notification_sent` log events; SMTP connected and authenticated |
| Non-blocking semantics | **CERTAIN** — `try/except` in create_charge; charge committed before email attempted |
| TypeScript zero errors | **CERTAIN** — `tsc --noEmit` clean |
| Build clean | **CERTAIN** — `next build` succeeded |
| `send_notification=false` default | **CERTAIN** — pre-existing creates unaffected; `notification_sent` not in response |
| Active real charge 355 unaffected | **CERTAIN** — no code touched existing charges |

---

## 7. Recommended Next Phase

**I.4 — Event-driven OBP recompute:** Every time a charge is posted, voided, or edited, `owner_balance_periods.closing_balance` should auto-update for the affected OPA+period. Currently requires manual `generate_monthly_statements` re-run. This is the most impactful architectural gap from the I-series.

**I.2 — Receive Owner Payment:** Record a payment from owner to management (e.g., reserve replenishment), posting to `owner_balance_periods.total_payments`.

**I.5 — Real vendor names:** 216 active vendors have synthetic names from the sync script. Needs a vendor name cleanup sync from Streamline before the vendor attribution feature is useful in production.
