# MarketClub Hedge Fund Signals Rollback Drill Checklist

**Status:** operator-controlled rollback drill; no automatic rollback
**Allowed target:** `execution_id` only

## Purpose

Prove that a promoted Hedge Fund signal execution can be inspected and rolled back safely using only audited `market_signal_id` rows from that execution.

This checklist must be rehearsed on staging before release and reviewed before any production rollback.

## Hard Rules

- Rollback may only target `execution_id`.
- Never roll back by ticker, date, action, score, or parameter set.
- Rollback preview must only include audited IDs from `hedge_fund.signal_promotion_execution_rows`.
- Repeat rollback must be safe: either no-op or already-rolled-back state.
- Rollback must write audit/status.
- No unaudited `hedge_fund.market_signals` rows may be affected.

## Pre-Drill Inputs

Record:

- environment
- operator
- execution id
- dry-run acceptance id
- candidate parameter set
- inserted market signal IDs
- rollback markers
- pre-drill reconciliation status
- pre-drill rollback eligibility

## Read-Only Preview

```sql
SELECT
  execution_id,
  dry_run_acceptance_id,
  inserted_market_signal_ids,
  rollback_markers,
  audited_market_signal_ids,
  rollback_preview_market_signal_ids,
  rollback_preview_count,
  rollback_eligibility,
  rollback_eligible,
  already_rolled_back,
  rollback_status,
  rollback_attempted_at,
  rolled_back_at
FROM hedge_fund.v_signal_promotion_rollback_drill
WHERE execution_id = :execution_id;
```

Pass criteria:

- exactly one execution row
- `rollback_eligible = true`
- `rollback_preview_market_signal_ids` is a subset of `audited_market_signal_ids`
- preview count equals the intended audited live row count
- no ticker/date predicate is used

Hard stop if:

- no execution row exists
- preview includes a row not audited to this execution
- execution is already rolled back and operator expected active
- reconciliation has `ERROR`

## Authorized Rollback Action

Use the cockpit rollback control or the guarded API only after preview passes.

API path:

```text
POST /api/financial/signals/promotion-dry-run/executions/{execution_id}/rollback
Header: X-MarketClub-Operator-Token: <operator token>
Body: { "rollback_reason": "<human reason>" }
```

Do not include ticker/date fields. The backend must ignore or reject any attempt to target rollback outside the path `execution_id`.

## Post-Rollback Verification

```sql
SELECT *
FROM hedge_fund.v_signal_promotion_rollback_drill
WHERE execution_id = :execution_id;

SELECT *
FROM hedge_fund.v_signal_promotion_reconciliation
WHERE execution_id::TEXT = :execution_id;

SELECT *
FROM hedge_fund.v_signal_promotion_lifecycle_timeline
WHERE execution_id::TEXT = :execution_id
ORDER BY ts;
```

Pass criteria:

- rollback status is `rolled_back`
- `already_rolled_back = true`
- rollback preview count is `0`
- audited IDs are absent from live `market_signals`
- unaudited `market_signals` rows remain untouched
- lifecycle timeline includes `ROLLBACK_COMPLETED`
- reconciliation is `HEALTHY` or expected `WARNING`, not `ERROR`

## Repeat Rollback Test

Repeat the same rollback request with the same `execution_id`.

Expected:

- no duplicate deletes
- no unaudited deletes
- state remains `rolled_back`
- response is safe no-op or explicit already-rolled-back state

## Drill Sign-Off

Record:

- execution id
- operator
- preview count
- audited IDs
- rollback response timestamp
- repeated rollback result
- reconciliation result
- incident link if any check failed

Release is blocked if the drill cannot prove audited-ID-only rollback.
