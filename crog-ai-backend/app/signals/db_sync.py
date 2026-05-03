"""Database sync helpers for Dochia signal scores."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.signals.db_preview import SignalScorePreview, SignalTransitionPreview

UPSERT_SIGNAL_SCORE_SQL = """
INSERT INTO hedge_fund.signal_scores (
    ticker,
    bar_date,
    parameter_set_id,
    monthly_state,
    weekly_state,
    daily_state,
    momentum_state,
    monthly_channel_high,
    monthly_channel_low,
    weekly_channel_high,
    weekly_channel_low,
    daily_channel_high,
    daily_channel_low,
    macd_histogram,
    computed_at
) VALUES (
    %(ticker)s,
    %(bar_date)s,
    %(parameter_set_id)s,
    %(monthly_state)s,
    %(weekly_state)s,
    %(daily_state)s,
    %(momentum_state)s,
    %(monthly_channel_high)s,
    %(monthly_channel_low)s,
    %(weekly_channel_high)s,
    %(weekly_channel_low)s,
    %(daily_channel_high)s,
    %(daily_channel_low)s,
    %(macd_histogram)s,
    now()
)
ON CONFLICT (ticker, bar_date, parameter_set_id)
DO UPDATE SET
    monthly_state = EXCLUDED.monthly_state,
    weekly_state = EXCLUDED.weekly_state,
    daily_state = EXCLUDED.daily_state,
    momentum_state = EXCLUDED.momentum_state,
    monthly_channel_high = EXCLUDED.monthly_channel_high,
    monthly_channel_low = EXCLUDED.monthly_channel_low,
    weekly_channel_high = EXCLUDED.weekly_channel_high,
    weekly_channel_low = EXCLUDED.weekly_channel_low,
    daily_channel_high = EXCLUDED.daily_channel_high,
    daily_channel_low = EXCLUDED.daily_channel_low,
    macd_histogram = EXCLUDED.macd_histogram,
    computed_at = now()
"""


INSERT_SIGNAL_TRANSITION_SQL = """
INSERT INTO hedge_fund.signal_transitions (
    ticker,
    parameter_set_id,
    transition_type,
    from_score,
    to_score,
    from_bar_date,
    to_bar_date,
    from_states,
    to_states,
    detected_at,
    notes
)
SELECT
    %(ticker)s,
    %(parameter_set_id)s,
    %(transition_type)s,
    %(from_score)s,
    %(to_score)s,
    %(from_bar_date)s,
    %(to_bar_date)s,
    %(from_states)s,
    %(to_states)s,
    now(),
    %(notes)s
WHERE NOT EXISTS (
    SELECT 1
    FROM hedge_fund.signal_transitions
    WHERE ticker = %(ticker)s
      AND parameter_set_id = %(parameter_set_id)s
      AND transition_type = %(transition_type)s
      AND from_score = %(from_score)s
      AND to_score = %(to_score)s
      AND from_bar_date = %(from_bar_date)s
      AND to_bar_date = %(to_bar_date)s
      AND from_states = %(from_states)s
      AND to_states = %(to_states)s
)
"""


def signal_score_params(
    preview: SignalScorePreview,
    *,
    parameter_set_id: UUID | str,
) -> dict[str, Any]:
    """Map a preview row to the hedge_fund.signal_scores write shape."""
    return {
        "ticker": preview.ticker,
        "bar_date": preview.bar_date,
        "parameter_set_id": parameter_set_id,
        "monthly_state": preview.monthly_state,
        "weekly_state": preview.weekly_state,
        "daily_state": preview.daily_state,
        "momentum_state": preview.momentum_state,
        "monthly_channel_high": preview.monthly_channel_high,
        "monthly_channel_low": preview.monthly_channel_low,
        "weekly_channel_high": preview.weekly_channel_high,
        "weekly_channel_low": preview.weekly_channel_low,
        "daily_channel_high": preview.daily_channel_high,
        "daily_channel_low": preview.daily_channel_low,
        "macd_histogram": None,
    }


def signal_transition_params(
    preview: SignalTransitionPreview,
    *,
    parameter_set_id: UUID | str,
) -> dict[str, Any]:
    """Map a transition preview to the hedge_fund.signal_transitions write shape."""
    return {
        "ticker": preview.ticker,
        "parameter_set_id": parameter_set_id,
        "transition_type": preview.transition_type,
        "from_score": preview.from_score,
        "to_score": preview.to_score,
        "from_bar_date": preview.from_bar_date,
        "to_bar_date": preview.to_bar_date,
        "from_states": Jsonb(preview.from_states),
        "to_states": Jsonb(preview.to_states),
        "notes": preview.notes,
    }
