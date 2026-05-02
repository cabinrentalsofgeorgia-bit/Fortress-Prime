# MarketClub / Dochia Build Plan

**Status:** Active build track
**Date:** 2026-05-02
**Scope:** CROG-AI backend, Financial Division hedge-fund signal app

## Thesis

MarketClub / INO.com discontinued on 2026-04-20. Fortress should replace it with
Dochia: a sovereign signal engine and command-center app that preserves the useful
Trade Triangle doctrine while improving auditability, backtesting, explainability,
and portfolio risk controls.

## Product Shape

Dochia should answer five questions for every ticker:

1. What is the daily, weekly, and monthly signal state?
2. Why did the signal fire?
3. Do the timeframes agree or conflict?
4. What happened historically when this setup appeared?
5. What does this do to portfolio exposure and risk?

## Signal Doctrine

| Layer | Lookback | Meaning |
|---|---:|---|
| Daily | 3 sessions | Short-term timing and stop/re-entry behavior |
| Weekly | 15 sessions | Intermediate trend timing |
| Monthly | 63 sessions | Long-term trend anchor |

The historical MarketClub corpus contains daily observations only. Weekly and
monthly states are generated from EOD bars and must be labeled as
Dochia-derived until independent truth data exists.

## Build Phases

### Phase 1 — Deterministic Signal Engine

- Pure Python module for channel-break daily/weekly/monthly state. Complete.
- Unit tests against synthetic bars. Complete.
- No database writes.
- Output includes explainability fields: prior channel high/low, close, fired
  state, reason, and current carried state.

### Phase 2 — Database Scorer

- Read `hedge_fund.eod_bars`. Complete.
- Compute daily/weekly/monthly states idempotently. Complete.
- Populate `hedge_fund.signal_scores`. First current batch complete.
- Create `signal_transitions` for new bullish/bearish breakouts and reversals.
  First recent transition batch complete.

### Phase 3 — Calibration

- Compare generated daily state and composite score against
  `hedge_fund.market_club_observations`.
- Produce ticker-level holdout metrics.
- Do not promote if deterministic baseline is not understood.
- Add ML only when it beats the baseline out of sample.

### Phase 4 — Production Contract

- Promote approved signals into `hedge_fund.market_signals`.
- Preserve lineage fields: source pipeline, parameter set, model version,
  computed_at, and explanation payload.

### Phase 5 — App Surface

- Scanner: recent daily/weekly/monthly triangles. Backend API and first
  Command Center UI route complete.
- Symbol page: chart with triangle overlays and explanation drawer. Backend
  detail endpoint complete; chart overlay UI remains.
- Portfolio board: first signal-lane/watchlist context complete; true holdings
  exposure remains.
- Alert inbox: new signals, reversals, whipsaw warnings.
- Backtest lab: setup history and return distribution.
- Model health: data freshness, failed tickers, drift, calibration metrics.

## API Contract

Base app entrypoint: `app.main:app`

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | backend health check |
| `GET /api/financial/signals/latest` | scanner-ready latest signal rows |
| `GET /api/financial/signals/transitions` | recent signal-change alert feed |
| `GET /api/financial/signals/watchlist-candidates` | portfolio-lens lanes with legacy watchlist context |
| `GET /api/financial/signals/{ticker}` | symbol-level latest score plus recent transitions |

Useful query params:

- `latest`: `limit`, `ticker`, `min_score`, `max_score`
- `transitions`: `limit`, `ticker`, `transition_type`, `since`, `lookback_days`
- `watchlist-candidates`: `limit`
- `{ticker}`: `transition_limit`, `lookback_days`

## Operations

- `crog-ai-backend.service` runs `app.main:app` on `127.0.0.1:8026`.
- Unit file is tracked at `deploy/systemd/crog-ai-backend.service`.
- The service is enabled on spark-node-2 and restarts automatically.
- Command Center proxies `/api/financial/signals/*` to the local CROG-AI
  backend.
- Legacy Hedge Fund tables are read-only to `crog_ai_app` via
  `deploy/sql/marketclub_legacy_read_grants.sql`.
- Command Center production build is promoted through
  `crog-ai-frontend.service` on port 3005.

## Design Guardrails

- Evidence cockpit, not retail gamification.
- Default to sidelines on timeframe conflict.
- No live brokerage execution in v1.
- Every signal must be explainable from stored data.
- Every production score must be reproducible from a parameter set.

## 2026-05-02 Build Checkpoint

- Added deterministic Trade Triangle style signal engine with 3/15/63-session
  daily, weekly, and monthly channel-break logic.
- Added read-only preview and idempotent sync scripts for `signal_scores`.
- Added a freshness guard that defaults to current/fresh instruments only, with
  `--include-stale` available for deliberate historical backfills.
- Wrote 328 current `signal_scores` rows, all dated 2026-04-24.
- Added recent transition event replay and idempotent sync for
  `signal_transitions`.
- Wrote 1,005 recent transition rows from 2026-03-25 through 2026-04-24.
- Added FastAPI scanner, transition feed, and symbol detail endpoints.
- Added Command Center Financial / Hedge Fund route at
  `/financial/hedge-fund` with scanner, score distribution, alert feed, and
  symbol explainability panel.
- Added `watchlist-candidates` endpoint and UI Portfolio Lens lanes:
  bullish alignment, risk alignment, re-entry, and mixed timeframes. These lanes
  use fresh 2026-04-24 scores with February legacy watchlist/market-signal
  context where available.
- Added and enabled `crog-ai-backend.service` on spark-node-2.
- Promoted the Command Center production build and restarted
  `crog-ai-frontend.service`; `/financial/hedge-fund` is live through
  `https://crog-ai.com/financial/hedge-fund`.
- Verification passed: 16 backend tests, focused UI test, eslint, TypeScript,
  production build, and live BFF reads are clean on spark-2.

Next clean build step: add chart overlays and the daily-signal calibration
harness.
