# MarketClub / Dochia Shadow Review Runbook

**Status:** Read-only promotion review + dry-run preview
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
- Decision records:
  `GET /api/financial/signals/shadow-review/decision-records?candidate_parameter_set=dochia_v0_2_range_daily`
  and `POST /api/financial/signals/shadow-review/decision-records`
- Promotion dry-run:
  `GET /api/financial/signals/promotion-dry-run/daily?candidate_parameter_set=dochia_v0_2_range_daily`

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

Capture in the Shadow Review panel or decision-record API:

- Reviewer and timestamp.
- Candidate parameter set.
- Promotion Gate recommendation.
- Lane churn summary.
- Transition-pressure tickers reviewed.
- Whipsaw/backtest tickers reviewed.
- Decision: `defer`, `continue_shadow`, or `promote_to_market_signals`.
- Rollback or depromotion criteria.

The API recomputes and stores the current Shadow Review evidence packet with
the record. A `promote_to_market_signals` decision is still only permission to
build the next dry-run promotion step; it is not a production write.

## Promotion Dry-Run Review

The dry-run endpoint and cockpit panel generate proposed `hedge_fund.market_signals`
rows without inserting them. Review:

- Approval state and decision record id.
- Proposed BUY/SELL counts and skipped neutral count.
- Target columns for `hedge_fund.market_signals`.
- Per-row source pipeline, parameter set, model version, computed timestamp,
  explanation payload, and rollback marker.

Dry-run output is still preview-only. It does not enable production writes.

## Hard Stops

- Any Promotion Gate `hold`.
- Missing live backend or frontend Promotion Gate data.
- Unreviewed high whipsaw-risk ticker in the shadow packet.
- No named human approver.

## Next Build Step After Dry-Run Approval

After a recorded `promote_to_market_signals` decision and accepted dry-run
output, build the guarded write path. It must insert only with named approval,
preserve lineage fields, attach rollback/depromotion controls, and provide a
safe way to disable or remove a promoted candidate set.
