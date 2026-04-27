# ADR-0001: Sprint Schema Design

**Status:** Accepted
**Date:** 2026-04-26
**Scope:** CROG-AI backend, Phase 0/1 sprint scaffolding

## Context

INO.com's MarketClub Trade Triangles service shut down. The CROG-AI command
center needs an in-house signal engine (codenamed **Dochia**) to replace it,
calibrated against the ~22k historical alerts harvested before shutdown.

This ADR documents schema decisions made for Phase 0 (foundation) + Phase 1
(NAS corpus ingestion), with explicit forward-compatibility hooks for the
enhancement layers (volatility-adaptive lookbacks, context filters, LLM
sentiment overlay, correlation-aware position sizing) deferred to post-sprint.

## Decision 1: Standalone Alembic chain

The CROG-AI backend runs its own Alembic chain independent of
`fortress-guest-platform/backend/alembic/`. Version tracking uses
`hedge_fund.alembic_version_crog_ai`.

**Rationale:**
- The fortress-guest-platform chain is broken (fails to load — multi-branch
  merges plus a 78KB "emergency_schema_fix" migration). Adding to it inherits
  the breakage.
- That chain targets `fortress_prod`. We need `fortress_db`.
- Frontend is Vercel/Cloudflare hosted at crog-ai.com, architecturally
  separate from the guest platform. Coupling release cycles is wrong.

## Decision 2: All new tables in `hedge_fund` schema

Extend the existing `hedge_fund` schema which already has legacy
`market_signals`, `extraction_log`, `active_strategies`, `watchlist`. Don't
create a new schema.

**Rationale:**
- `hedge_fund` was created for exactly this purpose. The legacy tables are
  artifacts of an earlier attempt at the same project.
- A new schema duplicates the concept without adding isolation value.

## Decision 3: Three-stage pipeline architecture

```
Stage 1: market_club_observations  ← parsed INO alerts (calibration corpus)
Stage 2: signal_scores             ← Dochia component states from EOD bars
Stage 3: market_signals (legacy)   ← canonical output, downstream contract
```

**Rationale:**
- Master Accounting reads from `market_signals`. That's the contract surface.
- Our staging tables are implementation detail. Don't break the contract.
- Stage 1 = what INO told us. Stage 2 = what Dochia says. Stage 3 = the
  promotion path. Clear separation, distinct testability per stage.

A future migration (deferred) extends `market_signals` for dual-tenancy:
adds `dochia_version`, `parameter_set_id`, `source_pipeline` columns so
legacy LLM rows and new Dochia rows coexist distinguishably.

## Decision 4: Scoped `crog_ai_app` role

A new Postgres role with `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
NOREPLICATION`, granted:
- `CONNECT` on `fortress_db`
- `USAGE, CREATE` on `hedge_fund`
- `USAGE` on `public` (required for cross-schema reference)
- `SELECT` on `public.email_archive` (one table only — needed for Phase 2)

**Rationale:**
- Fortress-Prime's `fortress_db` hosts guest platform, legal system, financial
  data, and mining intelligence. A compromise of CROG-AI code can't be allowed
  to damage those.
- `miner_bot` has broad access and a password hardcoded in legacy files —
  not trustworthy.

## Decision 5: Component scores stored separately; composite computed in view

`signal_scores` stores four SMALLINT columns (`monthly_state`, `weekly_state`,
`daily_state`, `momentum_state`), each -1/0/+1. The composite -100..+100
score is computed in `v_signal_scores_composite` by joining with
`scoring_parameters`.

**Rationale:**
- Weight retuning requires zero data backfill.
- When `dochia_v1_calibrated` lands, historical scores under
  `dochia_v0_estimated` remain comparable via the same view.
- Forensic queries become trivial because component state is addressable.

## Decision 6: Partitioning `eod_bars` by month

`eod_bars` partitioned by RANGE on `bar_date`, monthly partitions pre-created
Sept 2024 → end of 2027.

**Rationale:**
- Donchian calc requires 63-day range scans per ticker. Partition pruning
  on `bar_date` makes those reads efficient.
- Monthly partitions (~170k rows each at full universe) are small enough to
  keep indexes memory-resident per partition.

**Operational requirement:** partition auto-extension scheduled before 2027
(pg_partman or cron). If forgotten, ingestion fails with "no partition found".

## Decision 7: NUMERIC, never FLOAT, for money

All monetary values use `NUMERIC(12,4)`. Weight percentages use `INTEGER`.
Volumes use `BIGINT`.

**Rationale:**
- Floating-point accumulator error on millions of P&L calculations is
  unacceptable.
- Industry standard for financial systems.

## Decision 8: TIMESTAMPTZ everywhere

All timestamps are TIMESTAMPTZ. No naive `TIMESTAMP`.

**Rationale:** Market Club alerts arrive UTC; market data spans exchanges
with local conventions; IMAP fetch logs come from server local time.
TIMESTAMPTZ normalizes everything.

## Decision 9: Bootstrap `dochia_v0_estimated` parameter set

Migration seeds one row in `scoring_parameters` with guessed weights:
40/25/15/20 for Monthly/Weekly/Daily/Momentum, classic 63/15/3 Donchian,
MACD 12/26/9.

**Rationale:**
- Scoring engine needs *some* parameter set FK'd from `signal_scores`.
- Flagged `is_production = TRUE` so the engine uses it by default.
- Replaced (or augmented) by `dochia_v1_calibrated` after the 22k-observation
  calibration runs.

