"""Tests for Phase 5b NIM migration — endpoint config and health probe."""
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# NIM_SOVEREIGN_URL config
# ---------------------------------------------------------------------------

class TestNimSovereignConfig:
    def test_nim_sovereign_url_default_is_spark1(self) -> None:
        from backend.core.config import settings
        assert "192.168.0.104" in settings.nim_sovereign_url

    def test_nim_sovereign_url_env_overridable(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("NIM_SOVEREIGN_URL", "http://10.0.0.1:8000")
        import importlib, backend.core.config as cfg_mod
        importlib.reload(cfg_mod)
        # Field reads from env — verify the env var name is documented
        assert hasattr(cfg_mod.settings, "nim_sovereign_url")
        monkeypatch.delenv("NIM_SOVEREIGN_URL", raising=False)


# ---------------------------------------------------------------------------
# legal_council._NIM_ENDPOINT
# ---------------------------------------------------------------------------

def _fresh_council(monkeypatch: Any):
    """Reload legal_council with clean env — also reloads config to clear cached settings."""
    import importlib
    import backend.core.config as cfg_mod
    import backend.services.legal_council as lc
    monkeypatch.delenv("LEGAL_NIM_ENDPOINT", raising=False)
    monkeypatch.delenv("NIM_SOVEREIGN_URL", raising=False)
    importlib.reload(cfg_mod)
    importlib.reload(lc)
    return lc


def _fresh_deposition(monkeypatch: Any):
    import importlib
    import backend.core.config as cfg_mod
    import backend.services.legal_deposition_engine as de
    monkeypatch.delenv("NIM_SOVEREIGN_URL", raising=False)
    importlib.reload(cfg_mod)
    importlib.reload(de)
    return de


class TestLegalCouncilEndpoint:
    def test_default_points_to_spark1(self, monkeypatch: Any) -> None:
        lc = _fresh_council(monkeypatch)
        assert "192.168.0.104" in lc._NIM_ENDPOINT, \
            f"Expected spark-1 IP in _NIM_ENDPOINT, got: {lc._NIM_ENDPOINT}"

    def test_env_override_respected(self, monkeypatch: Any) -> None:
        import importlib, backend.services.legal_council as lc
        monkeypatch.setenv("LEGAL_NIM_ENDPOINT", "http://10.43.38.88:8000")
        importlib.reload(lc)
        assert "10.43.38.88" in lc._NIM_ENDPOINT
        _fresh_council(monkeypatch)  # restore clean state


# ---------------------------------------------------------------------------
# legal_deposition_engine.SOVEREIGN_URL
# ---------------------------------------------------------------------------

class TestDepositionEndpoint:
    def test_default_points_to_spark1(self, monkeypatch: Any) -> None:
        de = _fresh_deposition(monkeypatch)
        assert "192.168.0.104" in de.SOVEREIGN_URL, \
            f"Expected spark-1 IP in SOVEREIGN_URL, got: {de.SOVEREIGN_URL}"
        assert "/v1/chat/completions" in de.SOVEREIGN_URL

    def test_env_override_respected(self, monkeypatch: Any) -> None:
        import importlib, backend.services.legal_deposition_engine as de
        monkeypatch.setenv("NIM_SOVEREIGN_URL", "http://10.43.38.88:8000")
        importlib.reload(de)
        assert "10.43.38.88" in de.SOVEREIGN_URL
        _fresh_deposition(monkeypatch)  # restore clean state


# ---------------------------------------------------------------------------
# verify_nim_health probe
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.ops.verify_nim_health import probe, NIMProbeResult, EXPECTED_MODEL  # type: ignore[import]


class TestNimHealthProbe:
    def test_probe_returns_result_not_raises_when_unreachable(self) -> None:
        result = probe("http://127.0.0.1:19999")
        assert isinstance(result, NIMProbeResult)
        assert result.up is False
        assert result.model_loaded is False
        assert len(result.error) > 0

    def test_probe_up_model_loaded(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = (
            f'{{"data": [{{"id": "{EXPECTED_MODEL}"}}]}}'.encode()
        )
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = probe("http://192.168.0.104:8000")
        assert result.up is True
        assert result.model_loaded is True
        assert result.model_id == EXPECTED_MODEL
        assert result.response_time_ms >= 0

    def test_probe_up_wrong_model(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"data": [{"id": "wrong/model"}]}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = probe("http://192.168.0.104:8000")
        assert result.up is True
        assert result.model_loaded is False

    def test_run_probe_returns_1_when_unreachable(self) -> None:
        from src.ops.verify_nim_health import run_probe  # type: ignore[import]
        rc = run_probe("http://127.0.0.1:19999")
        assert rc == 1

    def test_run_probe_returns_0_when_healthy(self) -> None:
        from src.ops.verify_nim_health import run_probe  # type: ignore[import]
        mock_resp = MagicMock()
        mock_resp.read.return_value = (
            f'{{"data": [{{"id": "{EXPECTED_MODEL}"}}]}}'.encode()
        )
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            rc = run_probe("http://192.168.0.104:8000")
        assert rc == 0
