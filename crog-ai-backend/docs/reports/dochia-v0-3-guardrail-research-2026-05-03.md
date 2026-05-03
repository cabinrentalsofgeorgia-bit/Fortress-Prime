# Dochia v0.3 Range Guardrail Research

Generated: 2026-05-03T05:27:09.301327+00:00
Scope: ticker=all since=beginning until=latest
Event window: ±3 days
Candidates tested: 40

## Baselines

| Rule | F1 | Precision | Recall | ±3d recall | Carried | Generated |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| production close | 44.59% | 49.35% | 40.67% | 52.54% | 62.05% | 18158 |
| v0.2 raw range | 76.64% | 65.71% | 91.93% | 95.21% | 94.91% | 30806 |

## Top Guardrail Candidates

| Rank | Lookback | Break buffer | Debounce | Directional close | F1 | Precision | Recall | ±3d recall | Carried | Generated | Event reduction |
| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3 | 0.00% | 0 | no | 76.64% | 65.71% | 91.93% | 95.21% | 94.91% | 30806 | 0.00% |
| 2 | 3 | 0.10% | 0 | no | 73.12% | 63.77% | 85.69% | 91.48% | 90.16% | 29582 | 3.97% |
| 3 | 3 | 0.00% | 1 | no | 69.47% | 60.88% | 80.88% | 90.42% | 86.12% | 29247 | 5.06% |
| 4 | 3 | 0.25% | 0 | no | 66.93% | 60.19% | 75.36% | 84.39% | 82.79% | 27539 | 10.61% |
| 5 | 3 | 0.10% | 1 | no | 66.65% | 59.35% | 75.99% | 87.08% | 82.54% | 28179 | 8.53% |
| 6 | 3 | 0.25% | 1 | no | 61.44% | 56.35% | 67.53% | 80.51% | 76.68% | 26358 | 14.44% |
| 7 | 3 | 0.00% | 2 | no | 60.16% | 55.36% | 65.88% | 78.11% | 75.58% | 26209 | 14.92% |
| 8 | 3 | 0.00% | 0 | yes | 59.65% | 57.97% | 61.44% | 70.79% | 75.06% | 23343 | 24.23% |
| 9 | 3 | 0.50% | 0 | no | 58.79% | 55.83% | 62.09% | 73.67% | 73.94% | 24434 | 20.68% |
| 10 | 3 | 0.10% | 2 | no | 57.84% | 53.96% | 62.33% | 75.84% | 72.89% | 25436 | 17.43% |
| 11 | 3 | 0.10% | 0 | yes | 57.37% | 56.88% | 57.88% | 67.85% | 72.55% | 22404 | 27.27% |
| 12 | 3 | 0.00% | 1 | yes | 56.15% | 55.55% | 56.75% | 68.01% | 71.50% | 22500 | 26.96% |

## Recommendation

No v0.3 guardrail cleared the default quality bar of at least 85% of raw-range F1 while cutting generated events by at least 15%. Keep v0.2 in candidate-only mode and expand the research grid before promotion.

Next move: test ATR-normalized buffers and ticker-specific cooldowns against the same promotion-review churn packet.
