"""Tests for run.py PORT env var behaviour."""
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

_RUN_PY = Path(__file__).resolve().parents[2] / "run.py"


def _load_run(extra_env: dict[str, str]) -> tuple[Any, MagicMock]:
    """Import run.py in a clean module slot with the given env vars set."""
    mod_name = f"_fgp_run_{os.getpid()}"
    spec = importlib.util.spec_from_file_location(mod_name, _RUN_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    uvicorn_mock = MagicMock()
    with patch.dict(os.environ, extra_env, clear=False), \
         patch.dict(sys.modules, {"uvicorn": uvicorn_mock}):
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod, uvicorn_mock


class TestRunPort:
    def test_default_port_is_8000(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("PORT", raising=False)
        mod, uvicorn_mock = _load_run({})
        mod._serve()
        _, kwargs = uvicorn_mock.run.call_args
        assert kwargs["port"] == 8000

    def test_port_read_from_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("PORT", "8100")
        mod, uvicorn_mock = _load_run({"PORT": "8100"})
        mod._serve()
        _, kwargs = uvicorn_mock.run.call_args
        assert kwargs["port"] == 8100

    def test_port_is_integer(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("PORT", "9000")
        mod, uvicorn_mock = _load_run({"PORT": "9000"})
        mod._serve()
        _, kwargs = uvicorn_mock.run.call_args
        assert isinstance(kwargs["port"], int)
