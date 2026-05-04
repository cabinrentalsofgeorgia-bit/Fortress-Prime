"""MarketClub / Dochia signal API."""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.signals.repository import PostgresSignalDataStore, SignalDataStore

router = APIRouter(prefix="/api/financial/signals", tags=["financial-signals"])


OperatorToken = Annotated[str, Header(alias="X-MarketClub-Operator-Token", min_length=16)]


def _operator_token_sha256(operator_token: str) -> str:
    return hashlib.sha256(operator_token.strip().encode("utf-8")).hexdigest()


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
    exact_event_matches: int
    exact_event_accuracy: float | None
    window_event_matches: int
    window_event_accuracy: float | None
    event_window_days: int
    no_generated_event_observations: int
    opposite_generated_event_observations: int
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
    event_confusion: dict[str, dict[str, int]]
    top_tickers: list[TickerCalibrationStats]


class PromotionGateCalibrationSummary(BaseModel):
    total_observations: int
    covered_observations: int
    accuracy: float | None
    exact_event_accuracy: float | None
    window_event_accuracy: float | None
    coverage_rate: float | None
    exact_coverage_rate: float | None
    score_mae: float | None
    score_rmse: float | None


class PromotionGateModelSummary(BaseModel):
    id: Literal["production", "candidate"]
    label: str
    parameter_set_name: str
    daily_trigger_mode: str
    latest_bar_date: dt.date | None
    signal_count: int
    bullish_count: int
    risk_count: int
    neutral_count: int
    reentry_count: int
    average_score: float | None
    calibration: PromotionGateCalibrationSummary


class PromotionGateDeltas(BaseModel):
    window_event_accuracy: float | None
    exact_event_accuracy: float | None
    coverage_rate: float | None
    score_mae: float | None
    signal_count: int
    reentry_count: int


class PromotionGateGuardrail(BaseModel):
    id: str
    label: str
    status: Literal["pass", "watch", "fail"]
    detail: str


class PromotionGateRecommendation(BaseModel):
    status: Literal["hold", "review", "ready_for_shadow"]
    label: str
    rationale: str


class PromotionGateResponse(BaseModel):
    generated_at: dt.datetime
    candidate_parameter_set: str
    baseline_parameter_set: str
    since: dt.date | None
    until: dt.date | None
    event_window_days: int
    production: PromotionGateModelSummary
    candidate: PromotionGateModelSummary
    deltas: PromotionGateDeltas
    guardrails: list[PromotionGateGuardrail]
    recommendation: PromotionGateRecommendation


class ShadowReviewLaneChange(BaseModel):
    lane_id: str
    label: str
    production_tickers: list[str]
    candidate_tickers: list[str]
    added_tickers: list[str]
    removed_tickers: list[str]
    unchanged_tickers: list[str]
    churn_rate: float


class ShadowReviewTransitionPressure(BaseModel):
    ticker: str
    production_transition_count: int
    candidate_transition_count: int
    delta: int
    latest_candidate_transition_type: TransitionKind | None
    latest_candidate_transition_date: dt.date | None


class ShadowReviewWhipsawTicker(BaseModel):
    ticker: str
    risk_level: str
    risk_score: int
    event_count: int
    whipsaw_count: int
    whipsaw_rate: float | None
    win_rate: float | None
    average_directional_return: float | None
    latest_whipsaw_date: dt.date | None


class ShadowReviewChecklistItem(BaseModel):
    id: str
    label: str
    status: Literal["pass", "review", "hold", "blocked"]
    detail: str


class ShadowReviewRecommendation(BaseModel):
    status: Literal["ready_for_shadow_review", "needs_review", "hold"]
    label: str
    rationale: str


class ShadowReviewDecisionRecordTemplate(BaseModel):
    candidate_parameter_set: str
    allowed_decisions: list[str]
    required_approver: str
    required_evidence: list[str]


class ShadowReviewResponse(BaseModel):
    generated_at: dt.datetime
    candidate_parameter_set: str
    baseline_parameter_set: str
    lookback_days: int
    review_limit: int
    promotion_gate: PromotionGateResponse
    lane_reviews: list[ShadowReviewLaneChange]
    transition_pressure: list[ShadowReviewTransitionPressure]
    whipsaw_reviews: list[ShadowReviewWhipsawTicker]
    checklist: list[ShadowReviewChecklistItem]
    recommendation: ShadowReviewRecommendation
    decision_record_template: ShadowReviewDecisionRecordTemplate


