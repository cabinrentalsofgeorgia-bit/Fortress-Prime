# Division: Financial (Master Accounting + Market Club replacement)

Owner: Gary Mitchell Knight (operator); Comptroller-persona AI agent
Status: **active** (Master Accounting subsystem) | **scaffolding** (Market Club replacement, see [`market-club.md`](market-club.md))
Spark allocation:
- **Current:** Spark 2 (control plane @ `100.80.122.100`) — Master Accounting services + the Market Club replacement scaffolding live here as a tenant of the monorepo
- **Target (locked 2026-04-29 by ADR-004):** **Spark 2 (PERMANENT)** — Financial co-tenants on spark-2 with the control plane, CROG-VRS, Acquisitions, and Wealth. The previous "Spark 3 PLANNED" target under ADR-001 is canceled by ADR-004 ("App vs Inference Boundary"); Spark 3 leaves the app tier and joins the inference cluster (post-wipe).
Last updated: 2026-04-29

## Purpose

Enterprise-wide financial oversight + market intelligence. The Financial division has two cooperating subsystems:

1. **Master Accounting** — sovereign immutable trust ledger driven by Stripe webhooks; double-entry mirror of QuickBooks Online; daily hash-chain audit by Hermes. Stripe is the **only authoritative trigger** for ledger writes (per CONSTITUTION.md Article III). Streamline (PMS) supplies reconciliation metadata, never ledger truth.
2. **Market Club replacement** — scoring engine + signal pipeline replacing a legacy Market Club / Marriott Club source (operator confirmation required — see [`market-club.md`](market-club.md)). Currently at scaffolding stage; produces hedge_fund signals for the trust ledger's investment-tracking subsystem.

Per ADR-004 (LOCKED 2026-04-29): the "one spark per division" rule is retired except for Fortress Legal. Financial stays on **Spark 2 permanently** alongside CROG-VRS, Captain, Sentinel, the LiteLLM gateway, Acquisitions, and Wealth. Logical isolation (Postgres roles, schema separation, ARQ queue prefixes) replaces the planned physical isolation. ADR-001's earlier "migrate to Spark 3" plan is canceled — Spark 3 wipes and joins the inference cluster instead.

## Key data stores

### Postgres

Today (Spark 2 / `fortress_prod`):
- `public.trust_transactions` — append-only payment events, hash-chained
- `public.trust_ledger_entries` — append-only double-entry rows
- `division_a.transactions`, `division_a.audit_log` — division-scoped transaction log (per atlas)
- `division_a.chart_of_accounts`, `division_a.general_ledger`, `division_a.journal_entries` — accounting ledger
- `hedge_fund.market_signals`, `hedge_fund.watchlist`, `hedge_fund.active_strategies` — investment tracking; populated by Market Club scoring engine
- `public.market_intel`, `public.revenue_ledger`, `public.finance_invoices` — analytics + reporting
- `public.trust_balance` — derived view of trust positions

Both `trust_transactions` and `trust_ledger_entries` carry triggers `trg_immutable_*` that raise on UPDATE/DELETE.

**Spark 3 cutover canceled per ADR-004 (2026-04-29):** all Financial schemas (`division_a.*`, `hedge_fund.*`, `public.trust_*`, etc.) stay on Spark 2's Postgres permanently. Cross-spark Postgres-read complexity is no longer in scope. The `division_a` Postgres role is the per-division logical-isolation boundary; physical isolation (separate spark) is replaced by role + schema + queue separation.

### Qdrant

- `email_embeddings` filtered by `division=HEDGE_FUND` — financial correspondence

### NAS

- `/mnt/fortress_nas/Financial_Ledger/` — financial documents, statements, tax records

## Key services consumed

- Stripe webhooks (`payment_intent.succeeded`, `invoice.paid`) — the **only** authoritative trigger for trust ledger writes
- QuickBooks Online — chart of accounts mirror via `accounting/import_qbo_coa.py`
- Plaid — banking API via `division_a_holding/plaid_client.py`
- [Captain](../shared/captain-email-intake.md) — for inbound finance correspondence (live capture, division-tagged)
- [Council](../shared/council-deliberation.md) — for tax strategy + financial deliberation
- Market Club replacement scoring engine — produces `hedge_fund.market_signals` (see [`market-club.md`](market-club.md))

## Key services exposed

- `backend/services/trust_ledger.py` — `post_checkout_trust_entry`, `post_invoice_clearing_entry`, `post_variance_trust_entry`
- `backend/workers/hermes_daily_auditor.py` — daily integrity audit of the hash chain
- `src/cfo_extractor.py` — financial document extraction
- `src/quant_revenue.py` — revenue analytics
- `src/market_sentinel.py`, `src/market_watcher.py` — market signal extraction (legacy; the Market Club replacement is the forward path)
- `src/mining_rig_trader.py` — crypto trading hooks
- `accounting/` — QBO bridge

## Active workstreams

- **Master Accounting:** stable; production. Daily auditor running. Stripe webhook idempotency contract holding.
- **Market Club replacement:** scaffolding. See [`market-club.md`](market-club.md) for the 6 open questions blocking full spec.
- **Spark 3 provisioning:** PLANNED. Hardware not yet acquired. Migration plan blocked on provisioning timeline.

## Webhook idempotency contract

All webhook handlers MUST catch `sqlalchemy.exc.IntegrityError` on the `uq_trust_transactions_streamline_event_id` UNIQUE constraint and return **HTTP 200 OK** — duplicates are success, not error. Re-raising IntegrityError from an idempotent posting path is a violation.

## Open questions for operator

- **Spark 3 provisioning timeline** — when does the hardware land? The Market Club scaffolding cutover depends on this date.
- **Schema migration scope** — does `public.trust_*` migrate to Spark 3 (clean separation) or stay on Spark 2 (control-plane co-location)?
- **Cross-spark connectivity** — CROG-VRS (Spark 2) needs to read trust balances; what's the latency / consistency contract once Financial is on Spark 3?
- **Hermes auditor placement** — runs on Spark 2 today; moves with the ledger to Spark 3, or stays as cross-spark watcher?
- **Tax-treatment rules** — formalized in code today, or operator-managed in QBO?
- **CRITICAL BREACH alert routing** — paging system (PagerDuty / Slack / SMS), or stderr only? (Issue likely needs filing if undecided.)

## Cross-references

- Posting service: `backend/services/trust_ledger.py`
- Daily auditor: `backend/workers/hermes_daily_auditor.py`
- Atlas entry: [`../../../fortress_atlas.yaml`](../../../fortress_atlas.yaml) Sector 03 (COMP — Fortress Comptroller)
- CONSTITUTION.md Article III — sovereign ledger immutability
- Cross-division flow: [`../cross-division/email-to-financial.md`](../cross-division/email-to-financial.md)
- Architectural decisions: [`../cross-division/_architectural-decisions.md`](../cross-division/_architectural-decisions.md)
- Market Club replacement detail: [`market-club.md`](market-club.md)

Last updated: 2026-04-26
