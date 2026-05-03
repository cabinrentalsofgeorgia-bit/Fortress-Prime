# Dochia v0.3 Return Outcome Review

Generated: 2026-05-03T06:11:22.428810+00:00
Scope: ticker=all since=beginning until=latest
Whipsaw window: 5 sessions

## Forward Directional Returns

| Rule | Horizon | Events | Win rate | Average | Median | P25 | P75 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| production close | 5 | 18091 | 50.25% | -0.03% | +0.04% | -3.01% | +2.95% |
| production close | 10 | 17959 | 50.15% | +0.05% | +0.03% | -4.23% | +4.42% |
| production close | 20 | 17588 | 49.45% | -0.16% | -0.07% | -6.18% | +6.13% |
| v0.2 raw range | 5 | 30692 | 50.33% | +0.01% | +0.04% | -2.97% | +3.03% |
| v0.2 raw range | 10 | 30384 | 50.18% | +0.06% | +0.04% | -4.28% | +4.39% |
| v0.2 raw range | 20 | 29721 | 49.99% | -0.05% | -0.00% | -6.31% | +6.31% |

## v0.2 Whipsaw Clusters

| Ticker | Events | Whipsaws | Rate | 5-session events | Avg 5-session return | Latest |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| MOD | 111 | 82 | 74.55% | 110 | -1.29% | 2026-04-21 |
| ISRG | 112 | 82 | 73.87% | 110 | -0.57% | 2026-04-22 |
| MRVL | 107 | 78 | 73.58% | 107 | -1.81% | 2026-04-17 |
| DLR | 108 | 78 | 72.90% | 106 | -0.37% | 2026-04-24 |
| HD | 104 | 75 | 72.82% | 103 | -0.01% | 2026-04-08 |
| VRT | 105 | 75 | 72.12% | 102 | -1.12% | 2026-04-23 |
| GFS | 104 | 74 | 71.84% | 104 | -0.31% | 2026-04-16 |
| APG | 104 | 74 | 71.84% | 104 | -0.44% | 2026-04-01 |
| RUN | 105 | 74 | 71.15% | 104 | -0.87% | 2026-04-13 |
| WMB | 103 | 73 | 71.57% | 102 | -0.27% | 2026-04-20 |
| DT | 104 | 73 | 70.87% | 103 | -0.44% | 2026-04-15 |
| SIG | 107 | 73 | 68.87% | 106 | -0.29% | 2026-04-22 |
| DBC | 104 | 72 | 69.90% | 103 | -0.12% | 2026-04-21 |
| AVGO | 104 | 72 | 69.90% | 104 | -0.38% | 2026-04-01 |
| CME | 101 | 71 | 71.00% | 101 | -0.03% | 2026-04-09 |

## Recommendation

Do not promote or suppress v0.2 only from alert-match F1. Use this return-outcome layer with the promotion-review churn packet: candidates must preserve alert quality, reduce whipsaw clusters, and avoid degrading forward directional returns.