ShadowReviewDecision = Literal["defer", "continue_shadow", "promote_to_market_signals"]


class ShadowReviewDecisionRecordCreate(BaseModel):
    candidate_parameter_set: str = Field(
        default="dochia_v0_2_range_daily",
        min_length=1,
        max_length=100,
    )
    decision: ShadowReviewDecision
    reviewer: str = Field(min_length=2, max_length=120)
    rationale: str = Field(min_length=12, max_length=2000)
    rollback_criteria: str = Field(min_length=12, max_length=2000)
    reviewed_tickers: list[str] = Field(default_factory=list, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    lookback_days: int = Field(default=30, ge=1, le=365)
    review_limit: int = Field(default=8, ge=1, le=20)
    whipsaw_window_sessions: int = Field(default=5, ge=1, le=30)
    outcome_horizon_sessions: int = Field(default=5, ge=1, le=60)


class ShadowReviewDecisionRecord(BaseModel):
    id: UUID
    candidate_parameter_set: str
    baseline_parameter_set: str
    decision: ShadowReviewDecision
    reviewer: str
    rationale: str
    rollback_criteria: str
    reviewed_tickers: list[str]
    notes: str | None
    shadow_review_generated_at: dt.datetime
    promotion_gate_status: Literal["hold", "review", "ready_for_shadow"]
    recommendation_status: Literal["ready_for_shadow_review", "needs_review", "hold"]
    created_at: dt.datetime


class PromotionDryRunApproval(BaseModel):
    status: Literal["missing_promote_decision", "blocked_by_review", "ready_for_dry_run"]
    decision_id: UUID | None
    reviewer: str | None
    decision_created_at: dt.datetime | None
    rollback_criteria: str | None
    detail: str


class PromotionDryRunLineage(BaseModel):
    source_pipeline: str
    parameter_set: str
    model_version: str
    computed_at: dt.datetime
    explanation_payload: dict[str, object]
    rollback_marker: str


class PromotionDryRunMarketSignalRow(BaseModel):
    ticker: str
    action: Literal["BUY", "SELL"]
    signal_type: str
    confidence_score: int
    price_target: Decimal | None
    source_sender: str
    source_subject: str
    raw_reasoning: str
    model_used: str
    extracted_at: dt.datetime
    candidate_bar_date: dt.date
    composite_score: int
    lineage: PromotionDryRunLineage


class PromotionDryRunSummary(BaseModel):
    target_table: str
    target_columns: list[str]
    write_path_enabled: bool
    candidate_signal_count: int
    proposed_insert_count: int
    bullish_count: int
    risk_count: int
    skipped_neutral_count: int
    latest_bar_date: dt.date | None
    min_abs_score: int


class PromotionDryRunResponse(BaseModel):
    generated_at: dt.datetime
    candidate_parameter_set: str
    baseline_parameter_set: str
    approval: PromotionDryRunApproval
    summary: PromotionDryRunSummary
    proposed_rows: list[PromotionDryRunMarketSignalRow]


VerificationStatus = Literal["PASS", "FAIL", "INCONCLUSIVE"]
VerificationConflictType = Literal[
    "NONE",
    "CROSS_MODEL_DIAGNOSTIC_ONLY",
    "CANDIDATE_INTERNAL_CONFLICT",
    "SOURCE_LINEAGE_MISSING",
    "SOURCE_LINEAGE_DUPLICATE",
    "SOURCE_LINEAGE_PARAMETER_MISMATCH",
    "TRANSITION_UNSUPPORTED",
]


class PromotionDryRunVerificationRow(BaseModel):
    row_status: VerificationStatus
    ticker: str
    candidate_bar_date: dt.date
    candidate_score: int | None
    candidate_action: Literal["BUY", "SELL"] | None
    candidate_monthly_triangle: int | None
    candidate_weekly_triangle: int | None
    candidate_daily_triangle: int | None
    latest_candidate_transition_date: dt.date | None
    latest_candidate_transition_type: TransitionKind | None
    prior_score: int | None
    new_score: int | None
    production_score: int | None
    production_daily_triangle: int | None
    conflict_type: VerificationConflictType
    explanation: str


class PromotionDryRunVerificationResponse(BaseModel):
    generated_at: dt.datetime
    candidate_parameter_set: str
    production_parameter_set: str
    overall_status: VerificationStatus
    proposed_rows_checked: int
    passed_rows: int
    failed_rows: int
    inconclusive_rows: int
    cross_model_diagnostic_only_rows: int
    rows: list[PromotionDryRunVerificationRow]


class PromotionDryRunAcceptanceCreate(BaseModel):
    candidate_parameter_set: str = Field(
        default="dochia_v0_2_range_daily",
        min_length=1,
        max_length=100,
    )
    decision_id: UUID | None = None
    accepted_by: str = Field(min_length=2, max_length=120)
    acceptance_rationale: str = Field(min_length=12, max_length=2000)
    limit: int = Field(default=500, ge=1, le=500)
    min_abs_score: int = Field(default=50, ge=1, le=100)


class PromotionDryRunAcceptance(BaseModel):
    id: UUID
    decision_record_id: UUID
    candidate_parameter_set: str
    baseline_parameter_set: str
    accepted_by: str
    acceptance_rationale: str
    rollback_criteria: str
    dry_run_generated_at: dt.datetime
    dry_run_candidate_signal_count: int
    dry_run_proposed_insert_count: int
    dry_run_bullish_count: int
    dry_run_risk_count: int
    dry_run_skipped_neutral_count: int
    min_abs_score: int
    target_table: str
    target_columns: list[str]
    created_at: dt.datetime


class PromotionExecutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acceptance_id: UUID
    execution_rationale: str = Field(min_length=12, max_length=2000)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)


class PromotionExecutionRollbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rollback_reason: str = Field(min_length=12, max_length=2000)


class PromotionExecution(BaseModel):
    id: UUID
    acceptance_id: UUID
    decision_record_id: UUID
    candidate_parameter_set: str
    baseline_parameter_set: str
    operator_membership_id: UUID
    executed_by: str
    execution_rationale: str
    idempotency_key: str
    dry_run_generated_at: dt.datetime
    dry_run_proposed_insert_count: int
    verification_status: VerificationStatus
    inserted_market_signal_ids: list[int]
    rollback_markers: list[str]
    rollback_status: Literal["active", "rolled_back"]
    rollback_operator_membership_id: UUID | None
    rollback_by: str | None
    rollback_reason: str | None
    rolled_back_at: dt.datetime | None
    created_at: dt.datetime


class PromotionRollbackDrill(BaseModel):
    execution_id: UUID
    dry_run_acceptance_id: UUID
    candidate_parameter_set: str
    baseline_parameter_set: str
    executed_by: str
    executed_at: dt.datetime
    inserted_market_signal_ids: list[int]
    rollback_markers: list[str]
    audited_market_signal_ids: list[int]
    rollback_preview_market_signal_ids: list[int]
    rollback_preview_count: int
    rollback_eligibility: Literal[
        "ELIGIBLE",
        "ELIGIBLE_PARTIAL_AUDITED_ROWS",
        "ALREADY_ROLLED_BACK",
        "NOT_ELIGIBLE_NO_AUDITED_ROWS",
        "NOT_ELIGIBLE_NO_LIVE_AUDITED_ROWS",
    ]
    rollback_eligible: bool
    already_rolled_back: bool
    rollback_status: Literal["active", "rolled_back"]
    rollback_by: str | None
    rollback_attempted_at: dt.datetime | None
    rolled_back_at: dt.datetime | None


class PromotionLifecycleEvent(BaseModel):
    ts: dt.datetime
    type: Literal[
        "DECISION_CREATED",
        "DRY_RUN_GENERATED",
        "VERIFICATION_RESULT",
        "ACCEPTANCE_CREATED",
        "EXECUTION_COMPLETED",
        "ROLLBACK_ELIGIBLE",
        "ROLLBACK_COMPLETED",
    ]
    decision_id: UUID | None
    acceptance_id: UUID | None
    execution_id: UUID | None
    candidate_id: str
    actor: str | None
    meta: dict[str, object]


class PromotionReconciliation(BaseModel):
    execution_id: UUID | None
    acceptance_id: UUID
    candidate_id: str
    status: Literal["HEALTHY", "WARNING", "ERROR"]
    checks: dict[str, Literal["PASS", "FAIL", "NA"]]
    warnings: dict[str, object]
    drilldown: dict[str, object]
    explanation: str


class SymbolChartBar(BaseModel):
    ticker: str
    bar_date: dt.date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None
    daily_channel_high: Decimal | None
    daily_channel_low: Decimal | None
    weekly_channel_high: Decimal | None
    weekly_channel_low: Decimal | None
    monthly_channel_high: Decimal | None
    monthly_channel_low: Decimal | None


