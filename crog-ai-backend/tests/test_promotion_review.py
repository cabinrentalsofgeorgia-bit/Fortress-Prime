import datetime as dt
from decimal import Decimal

from app.signals.promotion_review import (
    build_chart_event_reviews,
    build_lane_reviews,
    build_whipsaw_clusters,
    focus_tickers_for_chart_review,
)


def test_build_lane_reviews_reports_candidate_churn() -> None:
    reviews = build_lane_reviews(
        {"bullish_alignment": [{"ticker": "AA"}, {"ticker": "MSFT"}]},
        {"bullish_alignment": [{"ticker": "AA"}, {"ticker": "NVDA"}]},
        sample_size=5,
    )

    bullish = reviews[0]
    assert bullish.lane == "bullish_alignment"
    assert bullish.baseline_count == 2
    assert bullish.candidate_count == 2
    assert bullish.overlap_count == 1
    assert bullish.entered == ["NVDA"]
    assert bullish.exited == ["MSFT"]
    assert bullish.churn_rate == 2 / 3


def test_build_whipsaw_clusters_prioritizes_candidate_transition_pressure() -> None:
    baseline = [
        {
            "ticker": "AA",
            "transition_type": "breakout_bullish",
            "to_bar_date": dt.date(2026, 4, 1),
            "notes": "daily triangle green",
        }
    ]
    candidate = [
        {
            "ticker": "AA",
            "transition_type": "breakout_bullish",
            "to_bar_date": dt.date(2026, 4, 2),
            "notes": "daily triangle green",
        },
        {
            "ticker": "AA",
            "transition_type": "peak_to_exit",
            "to_bar_date": dt.date(2026, 4, 5),
            "notes": "daily triangle red",
        },
        {
            "ticker": "AA",
            "transition_type": "exit_to_reentry",
            "to_bar_date": dt.date(2026, 4, 8),
            "notes": "weekly triangle green",
        },
    ]

    clusters = build_whipsaw_clusters(
        baseline,
        candidate,
        min_candidate_transitions=3,
        min_transition_delta=2,
    )

    assert clusters[0].ticker == "AA"
    assert clusters[0].baseline_transition_count == 1
    assert clusters[0].candidate_transition_count == 3
    assert clusters[0].transition_delta == 2
    assert clusters[0].candidate_daily_transition_count == 2
    assert clusters[0].candidate_transition_types["peak_to_exit"] == 1
    assert clusters[0].latest_candidate_transition_date == "2026-04-08"


def test_build_chart_event_reviews_surfaces_candidate_only_events() -> None:
    baseline_chart = {
        "events": [
            {
                "timeframe": "daily",
                "state": "green",
                "bar_date": "2026-04-01",
                "trigger_price": Decimal("10"),
                "reason": "close break",
            }
        ]
    }
    candidate_chart = {
        "events": [
            {
                "timeframe": "daily",
                "state": "green",
                "bar_date": "2026-04-01",
                "trigger_price": Decimal("10"),
                "reason": "close break",
            },
            {
                "timeframe": "daily",
                "state": "red",
                "bar_date": "2026-04-03",
                "trigger_price": Decimal("9"),
                "reason": "range break",
            },
            {
                "timeframe": "weekly",
                "state": "red",
                "bar_date": "2026-04-04",
                "trigger_price": Decimal("8"),
                "reason": "weekly break",
            },
        ]
    }

    reviews = build_chart_event_reviews({"AA": baseline_chart}, {"AA": candidate_chart})

    assert reviews[0].ticker == "AA"
    assert reviews[0].baseline_daily_event_count == 1
    assert reviews[0].candidate_daily_event_count == 2
    assert reviews[0].daily_event_delta == 1
    assert reviews[0].candidate_only_count == 1
    assert reviews[0].candidate_only_events[0]["bar_date"] == "2026-04-03"


def test_focus_tickers_prefers_churn_whipsaws_then_candidate_lanes() -> None:
    lane_reviews = build_lane_reviews(
        {"bullish_alignment": [{"ticker": "AA"}]},
        {"bullish_alignment": [{"ticker": "AA"}, {"ticker": "NVDA"}]},
        sample_size=5,
    )
    whipsaws = build_whipsaw_clusters(
        [],
        [
            {
                "ticker": "TSLA",
                "transition_type": "peak_to_exit",
                "to_bar_date": "2026-04-05",
                "notes": "daily triangle red",
            },
            {
                "ticker": "TSLA",
                "transition_type": "exit_to_reentry",
                "to_bar_date": "2026-04-08",
                "notes": "daily triangle green",
            },
        ],
        min_candidate_transitions=2,
    )

    focus = focus_tickers_for_chart_review(
        lane_reviews=lane_reviews,
        whipsaw_clusters=whipsaws,
        candidate_lanes={"bullish_alignment": [{"ticker": "AA"}]},
        limit=5,
    )

    assert focus[:3] == ["NVDA", "TSLA", "AA"]
