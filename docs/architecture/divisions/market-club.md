# Division: Market Club (replacement scaffolding)

Owner: TBD (requires operator input)
Status: **scaffolding** — code lives on Spark 2 as part of the Financial division during the temporary co-tenancy period; full spec blocked on operator answers
Spark allocation:
- **Current:** Spark 2 (control plane @ `100.80.122.100`) — tenant of the monorepo, co-tenant with Master Accounting + CROG-VRS + control plane
- **Target (locked 2026-04-29 by ADR-004):** **Spark 2 (PERMANENT)** — Market Club replacement stays on spark-2 with the rest of Financial. The previous "Spark 3 PLANNED" target under ADR-001 is canceled by ADR-004; Spark 3 wipes and joins the inference cluster instead.
Last updated: 2026-04-29

## Purpose

This division replaces a legacy market-signal source operator-codenamed "Market Club" (the legacy source's exact identity is operator-confirmable; see open question 1). The replacement scoring engine produces `hedge_fund.market_signals` rows that downstream feed Master Accounting's investment-tracking subsystem and the broader Financial division.

Currently in scaffolding stage. Full spec depends on operator answers to the 6 questions below.

## Open questions for operator

The 6 specific questions blocking the full Market Club spec:

1. **What is being replaced?** Marriott Club / `MarriottClub.com` / a different vendor / an internal legacy script set? Concrete identity needed before scoping the replacement.
2. **What is Dochia and what role does it serve?** Surfaces in operator conversation but absent from the repo + atlas. Is it the new signal source, a scoring component, a vendor, an internal codename for the replacement, something else?
3. **What is the backup signal source?** When the primary Market Club replacement is unavailable (provisioning gap, vendor outage, data quality alarm), what's the fallback path? Is there a legacy `src/market_sentinel.py` / `src/market_watcher.py` continuity plan?
4. ~~**When does Spark 3 get provisioned?**~~ **Closed 2026-04-29 by ADR-004:** Spark 3 wipes and joins the inference cluster instead. Market Club scaffolding stays on Spark 2 permanently.
5. ~~**Which `fortress_db` / `fortress_prod` schemas migrate to Spark 3?**~~ **Closed 2026-04-29 by ADR-004:** no schema migration. All Financial schemas stay on Spark 2 — `hedge_fund.*`, `division_a.*`, `public.trust_*`, `public.market_intel`, `revenue_ledger`, `finance_invoices` — under the existing logical-isolation contract (Postgres roles + schema separation).
6. ~~**What's the cutover plan from Spark 2 to Spark 3?**~~ **Closed 2026-04-29 by ADR-004:** no cutover. Market Club replacement scaffolding's permanent home is Spark 2.

## Stub-then-fill discipline

Per [`../README.md`](../README.md): when answers come in, fill the standard sections (Owner, Status, Key data stores, Key services consumed/exposed, Active workstreams) and remove this open-questions block. Don't fabricate facts in the meantime.

## Cross-references

- Parent division: [`financial.md`](financial.md) (Market Club is the replacement scoring engine inside Financial)
- Atlas Sector 04 (BLOOM — "Verses in Bloom" digital retail) — possibly related, possibly orthogonal; needs operator confirmation: [`../../../fortress_atlas.yaml`](../../../fortress_atlas.yaml)
- Architectural decision log: [`../cross-division/_architectural-decisions.md`](../cross-division/_architectural-decisions.md) ADR-002 (Spark 3 provisioning + cutover)
- Relevant legacy code (forward-deletion candidates after replacement ships): `src/market_sentinel.py`, `src/market_watcher.py`, `src/mining_rig_trader.py`

Last updated: 2026-04-26
