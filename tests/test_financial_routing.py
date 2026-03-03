#!/usr/bin/env python3
"""
FORTRESS PRIME — Financial Routing Integration Tests
=====================================================
Isolated tests for The Jordi (covariance matrix injection) and
The Fed Watcher (Qdrant fed_watcher_intel retrieval + God-Head routing).

Mocked path runs without API keys. Live path runs only when
ALLOW_CLOUD_LLM=true and XAI_API_KEY are configured.

Run: python -m pytest tests/test_financial_routing.py -v --tb=short
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.persona_template import Persona, Opinion, Signal


ALLOW_CLOUD = os.getenv("ALLOW_CLOUD_LLM", "false").lower() == "true"
XAI_KEY_SET = bool(os.getenv("XAI_API_KEY", ""))


def _fake_god_head_response() -> dict:
    """Minimal god_head_router.route() return value."""
    return {
        "response": json.dumps({
            "signal": "BUY",
            "conviction": 0.82,
            "reasoning": "Mocked God-Head response for testing.",
            "assets": ["BTC", "SPY"],
            "risk_factors": ["test risk"],
            "catalysts": ["test catalyst"],
        }),
        "provider": "xai",
        "tokens_used": 100,
        "escalation_id": 999,
        "fallback_used": False,
    }


def _fake_correlation_context() -> str:
    """Minimal correlation matrix markdown for injection testing."""
    return (
        "**90-Day Cross-Asset Correlation Matrix**\n\n"
        "| | SPY | BTC |\n|---|---|---|\n"
        "| **SPY** | 1.00 | 0.45 |\n"
        "| **BTC** | 0.45 | 1.00 |\n\n"
        "SPY/BTC are moderately positively correlated (0.45)."
    )


def _fake_qdrant_search_response() -> MagicMock:
    """Minimal Qdrant search response with FOMC payload."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": [
            {
                "id": "abc-123",
                "score": 0.92,
                "payload": {
                    "text": "FOMC held rates steady at 4.25-4.50% on January 29, 2026. "
                            "The committee noted ongoing progress toward 2% inflation.",
                    "source": "fomc_press_release",
                    "persona": "fed_watcher",
                },
            }
        ]
    }
    return mock_resp


# =========================================================================
# THE JORDI — Covariance Matrix Injection
# =========================================================================


class TestJordiRouting:
    """Tests for The Jordi persona: covariance engine + God-Head routing."""

    def test_god_head_domain_set(self):
        """Verify Jordi's persona JSON has god_head_domain='financial'."""
        persona = Persona.load("jordi")
        assert persona.god_head_domain == "financial", (
            f"Expected 'financial', got '{persona.god_head_domain}'"
        )
        print(f"[PASS] test_god_head_domain_set — jordi.god_head_domain == '{persona.god_head_domain}'")

    @patch("src.god_head_router.route", side_effect=lambda **kw: _fake_god_head_response())
    @patch("src.covariance_engine.get_correlation_context", return_value=_fake_correlation_context())
    @patch("src.persona_template.Persona.get_embedding", return_value=[0.1] * 768)
    @patch("src.persona_template.requests.post")
    def test_covariance_injection(self, mock_qdrant_post, mock_embed, mock_corr, mock_route):
        """Verify the correlation matrix is injected into Jordi's context before God-Head call."""
        mock_qdrant_post.return_value = _fake_qdrant_search_response()

        persona = Persona.load("jordi")
        opinion = persona.analyze_event("NVDA earnings beat by 20%")

        assert mock_route.called, "god_head_router.route() was not called"

        call_kwargs = mock_route.call_args
        context_sent = call_kwargs.kwargs.get("context") or call_kwargs[1].get("context", "")
        assert "Correlation Matrix" in context_sent, (
            f"Correlation matrix not found in context. First 200 chars: {context_sent[:200]}"
        )

        domain_sent = call_kwargs.kwargs.get("domain") or call_kwargs[1].get("domain", "")
        assert domain_sent == "financial", f"Expected domain 'financial', got '{domain_sent}'"

        assert isinstance(opinion, Opinion)
        assert opinion.signal in Signal
        print(f"[PASS] test_covariance_injection — Context contains 'Correlation Matrix', domain='financial'")
        print(f"       Context preview: {context_sent[:100]}...")

    @pytest.mark.skipif(
        not (ALLOW_CLOUD and XAI_KEY_SET),
        reason="XAI_API_KEY not configured or ALLOW_CLOUD_LLM != true",
    )
    def test_live_analysis(self):
        """Full round-trip: yfinance -> covariance -> xAI Grok -> Opinion."""
        persona = Persona.load("jordi")
        opinion = persona.analyze_event("NVDA earnings beat expectations by 20%")

        assert isinstance(opinion, Opinion)
        assert opinion.signal in Signal
        assert 0.0 <= opinion.conviction <= 1.0
        print(
            f"[PASS] test_live_analysis — JORDI LIVE: {opinion.signal.value} "
            f"@ {opinion.conviction:.0%} — {opinion.reasoning[:100]}"
        )


