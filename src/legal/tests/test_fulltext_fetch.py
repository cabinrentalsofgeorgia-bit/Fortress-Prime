"""Tests for Phase 4d Part 1b — full-text fetch + resumable ingestion."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError


def _ci():
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from src.legal import corpus_ingest as ci
    return ci


# ---------------------------------------------------------------------------
# Progress file helpers
# ---------------------------------------------------------------------------

class TestProgressFile:
    def test_load_progress_empty_when_missing(self, tmp_path: Path) -> None:
        ci = _ci()
        result = ci._load_progress(tmp_path / ".progress")
        assert result == set()

    def test_load_progress_reads_ids(self, tmp_path: Path) -> None:
        ci = _ci()
        p = tmp_path / ".progress"
        p.write_text("123\n456\n789\n")
        result = ci._load_progress(p)
        assert result == {"123", "456", "789"}

    def test_append_progress_creates_file(self, tmp_path: Path) -> None:
        ci = _ci()
        p = tmp_path / ".progress"
        ci._append_progress(p, "abc123")
        assert p.read_text().strip() == "abc123"

    def test_append_progress_accumulates(self, tmp_path: Path) -> None:
        ci = _ci()
        p = tmp_path / ".progress"
        ci._append_progress(p, "id1")
        ci._append_progress(p, "id2")
        ids = {l.strip() for l in p.read_text().splitlines() if l.strip()}
        assert ids == {"id1", "id2"}


# ---------------------------------------------------------------------------
# API retry logic
# ---------------------------------------------------------------------------

class TestApiRetry:
    def test_retries_on_502(self) -> None:
        ci = _ci()
        call_count = [0]

        def fake_urlopen(req, timeout=30):
            call_count[0] += 1
            if call_count[0] < 3:
                raise HTTPError(req.full_url, 502, "Bad Gateway", {}, None)
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"results": [], "count": 0}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             patch("time.sleep"):
            result = ci._api_get("https://example.com/api/", "fake_token", max_retries=5)
        assert call_count[0] == 3
        assert result == {"results": [], "count": 0}

    def test_raises_after_max_retries(self) -> None:
        ci = _ci()
        import pytest
        with patch("urllib.request.urlopen",
                   side_effect=HTTPError("http://x", 502, "Bad Gateway", {}, None)), \
             patch("time.sleep"):
            with pytest.raises(HTTPError):
                ci._api_get("https://example.com/", "tok", max_retries=3)

    def test_respects_retry_after_on_429(self) -> None:
        ci = _ci()
        slept: list[float] = []
        call_count = [0]

        def fake_urlopen(req, timeout=30):
            call_count[0] += 1
            if call_count[0] == 1:
                headers = MagicMock()
                headers.get = lambda k, d=None: "10" if k == "Retry-After" else d
                raise HTTPError(req.full_url, 429, "Too Many Requests", headers, None)
            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"ok": true}'
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             patch("time.sleep", side_effect=lambda s: slept.append(s)):
            ci._api_get("https://example.com/", "tok", max_retries=3)
        assert 10 in slept  # Retry-After value was respected

    def test_does_not_retry_404(self) -> None:
        ci = _ci()
        import pytest
        with patch("urllib.request.urlopen",
                   side_effect=HTTPError("http://x", 404, "Not Found", {}, None)):
            with pytest.raises(HTTPError) as exc_info:
                ci._api_get("https://example.com/", "tok", max_retries=5)
        assert exc_info.value.code == 404


# ---------------------------------------------------------------------------
# Resumption: mid-pull interruption
# ---------------------------------------------------------------------------

class TestResumption:
    def test_skips_already_fetched_ids(self, tmp_path: Path) -> None:
        ci = _ci()

        # Create 3-record metadata JSONL
        metadata = tmp_path / "meta.jsonl"
        metadata.write_text("\n".join([
            json.dumps({"cluster_id": "1", "case_name": "A v B", "court": "ga",
                        "date_filed": "2020-01-01", "citation": []}),
            json.dumps({"cluster_id": "2", "case_name": "C v D", "court": "ga",
                        "date_filed": "2021-01-01", "citation": []}),
            json.dumps({"cluster_id": "3", "case_name": "E v F", "court": "ga",
                        "date_filed": "2022-01-01", "citation": []}),
        ]))

        # Pre-seed progress with IDs 1 and 2 already done
        progress = tmp_path / ".progress"
        progress.write_text("1\n2\n")

        # Output file already has records for 1 and 2
        out_file = tmp_path / "opinions-full.jsonl"
        out_file.write_text(
            json.dumps({"cluster_id": "1", "plain_text": "existing text 1"}) + "\n" +
            json.dumps({"cluster_id": "2", "plain_text": "existing text 2"}) + "\n"
        )

        api_calls: list[str] = []

        def fake_api_get(url: str, token: str, **kw: Any) -> dict:
            api_calls.append(url)
            return {"results": [{
                "id": "99",
                "plain_text": f"full text for {url}",
                "html_with_citations": "",
            }]}

        with patch.object(ci, "CORPUS_ROOT", tmp_path), \
             patch.object(ci, "FULLTEXT_OUT", str(out_file.relative_to(tmp_path))), \
             patch.object(ci, "PROGRESS_FILE", str(progress.relative_to(tmp_path))), \
             patch.object(ci, "_api_get", side_effect=fake_api_get), \
             patch.object(ci, "FULLTEXT_SLEEP", 0), \
             patch("time.sleep"):
            ci.cmd_fetch_fulltext(metadata, resume=True, token="tok")

        # Only ID 3 should have been fetched
        assert len(api_calls) == 1
        assert "cluster=3" in api_calls[0]

    def test_no_resume_refetches_all(self, tmp_path: Path) -> None:
        ci = _ci()
        metadata = tmp_path / "meta.jsonl"
        metadata.write_text("\n".join([
            json.dumps({"cluster_id": "1", "case_name": "A", "court": "ga",
                        "date_filed": "2020-01-01", "citation": []}),
        ]))
        # Empty progress = all IDs skipped when resume=True but no prior progress
        api_calls: list[str] = []

        def fake_api_get(url: str, token: str, **kw: Any) -> dict:
            api_calls.append(url)
            return {"results": [{"id": "10", "plain_text": "text", "html_with_citations": ""}]}

        with patch.object(ci, "CORPUS_ROOT", tmp_path), \
             patch.object(ci, "FULLTEXT_OUT", "out.jsonl"), \
             patch.object(ci, "PROGRESS_FILE", ".prog"), \
             patch.object(ci, "_api_get", side_effect=fake_api_get), \
             patch.object(ci, "FULLTEXT_SLEEP", 0), \
             patch("time.sleep"):
            ci.cmd_fetch_fulltext(metadata, resume=False, token="tok")

        assert len(api_calls) == 1  # fetched the one record


# ---------------------------------------------------------------------------
# Missing download_url / empty results
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_handles_missing_cluster_id(self, tmp_path: Path) -> None:
        ci = _ci()
        metadata = tmp_path / "meta.jsonl"
        metadata.write_text(json.dumps({"case_name": "No ID Case", "date_filed": "2020-01-01", "citation": []}) + "\n")

        with patch.object(ci, "CORPUS_ROOT", tmp_path), \
             patch.object(ci, "FULLTEXT_OUT", "out.jsonl"), \
             patch.object(ci, "PROGRESS_FILE", ".prog"), \
             patch.object(ci, "FULLTEXT_SLEEP", 0), \
             patch("time.sleep"):
            # Should not raise
            ci.cmd_fetch_fulltext(metadata, resume=True, token="tok")

    def test_handles_empty_opinions_result(self, tmp_path: Path) -> None:
        ci = _ci()
        metadata = tmp_path / "meta.jsonl"
        metadata.write_text(json.dumps({"cluster_id": "999", "case_name": "X", "date_filed": "2020-01-01", "citation": []}) + "\n")

        def fake_api_get(url: str, token: str, **kw: Any) -> dict:
            return {"results": []}  # No opinions returned

        with patch.object(ci, "CORPUS_ROOT", tmp_path), \
             patch.object(ci, "FULLTEXT_OUT", "out.jsonl"), \
             patch.object(ci, "PROGRESS_FILE", ".prog"), \
             patch.object(ci, "_api_get", side_effect=fake_api_get), \
             patch.object(ci, "FULLTEXT_SLEEP", 0), \
             patch("time.sleep"):
            ci.cmd_fetch_fulltext(metadata, resume=True, token="tok")

        # Should have been marked in progress despite empty result
        progress = tmp_path / ".prog"
        assert "999" in progress.read_text()

    def test_clean_text_strips_excess_blanks(self) -> None:
        ci = _ci()
        messy = "Line 1\n\n\n\n\nLine 2\n\n\n\nLine 3"
        clean = ci._clean_text(messy)
        assert "\n\n\n" not in clean
        assert "Line 1" in clean
        assert "Line 3" in clean
