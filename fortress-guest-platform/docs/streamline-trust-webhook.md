# Streamline inbound webhook (`POST /api/webhooks/streamline`)

## Product decision (trust ledger)

- **Stripe remains the source of truth for guest payment trust postings** (`post_checkout_trust_entry`, `post_invoice_clearing_entry`) via existing Stripe webhook handlers.
- **Streamline may or may not push** HTTP callbacks to Fortress. Many deployments only **pull** Streamline via the API; in that case this endpoint receives no traffic and the trust ledger is unchanged.
- When Streamline **does** push reservation or pricing payloads, this route **always** persists the raw JSON in `streamline_payload_vault` for audit and reconciliation (same purpose as outbound `StreamlineClient._vault_log`).

## Authentication

Implemented as **HMAC-SHA256** over the **raw request body**, hex digest in header **`X-Fortress-Signature`** (same pattern as `POST /api/webhooks/reservations`).

| Env var | Role |
|--------|------|
| `STREAMLINE_WEBHOOK_SECRET` | Optional dedicated secret for `/streamline`. |
| `RESERVATION_WEBHOOK_SECRET` | Used when `STREAMLINE_WEBHOOK_SECRET` is empty (shared HMAC with `/reservations`). |

If **both** are unset, HMAC is **not** enforced (development convenience; do not use in production without a secret).

`STREAMLINE_API_SECRET` is **not** used here: it is for Streamline API signing, not webhook verification.

## Optional trust variance

If Streamline (or a proxy) sends a structured variance adjustment, include a top-level object:

```json
{
  "event_type": "price_reconciliation",
  "reservation_id": "12345",
  "fortress_trust_variance": {
    "reservation_id": "12345",
    "amount_cents": 5000,
    "debit_account_name": "Streamline Variance",
    "credit_account_name": "Guest Receivable",
    "event_id": "streamline:webhook:unique-id"
  }
}
```

This calls `post_variance_trust_entry` (idempotent on `event_id`). Omit `fortress_trust_variance` to vault only.

## Verification

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/api/webhooks/streamline \
  -H "Content-Type: application/json" -d '{}'
# With secrets configured: 401 (missing signature). Without secrets: 200.

```
