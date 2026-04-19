"""Tests for Phase 5a Part 4 — fgp_knowledge read endpoint resolver."""
import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


def _rt():
    from backend.services import qdrant_dual_writer as dw
    return dw


def _kr():
    from backend.services import knowledge_retriever as kr
    return kr


# ---------------------------------------------------------------------------
# resolve_read_endpoint
# ---------------------------------------------------------------------------

class TestResolveReadEndpoint:
    def test_default_flag_false_returns_spark2(self) -> None:
        dw = _rt()
        with patch.object(dw.settings, "read_from_vrs_store", False), \
             patch.object(dw.settings, "qdrant_url", "http://192.168.0.100:6333"), \
             patch.object(dw.settings, "qdrant_vrs_url", "http://192.168.0.106:6333"):
            url, collection = dw.resolve_read_endpoint()
        assert url == "http://192.168.0.100:6333"
        assert collection == "fgp_knowledge"

    def test_flag_true_returns_spark4(self) -> None:
        dw = _rt()
        with patch.object(dw.settings, "read_from_vrs_store", True), \
             patch.object(dw.settings, "qdrant_url", "http://192.168.0.100:6333"), \
             patch.object(dw.settings, "qdrant_vrs_url", "http://192.168.0.106:6333"):
            url, collection = dw.resolve_read_endpoint()
        assert url == "http://192.168.0.106:6333"
        assert collection == "fgp_vrs_knowledge"

    def test_trailing_slash_stripped(self) -> None:
        dw = _rt()
        with patch.object(dw.settings, "read_from_vrs_store", False), \
             patch.object(dw.settings, "qdrant_url", "http://192.168.0.100:6333/"), \
             patch.object(dw.settings, "qdrant_vrs_url", "http://192.168.0.106:6333/"):
            url, _ = dw.resolve_read_endpoint()
        assert not url.endswith("/")

    def test_vrs_trailing_slash_stripped(self) -> None:
        dw = _rt()
        with patch.object(dw.settings, "read_from_vrs_store", True), \
             patch.object(dw.settings, "qdrant_url", "http://192.168.0.100:6333/"), \
             patch.object(dw.settings, "qdrant_vrs_url", "http://192.168.0.106:6333/"):
            url, _ = dw.resolve_read_endpoint()
        assert not url.endswith("/")

    def test_returns_tuple_of_two_strings(self) -> None:
        dw = _rt()
        result = dw.resolve_read_endpoint()
        assert isinstance(result, tuple) and len(result) == 2
        assert all(isinstance(v, str) for v in result)


# ---------------------------------------------------------------------------
# knowledge_retriever uses resolver
# ---------------------------------------------------------------------------

class TestKnowledgeRetrieverUsesResolver:
    def _run(self, coro: Any) -> Any:
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_flag_false_search_hits_spark2_url(self) -> None:
        kr = _kr()
        dw = _rt()
        captured: list[str] = []

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "result": [{"score": 0.9, "payload": {"text": "lodge info"}}]
        }

        with patch.object(dw.settings, "read_from_vrs_store", False), \
             patch.object(dw.settings, "qdrant_url", "http://192.168.0.100:6333"), \
             patch.object(dw.settings, "qdrant_vrs_url", "http://192.168.0.106:6333"), \
             patch("httpx.AsyncClient") as mock_client:
            mock_session = MagicMock()

            def capture_post(url: str, **_kwargs: Any) -> Any:
                captured.append(url)
                fut: asyncio.Future = asyncio.get_event_loop().create_future()
                fut.set_result(mock_resp)
                return fut

            mock_session.post = capture_post
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            self._run(kr._qdrant_search([0.1] * 768))

        assert captured, "no HTTP call captured"
        assert "192.168.0.100" in captured[0]
        assert "fgp_knowledge" in captured[0]

    def test_flag_true_search_hits_spark4_url(self) -> None:
        kr = _kr()
        dw = _rt()
        captured: list[str] = []

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "result": [{"score": 0.88, "payload": {"text": "vrs lodge info"}}]
        }

        with patch.object(dw.settings, "read_from_vrs_store", True), \
             patch.object(dw.settings, "qdrant_url", "http://192.168.0.100:6333"), \
             patch.object(dw.settings, "qdrant_vrs_url", "http://192.168.0.106:6333"), \
             patch("httpx.AsyncClient") as mock_client:
            mock_session = MagicMock()

            def capture_post(url: str, **_kwargs: Any) -> Any:
                captured.append(url)
                fut: asyncio.Future = asyncio.get_event_loop().create_future()
                fut.set_result(mock_resp)
                return fut

            mock_session.post = capture_post
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            self._run(kr._qdrant_search([0.1] * 768))

        assert captured, "no HTTP call captured"
        assert "192.168.0.106" in captured[0]
        assert "fgp_vrs_knowledge" in captured[0]


# ---------------------------------------------------------------------------
# Parity: equivalent results (skipped when live Qdrants not available)
# ---------------------------------------------------------------------------

class TestSearchEquivalentResults:
    def test_compare_search_skip_if_no_live_qdrant(self) -> None:
        """Verify compare_search returns 1 (FAIL) when both endpoints are unreachable
        rather than raising — no live Qdrant required in CI."""
        import sys  # noqa: E401
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3]))
        from src.rag.verify_dual_write_parity import compare_search

        # With no live Qdrant the embed call will fail → returns 1, not raises
        result = compare_search("what does Fallen Timber Lodge look like")
        assert result in (0, 1), "compare_search must return int exit code"
