"""MarketClub / Dochia signal API."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, computed_field

from app.signals.repository import PostgresSignalDataStore, SignalDataStore

router = APIRouter(prefix="/api/financial/signals", tags=["financial-signals"])


class TransitionKind(StrEnum):
    PEAK_TO_EXIT = "peak_to_exit"
    EXIT_TO_REENTRY = "exit_to_reentry"
    FULL_REVERSAL = "full_reversal"
    BREAKOUT_BULLISH = "breakout_bullish"
    BREAKOUT_BEARISH = "breakout_bearish"


class LatestSignal(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    bar_date: dt.date
    parameter_set_id: UUID
    parameter_set_name: str
    dochia_version: str
    monthly_state: int
    weekly_state: int
    daily_state: int
    momentum_state: int
    composite_score: int
    computed_at: dt.datetime
    monthly_channel_high: Decimal | None
    monthly_channel_low: Decimal | None
    weekly_channel_high: Decimal | None
    weekly_channel_low: Decimal | None
    daily_channel_high: Decimal | None
    daily_channel_low: Decimal | None

    @computed_field
    @property
    def state_labels(self) -> dict[str, str]:
        return {
            "monthly": _state_label(self.monthly_state),
            "weekly": _state_label(self.weekly_state),
            "daily": _state_label(self.daily_state),
            "momentum": _state_label(self.momentum_state),
        }


class SignalTransition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ticker: str
    parameter_set_name: str
    transition_type: TransitionKind
    from_score: int
    to_score: int
    from_bar_date: dt.date
    to_bar_date: dt.date
    from_states: dict[str, int]
    to_states: dict[str, int]
    detected_at: dt.datetime
    acknowledged_by_user_id: UUID | None
    acknowledged_at: dt.datetime | None
    notes: str | None


class SymbolSignalDetail(BaseModel):
    ticker: str
    latest: LatestSignal
    recent_transitions: list[SignalTransition]


class SignalWatchlistCandidate(BaseModel):
    ticker: str
    bar_date: dt.date
    parameter_set_name: str
    monthly_state: int
    weekly_state: int
    daily_state: int
    momentum_state: int
    composite_score: int
    latest_transition_type: TransitionKind | None
    latest_transition_bar_date: dt.date | None
    latest_transition_notes: str | None
    sector: str | None
    watchlist_signal_count: int | None
    watchlist_last_signal_at: dt.datetime | None
    legacy_action: str | None
    legacy_signal_type: str | None
    legacy_confidence_score: int | None
    legacy_price_target: Decimal | None
    legacy_signal_at: dt.datetime | None

    @computed_field
    @property
    def state_labels(self) -> dict[str, str]:
        return {
            "monthly": _state_label(self.monthly_state),
            "weekly": _state_label(self.weekly_state),
            "daily": _state_label(self.daily_state),
            "momentum": _state_label(self.momentum_state),
        }


class SignalWatchlistLane(BaseModel):
    id: str
    label: str
    description: str
    candidates: list[SignalWatchlistCandidate]


class SignalWatchlistCandidatesResponse(BaseModel):
    generated_at: dt.datetime
    lanes: list[SignalWatchlistLane]


class TickerCalibrationStats(BaseModel):
    ticker: str
    observations: int
    covered_observations: int
    exact_bar_observations: int
    matches: int
    accuracy: float | None
    score_mae: float | None


class DailyCalibrationResponse(BaseModel):
    parameter_set_name: str
    generated_at: dt.datetime
    since: dt.date | None
    until: dt.date | None
    total_observations: int
    covered_observations: int
    exact_bar_observations: int
    missing_observations: int
    neutral_generated_observations: int
    matches: int
    accuracy: float | None
    coverage_rate: float | None
    exact_coverage_rate: float | None
    green_precision: float | None
    green_recall: float | None
    red_precision: float | None
    red_recall: float | None
    score_mae: float | None
    score_rmse: float | None
    confusion: dict[str, dict[str, int]]
    top_tickers: list[TickerCalibrationStats]


def _state_label(value: int) -> str:
    if value > 0:
        return "green"
    if value < 0:
        return "red"
    return "neutral"


def get_signal_store() -> SignalDataStore:
    return PostgresSignalDataStore()


@router.get("/latest", response_model=list[LatestSignal])
def latest_scores(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ticker: Annotated[str | None, Query(min_length=1, max_length=20)] = None,
    min_score: Annotated[int | None, Query(ge=-100, le=100)] = None,
    max_score: Annotated[int | None, Query(ge=-100, le=100)] = None,
) -> list[dict[str, object]]:
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(status_code=400, detail="min_score cannot exceed max_score")
    return store.latest_scores(
        limit=limit,
        ticker=ticker,
        min_score=min_score,
        max_score=max_score,
    )


@router.get("/transitions", response_model=list[SignalTransition])
def recent_transitions(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ticker: Annotated[str | None, Query(min_length=1, max_length=20)] = None,
    transition_type: TransitionKind | None = None,
    since: dt.date | None = None,
    lookback_days: Annotated[int | None, Query(ge=1, le=365)] = 30,
) -> list[dict[str, object]]:
    return store.recent_transitions(
        limit=limit,
        ticker=ticker,
        transition_type=transition_type.value if transition_type else None,
        since=since,
        lookback_days=lookback_days,
    )


@router.get("/watchlist-candidates", response_model=SignalWatchlistCandidatesResponse)
def watchlist_candidates(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
) -> dict[str, object]:
    lane_labels = {
        "bullish_alignment": {
            "label": "Bullish Alignment",
            "description": "Current scores with monthly, weekly, and daily support.",
        },
        "risk_alignment": {
            "label": "Risk Alignment",
            "description": "Current scores that should stay on the risk desk.",
        },
        "reentry": {
            "label": "Re-entry",
            "description": "Recent bullish turns with non-negative current scores.",
        },
        "mixed_timeframes": {
            "label": "Mixed Timeframes",
            "description": "Symbols where the timeframes are not in agreement.",
        },
    }
    candidate_lanes = store.watchlist_candidates(limit=limit)
    lanes = [
        {
            "id": lane_id,
            "label": lane_labels[lane_id]["label"],
            "description": lane_labels[lane_id]["description"],
            "candidates": candidate_lanes.get(lane_id, []),
        }
        for lane_id in lane_labels
    ]
    return {"generated_at": dt.datetime.now(dt.UTC), "lanes": lanes}


@router.get("/calibration/daily", response_model=DailyCalibrationResponse)
def daily_calibration(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    since: dt.date | None = None,
    until: dt.date | None = None,
    ticker: Annotated[str | None, Query(min_length=1, max_length=20)] = None,
    parameter_set: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    top_tickers: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=400, detail="since cannot be after until")
    return store.daily_calibration(
        since=since,
        until=until,
        ticker=ticker,
        parameter_set=parameter_set,
        top_tickers=top_tickers,
    )


@router.get("/{ticker}", response_model=SymbolSignalDetail)
def symbol_signal_detail(
    ticker: Annotated[str, Path(min_length=1, max_length=20)],
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    transition_limit: Annotated[int, Query(ge=1, le=200)] = 25,
    lookback_days: Annotated[int | None, Query(ge=1, le=365)] = 30,
) -> dict[str, object]:
    normalized_ticker = ticker.upper()
    latest = store.latest_scores(limit=1, ticker=normalized_ticker)
    if not latest:
        raise HTTPException(status_code=404, detail=f"signal not found for {normalized_ticker}")
    transitions = store.recent_transitions(
        limit=transition_limit,
        ticker=normalized_ticker,
        lookback_days=lookback_days,
    )
    return {
        "ticker": normalized_ticker,
        "latest": latest[0],
        "recent_transitions": transitions,
    }
