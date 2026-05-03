import datetime as dt
from decimal import Decimal

from app.signals.guardrail_sweep import (
    GuardedRangeCandidate,
    generated_guarded_range_event_history,
)
from app.signals.outcome_review import (
    build_ticker_whipsaw_outcomes,
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
