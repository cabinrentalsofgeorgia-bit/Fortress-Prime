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

## Post-Execution Alerts

Use `GET /api/financial/signals/promotion/{id}/alerts` with a candidate parameter set, dry-run acceptance id, or execution id. The alert view is `hedge_fund.v_signal_promotion_post_execution_alerts`.

The alert layer is read-only and derives from post-execution monitoring rows:

- `SIGNAL_DECAY`
- `WHIPSAW_AFTER_PROMOTION`
- `DRIFT`
- `STALE_EXECUTION_MONITORING`
- `ROLLBACK_RECOMMENDATION`

Alerts are operator warnings only. They do not call rollback functions, write or delete `market_signals`, create acceptance records, create execution records, change trades, or change signal state. Rollback recommendation alerts mean “review this audited execution,” not “rollback automatically.”

## Alert Acknowledgements

Use `POST /api/financial/signals/promotion-alerts/{alert_id}/acknowledgements` to record operator review notes for an active post-execution alert. The acknowledgement write is audit-only:

- it only accepts an `alert_id`, never ticker/date
- it requires an active `signal_operator` or `signal_admin` token
- it snapshots the alert evidence at acknowledgement time
- it writes only to `hedge_fund.signal_promotion_alert_acknowledgements`
- it does not call rollback, update trades, or change signal rows

Acknowledgement status values are `ACKNOWLEDGED`, `WATCHING`, and `NO_ACTION_NEEDED`. The alerts endpoint surfaces latest acknowledgement status and whether review is still open.

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
