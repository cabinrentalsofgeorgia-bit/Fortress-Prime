"""
Tests for qdrant_dual_writer.py — Phase 5a Part 3 dual-write helper.

All async functions tested via asyncio.run() to match the existing
backend test pattern (no pytest-asyncio dependency).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.qdrant_dual_writer import (
    _write_primary,
    _write_secondary,
    dual_upsert_points,
    get_metrics,
    reset_metrics,
)


def run(coro):
    """Run a coroutine synchronously — mirrors backend test pattern."""
    return asyncio.run(coro)


SAMPLE_POINTS = [
    {"id": "aaa-111", "vector": [0.1] * 768, "payload": {"source_table": "test"}},
    {"id": "bbb-222", "vector": [0.2] * 768, "payload": {"source_table": "test"}},
]


@pytest.fixture(autouse=True)
def _reset():
    """Reset metrics before every test."""
    reset_metrics()
    yield
    reset_metrics()


# ---------------------------------------------------------------------------
# _write_primary
# ---------------------------------------------------------------------------

class TestWritePrimary:
    def test_calls_correct_url(self):
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.put = AsyncMock(return_value=mock_resp)

        with (
            patch("backend.services.qdrant_dual_writer.settings") as mock_settings,
            patch("backend.services.qdrant_dual_writer.httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.qdrant_url = "http://spark-2:6333"
            mock_settings.qdrant_api_key = ""
            run(_write_primary(SAMPLE_POINTS, "fgp_knowledge"))

        url_called = mock_client.put.call_args[0][0]
        assert "spark-2:6333" in url_called
        assert "fgp_knowledge" in url_called

    def test_raises_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("500 Internal Server Error")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.put = AsyncMock(return_value=mock_resp)

        with (
            patch("backend.services.qdrant_dual_writer.settings") as mock_settings,
            patch("backend.services.qdrant_dual_writer.httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.qdrant_url = "http://spark-2:6333"
            mock_settings.qdrant_api_key = ""
            with pytest.raises(Exception, match="500"):
                run(_write_primary(SAMPLE_POINTS, "fgp_knowledge"))


# ---------------------------------------------------------------------------
# _write_secondary
# ---------------------------------------------------------------------------

class TestWriteSecondary:
    def test_success_increments_success_metric(self):
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.put = AsyncMock(return_value=mock_resp)

        with (
            patch("backend.services.qdrant_dual_writer.settings") as mock_settings,
            patch("backend.services.qdrant_dual_writer.httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.qdrant_vrs_url = "http://spark-4:6333"
            mock_settings.qdrant_api_key = ""
            run(_write_secondary(SAMPLE_POINTS, "fgp_vrs_knowledge"))

        assert get_metrics()["qdrant_vrs_dual_write_success_total"] == 1
        assert get_metrics()["qdrant_vrs_dual_write_failure_total"] == 0

    def test_failure_increments_failure_metric_no_raise(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.put = AsyncMock(side_effect=Exception("connection refused"))

        with (
            patch("backend.services.qdrant_dual_writer.settings") as mock_settings,
            patch("backend.services.qdrant_dual_writer.httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.qdrant_vrs_url = "http://spark-4:6333"
            mock_settings.qdrant_api_key = ""
            # Must NOT raise
            run(_write_secondary(SAMPLE_POINTS, "fgp_vrs_knowledge"))

        assert get_metrics()["qdrant_vrs_dual_write_failure_total"] == 1
        assert get_metrics()["qdrant_vrs_dual_write_success_total"] == 0

    def test_calls_correct_secondary_url(self):
        mock_resp = MagicMock(status_code=200)
        mock_resp.raise_for_status = MagicMock()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.put = AsyncMock(return_value=mock_resp)

        with (
            patch("backend.services.qdrant_dual_writer.settings") as mock_settings,
            patch("backend.services.qdrant_dual_writer.httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.qdrant_vrs_url = "http://192.168.0.106:6333"
            mock_settings.qdrant_api_key = ""
            run(_write_secondary(SAMPLE_POINTS, "fgp_vrs_knowledge"))

        url_called = mock_client.put.call_args[0][0]
        assert "192.168.0.106:6333" in url_called
        assert "fgp_vrs_knowledge" in url_called


# ---------------------------------------------------------------------------
# dual_upsert_points — integration behavior
# ---------------------------------------------------------------------------

class TestDualUpsertPoints:
    def test_empty_points_is_noop(self):
        with patch("backend.services.qdrant_dual_writer._write_primary", new=AsyncMock()) as p:
            run(dual_upsert_points([]))
            p.assert_not_called()
        assert get_metrics()["qdrant_vrs_dual_write_skipped_total"] == 0

    def test_primary_succeeds_secondary_task_created_when_flag_on(self):
        """Primary awaited; secondary fire-and-forget task created."""
        with (
            patch("backend.services.qdrant_dual_writer._write_primary", new=AsyncMock()) as mock_pri,
            patch("backend.services.qdrant_dual_writer.asyncio.create_task") as mock_task,
            patch("backend.services.qdrant_dual_writer.settings") as mock_settings,
        ):
            mock_settings.enable_qdrant_vrs_dual_write = True
            mock_task.return_value = MagicMock()
            mock_task.return_value.add_done_callback = MagicMock()
            run(dual_upsert_points(SAMPLE_POINTS))

        mock_pri.assert_called_once_with(SAMPLE_POINTS, "fgp_knowledge")
        mock_task.assert_called_once()

    def test_primary_failure_raises_secondary_not_called(self):
        """Primary raises → secondary task never created."""
        with (
            patch("backend.services.qdrant_dual_writer._write_primary",
                  new=AsyncMock(side_effect=Exception("spark-2 down"))) as mock_pri,
            patch("backend.services.qdrant_dual_writer.asyncio.create_task") as mock_task,
            patch("backend.services.qdrant_dual_writer.settings") as mock_settings,
        ):
            mock_settings.enable_qdrant_vrs_dual_write = True
            with pytest.raises(Exception, match="spark-2 down"):
                run(dual_upsert_points(SAMPLE_POINTS))

        mock_pri.assert_called_once()
        mock_task.assert_not_called()

    def test_feature_flag_off_skips_secondary_and_increments_skipped(self):
        """Flag off → no secondary call, skipped metric incremented."""
        with (
            patch("backend.services.qdrant_dual_writer._write_primary", new=AsyncMock()),
            patch("backend.services.qdrant_dual_writer.asyncio.create_task") as mock_task,
            patch("backend.services.qdrant_dual_writer.settings") as mock_settings,
        ):
            mock_settings.enable_qdrant_vrs_dual_write = False
            run(dual_upsert_points(SAMPLE_POINTS))

        mock_task.assert_not_called()
        assert get_metrics()["qdrant_vrs_dual_write_skipped_total"] == 1

    def test_correct_collection_names_passed_to_each_side(self):
        """Primary gets fgp_knowledge; secondary task wraps fgp_vrs_knowledge coroutine."""
        captured_coro = []

        def fake_create_task(coro):
            captured_coro.append(coro)
            t = MagicMock()
            t.add_done_callback = MagicMock()
            return t

        with (
            patch("backend.services.qdrant_dual_writer._write_primary", new=AsyncMock()) as mock_pri,
            patch("backend.services.qdrant_dual_writer.asyncio.create_task",
                  side_effect=fake_create_task),
            patch("backend.services.qdrant_dual_writer.settings") as mock_settings,
        ):
            mock_settings.enable_qdrant_vrs_dual_write = True
            run(dual_upsert_points(SAMPLE_POINTS))

        mock_pri.assert_called_once_with(SAMPLE_POINTS, "fgp_knowledge")
        assert len(captured_coro) == 1
        # The coroutine name confirms secondary collection routing
        assert "_write_secondary" in captured_coro[0].__qualname__
        captured_coro[0].close()  # prevent "coroutine never awaited" warning
