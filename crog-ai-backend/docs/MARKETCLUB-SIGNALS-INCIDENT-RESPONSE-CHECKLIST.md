# MarketClub Hedge Fund Signals Incident Response Checklist

**Status:** operator checklist; no automated remediation
**Scope:** Hedge Fund Signals promotion, execution, rollback, audit, monitoring, alerts, and Signal Health Dashboard

## First 15 Minutes

1. Freeze new operator mutations.
   - Do not accept a dry-run.
   - Do not execute an accepted dry-run.
   - Do not roll back unless the incident commander explicitly authorizes a scoped `execution_id` rollback.
2. Capture the incident header.
   - timestamp
   - reporter
   - environment
   - candidate parameter set
   - affected `decision_id`, `acceptance_id`, `execution_id`, or `alert_id`
3. Confirm system reachability.
   - `GET /healthz`
   - Command Center `/financial/hedge-fund`
   - database connectivity as read-only observer
4. Pull read-only evidence.
   - Lifecycle Timeline
   - Reconciliation
   - Post-Execution Monitoring
   - Post-Execution Alerts
   - Signal Health Dashboard
5. Assign severity and owner.

## Severity Guide

`SEV1`:

- production `market_signals` rows were written without an execution audit
- rollback removed unaudited rows
- RLS/policy exposure permits unauthorized write
- execution path bypassed human decision, acceptance, or verification PASS

`SEV2`:

- cockpit cannot trace decision -> execution -> outcome -> rollback
- reconciliation reports `ERROR`
- post-execution monitoring is stale for an active execution after expected data availability
- operator mutation endpoint is unavailable after a valid operator request

`SEV3`:

- Signal Health Dashboard or alert panel fails read-only rendering
- cross-model divergence spikes but candidate lineage is still clean
- acknowledgement write fails but core audit trail remains intact

## Evidence Queries

Use exact IDs. Do not investigate by ticker/date alone.

```sql
SELECT *
FROM hedge_fund.v_signal_promotion_lifecycle_timeline
WHERE candidate_id = :candidate_id
   OR acceptance_id::TEXT = :acceptance_id
   OR execution_id::TEXT = :execution_id
ORDER BY ts;

SELECT *
FROM hedge_fund.v_signal_promotion_reconciliation
WHERE candidate_id = :candidate_id
   OR acceptance_id::TEXT = :acceptance_id
   OR execution_id::TEXT = :execution_id;

SELECT *
FROM hedge_fund.v_signal_promotion_post_execution_monitoring
WHERE execution_id::TEXT = :execution_id
ORDER BY ticker;

SELECT *
FROM hedge_fund.v_signal_promotion_post_execution_alerts
WHERE execution_id::TEXT = :execution_id
ORDER BY severity, alert_type, ticker;
```

## Decision Tree

Verification or lineage incident:

- Check `verify_promotion_dry_run` output and acceptance verification snapshot.
- If source lineage cannot be traced, block acceptance and continue shadow.
- If acceptance already exists without PASS snapshot, classify as `SEV2` or higher.

Execution incident:

- Check `signal_promotion_executions`.
- Check `signal_promotion_execution_rows`.
- Confirm inserted IDs match audited rows.
- If unaudited production rows exist, classify as `SEV1`.

Rollback incident:

- Check rollback audit by `execution_id`.
- Confirm removed IDs are exactly audited IDs.
- If rollback was requested by ticker/date, classify as invalid operator procedure.
- If unaudited rows were removed, classify as `SEV1`.

Monitoring or alert incident:

- Check whether `eod_bars` has expected outcome windows.
- Check Signal Health Dashboard awareness alerts.
- Treat rollback recommendations as warnings only until a human authorizes a scoped rollback.

RLS/policy incident:

- Run the RLS section of `deploy/sql/marketclub_release_hardening_verification.sql`.
- Compare grants to the last release sign-off.
- If `PUBLIC` or `crog_ai_app` gained unintended write privileges, freeze operator mutations.

## Communication Template

```text
Incident:
Severity:
Environment:
Candidate parameter set:
Decision/acceptance/execution/alert id:
What changed:
Current operator impact:
Production write impact:
Rollback impact:
Evidence links:
Next human action:
Automation status: none
```

## Recovery Rules

- Prefer read-only diagnosis first.
- Do not auto-heal.
- Do not backfill from the cockpit.
- Do not create fake decisions, acceptances, or executions.
- Do not roll back by ticker/date.
- Rollback is permitted only by `execution_id`, only against audited `market_signal_id` rows, and only after the rollback drill checklist passes.

## Closeout

Close the incident only when:

- root cause is documented
- audit/reconciliation status is understood
- RLS/policy state is verified
- any rollback action has a matching audit row
- operator impact and data impact are written down
- follow-up issue or PR is linked
