# Dochia v0.3 Rolling Whipsaw-Risk Review

Generated: 2026-05-03T13:17:50.004419+00:00
Scope: ticker=all since=2025-09-25 until=latest
Whipsaw window: 5 sessions

## Raw v0.2 Baseline

| Events | F1 | Precision | Recall | ±3d recall | 5d win | Avg 5d | Top whipsaw count |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 8613 | 79.93% | 71.37% | 90.82% | 94.68% | 50.15% | -0.04% | 759 |

## Quality-Preserving Candidates

_No candidates preserved at least 95% of raw-range F1._

## Best Event-Reduction Candidates

| Rank | Candidate | Events | Event reduction | F1 | Precision | Recall | ±3d recall | 5d win | Avg 5d | Top whipsaws | Top whipsaw tickers |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| R1 | 2 whipsaws/60 sessions -> 20 cooldown | 16 | 99.81% | 0.41% | 87.50% | 0.21% | 0.22% | 43.75% | -0.06% | 9 | SPXC, MGA, HPQ, UVXY, PR |
| R2 | 3 whipsaws/60 sessions -> 20 cooldown | 53 | 99.38% | 0.99% | 64.15% | 0.50% | 0.53% | 52.83% | +0.06% | 28 | SPXC, MGA, NOW, TRMD, PR |
| R3 | 2 whipsaws/60 sessions -> 10 cooldown | 57 | 99.34% | 1.31% | 78.95% | 0.66% | 0.70% | 36.36% | -1.19% | 28 | SPXC, MGA, HPQ, ORN, ALGM |
| R4 | 2 whipsaws/45 sessions -> 20 cooldown | 81 | 99.06% | 1.77% | 75.31% | 0.90% | 0.93% | 48.15% | +0.34% | 40 | SPXC, MGA, MDT, MAS, LPX |
| R5 | 2 whipsaws/60 sessions -> 5 cooldown | 126 | 98.54% | 2.71% | 74.60% | 1.38% | 1.47% | 45.16% | -0.79% | 44 | SPXC, MGNX, MGA, HPQ, TREX |
| R6 | 4 whipsaws/60 sessions -> 20 cooldown | 128 | 98.51% | 2.22% | 60.16% | 1.13% | 1.20% | 48.44% | -0.20% | 67 | SPXC, MGA, NOW, HQH, FEIM |
| R7 | 3 whipsaws/45 sessions -> 20 cooldown | 179 | 97.92% | 3.63% | 70.95% | 1.87% | 2.03% | 46.93% | -0.11% | 87 | SPXC, MGA, MDT, MAS, LPX |
| R8 | 3 whipsaws/60 sessions -> 10 cooldown | 219 | 97.46% | 4.33% | 69.41% | 2.23% | 2.34% | 49.77% | -0.45% | 77 | NVAX, ZBRA, NTAP, NOW, MGA |
| R9 | 2 whipsaws/30 sessions -> 20 cooldown | 263 | 96.95% | 5.01% | 67.30% | 2.60% | 2.82% | 47.13% | +0.23% | 69 | TFC, ACLX, DCI, RDVT, PR |
| R10 | 2 whipsaws/45 sessions -> 10 cooldown | 282 | 96.73% | 6.01% | 75.53% | 3.13% | 3.26% | 49.28% | -0.21% | 65 | MAS, LPX, BLDR, ALGM, VKTX |
| R11 | 4 whipsaws/45 sessions -> 20 cooldown | 345 | 95.99% | 6.49% | 67.25% | 3.41% | 3.64% | 46.49% | -0.21% | 124 | FMB, OCUL, PR, SPXC, MGA |
| R12 | 3 whipsaws/60 sessions -> 5 cooldown | 370 | 95.70% | 7.41% | 71.89% | 3.91% | 4.13% | 47.54% | -0.38% | 89 | IOVA, OPEN, NVAX, ZBRA, TREX |

## Recommendation

No rolling whipsaw-risk candidate cleared the default gate: at least 95% of raw-range F1, at least 5% event reduction, fewer top whipsaws, and no worse 5-session average directional return. Keep v0.2 candidate-only.
