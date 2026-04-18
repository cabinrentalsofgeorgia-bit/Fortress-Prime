"""Tests for Phase 4e.1 labeling pipeline."""
import random
import threading
from collections import Counter
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------
def _import():
    from backend.services import labeling_pipeline as lp
    return lp


# ---------------------------------------------------------------------------
# Budget math
# ---------------------------------------------------------------------------

class TestBudgetMath:
    def test_estimate_cost_returns_decimal(self):
        lp = _import()
        cost = lp._estimate_call_cost("anthropic/claude-sonnet-4-6", 500, 200)
        assert isinstance(cost, Decimal)
        assert cost > 0

    def test_estimate_cost_scales_with_length(self):
        lp = _import()
        short = lp._estimate_call_cost("anthropic/claude-sonnet-4-6", 100, 50)
        long_ = lp._estimate_call_cost("anthropic/claude-sonnet-4-6", 1000, 500)
        assert long_ > short

    def test_unknown_model_uses_default_cost(self):
        lp = _import()
        cost = lp._estimate_call_cost("unknown/model-xyz", 500, 200)
        assert cost > 0  # falls back to default rates

    def test_daily_budget_default(self):
        lp = _import()
        assert lp.DAILY_BUDGET == Decimal("20.00")

    def test_rt_threshold_default(self):
        lp = _import()
        assert lp.RT_THRESHOLD == 80

    def test_budget_pct_used_calls_check_remaining(self):
        lp = _import()
        with patch.object(lp, "check_budget_remaining", return_value=Decimal("4.00")):
            pct = lp._budget_pct_used()
            # 20 - 4 = 16 spent of 20 = 80%
            assert pct == pytest.approx(80.0, abs=0.1)

    def test_budget_pct_100_when_exhausted(self):
        lp = _import()
        with patch.object(lp, "check_budget_remaining", return_value=Decimal("0")):
            assert lp._budget_pct_used() == pytest.approx(100.0, abs=0.1)


# ---------------------------------------------------------------------------
# Teacher routing
# ---------------------------------------------------------------------------

class TestTeacherRouting:
    def test_legal_tasks_route_to_claude_first(self):
        lp = _import()
        for task in ("legal_reasoning", "brief_drafting", "legal_citations"):
            teachers = lp._GODHEAD_TEACHERS.get(task, lp._DEFAULT_TEACHER)
            assert "claude" in teachers[0], f"{task} primary should be Claude"

    def test_code_generation_routes_to_gpt_first(self):
        lp = _import()
        teachers = lp._GODHEAD_TEACHERS["code_generation"]
        assert "gpt-4o" in teachers[0], "code_generation primary should be GPT"

    def test_vision_routes_to_gemini_first(self):
        lp = _import()
        for task in ("vision_damage", "vision_photo", "ocr"):
            teachers = lp._GODHEAD_TEACHERS.get(task, lp._DEFAULT_TEACHER)
            assert "gemini" in teachers[0], f"{task} primary should be Gemini"

    def test_real_time_routes_to_grok_first(self):
        lp = _import()
        teachers = lp._GODHEAD_TEACHERS["real_time"]
        assert "grok" in teachers[0], "real_time primary should be Grok"

    def test_math_routes_to_deepseek_first(self):
        lp = _import()
        for task in ("math_reasoning", "complex_logic"):
            teachers = lp._GODHEAD_TEACHERS.get(task, lp._DEFAULT_TEACHER)
            assert "deepseek" in teachers[0], f"{task} primary should be DeepSeek"

    def test_fallback_chain_has_multiple_entries(self):
        lp = _import()
        for task, chain in lp._GODHEAD_TEACHERS.items():
            assert len(chain) >= 1, f"{task} must have at least one teacher"

    def test_unknown_task_uses_default_teacher(self):
        lp = _import()
        teachers = lp._GODHEAD_TEACHERS.get("totally_unknown_task", lp._DEFAULT_TEACHER)
        assert len(teachers) >= 1
        assert "claude" in teachers[0]


# ---------------------------------------------------------------------------
# QC sampling weights
# ---------------------------------------------------------------------------