## Decision 10: Cross-schema FK NOT created

`market_club_observations.source_email_id` references
`public.email_archive(id)` but **no FK constraint** is created.

**Rationale:**
- `crog_ai_app` has SELECT-only on `public.email_archive`. A FK would require
  REFERENCES privilege which implies write access.
- Cross-schema FKs couple deployment.
- Referential integrity enforced at the application layer.

## Decision 11: Idempotent dedup via composite hash

`observation_hash` is SHA-256 of:
```
ticker | alert_timestamp_utc | triangle_color | timeframe | score | source_external_id
```

Where `source_external_id` is `meta.id` for NAS JSONs (precomputed by the
old ingester) or RFC 5322 `Message-Id` for email-sourced rows.

**Rationale:**
- Signal-identity tuple collapses same-alert-via-different-routes.
- `source_external_id` portion preserves true duplicates with distinct IDs.
- `ON CONFLICT (observation_hash) DO NOTHING` makes loaders trivially
  idempotent.

## Consequences

**Positive:**
- Clean separation from broken Fortress-Prime chain
- Scoped permissions limit blast radius
- Parameter set versioning supports rigorous calibration
- Forward-compatible — enhancement layers extend without rebuild
- Idempotent loaders are safely re-runnable

**Negative:**
- Two Alembic chains in one DB (not really negative — different cycles)
- Partition management requires ops automation
- View-computed composite has small query-time cost

**Risks:**
- If `crog_ai_app` password leaks to git, we've learned nothing from
  `miner_bot`. `.gitignore` includes `.env`; enforce in code review.
- Forgotten partition extension breaks ingestion in 2027. README flags this.

## Amendment 2026-04-26 — cross-source dedup hash

After Phase 1 NAS load completed, audit revealed all 22k NAS-corpus
files are daily Trade Triangles. Weekly and monthly tiers live only in
Gmail. Phase 3 IMAP harvester pulls them — but the same daily alert
also exists in Gmail and would duplicate against NAS rows unless
hashes are cross-source compatible.

**Decision:** drop `source_external_id` from `observation_hash`.

**Rationale:** dedup priority is "same alert = same row regardless of
source." The signal-identity tuple `(ticker, alert_timestamp_utc,
color, timeframe, score)` uniquely identifies an INO alert; the
`meta.id` (NAS) and `Message-Id` (IMAP) for the same alert are
necessarily different but logically refer to the same event.

**Implementation (migration 0003):**
- Drop UNIQUE constraint
- Recompute hash on all 15,950 existing rows using new formula
- Defensive de-dup (lowest id wins in any collision)
- Re-add UNIQUE constraint

**Architectural invariant** (verified in smoke test):
The hash formula in `app/intake/parser.py`, `scripts/phase1_nas_loader.py`,
and migration 0003 SQL must produce byte-identical output for the same
inputs. Any change to one requires changes to all three.

**Tradeoff accepted:** lose ability to detect parser disagreement
between NAS and IMAP for the same alert (would surface as duplicate
attempt → conflict → audit log). One-off verification queries can be
run if needed.

---

## Amendment 2026-04-27 — Dochia v1 architecture (daily-only)

After Phase 3 IMAP harvest completed, full corpus inspection (24,204
observations across NAS + IMAP) confirmed INO MarketClub ships only
daily Trade Triangles via the gary@garyknight.com subscription. Weekly
and monthly Trade Triangles do NOT exist in the source data. The IMAP
probe across the full mailbox returned zero matches for "Weekly Trade
Triangle" or "Monthly Trade Triangle" subjects from any sender.

This invalidates the original Dochia design assumption that calibration
would fit weights for all four components (monthly/weekly/daily/momentum
at 40/25/15/20).

**Decision:** Dochia v1 calibrates as daily-only.

- New parameter set: `dochia_v1_daily_only`
- Weights: monthly=0, weekly=0, daily=70, momentum=30
- Calibration corpus: 24,204 daily observations from 2024-03-18 to
  2026-04-21
- Composite formula and view (`v_signal_scores_composite`) unchanged —
  the multi-tier weighted-sum architecture remains. Only this parameter
  set sets monthly/weekly to zero.

**Rationale for honest naming over silent zero-fill:**
The parameter_set_id explicitly contains "daily_only" so consumers
selecting parameters cannot mistake v1 for a multi-tier model. This
prevents downstream code from reading the composite as "calibrated
across four timeframes" when it's actually calibrated across one.

**Future v2 path (NOT this sprint):**
When weekly/monthly truth becomes available — most likely via Polygon.io
EOD bars synthesizing Donchian channels at higher timeframes — a
`dochia_v2_multi_tier` parameter set can be calibrated and weights
revert to the v0 estimate or whatever the data fits. The schema and
view do not change. Only a new row in `scoring_parameters`.

**Tradeoff accepted:** No multi-timeframe alignment signal in v1. A
Green Daily Trade Triangle in a stock with Red Monthly trend produces
the same composite as a Green Daily in a Green Monthly stock. Real
signal lost; recovered when v2 ships.

**Calibration methodology (TBD):**
The actual fit method (logistic regression, gradient boosting,
constrained optimization, etc.) is deferred to the calibration sprint
ADR. This amendment locks only the *architecture* — daily-only,
parameter set name, weight schema. Methodology gets its own ADR before
fitting code runs.
