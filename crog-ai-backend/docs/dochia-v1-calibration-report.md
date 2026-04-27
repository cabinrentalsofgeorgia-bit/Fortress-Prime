# Dochia v1 Calibration Report

Status: **IN PROGRESS** — populated incrementally as ADR-0003 sprint
workflow steps complete.

This report mirrors the 11-step sprint workflow in
[ADR-0003](ADR-0003-dochia-v1-fit-method.md). Each section is filled in
as that step runs; sections still marked `<TBD>` have not yet executed.

---

## 1. Polygon.io setup

**Status:** complete (2026-04-27)

- Polygon Stocks Starter tier (paid, unlimited rate)
- `POLYGON_API_KEY` set in `crog-ai-backend/.env`
- Auth verified against `/v3/reference/tickers/AAPL` (`AUTH SUCCESS`)
- Fetch wrapper: `scripts/backfill_eod_bars.py` (httpx async client,
  defensive 429 backoff, no client-side rate limiter per ADR-0003 D5)

---

## 2. EOD bar backfill coverage

**Status:** populated by end-of-run summary from `scripts/backfill_eod_bars.py`
plus exclusion list from `scripts/audit_corpus_coverage.py`.

### Backfill summary

| Metric                          | Value         |
|---------------------------------|---------------|
| Tickers attempted               | `<TBD>`       |
| Tickers succeeded               | `<TBD>`       |
| Tickers no-data                 | `<TBD>`       |
| Tickers failed                  | `<TBD>`       |
| Bars inserted                   | `<TBD>`       |
| Bars dropped (pre-partition)    | `<TBD>`       |

State files (gitignored):
- `scripts/state/backfill_state.json` — completed-ticker checkpoint
- `scripts/state/backfill_errors.log` — per-ticker error trail
- `scripts/state/no_data_tickers.json` — tickers Polygon returned 0 bars for

### Coverage exclusions (ADR-0002 D2 / ADR-0003 sprint step 2)

A ticker is excluded from the calibration corpus if **any** of its
alert dates has fewer than 63 prior trading days of EOD bars within the
trailing 90-day window. Output written to
`calibration/excluded_tickers.json` (gitignored).

| Metric                          | Value         |
|---------------------------------|---------------|
| Total tickers in corpus         | `<TBD>`       |
| Kept                            | `<TBD>`       |
| Excluded                        | `<TBD>`       |
| Observations dropped            | `<TBD>`       |

Exclusion file pointer: `calibration/excluded_tickers.json`

### Partition coverage

`hedge_fund.eod_bars` is partitioned monthly from **2023-09-01** after
migration `0004_extend_eod_partitions` (this PR) extended
coverage backward by 12 months from the original 2024-09-01 floor in
migration 0002.

**Rationale:** the corpus's earliest alert is 2024-03-18 and the
longest Donchian lookback is 63 trading days. The original 2024-09-01
floor would have starved approximately the first 9 months of corpus
alerts (~8k observations) of prior history. Extending to 2023-09-01
gives a comfortable margin — every alert in the corpus has at least
~125 prior trading days of bar history available.

`backfill_eod_bars.py` retains a defense-in-depth client-side
`PARTITION_FLOOR` of 2023-09-01 in case the migration hasn't been
applied; after `alembic upgrade head` runs, `bars_dropped_pre_partition`
should be zero.

---

## 3. Feature extraction

**Status:** `<TBD — sprint step 3>`

---

## 4. Train/test split

**Status:** `<TBD — sprint step 4>`

---

## 5. Hyperparameter search

**Status:** `<TBD — sprint step 5>`

---

## 6. Final fit

**Status:** `<TBD — sprint step 6>`

---

## 7. Normalization fit

**Status:** `<TBD — sprint step 7>`

---

## 8. Test-set evaluation

**Status:** `<TBD — sprint step 8>`

---

## 9. Persistence

**Status:** `<TBD — sprint step 9>`

---

## 10. Reporting

**Status:** `<TBD — sprint step 10>`

---

## 11. Decision

**Status:** `<TBD — sprint step 11>`
