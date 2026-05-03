# Dochia v0.3 Rolling Whipsaw-Risk Review

Generated: 2026-05-03T13:18:02.480010+00:00
Scope: ticker=all since=beginning until=latest
Whipsaw window: 5 sessions

## Raw v0.2 Baseline

| Events | F1 | Precision | Recall | ±3d recall | 5d win | Avg 5d | Top whipsaw count |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 30806 | 76.64% | 65.71% | 91.93% | 95.21% | 50.33% | +0.01% | 2164 |

## Quality-Preserving Candidates

_No candidates preserved at least 95% of raw-range F1._

## Best Event-Reduction Candidates

| Rank | Candidate | Events | Event reduction | F1 | Precision | Recall | ±3d recall | 5d win | Avg 5d | Top whipsaws | Top whipsaw tickers |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| R1 | 2 whipsaws/60 sessions -> 20 cooldown | 1548 | 94.98% | 6.57% | 50.00% | 3.52% | 4.12% | 49.90% | -0.25% | 79 | CRM, HPQ, MGA, SPXC, MOS |
| R2 | 2 whipsaws/45 sessions -> 20 cooldown | 1688 | 94.52% | 7.35% | 51.66% | 3.96% | 4.58% | 49.61% | -0.21% | 123 | VZ, MOS, REGN, MSTR, HE |
| R3 | 2 whipsaws/60 sessions -> 10 cooldown | 1755 | 94.30% | 7.63% | 51.68% | 4.12% | 4.74% | 49.43% | -0.20% | 127 | SPXC, ORN, MGA, XLE, HQH |
| R4 | 2 whipsaws/60 sessions -> 5 cooldown | 1940 | 93.70% | 8.65% | 53.45% | 4.70% | 5.36% | 49.15% | -0.25% | 135 | SPXC, ORN, MOS, HQH, ANY |
| R5 | 2 whipsaws/30 sessions -> 20 cooldown | 2149 | 93.02% | 9.51% | 53.56% | 5.22% | 5.91% | 49.91% | -0.21% | 171 | BLDR, OXLC, MIGI, SPXC, TFC |
| R6 | 3 whipsaws/60 sessions -> 20 cooldown | 2236 | 92.74% | 9.64% | 52.33% | 5.31% | 5.95% | 49.91% | -0.20% | 156 | MOS, HE, CRM, MGA, DIS |
| R7 | 2 whipsaws/45 sessions -> 10 cooldown | 2414 | 92.16% | 11.07% | 55.92% | 6.15% | 6.85% | 49.31% | -0.23% | 184 | THQ, COP, MAS, ORN, MOS |
| R8 | 3 whipsaws/45 sessions -> 20 cooldown | 2597 | 91.57% | 11.45% | 54.33% | 6.40% | 7.13% | 49.94% | -0.23% | 201 | BLDR, AVAV, ADBE, MSTR, SPXC |
| R9 | 2 whipsaws/20 sessions -> 20 cooldown | 2694 | 91.25% | 12.14% | 55.79% | 6.81% | 7.59% | 50.45% | -0.16% | 229 | AVAV, OXLC, HE, ADBE, MIGI |
| R10 | 3 whipsaws/60 sessions -> 10 cooldown | 2875 | 90.67% | 12.71% | 55.13% | 7.18% | 7.90% | 49.74% | -0.20% | 219 | XLB, ORN, XLE, RVT, SPXC |
| R11 | 4 whipsaws/60 sessions -> 20 cooldown | 3021 | 90.19% | 13.18% | 54.68% | 7.49% | 8.24% | 49.29% | -0.18% | 236 | VZ, MOS, CMBT, MGA, HE |
| R12 | 2 whipsaws/45 sessions -> 5 cooldown | 3028 | 90.17% | 14.07% | 58.16% | 8.00% | 8.80% | 48.99% | -0.21% | 215 | OC, COP, MTRX, DIS, NBR |

## Recommendation

No rolling whipsaw-risk candidate cleared the default gate: at least 95% of raw-range F1, at least 5% event reduction, fewer top whipsaws, and no worse 5-session average directional return. Keep v0.2 candidate-only.
