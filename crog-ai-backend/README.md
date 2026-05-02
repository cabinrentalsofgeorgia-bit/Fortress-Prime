# CROG-AI Backend

Backend for the CROG-AI command center at [crog-ai.com](https://crog-ai.com).
Includes the Market Club replacement signal pipeline (Dochia engine) for
the Financial division.

## Architecture

```
Vercel (React frontend at crog-ai.com)
        │
        ▼
Cloudflare Tunnel
        │
        ▼
FastAPI backend on spark-node-2:8xxx   ← this repo (future phases)
        │
        ▼
Postgres fortress_db, hedge_fund schema
```

### Three-stage signal pipeline

```
Stage 1 — Ingestion (this sprint)
hedge_fund.market_club_observations  ← what INO MarketClub told us (~22k corpus)
        │
        ▼
Stage 2 — Dochia engine (Phase 4+)
hedge_fund.signal_scores              ← Dochia component states
        │
        ▼
Stage 3 — Promoted output (existing legacy table)
hedge_fund.market_signals             ← downstream contract surface
```

Master Accounting reads from `market_signals`. Our staging tables are
implementation detail not visible to consumers.

### App-facing API

FastAPI entrypoint:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8026
```

Current Financial / Hedge Fund endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | backend health check |
| `GET /api/financial/signals/latest` | scanner-ready latest signal rows |
| `GET /api/financial/signals/transitions` | recent signal-change alert feed |
| `GET /api/financial/signals/watchlist-candidates` | portfolio-lens lanes with legacy watchlist context |
| `GET /api/financial/signals/{ticker}` | symbol-level latest score plus recent transitions |

Systemd service on spark-node-2:

```bash
sudo systemctl status crog-ai-backend.service
sudo systemctl restart crog-ai-backend.service
journalctl -u crog-ai-backend.service -f
```

The unit file is tracked at `deploy/systemd/crog-ai-backend.service` and
installed to `/etc/systemd/system/crog-ai-backend.service`.

Legacy Hedge Fund watchlist context is exposed read-only to the app role with:

```bash
sudo -u postgres psql -d fortress_db -c "
GRANT USAGE ON SCHEMA hedge_fund TO crog_ai_app;
GRANT SELECT ON TABLE
    hedge_fund.watchlist,
    hedge_fund.market_signals,
    hedge_fund.active_strategies
TO crog_ai_app;"
```

The same SQL is tracked at `deploy/sql/marketclub_legacy_read_grants.sql`.

## Relationship to Fortress-Prime

This project lives at `~/Fortress-Prime/crog-ai-backend/` but maintains
its own independent Alembic chain. It does NOT share migrations with
`fortress-guest-platform/backend/alembic/`.

Why:
- The fortress-guest-platform chain is currently broken (fails to load).
- That chain targets `fortress_prod`; we need `fortress_db`.
- Different release cycles (Vercel command center vs. guest platform).

Our chain uses `hedge_fund.alembic_version_crog_ai` for version tracking,
coexisting with the orphan `public.alembic_version` in `fortress_db`.

## Bring-up sequence

### 1. Bootstrap the Postgres role

```bash
cd ~/Fortress-Prime/crog-ai-backend
sudo -u postgres psql -d fortress_db -f sql/00_bootstrap_user.sql
```

Generate a strong password and set it:

```bash
CROG_PW=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
echo "Save this password: $CROG_PW"
sudo -u postgres psql -d fortress_db \
    -c "ALTER ROLE crog_ai_app WITH PASSWORD '$CROG_PW'"
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set CROG_AI_DB_PASSWORD to the password from step 1
```

Verify:

```bash
set -a; source .env; set +a
echo "$DATABASE_URL"   # should be fully expanded
```

### 3. Install Python dependencies

```bash
uv sync
```

### 4. Apply migrations

```bash
uv run alembic upgrade head
```

Verify:

```bash
sudo -u postgres psql -d fortress_db -c "\dt hedge_fund.*"
```

You should see the legacy tables (`market_signals`, `extraction_log`,
`active_strategies`, `watchlist`) plus the new sprint tables
(`market_club_observations`, `parser_runs`, `scoring_parameters`,
`tickers_universe`, `eod_bars`, `corporate_actions`, `signal_scores`,
`signal_transitions`) and the version tracker
(`alembic_version_crog_ai`).

### 5. Run Phase 1 NAS loader

Dry run first to validate parsing without DB writes:

```bash
uv run python scripts/phase1_nas_loader.py --dry-run --limit 100
```

If clean, run for real:

```bash
uv run python scripts/phase1_nas_loader.py
```

Expected: ~22k observations inserted across both source corpora,
~5-15 minutes runtime depending on disk speed.

Audit:

```bash
sudo -u postgres psql -d fortress_db -c "
SELECT
    source_corpus,
    files_scanned,
    observations_inserted,
    files_skipped_dedup,
    parse_errors,
    duration_seconds,
    status
FROM hedge_fund.parser_runs
ORDER BY started_at DESC LIMIT 10"
```

```bash
sudo -u postgres psql -d fortress_db -c "
SELECT
    source_corpus,
    COUNT(*) AS observations,
    COUNT(DISTINCT ticker) AS unique_tickers,
    MIN(trading_day) AS earliest,
    MAX(trading_day) AS latest
FROM hedge_fund.market_club_observations
GROUP BY source_corpus"
```

### 6. Run Phase 3 IMAP harvester (recovers weekly/monthly Trade Triangles)

The NAS corpus is daily-only. Weekly and monthly Trade Triangles live
exclusively in `gary@garyknight.com` Gmail. Phase 3 pulls them via IMAP.

#### One-time Gmail setup

1. Confirm 2-Factor Authentication is enabled on the Google account.
2. Generate an App Password at https://myaccount.google.com/apppasswords
   (label it "CROG-AI Phase 3").
3. Paste into `.env`:
   ```
   IMAP_USERNAME=gary@garyknight.com
   IMAP_PASSWORD=<the-16-char-app-password>
   ```

#### Dry run first (read-only, no DB writes)

```bash
uv run python scripts/phase3_imap_harvester.py --dry-run --limit 50
```

What you're watching for:
- `preflight_passed` event (auth works, DB reachable)
- `imap_login_success` event
- ~50 lines showing classifier decisions per message
- `would_insert` events for messages categorized as `trade_triangle_alert`
- `harvester_complete` summary with category_counts breakdown

#### Live harvest

```bash
# Last 30 days (validation pass)
uv run python scripts/phase3_imap_harvester.py --since 2026-03-26

# Full historical
uv run python scripts/phase3_imap_harvester.py
```

Expected: 30k-50k INO emails scanned over 30-60 minutes. Of those:
- ~16k Trade Triangle alerts that match Phase 1 NAS rows → dedup-skip
- New weekly/monthly Trade Triangles → INSERT
- Daily Trade Triangles after Jan 16 2026 (post-NAS-corpus) → INSERT
- Triangle Reports / passwords / marketing → classifier-skip

The harvester is **read-only on Gmail**: messages are never marked-read,
labeled, moved, or deleted. Server-side state is identical before and after.

Resumability: if the harvester crashes or is killed, the next run picks
up where it left off via dedup on observation_hash. Re-running over the
same date range is safe and idempotent.

#### Audit

```bash
sudo -u postgres psql -d fortress_db -c "
SELECT source_corpus, timeframe, COUNT(*)
FROM hedge_fund.market_club_observations
GROUP BY source_corpus, timeframe
ORDER BY source_corpus, timeframe"
```

Expected after full historical harvest:
- `nas_processed | daily   | ~15,950`  (unchanged from Phase 1)
- `imap_live     | daily   | ~few hundred` (Jan 17 → today, post-NAS-cutoff)
- `imap_live     | weekly  | many`
- `imap_live     | monthly | some`

## Spark 3 cutover plan

This project lives on Spark 2 today as a temporary tenant. When Spark 3
is provisioned, the move:

| Asset | Spark 2 (today) | Spark 3 (after cutover) |
|---|---|---|
| Postgres | `fortress_db` on `127.0.0.1:5432` | New DB on Spark 3 host |
| `.env` `DATABASE_URL` | `127.0.0.1:5432/fortress_db` | `<spark3>:5432/<new-db>` |
| `.env` `NAS_*_PATH` | unchanged (NFS shared) | unchanged |
| Codebase | `~/Fortress-Prime/crog-ai-backend/` | `~/crog-ai-backend/` |

### Cutover steps

1. **Provision Spark 3 Postgres** — version 16 matched, similar tuning.
2. **Run bootstrap SQL** to create `crog_ai_app` role.
3. **Run Alembic migrations** to create schema fresh on Spark 3.
4. **Backfill data** Spark 2 → Spark 3:
   ```bash
   pg_dump -h <spark2> -d fortress_db -n hedge_fund \
       --table=hedge_fund.market_club_observations \
       --table=hedge_fund.parser_runs \
       --table=hedge_fund.scoring_parameters \
       --table=hedge_fund.signal_scores \
       --table=hedge_fund.signal_transitions \
       --table=hedge_fund.tickers_universe \
       --table=hedge_fund.eod_bars \
       --table=hedge_fund.corporate_actions \
       | psql -h <spark3> -d <new-db>
   ```
5. **Update `.env`** on Spark 3.
6. **Sanity check** row counts match between hosts.
7. **Start services** on Spark 3.
8. **Stop services** on Spark 2 that touch `hedge_fund`.
9. **Verification window** 24-48 hours.
10. **Drop hedge_fund** from Spark 2 only after operator confirmation.

### Rollback

Until step 10, Spark 2's hedge_fund is intact and can resume writes.
Reverting: stop Spark 3 services, restart Spark 2 services, restore
`.env` to localhost. Max data loss = verification window writes.

## Operational notes

- **Partition auto-extension**: `eod_bars` has partitions through end of
  2027. Schedule pg_partman or monthly cron before that boundary.
- **Backups**: piggybacks on Fortress-Prime's nightly `backup_db.sh`
  until Spark 3 cutover.
- **Monitoring**: query `hedge_fund.parser_runs` for ingestion health.

## Development

```bash
uv run ruff check .
uv run ruff format .
uv run mypy .
uv run pytest
```

## Gotchas discovered during audit (April 17-26, 2026)

- `fortress_db` has an orphan `public.alembic_version` from an older
  codebase. We do NOT write to it.
- `miner_bot` role has a hardcoded password in legacy market files. Should
  be rotated post-sprint; not used by this project.
- The fortress-guest-platform Alembic chain is broken; we use this
  standalone chain instead.
- `market_watcher.py`, `market_sentinel.py`, `ingest_market_imap.py`
  cron jobs have been failing silently since February. Out-of-scope.
- `watchtower_briefing.py` exists but fails on missing DB password.
  Separate concern; post-sprint cleanup.
