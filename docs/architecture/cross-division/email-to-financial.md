# Cross-Division Flow: Email → Financial

Last updated: 2026-04-26

## Summary

Email-driven financial events reach the Financial division (Master Accounting + Market Club replacement) **not** through email parsing but through Stripe webhooks for ledger writes, plus Captain capture for evidence trails and Market Club signal extraction.

The trust ledger source-of-truth is Stripe per CONSTITUTION.md Article III. Email captures land in `email_archive` for evidence; Stripe webhook events drive the immutable ledger; Market Club's scoring engine reads tagged email correspondence (`division=HEDGE_FUND`) for signal extraction.

Pattern reference: this flow follows the same shape established by **PR #225 (case-aware IMAP email backfill, Fortress Legal)** — Captain handles live capture, a separate division-scoped backfill script handles historical pulls. The Financial division will eventually need its own historical-backfill script (analogue of `email_backfill_legal.py`) once the Spark 3 cutover is complete.

## Path

```
[ Inbox emails ]              [ Captain ]              [ Financial Division ]
   │                              │                            │
   ├─ Stripe receipt    ──┬──► tag division=HEDGE_FUND   ───►  evidence trail
   ├─ Plaid alert         │      │                              (email_archive)
   ├─ QBO sync mail       │      │
   ├─ Bank statement      │      │
   └─ Vendor invoice      │      │
                           │      │
                           │      └─►  llm_training_captures
                           │           (Captain capture stream)
                           │
                           │  (NO automatic ledger write from email)
                           │
[ Stripe webhooks ]   ─────┴──►  trust_ledger.post_*()  ─────►  trust_transactions
   │                                  │                          trust_ledger_entries
   ├─ payment_intent.succeeded        │                          (immutable, hash-chained)
   ├─ invoice.paid                    │
   └─ ...                             └─►  hermes daily auditor
                                            (CRITICAL BREACH alert
                                             on hash chain divergence)
```

## Trigger

- **Email side (Captain):** every inbound message that touches finance domains; tagged `division=HEDGE_FUND` for division-routed retrieval. **No ledger writes.**
- **Stripe webhooks:** `payment_intent.succeeded`, `invoice.paid`, etc. The **only** authoritative trigger for trust ledger writes.

## Steps

1. Stripe sends webhook to FastAPI endpoint
2. Handler verifies Stripe signature
3. Calls `trust_ledger.post_checkout_trust_entry()` or sibling posting function
4. Posting function: writes append-only `trust_transactions` + matching `trust_ledger_entries` rows; computes SHA-256 hash chained to previous row
5. **Idempotency:** UNIQUE `(streamline_event_id)` constraint catches duplicates → handler catches `IntegrityError` and returns HTTP 200 (success), per CONSTITUTION
6. Hermes daily auditor reads the hash chain end-to-end at 00:00 UTC; any divergence triggers CRITICAL BREACH alert

## Failure modes

| Failure | Detection | Recovery |
|---|---|---|
| Webhook signature invalid | Stripe SDK raises | reject with 401 |
| Duplicate event | `IntegrityError` on `uq_trust_transactions_streamline_event_id` | catch + return 200; never re-raise |
| Hash chain divergence | hermes auditor scan | CRITICAL BREACH alert; operator investigates; never auto-repair |
| Direct ORM/raw-SQL insert into `trust_*` | DB triggers raise | non-recoverable from script; trigger fires before persist |
| Email-only signal (no Stripe match) | reconciliation report shows variance | log as variance; do not auto-write ledger entries from email |

## Authoritative source-of-truth

- **Stripe** for payment events
- **`trust_transactions` + `trust_ledger_entries`** for ledger state
- **CONSTITUTION.md Article III** for the immutability doctrine
- Email is **evidence**, not ledger

## Cross-references

- Source: [`../shared/captain-email-intake.md`](../shared/captain-email-intake.md)
- Target division: [`../divisions/financial.md`](../divisions/financial.md) (Master Accounting + Market Club replacement)
- Pattern reference: PR #225 (case-aware IMAP email backfill, Fortress Legal) — same shape, different division
- Posting service: `backend/services/trust_ledger.py`
- Daily auditor: `backend/workers/hermes_daily_auditor.py`
- Market Club replacement: [`../divisions/market-club.md`](../divisions/market-club.md)
- Architectural decisions: [`_architectural-decisions.md`](_architectural-decisions.md) ADR-001 (Spark per division), ADR-002 (Captain placement)
- CONSTITUTION.md Article III — sovereign ledger immutability

Last updated: 2026-04-26
