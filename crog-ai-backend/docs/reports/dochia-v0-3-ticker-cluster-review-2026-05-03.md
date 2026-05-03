# Dochia v0.3 Ticker-Cluster Candidate Review

Generated: 2026-05-03T12:50:39.698708+00:00
Scope: ticker=all since=beginning until=latest
Cluster source: top 30 v0.2 whipsaw tickers over 5 sessions; since=beginning until=latest

## Raw v0.2 Baseline

| Events | F1 | Precision | Recall | ±3d recall | 5d win | Avg 5d | Top whipsaw count |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 30806 | 76.64% | 65.71% | 91.93% | 95.21% | 50.33% | +0.01% | 2164 |

Top cluster tickers: MOD, ISRG, MRVL, DLR, HD, VRT, GFS, APG, RUN, WMB, DT, SIG, DBC, AVGO, CME

## Quality-Preserving Candidates

| Rank | Candidate | Events | Event reduction | F1 | Precision | Recall | ±3d recall | 5d win | Avg 5d | Top whipsaws | Top whipsaw tickers |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | top 15 exclude | 29232 | 5.11% | 74.98% | 65.73% | 87.28% | 90.44% | 50.58% | +0.05% | 2036 | BNDX, MO, RUM, PINS, KC |
| 2 | top 15 cooldown 20 | 29544 | 4.10% | 75.31% | 65.72% | 88.19% | 91.43% | 50.54% | +0.04% | 2036 | BNDX, MO, RUM, PINS, KC |
| 3 | top 10 exclude | 29750 | 3.43% | 75.46% | 65.65% | 88.72% | 91.90% | 50.53% | +0.04% | 2067 | DT, SIG, DBC, AVGO, CME |
| 4 | top 15 cooldown 10 | 29755 | 3.41% | 75.54% | 65.72% | 88.82% | 92.10% | 50.48% | +0.03% | 2036 | BNDX, MO, RUM, PINS, KC |
| 5 | top 10 cooldown 20 | 29959 | 2.75% | 75.69% | 65.66% | 89.35% | 92.59% | 50.51% | +0.04% | 2067 | DT, SIG, DBC, AVGO, CME |
| 6 | top 15 cooldown 5 | 30053 | 2.44% | 75.86% | 65.71% | 89.70% | 93.04% | 50.47% | +0.03% | 2036 | BNDX, MO, RUM, PINS, KC |
| 7 | top 10 cooldown 10 | 30098 | 2.30% | 75.86% | 65.68% | 89.78% | 93.05% | 50.45% | +0.03% | 2067 | DT, SIG, DBC, AVGO, CME |
| 8 | top 5 exclude | 30268 | 1.75% | 75.92% | 65.57% | 90.15% | 93.38% | 50.46% | +0.03% | 2104 | VRT, GFS, APG, RUN, WMB |
| 9 | top 10 cooldown 5 | 30299 | 1.65% | 76.07% | 65.67% | 90.37% | 93.69% | 50.46% | +0.03% | 2067 | DT, SIG, DBC, AVGO, CME |
| 10 | top 5 cooldown 20 | 30373 | 1.41% | 76.06% | 65.60% | 90.49% | 93.76% | 50.44% | +0.03% | 2104 | VRT, GFS, APG, RUN, WMB |
| 11 | top 5 cooldown 10 | 30441 | 1.18% | 76.16% | 65.63% | 90.73% | 93.99% | 50.41% | +0.02% | 2104 | VRT, GFS, APG, RUN, WMB |
| 12 | top 5 cooldown 5 | 30541 | 0.86% | 76.28% | 65.64% | 91.04% | 94.34% | 50.38% | +0.02% | 2104 | VRT, GFS, APG, RUN, WMB |

## Best Event-Reduction Candidates

| Rank | Candidate | Events | Event reduction | F1 | Precision | Recall | ±3d recall | 5d win | Avg 5d | Top whipsaws | Top whipsaw tickers |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| R1 | top 15 exclude | 29232 | 5.11% | 74.98% | 65.73% | 87.28% | 90.44% | 50.58% | +0.05% | 2036 | BNDX, MO, RUM, PINS, KC |
| R2 | top 15 cooldown 20 | 29544 | 4.10% | 75.31% | 65.72% | 88.19% | 91.43% | 50.54% | +0.04% | 2036 | BNDX, MO, RUM, PINS, KC |
| R3 | top 10 exclude | 29750 | 3.43% | 75.46% | 65.65% | 88.72% | 91.90% | 50.53% | +0.04% | 2067 | DT, SIG, DBC, AVGO, CME |
| R4 | top 15 cooldown 10 | 29755 | 3.41% | 75.54% | 65.72% | 88.82% | 92.10% | 50.48% | +0.03% | 2036 | BNDX, MO, RUM, PINS, KC |
| R5 | top 10 cooldown 20 | 29959 | 2.75% | 75.69% | 65.66% | 89.35% | 92.59% | 50.51% | +0.04% | 2067 | DT, SIG, DBC, AVGO, CME |
| R6 | top 15 cooldown 5 | 30053 | 2.44% | 75.86% | 65.71% | 89.70% | 93.04% | 50.47% | +0.03% | 2036 | BNDX, MO, RUM, PINS, KC |
| R7 | top 10 cooldown 10 | 30098 | 2.30% | 75.86% | 65.68% | 89.78% | 93.05% | 50.45% | +0.03% | 2067 | DT, SIG, DBC, AVGO, CME |
| R8 | top 5 exclude | 30268 | 1.75% | 75.92% | 65.57% | 90.15% | 93.38% | 50.46% | +0.03% | 2104 | VRT, GFS, APG, RUN, WMB |
| R9 | top 10 cooldown 5 | 30299 | 1.65% | 76.07% | 65.67% | 90.37% | 93.69% | 50.46% | +0.03% | 2067 | DT, SIG, DBC, AVGO, CME |
| R10 | top 5 cooldown 20 | 30373 | 1.41% | 76.06% | 65.60% | 90.49% | 93.76% | 50.44% | +0.03% | 2104 | VRT, GFS, APG, RUN, WMB |
| R11 | top 5 cooldown 10 | 30441 | 1.18% | 76.16% | 65.63% | 90.73% | 93.99% | 50.41% | +0.02% | 2104 | VRT, GFS, APG, RUN, WMB |
| R12 | top 5 cooldown 5 | 30541 | 0.86% | 76.28% | 65.64% | 91.04% | 94.34% | 50.38% | +0.02% | 2104 | VRT, GFS, APG, RUN, WMB |

## Recommendation

Use this as the next non-production v0.3 candidate only after a chronological holdout check:

| Rank | Candidate | Events | Event reduction | F1 | Precision | Recall | ±3d recall | 5d win | Avg 5d | Top whipsaws | Top whipsaw tickers |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | top 15 exclude | 29232 | 5.11% | 74.98% | 65.73% | 87.28% | 90.44% | 50.58% | +0.05% | 2036 | BNDX, MO, RUM, PINS, KC |
