# Operator Audit Playbook

This playbook describes the read-only audit surface for Hedge Fund Signals promotions.

## Lifecycle Timeline

Use `GET /api/financial/signals/promotion/{id}/timeline` with a candidate parameter set, decision id, dry-run acceptance id, or execution id. The timeline only emits events backed by audited rows:

- `DECISION_CREATED`
- `DRY_RUN_GENERATED`
- `VERIFICATION_RESULT`
- `ACCEPTANCE_CREATED`
- `EXECUTION_COMPLETED`
- `ROLLBACK_ELIGIBLE`
- `ROLLBACK_COMPLETED`

The timeline view is `hedge_fund.v_signal_promotion_lifecycle_timeline`.

## Reconciliation

Use `GET /api/financial/signals/promotion/{id}/reconciliation`. The reconciliation view is `hedge_fund.v_signal_promotion_reconciliation`.

The view checks:

- decision to acceptance linkage
- acceptance verification snapshot
- execution row count vs audited row count
- live write integrity for non-rolled-back executions
- audited ID integrity without ticker/date matching
- rollback integrity when rolled back
- idempotency for one execution per accepted dry-run

Acceptance rows are included even before execution. In that state, execution,
write, rollback, and idempotency checks are `NA`; a missing PASS verification
snapshot still returns `ERROR`.

Any failed invariant returns `ERROR`. Clean invariants with cross-model, high-churn, or whipsaw warnings return `WARNING`. Fully clean rows return `HEALTHY`.

## Post-Execution Monitoring

Use `GET /api/financial/signals/promotion/{id}/monitoring` with a candidate parameter set, dry-run acceptance id, or execution id. The monitoring view is `hedge_fund.v_signal_promotion_post_execution_monitoring`.

The monitor is read-only and evaluates only audited execution rows:

- 1-session, 5-session, and 20-session directional returns from `hedge_fund.eod_bars`
- whipsaw-after-promotion transitions from the candidate parameter set
- signal decay when candidate score or daily triangle no longer supports the promoted action
- drift between observed outcomes and the candidate expectation
- rollback recommendation warnings

Rollback recommendations are warnings only. The monitoring endpoint does not call rollback functions, delete `market_signals`, create rollback audit rows, or auto-heal promotion records.

## Snapshots

Acceptance records persist:

- verification status snapshot
- verification payload snapshot
- candidate set hash

Execution records persist:

- inserted `market_signals` ids hash

Rollback audit records persist:

- removed `market_signals` ids hash

These snapshots keep the audit stable if upstream scanner data changes later.

## Safety Rules

- Do not reconcile by ticker/date.
- Do not auto-heal or backfill from the cockpit.
- Use audited ids from `signal_promotion_execution_rows` for execution and rollback drilldowns.
- Treat `CROSS_MODEL_DIAGNOSTIC_ONLY` as a warning, not an execution failure.