class SymbolChartEvent(BaseModel):
    ticker: str
    timeframe: str
    state: str
    bar_date: dt.date
    trigger_price: Decimal
    channel_high: Decimal
    channel_low: Decimal
    lookback_sessions: int
    reason: str


class SymbolSignalChart(BaseModel):
    ticker: str
    parameter_set_name: str
    daily_trigger_mode: str
    sessions: int
    bars: list[SymbolChartBar]
    events: list[SymbolChartEvent]


class SignalReturnOutcome(BaseModel):
    horizon_sessions: int
    evaluated_events: int
    win_count: int
    win_rate: float | None
    average_directional_return: float | None
    median_directional_return: float | None
    p25_directional_return: float | None
    p75_directional_return: float | None


class SymbolWhipsawEvent(BaseModel):
    event_date: dt.date
    state: str
    sessions_since_previous: int | None
    is_whipsaw: bool
    directional_return: float | None


class SymbolWhipsawRisk(BaseModel):
    ticker: str
    parameter_set_name: str
    daily_trigger_mode: str
    sessions: int
    as_of: dt.date | None
    whipsaw_window_sessions: int
    outcome_horizon_sessions: int
    event_count: int
    whipsaw_count: int
    whipsaw_rate: float | None
    latest_whipsaw_date: dt.date | None
    risk_score: int
    risk_level: str
    outcome: SignalReturnOutcome
    recent_events: list[SymbolWhipsawEvent]


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
    parameter_set: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> list[dict[str, object]]:
    if min_score is not None and max_score is not None and min_score > max_score:
        raise HTTPException(status_code=400, detail="min_score cannot exceed max_score")
    return store.latest_scores(
        limit=limit,
        ticker=ticker,
        min_score=min_score,
        max_score=max_score,
        parameter_set=parameter_set,
    )


@router.get("/transitions", response_model=list[SignalTransition])
def recent_transitions(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ticker: Annotated[str | None, Query(min_length=1, max_length=20)] = None,
    transition_type: TransitionKind | None = None,
    since: dt.date | None = None,
    lookback_days: Annotated[int | None, Query(ge=1, le=365)] = 30,
    parameter_set: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> list[dict[str, object]]:
    return store.recent_transitions(
        limit=limit,
        ticker=ticker,
        transition_type=transition_type.value if transition_type else None,
        since=since,
        lookback_days=lookback_days,
        parameter_set=parameter_set,
    )


@router.get("/watchlist-candidates", response_model=SignalWatchlistCandidatesResponse)
def watchlist_candidates(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
    parameter_set: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
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
    candidate_lanes = store.watchlist_candidates(limit=limit, parameter_set=parameter_set)
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
    event_window_days: Annotated[int, Query(ge=0, le=10)] = 3,
) -> dict[str, object]:
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=400, detail="since cannot be after until")
    return store.daily_calibration(
        since=since,
        until=until,
        ticker=ticker,
        parameter_set=parameter_set,
        top_tickers=top_tickers,
        event_window_days=event_window_days,
    )


@router.get("/promotion-gate/daily", response_model=PromotionGateResponse)
def promotion_gate_daily(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    candidate_parameter_set: Annotated[
        str, Query(min_length=1, max_length=100)
    ] = "dochia_v0_2_range_daily",
    since: dt.date | None = None,
    until: dt.date | None = None,
    top_tickers: Annotated[int, Query(ge=1, le=100)] = 20,
    event_window_days: Annotated[int, Query(ge=0, le=10)] = 3,
) -> dict[str, object]:
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=400, detail="since cannot be after until")
    return store.promotion_gate(
        candidate_parameter_set=candidate_parameter_set,
        since=since,
        until=until,
        top_tickers=top_tickers,
        event_window_days=event_window_days,
    )


@router.get("/shadow-review/daily", response_model=ShadowReviewResponse)
def shadow_review_daily(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    candidate_parameter_set: Annotated[
        str, Query(min_length=1, max_length=100)
    ] = "dochia_v0_2_range_daily",
    lookback_days: Annotated[int, Query(ge=1, le=365)] = 30,
    review_limit: Annotated[int, Query(ge=1, le=20)] = 8,
    whipsaw_window_sessions: Annotated[int, Query(ge=1, le=30)] = 5,
    outcome_horizon_sessions: Annotated[int, Query(ge=1, le=60)] = 5,
) -> dict[str, object]:
    return store.shadow_review(
        candidate_parameter_set=candidate_parameter_set,
        lookback_days=lookback_days,
        review_limit=review_limit,
        whipsaw_window_sessions=whipsaw_window_sessions,
        outcome_horizon_sessions=outcome_horizon_sessions,
    )


