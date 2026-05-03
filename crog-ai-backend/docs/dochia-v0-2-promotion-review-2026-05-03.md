# Dochia v0.2 Promotion Review - 2026-05-03

## Scope

Candidate: `dochia_v0_2_range_daily`

Production baseline: `dochia_v0_estimated`

Reference market date: `2026-04-24`

Decision status: keep v0.2 in shadow/internal mode. It is healthy enough for operator review, but not ready for automatic production promotion until the whipsaw clusters are reviewed in chart context.

## Validation Summary

The candidate remains a major improvement against daily MarketClub truth.

| Segment | Baseline F1 | Candidate F1 | Delta | Candidate Recall | Candidate Precision | Candidate Carried |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Overall | 44.59% | 76.64% | +32.05pt | 91.93% | 65.71% | 94.91% |
| Train <= 2025-09-25 | 44.50% | 75.37% | +30.87pt | 92.45% | 63.62% | 94.84% |
| Holdout > 2025-09-25 | 46.26% | 83.18% | +36.92pt | 90.73% | 76.78% | 95.06% |

Every covered quarter from `2024-Q2` through `2026-Q2` improved versus the baseline.

## Live Cockpit Impact

The stored candidate set covers 328 tickers and overlaps production on all 328.

| Lane | Production | Candidate | Entered | Exited | Promotion Read |
| --- | ---: | ---: | ---: | ---: | --- |
| Bullish alignment | 129 | 129 | 0 | 0 | Stable |
| Risk alignment | 47 | 47 | 0 | 0 | Stable |
| Reentry | 164 | 146 | 16 | 35 | Needs review |
| Mixed timeframes | 202 | 203 | 18 | 17 | Acceptable churn |

Score changes: 61 tickers.

Daily state changes: 61 tickers.

The main production-facing lane counts stay stable. The reentry lane is the area that needs human review because the candidate removes more names than it adds.

## Largest Score Changes

| Ticker | Production | Candidate | Delta | Production Daily | Candidate Daily |
| --- | ---: | ---: | ---: | ---: | ---: |
| ZS | -50 | -80 | -30 | 1 | -1 |
| WES | 50 | 80 | +30 | -1 | 1 |
| WELL | 50 | 80 | +30 | -1 | 1 |
| UTG | 50 | 80 | +30 | -1 | 1 |
| ULH | 80 | 50 | -30 | 1 | -1 |
| ULBI | 80 | 50 | -30 | 1 | -1 |
| TRMD | 80 | 50 | -30 | 1 | -1 |
| TREX | 0 | -30 | -30 | 1 | -1 |
| TMF | -50 | -80 | -30 | 1 | -1 |
| TMDX | -80 | -50 | +30 | -1 | 1 |
| TFC | 0 | -30 | -30 | 1 | -1 |
| TEAM | 0 | -30 | -30 | 1 | -1 |

## Whipsaw Clusters

The candidate produces more daily range-triggered events. These are expected with range mode, but the following clusters should be reviewed before promotion.

| Ticker | Production Transitions | Candidate Transitions | Delta | Latest Candidate Transition | Latest Date |
| --- | ---: | ---: | ---: | --- | --- |
| LPX | 3 | 9 | +6 | breakout_bearish | 2026-04-21 |
| PNR | 4 | 9 | +5 | breakout_bullish | 2026-04-24 |
| IR | 4 | 9 | +5 | breakout_bearish | 2026-04-22 |
| DTE | 4 | 9 | +5 | exit_to_reentry | 2026-04-24 |
| UEC | 5 | 9 | +4 | breakout_bearish | 2026-04-23 |
| NTAP | 5 | 9 | +4 | breakout_bearish | 2026-04-24 |
| VRT | 7 | 9 | +2 | breakout_bullish | 2026-04-23 |
| BNDX | 1 | 8 | +7 | breakout_bearish | 2026-04-23 |
| XLI | 2 | 8 | +6 | breakout_bullish | 2026-04-23 |
| OLED | 2 | 8 | +6 | breakout_bullish | 2026-04-24 |
| CGON | 2 | 8 | +6 | breakout_bearish | 2026-04-23 |
| BDX | 2 | 8 | +6 | breakout_bearish | 2026-04-22 |

## Chart-Level Read

The chart overlay parity is working: candidate charts show range-trigger daily events and production charts stay close-triggered. Candidate daily event density is materially higher on the biggest score-change symbols.

| Ticker | Production Daily Events | Candidate Daily Events | Latest Candidate State | Latest Date | Trigger |
| --- | ---: | ---: | --- | --- | ---: |
| ZS | 26 | 39 | red | 2026-04-23 | 130.3400 |
| WES | 23 | 40 | green | 2026-04-23 | 41.4100 |
| WELL | 15 | 30 | green | 2026-04-24 | 211.5900 |
| UTG | 19 | 34 | green | 2026-04-24 | 42.3000 |
| ULH | 17 | 30 | red | 2026-04-24 | 21.9521 |
| ULBI | 21 | 33 | red | 2026-04-22 | 7.3364 |
| TRMD | 18 | 27 | red | 2026-04-22 | 29.1500 |
| TREX | 13 | 30 | red | 2026-04-22 | 41.6500 |
| TMF | 26 | 40 | red | 2026-04-16 | 35.7000 |
| TMDX | 19 | 26 | green | 2026-04-17 | 120.9100 |
| TFC | 15 | 28 | red | 2026-04-24 | 50.4800 |
| TEAM | 17 | 30 | red | 2026-04-23 | 65.2000 |

## Promotion Gate

Do not promote automatically yet.

Promotion can proceed after:

1. Review the 12 whipsaw-cluster tickers in the Hedge Fund chart panel.
2. Confirm the reentry lane exits are improvements rather than missed actionable reentries.
3. Add a promotion migration that flips `is_production` only after a final dry run and rollback plan.

Recommended next build step: add a compact Promotion Review panel to the Hedge Fund cockpit showing validation, lane deltas, whipsaw clusters, and the promotion gate status.
