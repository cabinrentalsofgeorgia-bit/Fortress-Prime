# Dochia v0.3 Ticker-Cluster Candidate Review

Generated: 2026-05-03T12:50:23.573566+00:00
Scope: ticker=all since=2025-09-25 until=latest
Cluster source: top 30 v0.2 whipsaw tickers over 5 sessions; since=beginning until=2025-09-24

## Raw v0.2 Baseline

| Events | F1 | Precision | Recall | ±3d recall | 5d win | Avg 5d | Top whipsaw count |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 8613 | 79.93% | 71.37% | 90.82% | 94.68% | 50.15% | -0.04% | 759 |

Top cluster tickers: MOD, CME, MRVL, WMB, RIO, ISRG, VICI, DT, DLR, VRT, FLNC, HD, GFS, KHC, ROL

## Quality-Preserving Candidates

| Rank | Candidate | Events | Event reduction | F1 | Precision | Recall | ±3d recall | 5d win | Avg 5d | Top whipsaws | Top whipsaw tickers |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | top 15 exclude | 8205 | 4.74% | 78.16% | 71.31% | 86.47% | 90.17% | 50.12% | -0.04% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| 2 | top 15 cooldown 20 | 8292 | 3.73% | 78.60% | 71.37% | 87.46% | 91.23% | 50.15% | -0.03% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| 3 | top 10 exclude | 8339 | 3.18% | 78.79% | 71.36% | 87.94% | 91.72% | 50.13% | -0.03% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| 4 | top 15 cooldown 10 | 8351 | 3.04% | 78.77% | 71.30% | 87.99% | 91.80% | 50.11% | -0.04% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| 5 | top 10 cooldown 20 | 8397 | 2.51% | 79.07% | 71.39% | 88.59% | 92.41% | 50.15% | -0.04% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| 6 | top 15 cooldown 5 | 8425 | 2.18% | 79.12% | 71.34% | 88.81% | 92.69% | 50.17% | -0.05% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| 7 | top 10 cooldown 10 | 8435 | 2.07% | 79.18% | 71.36% | 88.94% | 92.79% | 50.09% | -0.05% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| 8 | top 5 exclude | 8484 | 1.50% | 79.52% | 71.48% | 89.60% | 93.39% | 50.14% | -0.03% | 759 | GCT, SMCI, DBC, DIVO, PSTG |
| 9 | top 10 cooldown 5 | 8484 | 1.50% | 79.41% | 71.38% | 89.48% | 93.36% | 50.10% | -0.05% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| 10 | top 5 cooldown 20 | 8512 | 1.17% | 79.61% | 71.45% | 89.87% | 93.70% | 50.16% | -0.03% | 759 | GCT, SMCI, DBC, DIVO, PSTG |
| 11 | top 5 cooldown 10 | 8531 | 0.95% | 79.65% | 71.42% | 90.03% | 93.88% | 50.12% | -0.04% | 759 | GCT, SMCI, DBC, DIVO, PSTG |
| 12 | top 5 cooldown 5 | 8554 | 0.69% | 79.73% | 71.41% | 90.25% | 94.11% | 50.08% | -0.05% | 759 | GCT, SMCI, DBC, DIVO, PSTG |

## Best Event-Reduction Candidates

| Rank | Candidate | Events | Event reduction | F1 | Precision | Recall | ±3d recall | 5d win | Avg 5d | Top whipsaws | Top whipsaw tickers |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| R1 | top 15 exclude | 8205 | 4.74% | 78.16% | 71.31% | 86.47% | 90.17% | 50.12% | -0.04% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| R2 | top 15 cooldown 20 | 8292 | 3.73% | 78.60% | 71.37% | 87.46% | 91.23% | 50.15% | -0.03% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| R3 | top 10 exclude | 8339 | 3.18% | 78.79% | 71.36% | 87.94% | 91.72% | 50.13% | -0.03% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| R4 | top 15 cooldown 10 | 8351 | 3.04% | 78.77% | 71.30% | 87.99% | 91.80% | 50.11% | -0.04% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| R5 | top 10 cooldown 20 | 8397 | 2.51% | 79.07% | 71.39% | 88.59% | 92.41% | 50.15% | -0.04% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| R6 | top 15 cooldown 5 | 8425 | 2.18% | 79.12% | 71.34% | 88.81% | 92.69% | 50.17% | -0.05% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| R7 | top 10 cooldown 10 | 8435 | 2.07% | 79.18% | 71.36% | 88.94% | 92.79% | 50.09% | -0.05% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| R8 | top 5 exclude | 8484 | 1.50% | 79.52% | 71.48% | 89.60% | 93.39% | 50.14% | -0.03% | 759 | GCT, SMCI, DBC, DIVO, PSTG |
| R9 | top 10 cooldown 5 | 8484 | 1.50% | 79.41% | 71.38% | 89.48% | 93.36% | 50.10% | -0.05% | 756 | GCT, SMCI, DBC, DIVO, PSTG |
| R10 | top 5 cooldown 20 | 8512 | 1.17% | 79.61% | 71.45% | 89.87% | 93.70% | 50.16% | -0.03% | 759 | GCT, SMCI, DBC, DIVO, PSTG |
| R11 | top 5 cooldown 10 | 8531 | 0.95% | 79.65% | 71.42% | 90.03% | 93.88% | 50.12% | -0.04% | 759 | GCT, SMCI, DBC, DIVO, PSTG |
| R12 | top 5 cooldown 5 | 8554 | 0.69% | 79.73% | 71.41% | 90.25% | 94.11% | 50.08% | -0.05% | 759 | GCT, SMCI, DBC, DIVO, PSTG |

## Recommendation

No ticker-cluster candidate cleared the default gate: at least 95% of raw-range F1, at least 5% event reduction, fewer top whipsaws, and no worse 5-session average directional return. Keep v0.2 candidate-only.
