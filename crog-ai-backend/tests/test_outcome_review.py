import datetime as dt
from decimal import Decimal

from app.signals.calibration import CalibrationObservation
from app.signals.guardrail_sweep import (
    GuardedRangeCandidate,
    generated_guarded_range_event_history,
)
from app.signals.outcome_review import (
    TickerClusterCandidate,
    apply_ticker_cluster_candidate,
    build_ticker_whipsaw_outcomes,
    evaluate_event_histories,
    events_from_histories,
    summarize_forward_returns,
)
from app.signals.trade_triangles import EodBar


def _bar(index: int, *, open_: str, high: str, low: str, close: str) -> EodBar:
    return EodBar(
        ticker="AA",
        bar_date=dt.date(2026, 1, 1) + dt.timedelta(days=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=1000,
    )


def test_summarize_forward_returns_scores_directionally() -> None:
    bars = [
        _bar(0, open_="10", high="10", low="9", close="10"),
        _bar(1, open_="11", high="11", low="10", close="11"),
        _bar(2, open_="12", high="12", low="11", close="12"),
        _bar(3, open_="13", high="13", low="12", close="13"),
        _bar(4, open_="14", high="14", low="13", close="14"),
    ]
    history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2),
    )
    assert history is not None

    events = events_from_histories({"AA": history}, {"AA": bars})
    summaries = summarize_forward_returns(events, {"AA": bars}, horizons=[2])

    assert summaries[0].evaluated_events == 1
    assert summaries[0].win_count == 1
    assert summaries[0].win_rate == 1
    assert summaries[0].average_directional_return == float(Decimal("2") / Decimal("12"))


def test_build_ticker_whipsaw_outcomes_counts_fast_reversals() -> None:
    bars = [
        _bar(0, open_="10", high="10", low="9", close="10"),
        _bar(1, open_="11", high="11", low="10", close="11"),
        _bar(2, open_="12", high="12", low="10", close="12"),
        _bar(3, open_="9", high="10", low="8", close="8"),
        _bar(4, open_="13", high="13", low="9", close="12"),
        _bar(5, open_="14", high="14", low="12", close="13"),
    ]
    history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2),
    )
    assert history is not None

    events = events_from_histories({"AA": history}, {"AA": bars})
    clusters = build_ticker_whipsaw_outcomes(
        events,
        {"AA": bars},
        whipsaw_window_sessions=2,
        outcome_horizon_sessions=1,
        top=5,
    )

    assert clusters[0].ticker == "AA"
    assert clusters[0].event_count == 3
    assert clusters[0].whipsaw_count == 2
    assert clusters[0].whipsaw_rate == 1


def test_apply_ticker_cluster_cooldown_suppresses_selected_ticker_only() -> None:
    aa_bars = [
        _bar(0, open_="10", high="10", low="9", close="10"),
        _bar(1, open_="11", high="11", low="10", close="11"),
        _bar(2, open_="12", high="12", low="10", close="12"),
        _bar(3, open_="9", high="10", low="8", close="8"),
        _bar(4, open_="13", high="13", low="9", close="12"),
    ]
    bb_bars = [
        EodBar(
            ticker="BB",
            bar_date=bar.bar_date,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in aa_bars
    ]
    aa_history = generated_guarded_range_event_history(
        aa_bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2),
    )
    bb_history = generated_guarded_range_event_history(
        bb_bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2),
    )
    assert aa_history is not None
    assert bb_history is not None

    adjusted = apply_ticker_cluster_candidate(
        {"AA": aa_history, "BB": bb_history},
        {"AA": aa_bars, "BB": bb_bars},
        cluster_tickers={"AA"},
        candidate=TickerClusterCandidate(
            cluster_size=1,
            mode="cooldown",
            cooldown_sessions=2,
        ),
    )

    assert len(aa_history.event_by_date) == 3
    assert len(adjusted["AA"].event_by_date) == 1
    assert adjusted["BB"].event_by_date == bb_history.event_by_date


def test_evaluate_event_histories_scores_exact_and_precision() -> None:
    bars = [
        _bar(0, open_="10", high="10", low="9", close="10"),
        _bar(1, open_="11", high="11", low="10", close="11"),
        _bar(2, open_="12", high="12", low="10", close="12"),
        _bar(3, open_="9", high="10", low="8", close="8"),
    ]
    history = generated_guarded_range_event_history(
        bars,
        candidate=GuardedRangeCandidate(lookback_sessions=2),
    )
    assert history is not None

    summary = evaluate_event_histories(
        [
            CalibrationObservation(
                ticker="AA",
                trading_day=dt.date(2026, 1, 3),
                triangle_color="green",
                score=15,
            ),
            CalibrationObservation(
                ticker="AA",
                trading_day=dt.date(2026, 1, 4),
                triangle_color="red",
                score=-15,
            ),
        ],
        {"AA": history},
    )

    assert summary.generated_events == 2
    assert summary.exact_event_matches == 2
    assert summary.exact_event_f1 == 1
