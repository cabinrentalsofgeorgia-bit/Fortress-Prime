# MarketClub / Dochia Shadow Review Runbook

**Status:** Read-only promotion review
**Date:** 2026-05-03

## Purpose

Use this runbook before any Dochia candidate writes to
`hedge_fund.market_signals`. The shadow review is an evidence packet, not an
approval mechanism.

## Inputs

- Candidate parameter set: `dochia_v0_2_range_daily`
- Baseline parameter set: production `dochia_v0_estimated`
- Live app panel: Command Center -> Financial -> Hedge Fund -> Shadow Review
- API packet:
  `GET /api/financial/signals/shadow-review/daily?candidate_parameter_set=dochia_v0_2_range_daily`

## Review Gates

1. Promotion Gate must not be `hold`.
2. Lane churn must be reviewed for bullish alignment, risk alignment, re-entry,
   and mixed timeframes.
3. Transition-pressure tickers must be inspected on chart overlay.
4. High whipsaw-risk tickers must be reviewed in the Whipsaw / Backtest panel.
5. A human decision record must be captured before promotion.

## Allowed Decisions

- `defer`: do not promote; continue research.
- `continue_shadow`: keep candidate visible in the app, no production write.
- `promote_to_market_signals`: permit the next build step to create a controlled
  dry-run and then a guarded write path.

## Required Decision Record

Capture:

- Reviewer and timestamp.
- Candidate parameter set.
- Promotion Gate recommendation.
- Lane churn summary.
- Transition-pressure tickers reviewed.
- Whipsaw/backtest tickers reviewed.
- Decision: `defer`, `continue_shadow`, or `promote_to_market_signals`.
- Rollback or depromotion criteria.

## Hard Stops

- Any Promotion Gate `hold`.
- Missing live backend or frontend Promotion Gate data.
- Unreviewed high whipsaw-risk ticker in the shadow packet.
- No named human approver.

## Next Build Step After Approval

If the decision is `promote_to_market_signals`, build the promotion pipeline as
dry-run first. It must preserve lineage fields: source pipeline, parameter set,
model version, computed time, explanation payload, and rollback marker.
