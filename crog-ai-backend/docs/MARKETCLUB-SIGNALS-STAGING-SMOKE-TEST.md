# MarketClub Hedge Fund Signals Staging Smoke Test

**Status:** final read-only staging smoke before release
**Mutation rule:** do not create decisions, acceptances, executions, acknowledgements, or rollbacks during this smoke unless the release owner explicitly starts a separate rollback drill.

## Smoke Inputs

Record before starting:

- staging backend URL:
- staging cockpit URL:
- database host/name:
- release PR:
- release commit:
- Alembic head:
- candidate parameter set: `dochia_v0_2_range_daily`
- production parameter set: `dochia_v0_estimated`

## Backend Health

```bash
curl -fsS "$STAGING_BACKEND_URL/healthz"
```

Pass:

- response is HTTP 200
- no stack trace
- no secret values in response

## Read-Only API Smoke

```bash
curl -fsS "$STAGING_BACKEND_URL/api/financial/signals/latest?limit=5"
curl -fsS "$STAGING_BACKEND_URL/api/financial/signals/promotion-gate/daily?candidate_parameter_set=dochia_v0_2_range_daily&top_tickers=3"
curl -fsS "$STAGING_BACKEND_URL/api/financial/signals/promotion-dry-run/verification?candidate_parameter_set=dochia_v0_2_range_daily&production_parameter_set=dochia_v0_estimated&limit=25"
curl -fsS "$STAGING_BACKEND_URL/api/financial/signals/promotion-dry-run/executions?candidate_parameter_set=dochia_v0_2_range_daily&limit=3"
curl -fsS "$STAGING_BACKEND_URL/api/financial/signals/promotion-dry-run/executions/rollback-drill?candidate_parameter_set=dochia_v0_2_range_daily&limit=3"
curl -fsS "$STAGING_BACKEND_URL/api/financial/signals/health-dashboard?candidate_parameter_set=dochia_v0_2_range_daily&production_parameter_set=dochia_v0_estimated"
```

Pass:

- all calls return HTTP 200
- verification returns `PASS`, `FAIL`, or `INCONCLUSIVE` explicitly
- health dashboard returns active promotions, at-risk signals, divergence, outcome summary, and awareness alerts fields
- no POST requests are made
- no `market_signals` row count changes during the smoke

## Cockpit Smoke

Open staging Command Center:

```text
/financial/hedge-fund
```

Verify panels render:

- Portfolio Lens
- Calibration Baseline
- Promotion Gate
- Shadow Review
- Signal Health Dashboard
- Promotion Dry-Run
- Dry-Run Verification Gate
- Lifecycle Timeline
- Reconciliation
- Post-Execution Monitoring
- Post-Execution Alerts
- Execution Records
- Rollback Drill

Required operator checks:

- acceptance button is disabled unless verification is `PASS`
- execution action only appears for accepted dry-runs that are not executed
- rollback action only appears when `rollback_eligible = true`
- Signal Health Dashboard alerts are non-blocking and have no automatic action
- any rollback recommendation is phrased as operator review only

## Hosted DB Verification

Run:

```bash
psql "$DATABASE_URL" \
  -v ON_ERROR_STOP=1 \
  -f deploy/sql/marketclub_release_hardening_verification.sql
```

Pass:

- required objects exist
- RLS and grants match expectations
- no duplicate execution idempotency rows
- no unaudited rollback target is implied

## Evidence Table

| Check | Result | Evidence |
|---|---|---|
| backend health |  |  |
| read-only API smoke |  |  |
| cockpit panel smoke |  |  |
| DB migration head |  |  |
| RLS/policy verification |  |  |
| rollback drill preview |  |  |
| signal health dashboard |  |  |
| no mutation during smoke |  |  |

## Release Blockers

Block release if:

- any required panel fails to render
- any read-only endpoint returns 5xx
- verification status is missing or ambiguous
- RLS/policy verification fails
- migration head differs from expected release head
- any smoke step writes production rows
- operator cannot trace decision -> execution -> outcome -> rollback
