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
  detail endpoint and first chart overlay UI complete.
- Portfolio board: first signal-lane/watchlist context complete; true holdings
  exposure remains.
- Alert inbox: new signals, reversals, whipsaw warnings.
- Backtest lab: setup history and return distribution.
- Model health: daily calibration baseline complete; freshness, failed-ticker,
  and drift views remain.

## API Contract

Base app entrypoint: `app.main:app`

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | backend health check |
| `GET /api/financial/signals/latest` | scanner-ready latest signal rows |
| `GET /api/financial/signals/transitions` | recent signal-change alert feed |
| `GET /api/financial/signals/watchlist-candidates` | portfolio-lens lanes with legacy watchlist context |
| `GET /api/financial/signals/calibration/daily` | daily MarketClub truth calibration metrics |
| `GET /api/financial/signals/{ticker}/chart` | EOD bars, rolling channels, and triangle overlay events |
| `GET /api/financial/signals/{ticker}` | symbol-level latest score plus recent transitions |

Useful query params:

- `latest`: `limit`, `ticker`, `min_score`, `max_score`, optional
  `parameter_set`
- `transitions`: `limit`, `ticker`, `transition_type`, `since`, `lookback_days`,
  optional `parameter_set`
- `watchlist-candidates`: `limit`, optional `parameter_set`
- `calibration/daily`: `since`, `until`, `ticker`, `parameter_set`, `top_tickers`
- `{ticker}/chart`: `sessions`, `as_of`
- `{ticker}`: `transition_limit`, `lookback_days`, optional `parameter_set`

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
- Added a read-only daily calibration harness and endpoint. Baseline against
  24,204 MarketClub daily observations: 91.44% coverage, 62.05% daily color
  accuracy on covered observations, score MAE 43.94.
- Refined calibration to separate carried-state agreement from alert-event
  agreement. Exact same-day daily alert match is 40.67%; ±3-day alert match is
  52.54%; 12,952 covered observations have no generated event on the same day.
- Added a read-only daily parameter sweep harness. Best research candidate is
  the 3-session intraday range trigger: exact alert F1 improves from 44.59% to
  76.64%, exact recall from 40.67% to 91.93%, precision is 65.71%, ±3-day
  recall is 95.21%, and carried-state agreement is 94.91%. Production scoring
  remains on the close-break baseline until out-of-sample validation.
- Added a read-only candidate validation report and corrected sweep precision
  to count distinct generated events matched. Chronological holdout after
  2025-09-25 is stronger than train: candidate F1 83.18% vs 46.26% baseline,
  exact recall 90.73%, precision 76.78%, and carried-state agreement 95.06%.
  Every covered quarter from 2024-Q2 through 2026-Q2 improves over baseline.
- Wired the validated daily range trigger as a selectable engine mode and
  registered non-production parameter set `dochia_v0_2_range_daily`. Dry-run
  previews remain read-only: 328 latest candidate score rows, 1,624 recent
  candidate transition rows since 2026-03-25 versus 1,005 baseline transition
  rows. Candidate lane comparison over 328 fresh tickers keeps bullish
  alignment at 129 and risk alignment at 47, changes 61 daily states/scores,
  moves re-entry from 164 to 145, and mixed timeframes from 202 to 203.
- Persisted v0.2 candidate scores/transitions under the non-production
  parameter set: 328 `signal_scores` rows and 1,624 `signal_transitions` rows.
  Added internal `parameter_set` selectors for scanner, transition feed, symbol
  detail, Portfolio Lens, and chart-overlay reads. Defaults still use
  production only.
- Added the internal Command Center parameter-set toggle on the Hedge Fund page.
  The cockpit defaults to Production and can switch scanner, transition feed,
  symbol detail, Portfolio Lens, and chart overlays to v0.2 Range.
- Surfaced the calibration baseline in the Hedge Fund UI.
- Added chart-data endpoint and UI chart overlay with close, daily/weekly
  channel bands, and generated triangle event markers.
- Added v0.2 chart-overlay parity: the chart endpoint accepts `parameter_set`
  and switches daily event markers from close-break production mode to
  range-trigger v0.2 candidate mode.
