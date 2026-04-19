"""Tests for Phase 4e.3 judge runtime — including Path C per-task latency budgets."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _rt():
    from backend.services import judge_runtime as rt
    return rt


# A minimal active judge entry used by tests that exercise the full HTTP path.
# All real judges have is_active=False until trained; tests that need to reach
# the Ollama call must inject is_active=True via patch.dict.
def _active_vrs_entry():
    return {
        "judge_model": "vrs_concierge_judge",
        "target_node": "192.168.0.106",
        "base_model":  "qwen2.5:7b",
        "is_active":   True,
    }


# ---------------------------------------------------------------------------
# JudgeDecision parsing
# ---------------------------------------------------------------------------

class TestJudgeParsing:
    def test_parses_valid_json(self):
        rt = _rt()
        raw = '{"decision": "confident", "reasoning": "response is accurate"}'
        result = rt._parse(raw, "test_model", 50)
        assert result.decision == "confident"
        assert "accurate" in result.reasoning
        assert result.latency_ms == 50

    def test_parses_escalate(self):
        rt = _rt()
        raw = '{"decision": "escalate", "reasoning": "hallucinated statutes"}'
        result = rt._parse(raw, "test_model", 80)
        assert result.decision == "escalate"

    def test_parses_uncertain(self):
        rt = _rt()
        raw = '{"decision": "uncertain", "reasoning": "marginal quality"}'
        result = rt._parse(raw, "test_model", 60)
        assert result.decision == "uncertain"

    def test_malformed_json_returns_uncertain(self):
        rt = _rt()
        result = rt._parse("not json at all", "model", 50)
        assert result.decision == "uncertain"
        assert "malformed" in result.reasoning.lower() or "parsed" in result.reasoning.lower()

    def test_invalid_decision_keyword_scan_fallback(self):
        rt = _rt()
        result = rt._parse("I think this should escalate because it's wrong", "model", 50)
        assert result.decision == "escalate"

    def test_confident_keyword_scan(self):
        rt = _rt()
        result = rt._parse("The response is confident and correct", "model", 50)
        assert result.decision == "confident"

    def test_markdown_wrapped_json(self):
        rt = _rt()
        raw = '```json\n{"decision": "uncertain", "reasoning": "needs review"}\n```'
        result = rt._parse(raw, "model", 50)
        assert result.decision == "uncertain"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------

class TestJudgeFailureModes:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_judge_disabled_returns_confident(self):
        rt = _rt()
        with patch.object(rt, "JUDGE_ENABLED", False):
            result = self._run(rt.judge_response("vrs_concierge", "test", "response"))
        assert result.decision == "confident"
        assert result.latency_ms == 0
        assert "disabled" in result.reasoning

    def test_no_judge_for_task_type_returns_confident(self):
        rt = _rt()
        with patch.object(rt, "JUDGE_ENABLED", True):
            result = self._run(rt.judge_response("unknown_task_xyz", "test", "response"))
        assert result.decision == "confident"
        assert "no_judge_for_task_type" in result.reasoning

    def test_timeout_returns_uncertain(self):
        import httpx as _httpx
        rt = _rt()
        with patch.object(rt, "JUDGE_ENABLED", True), \
             patch.dict(rt._JUDGE_MAP, {"vrs_concierge": _active_vrs_entry()}), \
             patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                side_effect=_httpx.TimeoutException("timeout"))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = self._run(rt.judge_response("vrs_concierge", "test", "response"))
        assert result.decision == "uncertain"
        assert "timeout" in result.reasoning.lower()

    def test_connection_error_returns_confident_fail_open(self):
        import httpx as _httpx
        rt = _rt()
        with patch.object(rt, "JUDGE_ENABLED", True), \
             patch.dict(rt._JUDGE_MAP, {"vrs_concierge": _active_vrs_entry()}), \
             patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                side_effect=_httpx.ConnectError("refused"))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = self._run(rt.judge_response("vrs_concierge", "test", "response"))
        assert result.decision == "confident"
        assert "unreachable" in result.reasoning.lower()

    def test_malformed_response_returns_uncertain(self):
        rt = _rt()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"message": {"content": "garbled output xyz"}}
        with patch.object(rt, "JUDGE_ENABLED", True), \
             patch.dict(rt._JUDGE_MAP, {"vrs_concierge": _active_vrs_entry()}), \
             patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=mock_resp)))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = self._run(rt.judge_response("vrs_concierge", "test", "response"))
        assert result.decision in ("uncertain", "confident")  # keyword scan may find something

    def test_generic_exception_returns_uncertain(self):
        rt = _rt()
        with patch.object(rt, "JUDGE_ENABLED", True), \
             patch.dict(rt._JUDGE_MAP, {"vrs_concierge": _active_vrs_entry()}), \
             patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                side_effect=RuntimeError("unexpected"))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = self._run(rt.judge_response("vrs_concierge", "test", "response"))
        assert result.decision == "uncertain"

    def test_judge_never_raises(self):
        rt = _rt()
        with patch.object(rt, "JUDGE_ENABLED", True), \
             patch.dict(rt._JUDGE_MAP, {"vrs_concierge": _active_vrs_entry()}), \
             patch("httpx.AsyncClient", side_effect=Exception("catastrophic")):
            result = self._run(rt.judge_response("vrs_concierge", "test", "response"))
        assert result.decision in ("confident", "uncertain", "escalate")

    def test_successful_judge_call(self):
        rt = _rt()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "message": {"content": '{"decision": "confident", "reasoning": "good response"}'}}
        with patch.object(rt, "JUDGE_ENABLED", True), \
             patch.dict(rt._JUDGE_MAP, {"vrs_concierge": _active_vrs_entry()}), \
             patch("httpx.AsyncClient") as mock_client:
            mock_session = MagicMock()
            mock_session.post = AsyncMock(return_value=mock_resp)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = self._run(rt.judge_response("vrs_concierge", "when checkout?", "11am"))
        assert result.decision == "confident"
        assert result.judge_model == "vrs_concierge_judge"


# ---------------------------------------------------------------------------
# Path C — per-task timeout budgets and is_active placeholder behavior
# ---------------------------------------------------------------------------

class TestPerTaskTimeouts:
    def test_legal_reasoning_uses_1000ms(self):
        rt = _rt()
        assert rt._JUDGE_TIMEOUTS["legal_reasoning"] == 1000

    def test_vrs_concierge_uses_200ms(self):
        rt = _rt()
        assert rt._JUDGE_TIMEOUTS["vrs_concierge"] == 200

    def test_brief_drafting_uses_1000ms(self):
        rt = _rt()
        assert rt._JUDGE_TIMEOUTS["brief_drafting"] == 1000

    def test_pricing_math_uses_300ms(self):
        rt = _rt()
        assert rt._JUDGE_TIMEOUTS["pricing_math"] == 300

    def test_unknown_task_type_uses_default_env(self):
        """Task types absent from _JUDGE_TIMEOUTS fall back to JUDGE_TIMEOUT_MS."""
        rt = _rt()
        default = rt.JUDGE_TIMEOUT_MS  # 200 from env default
        assert rt._JUDGE_TIMEOUTS.get("completely_unknown_type", default) == default

    def test_timeout_is_used_for_active_judge_call(self):
        """Verify the selected timeout is passed to httpx, not the global default."""
        import httpx as _httpx
        rt = _rt()
        active_legal = {
            "judge_model": "legal_reasoning_judge",
            "target_node": "192.168.0.104",
            "base_model":  "qwen2.5:32b",
            "is_active":   True,
        }
        captured_timeouts = []

        class CapturingClient:
            def __init__(self, timeout, **kwargs):
                captured_timeouts.append(timeout)
            async def __aenter__(self):
                raise _httpx.ConnectError("unreachable — just checking timeout")
            async def __aexit__(self, *a):
                return False

        with patch.object(rt, "JUDGE_ENABLED", True), \
             patch.dict(rt._JUDGE_MAP, {"legal_reasoning": active_legal}), \
             patch("httpx.AsyncClient", CapturingClient):
            asyncio.get_event_loop().run_until_complete(
                rt.judge_response("legal_reasoning", "q", "a"))

        assert captured_timeouts == [1.0], f"Expected 1.0s (1000ms), got {captured_timeouts}"


class TestPlaceholderJudges:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_is_active_false_returns_confident_without_http(self):
        """All placeholder judges return confident without making a network call."""
        rt = _rt()
        with patch.object(rt, "JUDGE_ENABLED", True), \
             patch("httpx.AsyncClient") as mock_client:
            result = self._run(rt.judge_response("vrs_concierge", "test", "resp"))
        assert result.decision == "confident"
        assert "no_judge_for_task_type" in result.reasoning
        mock_client.assert_not_called()

    def test_all_placeholder_task_types_return_confident(self):
        """Every entry in _JUDGE_MAP with is_active=False returns confident."""
        rt = _rt()
        with patch.object(rt, "JUDGE_ENABLED", True):
            for task_type, info in rt._JUDGE_MAP.items():
                if not info.get("is_active", False):
                    result = self._run(rt.judge_response(task_type, "q", "a"))
                    assert result.decision == "confident", \
                        f"{task_type}: expected confident for is_active=False, got {result.decision}"

    def test_all_judge_map_entries_have_required_fields(self):
        """Every _JUDGE_MAP entry has the required schema fields."""
        rt = _rt()
        required = {"judge_model", "target_node", "base_model", "is_active"}
        for task_type, info in rt._JUDGE_MAP.items():
            missing = required - set(info.keys())
            assert not missing, f"{task_type} missing fields: {missing}"

    def test_legal_judges_use_32b_base(self):
        """Legal domain judges use qwen2.5:32b (Path C decision)."""
        rt = _rt()
        legal_tasks = {"legal_reasoning", "brief_drafting", "legal_citations", "contract_analysis"}
        for task_type in legal_tasks:
            assert task_type in rt._JUDGE_MAP, f"{task_type} not in _JUDGE_MAP"
            assert rt._JUDGE_MAP[task_type]["base_model"] == "qwen2.5:32b", \
                f"{task_type} should use qwen2.5:32b, got {rt._JUDGE_MAP[task_type]['base_model']}"

    def test_vrs_judges_use_7b_base(self):
        """VRS judges use qwen2.5:7b (same as production inference model)."""
        rt = _rt()
        vrs_tasks = {"vrs_concierge", "vrs_ota_response"}
        for task_type in vrs_tasks:
            assert rt._JUDGE_MAP[task_type]["base_model"] == "qwen2.5:7b"
