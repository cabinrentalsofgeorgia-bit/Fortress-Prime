# Division: Market Club (replacement scaffolding)

Owner: TBD (requires operator input)
Status: **scaffolding** — code lives on Spark 2 as part of the Financial division during the temporary co-tenancy period; full spec blocked on operator answers
Spark allocation:
- **Current:** Spark 2 (control plane @ `100.80.122.100`) — temporary tenant of the monorepo until Spark 3 is provisioned
- **Target:** **Spark 3 (PLANNED)** — co-located with Master Accounting + `hedge_fund.*` schema migration as the unified Financial division
Last updated: 2026-04-26

## Purpose

This division replaces a legacy market-signal source operator-codenamed "Market Club" (the legacy source's exact identity is operator-confirmable; see open question 1). The replacement scoring engine produces `hedge_fund.market_signals` rows that downstream feed Master Accounting's investment-tracking subsystem and the broader Financial division.

Currently in scaffolding stage. Full spec depends on operator answers to the 6 questions below.

## Open questions for operator

The 6 specific questions blocking the full Market Club spec:

1. **What is being replaced?** Marriott Club / `MarriottClub.com` / a different vendor / an internal legacy script set? Concrete identity needed before scoping the replacement.
2. **What is Dochia and what role does it serve?** Surfaces in operator conversation but absent from the repo + atlas. Is it the new signal source, a scoring component, a vendor, an internal codename for the replacement, something else?
3. **What is the backup signal source?** When the primary Market Club replacement is unavailable (provisioning gap, vendor outage, data quality alarm), what's the fallback path? Is there a legacy `src/market_sentinel.py` / `src/market_watcher.py` continuity plan?
4. **When does Spark 3 get provisioned?** Concrete date (or quarter) needed for the cutover plan. Today the scaffolding lives on Spark 2 as a tenant; the move to Spark 3 is the architectural-decision-pending milestone (ADR-002).
5. **Which `fortress_db` / `fortress_prod` schemas migrate to Spark 3?** Candidate list:
   - `hedge_fund.market_signals` (definite)
   - `hedge_fund.watchlist` (definite)
   - `hedge_fund.active_strategies` (definite)
   - `hedge_fund.extraction_log` (likely)
   - `division_a.transactions` (open — depends on Master Accounting placement)
   - `division_a.chart_of_accounts`, `general_ledger`, `journal_entries` (open — same)
   - `public.trust_transactions`, `trust_ledger_entries` (open — control-plane co-location vs Financial-spark co-location)
   - `public.market_intel`, `revenue_ledger`, `finance_invoices` (open)
6. **What's the cutover plan from Spark 2 to Spark 3?** Step sequence, downtime budget, rollback path, dual-write window, verification checks. Today the scaffolding doesn't yet have a defined migration runbook because Spark 3 isn't provisioned.

## Stub-then-fill discipline

Per [`../README.md`](../README.md): when answers come in, fill the standard sections (Owner, Status, Key data stores, Key services consumed/exposed, Active workstreams) and remove this open-questions block. Don't fabricate facts in the meantime.

## Cross-references

- Parent division: [`financial.md`](financial.md) (Market Club is the replacement scoring engine inside Financial)
- Atlas Sector 04 (BLOOM — "Verses in Bloom" digital retail) — possibly related, possibly orthogonal; needs operator confirmation: [`../../../fortress_atlas.yaml`](../../../fortress_atlas.yaml)
- Architectural decision log: [`../cross-division/_architectural-decisions.md`](../cross-division/_architectural-decisions.md) ADR-002 (Spark 3 provisioning + cutover)
- Relevant legacy code (forward-deletion candidates after replacement ships): `src/market_sentinel.py`, `src/market_watcher.py`, `src/mining_rig_trader.py`

Last updated: 2026-04-26
