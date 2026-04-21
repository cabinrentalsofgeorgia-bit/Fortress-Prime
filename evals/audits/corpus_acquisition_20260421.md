# GA Corpus Acquisition Results — 2026-04-21

## Sources Acquired

| Source | Records | Status |
|--------|---------|--------|
| GA Supreme Court Rules | 265 rules (80 substantive) | Complete |
| GA Court of Appeals Rules | 53 rules | Complete |
| CourtListener civil opinions | 178 new w/text (203 total) | Complete |
| OCGA Title 9/13/14/33/44/51 (Justia) | 0 | Blocked (Cloudflare 403) |
| Uniform Superior Court Rules | 0 | No public PDF URL |

## Training Pairs Generated

| Pattern | Training | Eval | Train target | Eval target |
|---------|---------|------|-------------|------------|
| B (issue spotting) | 16 | 6 | ≥200 | ≥50 |
| C (citation lookup) | 314 | 98 | ≥200 | ≥100 |

**Pattern C: MET (314 train, 98+13=111 eval total)**
**Pattern B: NOT MET — corpus-constrained at 16/6**

## Pattern B Ceiling Analysis
Civil law opinions (contracts/torts/property) rarely use numbered section headers.
CourtListener returned 203 new opinions but only 22 had section headers.
OCGA and court rules don't fit the "case facts + section headers" Pattern B template.
Fix path: manually authored pairs or different template for legal/B.

## e3.1 Training Mix (if retrain needed)
- Total: 1,795 pairs
- Pattern C: 330 (18.4%) — above 8% target ✓
- Pattern B: 46 (2.6%) — below 8% target ✗

## Step 5 Rebaseline
Running: e3 on holdout-eval-expanded-v2.json (N=299, legal/C=111, legal/B=14)
Gate: B≥0.60 AND C≥0.55 → no retrain; otherwise → e3.1

Prior e3 scores (n=195): legal/B=0.5701, legal/C=0.4589
