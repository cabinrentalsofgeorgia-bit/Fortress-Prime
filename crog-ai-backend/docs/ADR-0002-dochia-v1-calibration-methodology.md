# ADR-0002 — Dochia v1 Calibration Methodology

**Status:** PROPOSED
**Date:** 2026-04-27
**Supersedes:** none
**Superseded by:** none
**Related:** ADR-0001 (sprint schema + cross-source dedup amendment + Dochia v1 architecture amendment)

---

## Context

ADR-0001 (Amendment 2026-04-27) locked the architecture for Dochia v1: daily-only with weights `(monthly=0, weekly=0, daily=70, momentum=30)` and parameter set name `dochia_v1_daily_only`. That amendment defines *what to build*. This ADR defines *how to fit it*.

Calibration corpus: 24,204 daily Trade Triangle observations spanning 2024-03-18 → 2026-04-21, sourced from Phase 1 (NAS) + Phase 3 (IMAP) intake. Each observation has a known ticker, alert timestamp, triangle color (green/red), and INO-published score (-100 to +100).

Without this ADR, calibration code would fit to a moving target — the methodology has to be locked before any optimization runs, otherwise "good fit" can be redefined post-hoc to match whatever the code produced.

---

## Decisions

### D1 — Calibration target: replicate INO's published score

For each observation, the target value is the INO-published `score` field (-100 to +100). The fitted model's daily-tier and momentum-tier component scores must combine via the locked weights `(70, 30)` to reproduce that score.

**Rationale:** "Strangler Fig" means replicate before iterating. Forward-return fitting is a different model architecture (profitability prediction, not signal replica) and belongs to a future enhancement layer. Alert-occurrence classification is a sub-problem that doesn't yield a score regression. Fitting to INO's score is the contract that defines whether v1 successfully replaced Market Club's signal output.

**Tradeoff accepted:** the fitted model inherits whatever biases or quirks exist in INO's algorithm. If INO's scoring formula is suboptimal in some regime, Dochia v1 inherits that suboptimality. Future v2+ can deviate; v1 explicitly does not.

### D2 — EOD bar source: Polygon.io paid tier

Calibration requires daily OHLCV bars for every ticker in the corpus to compute Donchian channel position and MACD divergence as inputs.

**Source:** Polygon.io Stocks Starter tier ($30/month or current rate at time of purchase). Provides 5-year historical EOD coverage, 100k+ US-listed tickers, REST API.

**Coverage requirement:** for every (ticker, alert_date) in the corpus, EOD bars must exist for at least the prior 63 trading days (matches the longest Donchian lookback in the architecture). Tickers without sufficient history get filtered out of the calibration corpus with explicit logging.

**Rationale:** Yahoo Finance free tier has documented gaps and silent data quality issues; calibration sensitivity to bad bars is high. Polygon's $30/mo cost is trivial against the strategic value of a correctly-fitted signal. Deferring EOD entirely (Option C) eliminates price-derived features and degenerates the model into a pattern-only classifier — not the architecture we agreed to.

**Population target:** ~700 unique tickers (the union across the 24,204-row corpus). Estimated ~520k EOD bar rows pulled at one-time backfill, then ongoing daily updates.

### D3 — Train/test split: ticker-level 80/20

- **Population:** all unique tickers in the calibration corpus (~700)
- **Random assignment:** ~560 tickers (80%) → train, ~140 tickers (20%) → test
- **Per-observation routing:** every observation for a train ticker goes to train; every observation for a test ticker goes to test
- **Zero same-ticker overlap** between train and test sets

**Random seed must be fixed** in calibration code and recorded in the calibration report so the split is reproducible across re-runs.

**Rationale:** Ticker-level splitting eliminates rolling-window feature leakage entirely. Same-ticker observations on adjacent days share mechanical correlation through the 63-day Donchian and 26-day MACD windows. Chronological splits leak this correlation across the train/test boundary. Ticker-level eliminates the boundary entirely — test predictions are on tickers the model has never seen during training, so test accuracy is an honest estimate of generalization.

**Tradeoff accepted — does not test temporal regime stability:** Ticker-level split spans the full 2024-2026 window in both train AND test sets. A chronological split would test "model trained on regime A, applied to regime B"; ticker-level does not. If 2026's market regime is meaningfully different from 2024-2025, ticker-level test accuracy may overstate production accuracy because the test set includes 2024 and 2025 era data the model has effectively seen the distribution of (via OTHER tickers in train).

Mitigation: the corpus spans 25 months including multiple regime sub-windows. Training data already includes regime variability; ticker-level test holds out the *tickers*, not the *time periods*, so the model is exposed to regime shifts during training.

**Tradeoff accepted — train set composition variance:** A random draw could place high-frequency tickers (AAPL, MSFT, SPY-like names with hundreds of historical alerts each) into the test set, shrinking the train corpus disproportionately. Calibration code MUST report train/test row counts and surface composition imbalance for review before fitting begins. If imbalance is severe (test set takes >25% of total observations OR train set drops below 15,000 rows), the random seed is rejected and re-drawn.

**Tradeoff accepted — does not match production deployment scenario of "score every ticker":** In production, Dochia v1 will likely score every ticker the user wants to watch, including ones already in training. Ticker-level test answers "does the model generalize to NEW tickers?" — the harder question and the more honest metric, but not literally identical to deployment use.

