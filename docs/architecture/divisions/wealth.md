# Division: Wealth

Owner: TBD (requires operator input)
Status: **planned, requires operator input**
Last updated: 2026-04-26

## Purpose

Unknown to the architecture-foundation drafter. Signals of existence:

- A `wealth` tmux session created 2026-04-20 (active Claude Code instance)
- A git worktree at `/home/admin/fortress-worktrees/Fortress-Prime-wealth` on a `wealth/main` branch
- `fortress_atlas.yaml` has no "Wealth" sector (closest is Sector 03 COMP — Fortress Comptroller — for finance, but that's a separate division mapped in `master-accounting.md`)

## Open questions for operator

1. **What does Wealth track?** Personal net-worth aggregation, family-office accounting, hedge-fund / portfolio management, estate planning, something else?
2. **How does it differ from `master-accounting`?** Master Accounting is enterprise-finance (Stripe webhooks, immutable ledger, QBO mirror). Is Wealth personal-finance-of-Gary-Knight? Family trust? Investment allocations?
3. **Why a separate worktree on `wealth/main` branch?** Is this a long-running parallel branch with its own ship cadence, or experimental?
4. **What does the `wealth` tmux session do today?** A peek shows an empty Claude Code prompt — was it set up for an upcoming task or actively used?
5. **Data stores** — distinct from `division_a` / `hedge_fund` schemas, or shared?
6. **Privacy boundary** — does Wealth contain Gary's personal/family financial data that should NOT cross-link with corporate-finance / public-storefront divisions?
7. **Integrations** — banks, brokerages, custodians, crypto exchanges, real-estate appraisers?
8. **Is Sector "WEALTH" missing from `fortress_atlas.yaml`** because it predates the atlas, or because it's intentionally not in the routing config?

## Stub-then-fill discipline

When answers come in, fill the standard sections and remove this open-questions block.

## Cross-references

- tmux session: `wealth` (created 2026-04-20)
- Worktree: `/home/admin/fortress-worktrees/Fortress-Prime-wealth` on branch `wealth/main`
- Possibly-related: [`master-accounting.md`](master-accounting.md) (Sector 03 / Fortress Comptroller)

Last updated: 2026-04-26
