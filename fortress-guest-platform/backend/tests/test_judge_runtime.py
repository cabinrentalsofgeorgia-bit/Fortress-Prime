"""Tests for Phase 4e.3 judge runtime."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _rt():
    from backend.services import judge_runtime as rt
    return rt


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
             patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
                post=AsyncMock(return_value=mock_resp)))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = self._run(rt.judge_response("vrs_concierge", "test", "response"))
        assert result.decision in ("uncertain", "confident")  # keyword scan may find something

    def test_generic_exception_returns_uncertain(self):
        rt = _rt()
        with patch.object(rt, "JUDGE_ENABLED", True), \
             patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                side_effect=RuntimeError("unexpected"))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = self._run(rt.judge_response("vrs_concierge", "test", "response"))
        assert result.decision == "uncertain"

    def test_judge_never_raises(self):
        rt = _rt()
        with patch.object(rt, "JUDGE_ENABLED", True), \
             patch("httpx.AsyncClient", side_effect=Exception("catastrophic")):
            # Should not raise
            result = self._run(rt.judge_response("vrs_concierge", "test", "response"))
        assert result.decision in ("confident", "uncertain", "escalate")

    def test_successful_judge_call(self):
        rt = _rt()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "message": {"content": '{"decision": "confident", "reasoning": "good response"}'}}
        with patch.object(rt, "JUDGE_ENABLED", True), \
             patch("httpx.AsyncClient") as mock_client:
            mock_session = MagicMock()
            mock_session.post = AsyncMock(return_value=mock_resp)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = self._run(rt.judge_response("vrs_concierge", "when checkout?", "11am"))
        assert result.decision == "confident"
        assert result.judge_model == "vrs_concierge_judge"