- Added a read-only promotion-review harness that combines persisted top-lane
  churn, recent whipsaw/transition pressure, and chart-level candidate-only
  daily events before any production flip.
- First promotion-review run is tracked at
  `docs/reports/dochia-v0-2-promotion-review-2026-05-03.md`. Decision: do not
  promote v0.2 yet. Re-entry lane churn is 66.7%, mixed-timeframe churn is
  52.9%, top whipsaw tickers show 8-9 candidate transitions in the 30-day
  window, and reviewed chart overlays add up to 29 candidate-only daily events
  on some symbols.
- Added a read-only v0.3 guardrail research harness for the range trigger. It
  sweeps minimum intraday break buffers, same-direction close confirmation, and
  post-event debounce windows against the MarketClub daily alert corpus before
  creating another non-production parameter set.
- First v0.3 guardrail report is tracked at
  `docs/reports/dochia-v0-3-guardrail-research-2026-05-03.md`. Decision: do
  not promote or parameterize these simple filters yet. Raw v0.2 range remains
  the strongest F1 candidate at 76.64%. The best simple reductions cut events
  by 15-27%, but exact F1 falls to roughly 56-60%, below the default quality
  bar.
- Added ATR-normalized buffers and trailing per-symbol adaptive cooldowns to
  the same read-only research harness. Second report is tracked at
  `docs/reports/dochia-v0-3-atr-cooldown-research-2026-05-03.md`. Decision:
  do not persist this grid as a parameter set. A 14-session ATR buffer at
  0.025 keeps F1 at 74.40% but cuts only 2.23% of events. The best adaptive
  cooldown row cuts 21.48% of events but drops F1 to 56.22%.
- Added a return-outcome and ticker whipsaw-cluster review layer. Report is
  tracked at `docs/reports/dochia-v0-3-return-outcome-review-2026-05-03.md`.
  Directional forward returns are flat for both production close and v0.2 raw
  range: v0.2 5-session win rate is 50.33% with +0.01% average directional
  return. The worst v0.2 whipsaw clusters are concentrated in MOD, ISRG, MRVL,
  DLR, and HD.
- Added ticker-cluster cooldown/exclusion research with a chronological
  holdout. Reports are tracked at
  `docs/reports/dochia-v0-3-ticker-cluster-review-2026-05-03.md` and
  `docs/reports/dochia-v0-3-ticker-cluster-holdout-2026-05-03.md`. Full-period
  top-15 exclusion is promising: 5.11% fewer events, 74.98% F1, and +0.05%
  average 5-session directional return. The holdout learns clusters before
  2025-09-25 and evaluates after; it does not clear the default gate, with
  4.74% event reduction, 78.16% F1, and -0.04% average 5-session directional
  return. Do not persist this candidate yet.
- Added a rolling, date-safe whipsaw-risk suppressor and review script. Reports
  are tracked at
  `docs/reports/dochia-v0-3-rolling-whipsaw-review-2026-05-03.md` and
  `docs/reports/dochia-v0-3-rolling-whipsaw-holdout-2026-05-03.md`. The
  suppressor only uses prior raw whipsaws before cooling down a ticker, but no
  candidate preserves at least 95% of raw v0.2 F1. Full-period high-reduction
  rows collapse exact F1 into the 6.57%-14.07% range, and holdout rows with
  95%+ event reduction stay below 7.41% F1. Do not persist this as a filter;
  surface whipsaw risk as evidence in the app.
- Added and enabled `crog-ai-backend.service` on spark-node-2.
- Promoted the Command Center production build and restarted
  `crog-ai-frontend.service`; `/financial/hedge-fund` is live through
  `https://crog-ai.com/financial/hedge-fund`.
- Latest verification passed: 28 backend tests, ruff, backend health, focused UI
  tests, focused UI lint, TypeScript, production Command Center build, service
  status, and live backend/BFF reads for both production and v0.2 candidate
  selectors. `/financial/hedge-fund` returns 200 after frontend restart.

Next clean build step: add a user-facing Whipsaw Risk / Backtest panel to the
Hedge Fund cockpit so noisy names are explainable without suppressing validated
daily range signals.
