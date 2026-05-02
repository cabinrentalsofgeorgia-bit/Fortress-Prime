"""Read-only preview helpers for Dochia signal-score rows."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from app.signals.trade_triangles import (
    EodBar,
    TriangleEvent,
    TriangleSnapshot,
    TriangleState,
    TriangleTimeframe,
)


@dataclass(frozen=True, slots=True)
class SignalScorePreview:
    ticker: str
    bar_date: str
    parameter_set_name: str
    monthly_state: int
    weekly_state: int
    daily_state: int
    momentum_state: int
    composite_score: int
    monthly_channel_high: Decimal | None
    monthly_channel_low: Decimal | None
    weekly_channel_high: Decimal | None
    weekly_channel_low: Decimal | None
    daily_channel_high: Decimal | None
    daily_channel_low: Decimal | None
    event_count: int

    def as_json_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key, value in list(out.items()):
            if isinstance(value, Decimal):
                out[key] = str(value)
        return out


@dataclass(frozen=True, slots=True)
class SignalTransitionPreview:
    ticker: str
    parameter_set_name: str
    transition_type: str
    from_score: int
    to_score: int
    from_bar_date: str
    to_bar_date: str
    from_states: dict[str, int]
    to_states: dict[str, int]
    notes: str

    def as_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_psycopg_url(url: str) -> str:
    """Convert SQLAlchemy's psycopg URL scheme into psycopg's URL scheme."""
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url.removeprefix("postgresql+psycopg://")
    if url.startswith("postgresql+psycopg:"):
        return "postgresql:" + url.removeprefix("postgresql+psycopg:")
    return url


def eod_row_to_bar(row: dict[str, Any]) -> EodBar:
    return EodBar(
        ticker=str(row["ticker"]),
        bar_date=row["bar_date"],
        open=Decimal(row["open"]),
        high=Decimal(row["high"]),
        low=Decimal(row["low"]),
        close=Decimal(row["close"]),
        volume=int(row["volume"]) if row.get("volume") is not None else None,
    )


def _state_score(
    states: dict[str, int],
    *,
    monthly_weight: int,
    weekly_weight: int,
    daily_weight: int,
    momentum_weight: int,
) -> int:
    return (
        states["monthly"] * monthly_weight
        + states["weekly"] * weekly_weight
        + states["daily"] * daily_weight
        + states.get("momentum", 0) * momentum_weight
    )


def _transition_type(event: TriangleEvent, from_score: int, to_score: int) -> str:
    if (from_score < 0 < to_score) or (from_score > 0 > to_score):
        return "full_reversal"
    if event.state is TriangleState.GREEN:
        if from_score <= 0 < to_score:
            return "exit_to_reentry"
        return "breakout_bullish"
    if event.state is TriangleState.RED:
        if from_score > 0 >= to_score:
            return "peak_to_exit"
        return "breakout_bearish"
    raise ValueError(f"unsupported triangle event state: {event.state}")


def transition_previews_from_snapshot(
    snapshot: TriangleSnapshot,
    *,
    parameter_set_name: str,
    monthly_weight: int,
    weekly_weight: int,
    daily_weight: int,
    momentum_weight: int,
    since: dt.date | None = None,
) -> list[SignalTransitionPreview]:
    states = {"monthly": 0, "weekly": 0, "daily": 0, "momentum": 0}
    current_score = _state_score(
        states,
        monthly_weight=monthly_weight,
        weekly_weight=weekly_weight,
        daily_weight=daily_weight,
        momentum_weight=momentum_weight,
    )
    previous_bar_date = snapshot.events[0].bar_date if snapshot.events else snapshot.bar_date
    previews: list[SignalTransitionPreview] = []

    state_key_by_timeframe = {
        TriangleTimeframe.MONTHLY: "monthly",
        TriangleTimeframe.WEEKLY: "weekly",
        TriangleTimeframe.DAILY: "daily",
    }

    for event in snapshot.events:
        from_states = states.copy()
        from_score = current_score
        states[state_key_by_timeframe[event.timeframe]] = event.state.numeric
        to_states = states.copy()
        to_score = _state_score(
            states,
            monthly_weight=monthly_weight,
            weekly_weight=weekly_weight,
            daily_weight=daily_weight,
            momentum_weight=momentum_weight,
        )

        if since is None or event.bar_date >= since:
            previews.append(
                SignalTransitionPreview(
                    ticker=snapshot.ticker,
                    parameter_set_name=parameter_set_name,
                    transition_type=_transition_type(event, from_score, to_score),
                    from_score=from_score,
                    to_score=to_score,
                    from_bar_date=previous_bar_date.isoformat(),
                    to_bar_date=event.bar_date.isoformat(),
                    from_states=from_states,
                    to_states=to_states,
                    notes=f"{event.timeframe.value} triangle {event.state.value}: {event.reason}",
                )
            )

        current_score = to_score
        previous_bar_date = event.bar_date

    return previews


def preview_from_snapshot(
    snapshot: TriangleSnapshot,
    *,
    parameter_set_name: str,
    monthly_weight: int,
    weekly_weight: int,
    daily_weight: int,
    momentum_weight: int,
    momentum_state: int = 0,
) -> SignalScorePreview:
    return SignalScorePreview(
        ticker=snapshot.ticker,
        bar_date=snapshot.bar_date.isoformat(),
        parameter_set_name=parameter_set_name,
        monthly_state=snapshot.monthly_state.numeric,
        weekly_state=snapshot.weekly_state.numeric,
        daily_state=snapshot.daily_state.numeric,
        momentum_state=momentum_state,
        composite_score=snapshot.composite_score(
            monthly_weight=monthly_weight,
            weekly_weight=weekly_weight,
            daily_weight=daily_weight,
            momentum_state=momentum_state,
            momentum_weight=momentum_weight,
        ),
        monthly_channel_high=snapshot.monthly_channel_high,
        monthly_channel_low=snapshot.monthly_channel_low,
        weekly_channel_high=snapshot.weekly_channel_high,
        weekly_channel_low=snapshot.weekly_channel_low,
        daily_channel_high=snapshot.daily_channel_high,
        daily_channel_low=snapshot.daily_channel_low,
        event_count=len(snapshot.events),
    )
