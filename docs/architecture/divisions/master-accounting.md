# Division: Master Accounting (Sector 03 — "Fortress Comptroller")

Owner: Gary Mitchell Knight (operator); Comptroller-persona AI agent
Status: **active**
Last updated: 2026-04-26

## Purpose

Enterprise-wide financial oversight. Mirrors QuickBooks Online into Postgres double-entry ledger. Tracks cash flow across all divisions, monitors gold/BTC positions, optimizes tax strategy. Sovereign immutable ledger is the single source of truth for trust posting; Stripe webhooks drive every payment entry (Streamline metadata is reconciliation-only, never authoritative).

Per CONSTITUTION.md Article III: trust ledger writes go through `backend/services/trust_ledger.py` posting functions. Direct ORM/raw-SQL inserts are forbidden — they break the SHA-256 hash chain and trigger CRITICAL BREACH alerts from the daily auditor.

## Key data stores

### Postgres

- `public.trust_transactions` — append-only payment events, hash-chained
- `public.trust_ledger_entries` — append-only double-entry rows
- `division_a.transactions`, `division_a.audit_log` — division-scoped transaction log (per atlas)
- `division_a.chart_of_accounts`, `division_a.general_ledger`, `division_a.journal_entries` — accounting ledger
- `hedge_fund.market_signals`, `hedge_fund.watchlist`, `hedge_fund.active_strategies` — investment tracking
- `public.market_intel`, `public.revenue_ledger`, `public.finance_invoices` — analytics + reporting
- `public.trust_balance` — derived view of trust positions

Both `trust_transactions` and `trust_ledger_entries` carry triggers `trg_immutable_*` that raise on UPDATE/DELETE.

### Qdrant

- `email_embeddings` filtered by `division=HEDGE_FUND` — financial correspondence

### NAS

- `/mnt/fortress_nas/Financial_Ledger/` — financial documents, statements, tax records

## Key services consumed

- Stripe (`payment_intent.succeeded`, `invoice.paid` webhooks) — the **only** authoritative trigger for trust ledger writes
- QuickBooks Online — chart of accounts mirror via `accounting/import_qbo_coa.py`
- Plaid — banking API via `division_a_holding/plaid_client.py`
- [Captain](../shared/captain-email-intake.md) — for inbound finance correspondence
- [Council](../shared/council-deliberation.md) — for tax strategy + financial deliberation

## Key services exposed

- `backend/services/trust_ledger.py` — `post_checkout_trust_entry`, `post_invoice_clearing_entry`, `post_variance_trust_entry`
- `backend/workers/hermes_daily_auditor.py` — daily integrity audit of the hash chain
- `src/cfo_extractor.py` — financial document extraction
- `src/quant_revenue.py` — revenue analytics
- `src/market_sentinel.py`, `src/market_watcher.py` — market signal extraction
- `accounting/` — QBO bridge

## Webhook idempotency contract

All webhook handlers MUST catch `sqlalchemy.exc.IntegrityError` on the `uq_trust_transactions_streamline_event_id` UNIQUE constraint and return **HTTP 200 OK** — duplicates are success, not error. Re-raising IntegrityError from an idempotent posting path is a violation.

## Open questions for operator

- Are there division-scoped audit views for non-finance staff (e.g. CROG ops needs to see revenue but not trust internals)?
- Are tax-treatment rules per-division formalized in code, or operator-managed in QBO?
- Does the daily auditor's CRITICAL BREACH alert route to a paging system (PagerDuty / Slack / SMS), or stderr only?

## Cross-references

- Posting service: `backend/services/trust_ledger.py`
- Daily auditor: `backend/workers/hermes_daily_auditor.py`
- Atlas entry: [`../../../fortress_atlas.yaml`](../../../fortress_atlas.yaml) Sector 03
- CONSTITUTION.md Article III — sovereign ledger immutability
- Cross-division flow: [`../cross-division/email-to-accounting.md`](../cross-division/email-to-accounting.md)

Last updated: 2026-04-26
