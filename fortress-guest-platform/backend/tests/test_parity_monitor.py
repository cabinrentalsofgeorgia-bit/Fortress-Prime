"""Tests for verify_dual_write_parity --monitor mode."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.rag.verify_dual_write_parity import (  # type: ignore[import]
    _parity_log_append,
    _write_alarm,
    run_monitor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_client(count: int = 168) -> MagicMock:
    client = MagicMock()
    collection_info = MagicMock()
    collection_info.points_count = count
    client.get_collection.return_value = collection_info
    return client


# ---------------------------------------------------------------------------
# Log append + rotation
# ---------------------------------------------------------------------------

class TestParityLogAppend:
    def test_writes_line(self, tmp_path: Path) -> None:
        log_file = tmp_path / "parity.log"
        with patch("src.rag.verify_dual_write_parity.PARITY_LOG", log_file):
            _parity_log_append('{"status":"pass"}')
        assert log_file.exists()
        assert '{"status":"pass"}' in log_file.read_text()

    def test_rotation_keeps_last_n_lines(self, tmp_path: Path) -> None:
        log_file = tmp_path / "parity.log"
        # Write 5 lines with max=3
        with patch("src.rag.verify_dual_write_parity.PARITY_LOG", log_file), \
             patch("src.rag.verify_dual_write_parity.PARITY_LOG_MAX_LINES", 3):
            for i in range(5):
                _parity_log_append(f"line-{i}")
        lines = [l for l in log_file.read_text().splitlines() if l]
        assert len(lines) == 3
        assert lines[-1] == "line-4"
        assert "line-0" not in lines
        assert "line-1" not in lines

    def test_fallback_on_permission_error(self, tmp_path: Path) -> None:
        fallback = tmp_path / "fallback.log"
        with patch("src.rag.verify_dual_write_parity.PARITY_LOG", Path("/proc/nonexistent/nope.log")), \
             patch("src.rag.verify_dual_write_parity._PARITY_LOG_FALLBACK", fallback):
            _parity_log_append('{"status":"pass"}')
        assert fallback.exists()


# ---------------------------------------------------------------------------
# Alarm file
# ---------------------------------------------------------------------------

class TestWriteAlarm:
    def test_writes_alarm_file_on_hard_fail(self, tmp_path: Path) -> None:
        alarm_dir = tmp_path / "parity-alarm"
        with patch("src.rag.verify_dual_write_parity.PARITY_ALARM_DIR", alarm_dir):
            _write_alarm("2026-04-19T12:00:00Z", "count_mismatch", {"src": 168, "tgt": 150})
        alarm_files = list(alarm_dir.glob("alarm-*.error"))
        assert len(alarm_files) == 1
        content = json.loads(alarm_files[0].read_text())
        assert content["reason"] == "count_mismatch"
        assert "timestamp" in content

    def test_alarm_file_not_written_on_success(self, tmp_path: Path) -> None:
        alarm_dir = tmp_path / "parity-alarm"
        # Don't call _write_alarm — verify it's not called during a PASS run
        with patch("src.rag.verify_dual_write_parity.PARITY_ALARM_DIR", alarm_dir), \
             patch("src.rag.verify_dual_write_parity._client") as mock_client_fn, \
             patch("src.rag.verify_dual_write_parity._search_agreement", return_value=(1.0, "pass")), \
             patch("src.rag.verify_dual_write_parity._parity_log_append"):
            mock_client_fn.return_value = _mock_client(168)
            rc = run_monitor()
        assert rc == 0
        assert not alarm_dir.exists() or list(alarm_dir.glob("alarm-*.error")) == []

    def test_alarm_file_not_written_on_soft_fail(self, tmp_path: Path) -> None:
        alarm_dir = tmp_path / "parity-alarm"
        with patch("src.rag.verify_dual_write_parity.PARITY_ALARM_DIR", alarm_dir), \
             patch("src.rag.verify_dual_write_parity._client") as mock_client_fn, \
             patch("src.rag.verify_dual_write_parity._search_agreement", return_value=(0.92, "soft_fail")), \
             patch("src.rag.verify_dual_write_parity._parity_log_append"):
            mock_client_fn.return_value = _mock_client(168)
            rc = run_monitor()
        assert rc == 1
        assert not alarm_dir.exists() or list(alarm_dir.glob("alarm-*.error")) == []


# ---------------------------------------------------------------------------
# Soft vs hard fail classification
# ---------------------------------------------------------------------------

class TestFailClassification:
    def test_pass_on_full_agreement(self, tmp_path: Path) -> None:
        alarm_dir = tmp_path / "alarms"
        with patch("src.rag.verify_dual_write_parity.PARITY_ALARM_DIR", alarm_dir), \
             patch("src.rag.verify_dual_write_parity._client") as mcf, \
             patch("src.rag.verify_dual_write_parity._search_agreement", return_value=(1.0, "pass")), \
             patch("src.rag.verify_dual_write_parity._parity_log_append"):
            mcf.return_value = _mock_client(168)
            assert run_monitor() == 0

    def test_soft_fail_on_90_to_95_agreement(self, tmp_path: Path) -> None:
        alarm_dir = tmp_path / "alarms"
        with patch("src.rag.verify_dual_write_parity.PARITY_ALARM_DIR", alarm_dir), \
             patch("src.rag.verify_dual_write_parity._client") as mcf, \
             patch("src.rag.verify_dual_write_parity._search_agreement", return_value=(0.92, "soft_fail")), \
             patch("src.rag.verify_dual_write_parity._parity_log_append"):
            mcf.return_value = _mock_client(168)
            assert run_monitor() == 1

    def test_hard_fail_on_count_mismatch(self, tmp_path: Path) -> None:
        alarm_dir = tmp_path / "alarms"
        with patch("src.rag.verify_dual_write_parity.PARITY_ALARM_DIR", alarm_dir), \
             patch("src.rag.verify_dual_write_parity._client") as mcf, \
             patch("src.rag.verify_dual_write_parity._search_agreement", return_value=(1.0, "pass")), \
             patch("src.rag.verify_dual_write_parity._parity_log_append"):
            # Return different counts for source vs target
            src_client = _mock_client(168)
            tgt_client = _mock_client(150)
            mcf.side_effect = [src_client, tgt_client]
            rc = run_monitor()
        assert rc == 2
        assert list(alarm_dir.glob("alarm-*.error"))

    def test_hard_fail_on_search_below_90(self, tmp_path: Path) -> None:
        alarm_dir = tmp_path / "alarms"
        with patch("src.rag.verify_dual_write_parity.PARITY_ALARM_DIR", alarm_dir), \
             patch("src.rag.verify_dual_write_parity._client") as mcf, \
             patch("src.rag.verify_dual_write_parity._search_agreement", return_value=(0.80, "hard_fail")), \
             patch("src.rag.verify_dual_write_parity._parity_log_append"):
            mcf.return_value = _mock_client(168)
            rc = run_monitor()
        assert rc == 2
        assert list(alarm_dir.glob("alarm-*.error"))

    def test_hard_fail_on_connection_error(self, tmp_path: Path) -> None:
        alarm_dir = tmp_path / "alarms"
        with patch("src.rag.verify_dual_write_parity.PARITY_ALARM_DIR", alarm_dir), \
             patch("src.rag.verify_dual_write_parity._client", side_effect=ConnectionError("refused")), \
             patch("src.rag.verify_dual_write_parity._parity_log_append"):
            rc = run_monitor()
        assert rc == 2
        assert list(alarm_dir.glob("alarm-*.error"))


# ---------------------------------------------------------------------------
# JSON output format
# ---------------------------------------------------------------------------

class TestMonitorJsonOutput:
    def test_json_line_contains_required_fields(self, tmp_path: Path) -> None:
        log_file = tmp_path / "parity.log"
        alarm_dir = tmp_path / "alarms"
        with patch("src.rag.verify_dual_write_parity.PARITY_LOG", log_file), \
             patch("src.rag.verify_dual_write_parity.PARITY_ALARM_DIR", alarm_dir), \
             patch("src.rag.verify_dual_write_parity._client") as mcf, \
             patch("src.rag.verify_dual_write_parity._search_agreement", return_value=(1.0, "pass")):
            mcf.return_value = _mock_client(168)
            run_monitor()
        lines = [l for l in log_file.read_text().splitlines() if l]
        assert lines
        entry = json.loads(lines[-1])
        assert "timestamp" in entry
        assert "overall_status" in entry
        assert "count_parity_pct" in entry
        assert "src_count" in entry
        assert "tgt_count" in entry
        assert "count_match" in entry
        assert "search_parity" in entry
        assert isinstance(entry["search_parity"], dict)


# ---------------------------------------------------------------------------
# drift_alarm integration
# ---------------------------------------------------------------------------

class TestDriftAlarmIntegration:
    def test_check_parity_alarms_empty_dir(self, tmp_path: Path) -> None:
        import tools.drift_alarm as da  # type: ignore[import]
        (tmp_path / "parity-alarm").mkdir()
        with patch.object(da, "PARITY_ALARM_DIR", tmp_path / "parity-alarm"):
            result = da.check_parity_alarms()
        assert result == []

    def test_check_parity_alarms_finds_error_files(self, tmp_path: Path) -> None:
        import tools.drift_alarm as da  # type: ignore[import]
        alarm_dir = tmp_path / "parity-alarm"
        alarm_dir.mkdir()
        (alarm_dir / "alarm-20260419T120000Z.error").write_text("{}")
        (alarm_dir / "alarm-20260419T130000Z.error").write_text("{}")
        with patch.object(da, "PARITY_ALARM_DIR", alarm_dir):
            result = da.check_parity_alarms()
        assert len(result) == 2

    def test_check_parity_alarms_missing_dir(self, tmp_path: Path) -> None:
        import tools.drift_alarm as da  # type: ignore[import]
        with patch.object(da, "PARITY_ALARM_DIR", tmp_path / "nonexistent"):
            result = da.check_parity_alarms()
        assert result == []
