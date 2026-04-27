# ADR-0003 — Dochia v1 Fit Method Specifics

**Status:** PROPOSED
**Date:** 2026-04-27
**Supersedes:** none
**Superseded by:** none
**Related:** ADR-0001 (sprint schema + amendments), ADR-0002 (calibration methodology)

---

## Context

ADR-0002 locked the calibration sprint contract: target (replicate INO's published score), data source (Polygon.io paid tier), train/test split (ticker-level 80/20). It explicitly deferred fit method specifics to a separate ADR — this one — to be authored at sprint kickoff.

This ADR locks the implementation specifics for the calibration sprint so that fitting code has no remaining ambiguity. After this merges, sprint can produce calibration output without further architectural decisions.

---

## Decisions

### D1 — Fit method: gradient boosting (LightGBM)

Fit per-component score functions using LightGBM gradient-boosted decision trees. Two independent regressors:

- `daily_score_model` — predicts daily-tier score (-100..100) from Donchian features
- `momentum_score_model` — predicts momentum-tier score (-100..100) from MACD features

Composite is computed deterministically as `70 * daily_score + 30 * momentum_score` per the ADR-0001 amendment. Compared against INO's published score for evaluation.

**Library choice — LightGBM over XGBoost:** Slightly faster training on this corpus size (~20k rows, 7 features per component model), better handling of categorical breakout-direction feature, smaller artifact size when serialized for parameter storage.

**Rationale:** Gradient boosting handles the unknown nonlinearity of INO's actual scoring formula without requiring us to guess functional form. Decision trees naturally bracket Donchian channel positions (e.g. "if D63 position > 0.85 AND breakout_direction = up THEN ...") which matches how Donchian-based scoring intuitively works. Linear regression was rejected because it assumes additive feature effects that almost certainly don't hold for Donchian/MACD interactions. Constrained optimization was rejected because it requires guessing INO's parametric form. Two-stage hybrid was rejected as scope creep for v1.

**Tradeoff accepted — interpretability:** Gradient boosting models are opaque. When v1 produces a score, the explanation "feature 3 had high SHAP value" is less actionable than "coefficient β₂ = 0.4." This is acceptable for v1 because we're replicating an opaque external system (INO); interpretability becomes important only when we deviate from INO in v2+. Calibration report will include feature importance ranking + SHAP plots for the most-impactful features.

### D2 — Per-component score normalization: linear scaling

Map raw model output to [-100, 100] via linear scaling:
`score = 100 * (raw_pred - midpoint) / half_range`
where midpoint and half_range are derived from training-set predictions.

**Rationale:** Simplest method. Preserves rank ordering of predictions. Treats the full prediction distribution uniformly rather than saturating extremes (sigmoid) or losing information at boundaries (clipping).

**Tradeoff flagged — distribution squashing:** If the raw model occasionally outputs extreme values (e.g. 250 or -180 due to unconstrained boosting output), linear scaling shrinks the WHOLE distribution to compensate. Concretely: this could cause the threshold-crossing precision metric (≥90 → 70-75) in ADR-0002 to underperform because squashed predictions may not cross the 90 threshold cleanly even when INO's score does.

**Diagnostic during fitting:** Calibration code MUST report the distribution of raw predictions before scaling, including:
- 99th and 1st percentiles
- max and min
- proportion of predictions outside ±150 in raw space

If raw output regularly exceeds ±200, linear scaling is the wrong choice and we fall back to clipping or sigmoid. The decision to maintain or change normalization is made AFTER seeing real Polygon feature data and pre-fit raw predictions, not before.

**Fallback path:** If linear scaling fails the diagnostic, switch to clipping at ±100. Document the fallback in the calibration report. This is not a v2 deferral — it's an in-sprint fallback that doesn't require a new ADR.

### D3 — Hyperparameter selection: k-fold cross-validation on train

Use 5-fold cross-validation within the train set to select LightGBM hyperparameters. Hyperparameter grid (small, intentional):

- `num_leaves`: [15, 31, 63, 127]
- `learning_rate`: [0.05, 0.1]
- `min_child_samples`: [10, 20, 50]
- `n_estimators`: [200, 500, 1000] (with early stopping)
- All other hyperparameters at LightGBM defaults

Selection criterion: composite score MAE on held-out fold, averaged across 5 folds.

**Cross-validation construction:** k-fold on TICKERS within the train set, NOT on rows. Five folds, 80% of train tickers per fold. This preserves the no-leakage discipline from ADR-0002 D3 — within training, the model never sees a ticker's data in both train and validation.

**Rationale:** k-fold is the standard hyperparameter selection approach. Bayesian optimization (Optuna) would explore the search space more efficiently but adds setup complexity that v1 doesn't need given the small grid. Default hyperparameters were rejected because LightGBM's defaults are tuned for general-purpose problems, not for this corpus shape.

**Tradeoff accepted — small grid:** 4×2×3×3 = 72 combinations × 5 folds = 360 model fits per component model = 720 total. Manageable on Spark 2 in <1 hour. Larger grid would explore more but risks overfitting hyperparameters to the train set.

### D4 — Random seed: 42, accept result

Fixed seed `42` for the ticker-level train/test split. Composition imbalance check from ADR-0002 D3 still applies — if the resulting split has test set >25% of total observations or train set <15,000 rows, the calibration code aborts with a clear error message and manual seed adjustment is required as a separate decision.

**Rationale:** Fixed deterministic seed. No seed shopping (which is subtle leakage by another name). The composition check is the safety valve, not seed search.

**If composition check fails:** Calibration code halts. Operator manually selects seed 43 and re-runs. Document the chosen seed in the calibration report. No automated re-draw — one manual decision is acceptable; loops aren't.

**Tradeoff accepted:** seed 42 may produce a suboptimal split (e.g. the random draw places several high-frequency tickers in test). If it passes the composition check, we accept it. Tighter optimization of split balance is a v2 concern.

### D5 — EOD bar quality validation: trust Polygon adjustments

Use Polygon's pre-adjusted EOD bars as-is. No manual validation of splits, dividends, or ticker history during v1 calibration.

**Rationale:** Polygon's split/dividend adjustment is industry-standard and well-respected. Manual validation would add 1+ week of sprint scope for a small-probability quality issue. v1 sprint discipline prefers ship-and-monitor over over-engineer.

**Tradeoff flagged — INO/Polygon adjustment mismatch:** INO's original alert was emitted at a specific point in time using whatever price-adjustment policy INO had. Polygon retroactively applies splits and dividends to historical bars. If INO's emitted score was based on unadjusted prices and Polygon presents adjusted bars, the Donchian channel position computed from Polygon will not match what INO computed. This affects every feature.

**Concrete example:** Stock has 2:1 split on 2025-06-15. INO emits alert on 2025-06-10 based on unadjusted price of $100, with Donchian channel showing breakout at $98. Polygon's "2025-06-10 close" is retroactively shown as $50 (adjusted), with Donchian channel showing breakout at $49. Same logical event, but the percentage position within the channel is identical, so the impact is mostly on absolute levels not relative position. Donchian features SHOULD be robust to this because they're position-relative, not absolute. MACD features are also relative (rate of change) so should be robust.

**Discoverable failure mode:** if calibration MAE is unexpectedly bad on tickers with known recent splits, we'll know adjustment mismatch is the cause. Sprint includes a diagnostic — flag the worst-MAE tickers and check whether they have historical splits in the Polygon data.

**Future v2 path:** A more complete v2 would track corporate actions explicitly via the empty `hedge_fund.corporate_actions` table from migration 0002, and recompute features at INO's adjustment-policy. Out of scope for v1.

---

## Sprint workflow (locked)

With D1-D5 fixed, the calibration sprint executes in this order:

1. **Polygon.io setup** — create account, obtain API key, add `POLYGON_API_KEY` to `.env`, write rate-limit-aware fetch wrapper.
2. **EOD bar backfill** — populate `hedge_fund.eod_bars` with 5 years of historical bars for the ~700 corpus tickers. Filter out tickers with insufficient history (<63 prior trading days at any alert date). Document filtered tickers in calibration report.
3. **Feature extraction** — for each observation in the corpus, compute the 4 daily-tier features and 4 momentum-tier features from EOD bars. Store as parquet at `/mnt/fortress_nas/fortress_data/ai_brain/dochia_calibration/features.parquet`.
4. **Train/test split** — apply seed=42 ticker-level 80/20 with composition check.
5. **Hyperparameter search** — 5-fold CV over the small grid for each component model.
6. **Final fit** — train each component model on full train set with selected hyperparameters.
7. **Normalization fit** — derive linear scaling parameters from training-set raw predictions. Run diagnostic: if raw predictions regularly exceed ±200, fall back to clipping (document fallback in calibration report).
8. **Test-set evaluation** — score the held-out test tickers, compute the three success metrics from ADR-0002.
9. **Persistence** — write fitted parameters to `hedge_fund.scoring_parameters` row with ID `dochia_v1_daily_only`. Model artifacts (LightGBM boosters as joblib pickle) go to `/mnt/fortress_nas/fortress_data/ai_brain/dochia_calibration/models/`.
10. **Reporting** — generate `docs/dochia-v1-calibration-report.md` with metrics, leakage disclosures, feature importances, SHAP plots, normalization diagnostic, seed used, raw vs. scaled distributions.
11. **Decision** — operator reads the report. If success metrics pass, parameter set is approved for production use. If they fail, calibration sprint produces failure diagnosis ADR (ADR-0004) before any retry.

---

## Out of scope for v1 (still)

- Multi-timeframe calibration — v2
- Volatility-adaptive lookbacks — Layer 2
- Volume / regime / earnings filters — Layer 3
- LLM sentiment overlay — Layer 4
- Correlation-aware position sizing — Layer 5
- Forward-return profitability evaluation — separate sprint after v1 production
- Chronological hold-out as secondary metric — possible v2 addition
- Manual corporate action validation — possible v2 addition

---

## Decisions log

| Date       | Decision                                         | By  |
|------------|--------------------------------------------------|-----|
| 2026-04-27 | D1 — LightGBM gradient boosting                  | GK  |
| 2026-04-27 | D2 — Linear scaling, with raw-output diagnostic  | GK  |
| 2026-04-27 | D3 — 5-fold ticker-level CV, small grid          | GK  |
| 2026-04-27 | D4 — Seed 42, manual escalation if check fails   | GK  |
| 2026-04-27 | D5 — Trust Polygon adjustments, monitor for      | GK  |
|            |       discoverable mismatch failures             |     |

---

## Diagnostic gates (NEW — explicit)

Three diagnostics that calibration code MUST run and report. None require operator approval to proceed (they're informational), but each surfaces a known risk:

1. **Composition imbalance check** (post-split, pre-fit):
   - Train rows must be ≥ 15,000 OR ≤ 75% of total
   - Test rows must be ≤ 25% of total
   - On failure: halt, surface for manual seed change.

2. **Raw prediction distribution check** (post-fit, pre-normalization):
   - 99th/1st percentile, max/min of raw predictions
   - Fraction of predictions outside ±150
   - On extreme distribution: switch normalization to clipping, document fallback in report.

3. **Per-ticker MAE outlier check** (post-evaluation):
   - Identify worst-10% MAE tickers
   - Cross-reference against known corporate actions in their history
   - Surface findings in calibration report
   - Does NOT halt — informational only.

These gates ensure that issues from accepted-tradeoff decisions (D2 squashing, D4 seed-of-the-day, D5 trust-Polygon) are surfaced empirically rather than ignored.
