"""core sprint schema: observations, scoring, transitions

Revision ID: 0002_crog_ai_core_schema
Revises: 0001_crog_ai_baseline
Create Date: 2026-04-26

Three-stage pipeline architecture:

    Stage 1 — Ingestion / Calibration corpus
    hedge_fund.market_club_observations  ← what INO MarketClub told us
              │
              ▼
    Stage 2 — Dochia engine computes its own signals
    hedge_fund.signal_scores              ← Dochia component states
              │
              ▼
    Stage 3 — Promoted to canonical output
    hedge_fund.market_signals             ← legacy table; downstream contract

`market_signals` already exists (1,105 legacy LLM-extracted rows). This
migration does NOT touch it. A future migration will extend it for
dual-tenancy with source_pipeline / dochia_version columns.

Tables this migration creates (all in hedge_fund):
  parser_runs, market_club_observations, scoring_parameters,
  tickers_universe, eod_bars (partitioned), corporate_actions,
  signal_scores, signal_transitions

View: v_signal_scores_composite
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0002_crog_ai_core_schema"
down_revision: str | None = "0001_crog_ai_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # parser_runs — audit trail for every loader invocation
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE hedge_fund.parser_runs (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            run_name            TEXT        NOT NULL,
            source_corpus       TEXT        NOT NULL
                                CHECK (source_corpus IN (
                                    'nas_processed', 'nas_failed',
                                    'email_archive', 'imap_live'
                                )),
            parser_version      TEXT        NOT NULL,
            git_sha             TEXT,
            host                TEXT,
            status              TEXT        NOT NULL DEFAULT 'running'
                                CHECK (status IN ('running', 'completed', 'failed')),
            files_scanned       INTEGER     NOT NULL DEFAULT 0,
            files_skipped_dedup INTEGER     NOT NULL DEFAULT 0,
            observations_inserted INTEGER   NOT NULL DEFAULT 0,
            parse_errors        INTEGER     NOT NULL DEFAULT 0,
            error_summary       JSONB,
            jsonl_audit_path    TEXT,
            started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at        TIMESTAMPTZ,
            duration_seconds    NUMERIC(10,3)
        )
        """
    )
    op.create_index(
        "ix_parser_runs_corpus_started",
        "parser_runs",
        ["source_corpus", "started_at"],
        schema="hedge_fund",
    )
    op.create_index(
        "ix_parser_runs_status",
        "parser_runs",
        ["status", "started_at"],
        schema="hedge_fund",
    )

    # ------------------------------------------------------------------
    # market_club_observations — calibration corpus
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE hedge_fund.market_club_observations (
            id                  BIGSERIAL   PRIMARY KEY,
            observation_hash    TEXT        NOT NULL UNIQUE,
            source_corpus       TEXT        NOT NULL
                                CHECK (source_corpus IN (
                                    'nas_processed', 'nas_failed',
                                    'email_archive', 'imap_live'
                                )),
            source_reference    TEXT        NOT NULL,
            source_external_id  TEXT,
            source_email_id     INTEGER,
            parser_run_id       UUID        NOT NULL
                                REFERENCES hedge_fund.parser_runs(id),
            ticker              VARCHAR(10) NOT NULL,
            exchange            VARCHAR(20),
            triangle_color      TEXT        NOT NULL
                                CHECK (triangle_color IN ('green', 'red')),
            timeframe           TEXT        NOT NULL
                                CHECK (timeframe IN ('monthly', 'weekly', 'daily')),
            score               SMALLINT    NOT NULL
                                CHECK (score BETWEEN -100 AND 100),
            last_price          NUMERIC(12,4),
            net_change          NUMERIC(12,4),
            net_change_pct      NUMERIC(8,4),
            volume              BIGINT,
            open_price          NUMERIC(12,4),
            day_high            NUMERIC(12,4),
            day_low             NUMERIC(12,4),
            prev_close          NUMERIC(12,4),
            alert_timestamp_utc TIMESTAMPTZ NOT NULL,
            trading_day         DATE        NOT NULL,
            ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            raw_subject         TEXT        NOT NULL,
            raw_body_text       TEXT,
            raw_json_path       TEXT,
            parse_warnings      JSONB
        )
        """
    )
    op.create_index(
        "ix_mco_ticker_day",
        "market_club_observations",
        ["ticker", "trading_day"],
        schema="hedge_fund",
    )
    op.create_index(
        "ix_mco_timeframe_day",
        "market_club_observations",
        ["timeframe", "trading_day"],
        schema="hedge_fund",
    )
    op.create_index(
        "ix_mco_score",
        "market_club_observations",
        ["score", "trading_day"],
        schema="hedge_fund",
    )
    op.create_index(
        "ix_mco_source",
        "market_club_observations",
        ["source_corpus", "ingested_at"],
        schema="hedge_fund",
    )
    op.create_index(
        "ix_mco_external_id",
        "market_club_observations",
        ["source_external_id"],
        schema="hedge_fund",
    )

    # ------------------------------------------------------------------
    # scoring_parameters — Dochia parameter sets
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE hedge_fund.scoring_parameters (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name                    TEXT        NOT NULL UNIQUE,
            dochia_version          TEXT        NOT NULL,
            description             TEXT,
            monthly_lookback_days   INTEGER     NOT NULL DEFAULT 63,
            weekly_lookback_days    INTEGER     NOT NULL DEFAULT 15,
            daily_lookback_days     INTEGER     NOT NULL DEFAULT 3,
            macd_fast               INTEGER     NOT NULL DEFAULT 12,
            macd_slow               INTEGER     NOT NULL DEFAULT 26,
            macd_signal             INTEGER     NOT NULL DEFAULT 9,
            weight_monthly          INTEGER     NOT NULL DEFAULT 40,
            weight_weekly           INTEGER     NOT NULL DEFAULT 25,
            weight_daily            INTEGER     NOT NULL DEFAULT 15,
            weight_momentum         INTEGER     NOT NULL DEFAULT 20,
            min_close_price         NUMERIC(12,4) NOT NULL DEFAULT 5.00,
            min_adv_50              BIGINT      NOT NULL DEFAULT 500000,
            is_active               BOOLEAN     NOT NULL DEFAULT FALSE,
            is_production           BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            calibrated_at           TIMESTAMPTZ,
            CHECK (weight_monthly + weight_weekly + weight_daily + weight_momentum = 100),
            CHECK (monthly_lookback_days > weekly_lookback_days),
            CHECK (weekly_lookback_days > daily_lookback_days)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ix_scoring_parameters_production
        ON hedge_fund.scoring_parameters (is_production)
        WHERE is_production = TRUE
        """
    )
    op.execute(
        """
        INSERT INTO hedge_fund.scoring_parameters (
            name, dochia_version, description, is_active, is_production
        ) VALUES (
            'dochia_v0_estimated',
            'v0',
            'Bootstrap weights (40/25/15/20 Monthly/Weekly/Daily/Momentum). '
            'Estimated from public INO MarketClub Trade Triangle behavior. '
            'Replaced by dochia_v1_calibrated after calibration against the '
            '~22k INO observation corpus completes.',
            TRUE,
            TRUE
        )
        """
    )

    # ------------------------------------------------------------------
    # tickers_universe — daily snapshot for survivorship integrity
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE hedge_fund.tickers_universe (
            ticker              TEXT        NOT NULL,
            as_of_date          DATE        NOT NULL,
            asset_class         TEXT        NOT NULL
                                CHECK (asset_class IN ('stock', 'etf')),
            primary_exchange    TEXT        NOT NULL,
            name                TEXT        NOT NULL,
            is_active           BOOLEAN     NOT NULL DEFAULT TRUE,
            delisted_date       DATE,
            cik                 TEXT,
            figi                TEXT,
            ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (ticker, as_of_date)
        )
        """
    )
    op.create_index(
        "ix_tickers_universe_as_of_active",
        "tickers_universe",
        ["as_of_date", "is_active"],
        schema="hedge_fund",
    )

    # ------------------------------------------------------------------
    # eod_bars — OHLCV history, partitioned by month
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE hedge_fund.eod_bars (
            ticker              TEXT        NOT NULL,
            bar_date            DATE        NOT NULL,
            open                NUMERIC(12,4) NOT NULL,
            high                NUMERIC(12,4) NOT NULL,
            low                 NUMERIC(12,4) NOT NULL,
            close               NUMERIC(12,4) NOT NULL,
            volume              BIGINT      NOT NULL,
            vwap                NUMERIC(12,4),
            adjusted_close      NUMERIC(12,4) NOT NULL,
            split_factor        NUMERIC(12,8) NOT NULL DEFAULT 1.0,
            dividend_cash       NUMERIC(12,4) NOT NULL DEFAULT 0,
            source_vendor       TEXT        NOT NULL,
            ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (ticker, bar_date),
            CHECK (high >= low),
            CHECK (high >= open AND high >= close),
            CHECK (low  <= open AND low  <= close),
            CHECK (volume >= 0)
        ) PARTITION BY RANGE (bar_date)
        """
    )
    for year in (2024, 2025, 2026, 2027):
        for month in range(1, 13):
            if year == 2024 and month < 9:
                continue
            next_month = month + 1
            next_year = year
            if next_month == 13:
                next_month = 1
                next_year = year + 1
            op.execute(
                f"""
                CREATE TABLE hedge_fund.eod_bars_{year}_{month:02d}
                PARTITION OF hedge_fund.eod_bars
                FOR VALUES FROM ('{year}-{month:02d}-01')
                           TO   ('{next_year}-{next_month:02d}-01')
                """
            )
    op.create_index(
        "ix_eod_bars_date_ticker",
        "eod_bars",
        ["bar_date", "ticker"],
        schema="hedge_fund",
    )

    # ------------------------------------------------------------------
    # corporate_actions
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE hedge_fund.corporate_actions (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            ticker              TEXT        NOT NULL,
            action_type         TEXT        NOT NULL
                                CHECK (action_type IN (
                                    'split', 'cash_dividend', 'stock_dividend',
                                    'symbol_change', 'delisting', 'spinoff'
                                )),
            ex_date             DATE        NOT NULL,
            record_date         DATE,
            payable_date        DATE,
            numeric_value       NUMERIC(18,8),
            new_ticker          TEXT,
            source_vendor       TEXT        NOT NULL,
            raw_payload         JSONB       NOT NULL,
            ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.create_index(
        "ix_corporate_actions_ticker_ex_date",
        "corporate_actions",
        ["ticker", "ex_date"],
        schema="hedge_fund",
    )

    # ------------------------------------------------------------------
    # signal_scores — Dochia component states
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE hedge_fund.signal_scores (
            ticker              TEXT        NOT NULL,
            bar_date            DATE        NOT NULL,
            parameter_set_id    UUID        NOT NULL
                                REFERENCES hedge_fund.scoring_parameters(id),
            monthly_state       SMALLINT    NOT NULL CHECK (monthly_state IN (-1, 0, 1)),
            weekly_state        SMALLINT    NOT NULL CHECK (weekly_state IN (-1, 0, 1)),
            daily_state         SMALLINT    NOT NULL CHECK (daily_state IN (-1, 0, 1)),
            momentum_state      SMALLINT    NOT NULL CHECK (momentum_state IN (-1, 0, 1)),
            monthly_channel_high NUMERIC(12,4),
            monthly_channel_low  NUMERIC(12,4),
            weekly_channel_high  NUMERIC(12,4),
            weekly_channel_low   NUMERIC(12,4),
            daily_channel_high   NUMERIC(12,4),
            daily_channel_low    NUMERIC(12,4),
            macd_histogram       NUMERIC(12,6),
            computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (ticker, bar_date, parameter_set_id)
        )
        """
    )
    op.create_index(
        "ix_signal_scores_date",
        "signal_scores",
        ["bar_date"],
        schema="hedge_fund",
    )

    # ------------------------------------------------------------------
    # signal_transitions — flagged events for command center
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE hedge_fund.signal_transitions (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            ticker                  TEXT        NOT NULL,
            parameter_set_id        UUID        NOT NULL
                                    REFERENCES hedge_fund.scoring_parameters(id),
            transition_type         TEXT        NOT NULL
                                    CHECK (transition_type IN (
                                        'peak_to_exit', 'exit_to_reentry',
                                        'full_reversal', 'breakout_bullish',
                                        'breakout_bearish'
                                    )),
            from_score              SMALLINT    NOT NULL,
            to_score                SMALLINT    NOT NULL,
            from_bar_date           DATE        NOT NULL,
            to_bar_date             DATE        NOT NULL,
            from_states             JSONB       NOT NULL,
            to_states               JSONB       NOT NULL,
            detected_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            acknowledged_by_user_id UUID,
            acknowledged_at         TIMESTAMPTZ,
            notes                   TEXT
        )
        """
    )
    op.create_index(
        "ix_signal_transitions_detected",
        "signal_transitions",
        ["detected_at"],
        schema="hedge_fund",
    )
    op.create_index(
        "ix_signal_transitions_ticker_param",
        "signal_transitions",
        ["ticker", "parameter_set_id", "to_bar_date"],
        schema="hedge_fund",
    )
    op.create_index(
        "ix_signal_transitions_type_date",
        "signal_transitions",
        ["transition_type", "to_bar_date"],
        schema="hedge_fund",
    )

    # ------------------------------------------------------------------
    # VIEW: composite score
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE VIEW hedge_fund.v_signal_scores_composite AS
        SELECT
            s.ticker,
            s.bar_date,
            s.parameter_set_id,
            p.name AS parameter_set_name,
            p.dochia_version,
            s.monthly_state,
            s.weekly_state,
            s.daily_state,
            s.momentum_state,
            (
                s.monthly_state  * p.weight_monthly +
                s.weekly_state   * p.weight_weekly +
                s.daily_state    * p.weight_daily +
                s.momentum_state * p.weight_momentum
            )::SMALLINT AS composite_score,
            s.computed_at
        FROM hedge_fund.signal_scores s
        JOIN hedge_fund.scoring_parameters p ON p.id = s.parameter_set_id
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS hedge_fund.v_signal_scores_composite")
    op.execute("DROP TABLE IF EXISTS hedge_fund.signal_transitions")
    op.execute("DROP TABLE IF EXISTS hedge_fund.signal_scores")
    op.execute("DROP TABLE IF EXISTS hedge_fund.corporate_actions")
    op.execute("DROP TABLE IF EXISTS hedge_fund.eod_bars CASCADE")
    op.execute("DROP TABLE IF EXISTS hedge_fund.tickers_universe")
    op.execute("DROP TABLE IF EXISTS hedge_fund.scoring_parameters CASCADE")
    op.execute("DROP TABLE IF EXISTS hedge_fund.market_club_observations")
    op.execute("DROP TABLE IF EXISTS hedge_fund.parser_runs")
