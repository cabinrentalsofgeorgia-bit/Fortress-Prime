# ADR: Phase 7 — Sovereign Ledger Immutability

**Status:** Accepted  
**Date:** 2026-04-04  
**Context:** Financial-grade trust accounting for guest funds; tamper-evidence at the database kernel; Stripe as source of truth for payments.

This record documents the **Phase 7 Sovereign Ledger hardening**: Postgres-level immutability, SHA-256 hash chaining, webhook-driven idempotent postings, and continuous Hermes verification.

---

## 1. The Postgres Armor

`UPDATE` and `DELETE` on ledger tables are **physically forbidden** at the PostgreSQL kernel.

- **Function:** `prevent_mutation()` — PL/pgSQL trigger function that raises an exception on any row mutation attempt.
- **Migration:** `backend/alembic/versions/g9a8b7c6d5e4_harden_sovereign_ledger_immutability.py`
- **Triggers (BEFORE UPDATE OR DELETE):**
  - `trg_immutable_trust_transactions` on `trust_transactions`
  - `trg_immutable_trust_ledger_entries` on `trust_ledger_entries`
  - `trg_immutable_streamline_payload_vault` on `streamline_payload_vault`

Any ORM or raw SQL that attempts to modify or remove rows in these tables receives a database error; the application layer cannot bypass this without superuser DDL (which is out of scope for runtime code).

**Design implication:** The ledger is **append-only**. Corrections are modeled as **new** offsetting transactions, never in-place edits.

---

## 2. The Cryptographic Chain

Each `TrustTransaction` row carries:

| Column               | Role |
|----------------------|------|
| `signature`          | 64-character hex SHA-256 of the chain payload for this row. |
| `previous_signature` | The prior row’s `signature` in chain order, or `NULL` at genesis. |

**Signing** happens in `backend/services/trust_ledger.py` in `_sign_transaction()`, invoked only on **insert** paths inside `_add_trust_transaction_idempotent()` (updates to existing rows are blocked by triggers).

The **exact payload** concatenation before hashing:

```text
{previous_chain_signature}|{streamline_event_id}|{transaction_uuid}|{timestamp_iso8601}
```

- `previous_chain_signature` is the **latest** non-null `signature` by `timestamp DESC` (single-row query), or the literal string **`GENESIS`** when no prior signed row exists.
- `timestamp` uses the transaction’s `timestamp` field (timezone-aware ISO format from `datetime.isoformat()`).

The digest is:

```text
signature = SHA256(utf8(payload)).hexdigest()
```

**Verification:** `verify_hash_chain()` in `backend/workers/hermes_daily_auditor.py` loads all rows with non-null `signature`, orders by `timestamp ASC`, `id ASC`, and recomputes each hash; any mismatch yields `status: "broken"` and optional Nemo escalation.

---

## 3. The Webhooks

**Stripe (source of truth for guest funds)**  
- Router: `backend/api/stripe_webhooks.py` (mounted under `/api/webhooks`).  
- Signature verification via `settings.stripe_webhook_secret` / `StripePayments.handle_webhook()`.  
- Typical paths into the trust ledger:
  - `payment_intent.succeeded` (storefront checkout metadata) → `post_checkout_trust_entry(...)` — idempotent key `stripe:{payment_intent_id}` style via `streamline_event_id`.
  - `invoice.paid` (financial approval flow) → `post_invoice_clearing_entry(...)`.

**Streamline (audit + optional variance)**  
- `POST /api/webhooks/streamline` in `backend/api/reservation_webhooks.py`.  
- HMAC via `STREAMLINE_WEBHOOK_SECRET` or fallback `RESERVATION_WEBHOOK_SECRET`.  
- Raw JSON persisted to **`StreamlinePayloadVault`** for immutable audit.  
- Optional structured block `fortress_trust_variance` can invoke `post_variance_trust_entry(...)` when all required fields are present.

**Idempotency**  
All trust postings go through `_add_trust_transaction_idempotent()` in `trust_ledger.py`, which uses the unique constraint on `streamline_event_id` (`uq_trust_transactions_streamline_event_id`). Duplicate webhook deliveries return the existing `TrustTransaction`; handlers **must** respond **HTTP 200** so Stripe and Streamline do not retry indefinitely.

---

## 4. The Hermes Sentry

**Daily hash-chain audit + parity work**  
- Module: `backend/workers/hermes_daily_auditor.py`.  
- `run_daily_audit()` opens its own DB session, audits active reservations against Streamline where applicable, and calls **`verify_hash_chain(db)`** to validate the full signed chain.  
- **`hermes_daily_auditor_loop()`** is started from the FastAPI **`lifespan`** in `backend/main.py` via `asyncio.create_task`. It sleeps until **00:00 UTC** each day, then runs `run_daily_audit()`, then repeats.

**Operational visibility**  
- Structured logs: `hermes_continuous_auditor_scheduled`, `hermes_auditor_sleeping_until_midnight`, `hermes_daily_audit_finished`.  
- Staff UI: **NeMo Command Center** — Next.js route `/nemo-command-center` (Command Center app) backed by `GET /api/trust-ledger/command-center` (`backend/api/trust_ledger_command_center.py`), showing hash-chain status and recent `TrustTransaction` rows.

---

## References

| Artifact | Path |
|----------|------|
| Trust ledger service | `backend/services/trust_ledger.py` |
| Stripe webhooks | `backend/api/stripe_webhooks.py` |
| Reservation + Streamline inbound webhook | `backend/api/reservation_webhooks.py` |
| Hermes auditor | `backend/workers/hermes_daily_auditor.py` |
| Command Center API | `backend/api/trust_ledger_command_center.py` |
| Immutability migration | `backend/alembic/versions/g9a8b7c6d5e4_harden_sovereign_ledger_immutability.py` |
| Streamline webhook auth doc | `docs/streamline-trust-webhook.md` |