@router.get(
    "/shadow-review/decision-records",
    response_model=list[ShadowReviewDecisionRecord],
)
def shadow_review_decision_records(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    candidate_parameter_set: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict[str, object]]:
    return store.shadow_review_decision_records(
        candidate_parameter_set=candidate_parameter_set,
        limit=limit,
    )


@router.post(
    "/shadow-review/decision-records",
    response_model=ShadowReviewDecisionRecord,
    status_code=201,
)
def create_shadow_review_decision_record_endpoint(
    payload: ShadowReviewDecisionRecordCreate,
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
) -> dict[str, object]:
    reviewed_tickers = [
        ticker.strip().upper()
        for ticker in payload.reviewed_tickers
        if ticker.strip()
    ]
    try:
        return store.create_shadow_review_decision_record(
            candidate_parameter_set=payload.candidate_parameter_set,
            decision=payload.decision,
            reviewer=payload.reviewer.strip(),
            rationale=payload.rationale.strip(),
            rollback_criteria=payload.rollback_criteria.strip(),
            reviewed_tickers=list(dict.fromkeys(reviewed_tickers)),
            notes=payload.notes.strip() if payload.notes else None,
            lookback_days=payload.lookback_days,
            review_limit=payload.review_limit,
            whipsaw_window_sessions=payload.whipsaw_window_sessions,
            outcome_horizon_sessions=payload.outcome_horizon_sessions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/promotion-dry-run/daily", response_model=PromotionDryRunResponse)
def promotion_dry_run_daily(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    candidate_parameter_set: Annotated[
        str, Query(min_length=1, max_length=100)
    ] = "dochia_v0_2_range_daily",
    decision_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    min_abs_score: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, object]:
    return store.promotion_dry_run(
        candidate_parameter_set=candidate_parameter_set,
        decision_id=str(decision_id) if decision_id else None,
        limit=limit,
        min_abs_score=min_abs_score,
    )


@router.get(
    "/promotion-dry-run/verification",
    response_model=PromotionDryRunVerificationResponse,
)
def promotion_dry_run_verification(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    candidate_parameter_set: Annotated[
        str, Query(min_length=1, max_length=100)
    ] = "dochia_v0_2_range_daily",
    production_parameter_set: Annotated[
        str, Query(min_length=1, max_length=100)
    ] = "dochia_v0_estimated",
    decision_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
    min_abs_score: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, object]:
    return store.promotion_dry_run_verification(
        candidate_parameter_set=candidate_parameter_set,
        production_parameter_set=production_parameter_set,
        decision_id=str(decision_id) if decision_id else None,
        limit=limit,
        min_abs_score=min_abs_score,
    )


@router.get(
    "/promotion-dry-run/acceptances",
    response_model=list[PromotionDryRunAcceptance],
)
def promotion_dry_run_acceptances(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    candidate_parameter_set: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict[str, object]]:
    return store.promotion_dry_run_acceptances(
        candidate_parameter_set=candidate_parameter_set,
        limit=limit,
    )


@router.post(
    "/promotion-dry-run/acceptances",
    response_model=PromotionDryRunAcceptance,
    status_code=201,
)
def create_promotion_dry_run_acceptance_endpoint(
    payload: PromotionDryRunAcceptanceCreate,
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
) -> dict[str, object]:
    try:
        return store.create_promotion_dry_run_acceptance(
            candidate_parameter_set=payload.candidate_parameter_set,
            accepted_by=payload.accepted_by.strip(),
            acceptance_rationale=payload.acceptance_rationale.strip(),
            decision_id=str(payload.decision_id) if payload.decision_id else None,
            limit=payload.limit,
            min_abs_score=payload.min_abs_score,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/promotion-dry-run/executions",
    response_model=list[PromotionExecution],
)
def promotion_executions(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    candidate_parameter_set: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict[str, object]]:
    return store.promotion_executions(
        candidate_parameter_set=candidate_parameter_set,
        limit=limit,
    )


@router.get(
    "/promotion-dry-run/executions/rollback-drill",
    response_model=list[PromotionRollbackDrill],
)
def promotion_rollback_drills(
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    candidate_parameter_set: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict[str, object]]:
    return store.promotion_rollback_drills(
        candidate_parameter_set=candidate_parameter_set,
        limit=limit,
    )


@router.get(
    "/promotion/{promotion_id}/timeline",
    response_model=list[PromotionLifecycleEvent],
)
def promotion_lifecycle_timeline(
    promotion_id: Annotated[str, Path(min_length=1, max_length=120)],
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, object]]:
    return store.promotion_lifecycle_timeline(
        promotion_id=promotion_id,
        limit=limit,
    )