# =========================================================================
# THE FED WATCHER — Qdrant Retrieval + God-Head Routing
# =========================================================================


class TestFedWatcherRouting:
    """Tests for The Fed Watcher persona: Qdrant retrieval + God-Head routing."""

    def test_god_head_domain_set(self):
        """Verify Fed Watcher's persona JSON has god_head_domain='financial'."""
        persona = Persona.load("fed_watcher")
        assert persona.god_head_domain == "financial", (
            f"Expected 'financial', got '{persona.god_head_domain}'"
        )
        print(f"[PASS] test_god_head_domain_set — fed_watcher.god_head_domain == '{persona.god_head_domain}'")

    @patch("src.persona_template.requests.post")
    @patch("src.persona_template.Persona.get_embedding", return_value=[0.1] * 768)
    def test_qdrant_search(self, mock_embed, mock_post):
        """Verify Fed Watcher queries the fed_watcher_intel collection."""
        mock_post.return_value = _fake_qdrant_search_response()

        persona = Persona.load("fed_watcher")
        assert persona.vector_collection == "fed_watcher_intel", (
            f"Expected 'fed_watcher_intel', got '{persona.vector_collection}'"
        )

        results = persona.search_knowledge("FOMC rate decision")

        assert mock_post.called, "Qdrant search was not called"
        call_args = mock_post.call_args
        url_called = call_args[0][0] if call_args[0] else call_args.kwargs.get("url", "")
        assert "fed_watcher_intel" in url_called, (
            f"Expected 'fed_watcher_intel' in URL, got: {url_called}"
        )

        assert len(results) > 0, "No results returned from Qdrant search"
        assert "FOMC" in results[0].get("payload", {}).get("text", ""), (
            "FOMC content not in search result payload"
        )
        print(f"[PASS] test_qdrant_search — fed_watcher queries fed_watcher_intel collection")
        print(f"       Result preview: {results[0]['payload']['text'][:100]}...")

    @pytest.mark.skipif(
        not (ALLOW_CLOUD and XAI_KEY_SET),
        reason="XAI_API_KEY not configured or ALLOW_CLOUD_LLM != true",
    )
    def test_live_analysis(self):
        """Full round-trip: Qdrant RAG -> xAI Grok -> Opinion."""
        persona = Persona.load("fed_watcher")
        opinion = persona.analyze_event("FOMC holds rates steady at 4.5%")

        assert isinstance(opinion, Opinion)
        assert opinion.signal in Signal
        assert 0.0 <= opinion.conviction <= 1.0
        print(
            f"[PASS] test_live_analysis — FED_WATCHER LIVE: {opinion.signal.value} "
            f"@ {opinion.conviction:.0%} — {opinion.reasoning[:100]}"
        )