class TestQCSampling:
    def test_legal_tasks_have_weight_1_0(self):
        lp = _import()
        for task in ("legal_reasoning", "brief_drafting", "legal_citations", "contract_analysis"):
            assert lp._QC_WEIGHTS[task] == 1.0, f"{task} should have 100% QC rate"

    def test_vrs_concierge_has_low_weight(self):
        lp = _import()
        assert lp._QC_WEIGHTS["vrs_concierge"] <= 0.10

    def test_unknown_task_defaults_to_10pct(self):
        lp = _import()
        weight = lp._QC_WEIGHTS.get("unknown_task", lp._DEFAULT_QC_WEIGHT)
        assert weight == pytest.approx(0.10, abs=0.01)

    def test_sampling_statistical_correctness(self):
        """Over 10k trials, sampling rate should be close to weight."""
        lp = _import()
        task = "vrs_concierge"
        expected_rate = lp._QC_WEIGHTS[task]
        N = 10_000
        sampled = sum(
            1 for _ in range(N)
            if random.random() < lp._QC_WEIGHTS.get(task, lp._DEFAULT_QC_WEIGHT)
        )
        actual_rate = sampled / N
        # Allow ±3% for statistical noise
        assert abs(actual_rate - expected_rate) < 0.03, (
            f"Expected ~{expected_rate:.2%}, got {actual_rate:.2%}"
        )

    def test_sampling_legal_is_always_100pct(self):
        """Legal tasks should always be sampled (weight=1.0)."""
        lp = _import()
        task = "legal_reasoning"
        N = 1_000
        sampled = sum(
            1 for _ in range(N)
            if random.random() < lp._QC_WEIGHTS.get(task, lp._DEFAULT_QC_WEIGHT)
        )
        assert sampled == N, "Legal reasoning should be sampled 100% of the time"


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------

class TestFallbackChain:
    def test_fallback_used_when_primary_fails(self):
        lp = _import()
        call_count = {"n": 0}

        def mock_post(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Exception("rate limit")
            m = MagicMock()
            m.json.return_value = {
                "choices": [{"message": {"content": '{"decision":"confident","reasoning":"ok","confidence_score":0.9}'}}]
            }
            m.raise_for_status = MagicMock()
            return m

        with patch("httpx.post", side_effect=mock_post):
            model, decision, reasoning, cost = lp.call_godhead_sync(
                "legal_reasoning", "test prompt", "test response")
        assert call_count["n"] == 2, "Should have tried primary then fallback"
        assert decision == "confident"

    def test_all_teachers_fail_returns_skip(self):
        lp = _import()
        with patch("httpx.post", side_effect=Exception("all failed")):
            model, decision, reasoning, cost = lp.call_godhead_sync(
                "legal_reasoning", "test prompt", "test response")
        assert decision == "skip"
        assert model == "none"
        assert cost == Decimal("0")


# ---------------------------------------------------------------------------
# Fire-and-forget / non-blocking
# ---------------------------------------------------------------------------

class TestFireAndForget:
    def test_queue_capture_does_not_block(self):
        lp = _import()
        called = threading.Event()

        def slow_label(*a, **kw):
            import time
            called.set()
            time.sleep(10)  # simulate slow Godhead call

        with patch.object(lp, "_budget_pct_used", return_value=50.0), \
             patch.object(lp, "call_godhead_sync", side_effect=slow_label):
            start = __import__("time").perf_counter()
            lp.queue_capture_for_labeling(
                capture_id="test-uuid",
                capture_table="llm_training_captures",
                task_type="vrs_concierge",
                user_prompt="test",
                sovereign_response="test response",
            )
            elapsed = __import__("time").perf_counter() - start
        # Should return almost immediately (< 0.5s), not wait for label
        assert elapsed < 0.5, f"queue_capture blocked for {elapsed:.2f}s — must be non-blocking"

    def test_queue_capture_never_raises(self):
        lp = _import()
        # Even if everything explodes, queue_capture should swallow it
        with patch.object(lp, "_budget_pct_used", side_effect=Exception("DB down")):
            lp.queue_capture_for_labeling(
                "uuid", "llm_training_captures", "legal_reasoning", "p", "r")
        # If we get here without exception, the test passes

    def test_labeling_deferred_when_over_threshold(self):
        lp = _import()
        called = {"labeling": False}

        def mock_label(*a, **kw):
            called["labeling"] = True
            return "model", "confident", "ok", Decimal("0.01")

        with patch.object(lp, "_budget_pct_used", return_value=90.0), \
             patch.object(lp, "call_godhead_sync", side_effect=mock_label):
            lp.queue_capture_for_labeling("uuid", "llm_tc", "vrs_concierge", "p", "r")
            import time; time.sleep(0.2)

        assert not called["labeling"], "Should not call Godhead when over budget threshold"


# ---------------------------------------------------------------------------
# QC flag
# ---------------------------------------------------------------------------

class TestQCFlag:
    def test_write_label_sets_qc_sampled(self):
        lp = _import()
        calls = []

        def mock_connect(*a, **kw):
            conn = MagicMock()
            cur  = MagicMock()
            conn.cursor.return_value = cur
            cur.execute.side_effect = lambda sql, params: calls.append(params)
            return conn

        with patch("psycopg2.connect", side_effect=mock_connect):
            lp.write_label_sync(
                "uuid-123", "llm_training_captures", "legal_reasoning",
                "claude", "confident", "good", Decimal("0.001"),
            )

        assert len(calls) == 1
        # qc_sampled is the 10th parameter in the INSERT (0-indexed: index 9)
        # For legal_reasoning weight=1.0, qc_sampled must be True
        qc_param = calls[0][9]  # qc_sampled position
        assert qc_param is True, "legal_reasoning should always be QC sampled"