**Future-version note:** A future v2 calibration may add a chronological hold-out as a secondary metric to test temporal regime stability. v1 explicitly does not, to keep sprint scope minimal. The ticker-level result is the gating metric for v1 production deployment.

---

## Components to fit

The schema's locked weights `(0, 0, 70, 30)` operate on per-component scores, each in range -100..100. v1 calibration fits two component scoring functions:

### Daily-tier component (weight 70)

**Input features (computed from EOD bars):**
- 63-day Donchian channel position: where does the alert-day close sit relative to the 63-day rolling high/low?
- 15-day Donchian channel position: same for 15-day window
- 3-day Donchian channel position: same for 3-day window
- Breakout direction: whether the close set a new N-day high (green-signaling) or low (red-signaling) for any of the three windows

**Target:** Component score in -100..100 such that `70 * daily_score + 30 * momentum_score ≈ ino_published_score`

### Momentum-tier component (weight 30)

**Input features:**
- MACD line value (12/26 EMA difference) on alert day
- MACD signal line value (9-period EMA of MACD line)
- MACD histogram (line minus signal)
- MACD divergence direction (positive/negative)

**Target:** same composite-fit constraint

---

## Fitting method

**Deferred to calibration sprint implementation ADR.**

This ADR locks the *targets and data*, not the fit procedure. The implementation sprint will choose between linear regression, gradient boosting, constrained optimization, or other methods based on what fits the architecture. That decision lives in a separate ADR-0003 when the sprint starts.

The constraint that any chosen method must satisfy: the resulting component scores are deterministic functions of EOD-bar-derived features, are bounded -100..100, and produce a composite via the locked weighted sum that approximates INO's published score with documented accuracy on the held-out ticker-level test set.

---

## Success metrics

The v1 calibration is considered successful and ready to advance to Layer 2 if all the following hold on the held-out ticker-level test set (the ~140 unseen tickers):

1. **Mean absolute error on composite score:** ≤ 15 points (out of 200-point range). I.e. when INO publishes -85, the model predicts somewhere in -100 to -70.
2. **Sign agreement (color match):** ≥ 90% of test observations produce a composite score with the same sign as INO (green stays green, red stays red).
3. **Threshold agreement:** for the historically meaningful threshold transitions (≥90 → 70-75 trailing-stop signal per the original Market Club spec), the model produces threshold-crossing events with ≥85% precision and ≥80% recall against INO's events.

Metrics 1-2 evaluate continuous-score fidelity. Metric 3 evaluates operational fidelity — the actual trading-decision points that production code will key off.

If metrics fail, calibration sprint produces a failure report with component-level diagnosis (is daily-tier fitting badly? momentum?) and ADR-0003 documents the next iteration's methodology change. v1 does NOT ship to production until all three metrics pass.

---

## Out of scope for v1

- Multi-timeframe (weekly/monthly) calibration — locked to v2 in ADR-0001 amendment 2026-04-27
- Volatility-adaptive Donchian lookbacks — Layer 2 enhancement
- Volume confirmation or regime filters — Layer 3 enhancement
- LLM sentiment overlay — Layer 4 enhancement
- Correlation-aware position sizing — Layer 5 enhancement
- Forward-return profitability evaluation — separate sprint after v1 is in production, not before
- Chronological hold-out as secondary metric — possible v2 addition

Each of these has its own future ADR. v1 keeps the smallest possible scope: replicate INO's daily score using EOD bars on held-out tickers.

---

## Calibration sprint deliverables (preview)

When the sprint executes:

- New module `app/calibration/` with feature extraction, fitting code, and evaluation utilities
- New script `scripts/calibrate_dochia_v1.py` that runs the full pipeline (extract features → fit → evaluate → write parameters)
- Population of `hedge_fund.eod_bars` with Polygon.io backfill
- Fitted parameters written to `hedge_fund.scoring_parameters` as `dochia_v1_daily_only` row with calibration metadata
- Calibration report at `docs/dochia-v1-calibration-report.md` including test set metrics on held-out ticker set, composition-balance check results, random seed used for split, and visualizations
- ADR-0003 documenting the chosen fit method (regression / gradient boosting / constrained optimization / etc.) and rationale

These deliverables are committed across one or more PRs at sprint end. None of them ship in this ADR.

---

## Decisions log

| Date       | Decision                                               | By  |
|------------|--------------------------------------------------------|-----|
| 2026-04-27 | D1 — Fit to INO's published score                      | GK  |
| 2026-04-27 | D2 — Polygon.io paid tier as EOD source                | GK  |
| 2026-04-27 | D3 — Ticker-level 80/20 split (zero-leakage)           | GK  |

---

## Open items deferred to ADR-0003

- Specific fit method (linear / gradient boosting / etc.)
- Per-component score normalization (linear scaling / sigmoid / clipped)
- Hyperparameter selection process
- Polygon.io API rate limit handling and incremental update strategy
- EOD bar quality validation (corporate actions, splits, ticker changes)
- Failure mode handling when ticker has insufficient prior history
- Random seed selection process for ticker split (and re-draw policy if composition imbalance threshold is exceeded)