@router.get(
    "/promotion/{promotion_id}/reconciliation",
    response_model=list[PromotionReconciliation],
)
def promotion_reconciliation(
    promotion_id: Annotated[str, Path(min_length=1, max_length=120)],
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict[str, object]]:
    return store.promotion_reconciliation(
        promotion_id=promotion_id,
        limit=limit,
    )


@router.post(
    "/promotion-dry-run/executions",
    response_model=PromotionExecution,
    status_code=201,
)
def execute_guarded_promotion(
    payload: PromotionExecutionCreate,
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    operator_token: OperatorToken,
) -> dict[str, object]:
    try:
        return store.execute_guarded_promotion(
            acceptance_id=str(payload.acceptance_id),
            operator_token_sha256=_operator_token_sha256(operator_token),
            execution_rationale=payload.execution_rationale.strip(),
            idempotency_key=payload.idempotency_key.strip() if payload.idempotency_key else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/promotion-dry-run/executions/{execution_id}/rollback",
    response_model=PromotionExecution,
)
def rollback_promotion_execution(
    execution_id: UUID,
    payload: PromotionExecutionRollbackCreate,
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    operator_token: OperatorToken,
) -> dict[str, object]:
    try:
        return store.rollback_promotion_execution(
            execution_id=str(execution_id),
            operator_token_sha256=_operator_token_sha256(operator_token),
            rollback_reason=payload.rollback_reason.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{ticker}/chart", response_model=SymbolSignalChart)
def symbol_signal_chart(
    ticker: Annotated[str, Path(min_length=1, max_length=20)],
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    sessions: Annotated[int, Query(ge=30, le=500)] = 180,
    as_of: dt.date | None = None,
    parameter_set: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> dict[str, object]:
    chart = store.symbol_chart(
        ticker=ticker.upper(),
        sessions=sessions,
        as_of=as_of,
        parameter_set=parameter_set,
    )
    if not chart["bars"]:
        raise HTTPException(status_code=404, detail=f"chart data not found for {ticker.upper()}")
    return chart


@router.get("/{ticker}/whipsaw-risk", response_model=SymbolWhipsawRisk)
def symbol_whipsaw_risk(
    ticker: Annotated[str, Path(min_length=1, max_length=20)],
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    sessions: Annotated[int, Query(ge=30, le=500)] = 260,
    as_of: dt.date | None = None,
    parameter_set: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    whipsaw_window_sessions: Annotated[int, Query(ge=1, le=30)] = 5,
    outcome_horizon_sessions: Annotated[int, Query(ge=1, le=60)] = 5,
) -> dict[str, object]:
    risk = store.symbol_whipsaw_risk(
        ticker=ticker.upper(),
        sessions=sessions,
        as_of=as_of,
        parameter_set=parameter_set,
        whipsaw_window_sessions=whipsaw_window_sessions,
        outcome_horizon_sessions=outcome_horizon_sessions,
    )
    if risk["sessions"] == 0:
        raise HTTPException(status_code=404, detail=f"whipsaw data not found for {ticker.upper()}")
    return risk


@router.get("/{ticker}", response_model=SymbolSignalDetail)
def symbol_signal_detail(
    ticker: Annotated[str, Path(min_length=1, max_length=20)],
    store: Annotated[SignalDataStore, Depends(get_signal_store)],
    transition_limit: Annotated[int, Query(ge=1, le=200)] = 25,
    lookback_days: Annotated[int | None, Query(ge=1, le=365)] = 30,
    parameter_set: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> dict[str, object]:
    normalized_ticker = ticker.upper()
    latest = store.latest_scores(
        limit=1,
        ticker=normalized_ticker,
        parameter_set=parameter_set,
    )
    if not latest:
        raise HTTPException(status_code=404, detail=f"signal not found for {normalized_ticker}")
    transitions = store.recent_transitions(
        limit=transition_limit,
        ticker=normalized_ticker,
        lookback_days=lookback_days,
        parameter_set=parameter_set,
    )
    return {
        "ticker": normalized_ticker,
        "latest": latest[0],
        "recent_transitions": transitions,
    }
