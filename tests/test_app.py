"""Isolated tests for root app helper routing behavior."""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest


class _DummyContext:
    """Simple context manager used to emulate Streamlit layout primitives."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def metric(self, *args, **kwargs):
        return None

    def write(self, *args, **kwargs):
        return None


class _SessionState(dict):
    """Dict-like state that also supports attribute access used by Streamlit."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _FakeStreamlit:
    """Minimal Streamlit facade to make `app.py` import side-effect free."""

    def __init__(self):
        self.sidebar = _DummyContext()
        self.session_state = _SessionState()

    def set_page_config(self, **kwargs):
        return None

    def image(self, *args, **kwargs):
        return None

    def header(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def subheader(self, *args, **kwargs):
        return None

    def file_uploader(self, *args, **kwargs):
        return None

    def button(self, *args, **kwargs):
        return False

    def spinner(self, *args, **kwargs):
        return _DummyContext()

    def progress(self, *args, **kwargs):
        class _P:
            def progress(self, *_a, **_k):
                return None

        return _P()

    def rerun(self):
        return None

    def tabs(self, labels):
        return [_DummyContext() for _ in labels]

    def columns(self, n):
        return [_DummyContext() for _ in range(n)]

    def dataframe(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def text_input(self, *args, **kwargs):
        return ""

    def expander(self, *args, **kwargs):
        return _DummyContext()

    def chat_input(self, *args, **kwargs):
        return None

    def chat_message(self, *args, **kwargs):
        return _DummyContext()

    def plotly_chart(self, *args, **kwargs):
        return None

    def caption(self, *args, **kwargs):
        return None

    def metric(self, *args, **kwargs):
        return None


def _import_app_isolated(monkeypatch: pytest.MonkeyPatch):
    """Import `app.py` with all network/filesystem touchpoints stubbed."""
    module_name = "fortress_root_app_under_test"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setattr(os.path, "isfile", lambda *_a, **_k: False)

    fake_streamlit = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    fake_psycopg2 = types.SimpleNamespace(connect=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("db disabled in tests")))
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)

    fake_plotly_express = types.SimpleNamespace(bar=lambda *args, **kwargs: types.SimpleNamespace(update_layout=lambda **_k: None))
    monkeypatch.setitem(sys.modules, "plotly", types.SimpleNamespace(express=fake_plotly_express))
    monkeypatch.setitem(sys.modules, "plotly.express", fake_plotly_express)

    monkeypatch.setitem(sys.modules, "pdf2image", types.SimpleNamespace(convert_from_path=lambda *_a, **_k: []))
    monkeypatch.setitem(sys.modules, "pytesseract", types.SimpleNamespace(image_to_string=lambda *_a, **_k: ""))

    class _PromptObj:
        def render(self):
            return "SYSTEM ROLE"

    fake_loader = types.SimpleNamespace(load_prompt=lambda _name: _PromptObj())
    monkeypatch.setitem(sys.modules, "prompts.loader", fake_loader)

    fake_config = types.SimpleNamespace(
        CAPTAIN_MODEL="deepseek-r1:70b",
        MUSCLE_NODE="muscle",
        MUSCLE_VISION_MODEL="vision",
        MUSCLE_GENERATE_URL="http://127.0.0.1/generate",
        MUSCLE_EMBED_MODEL="embed-model",
        MUSCLE_IP="127.0.0.1",
        WORKER_IP="127.0.0.1",
        DB_HOST="127.0.0.1",
        DB_PORT=5432,
        DB_NAME="fortress",
        DB_USER="tester",
        DB_PASSWORD="pw",
        muscle_see=lambda _prompt: "ok",
        muscle_embed=lambda _text: [0.1, 0.2],
        captain_think=lambda **_kwargs: "ready",
    )
    monkeypatch.setitem(sys.modules, "config", fake_config)

    app_path = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location(module_name, app_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_ask_worker_uses_central_captain_helper(monkeypatch: pytest.MonkeyPatch):
    """Verifies app chat logic routes through `captain_think` helper instead of direct endpoint posting."""
    app_module = _import_app_isolated(monkeypatch)
    calls = {}

    def fake_captain_think(*, prompt, system_role, temperature):
        calls["prompt"] = prompt
        calls["system_role"] = system_role
        calls["temperature"] = temperature
        return "mocked-answer"

    monkeypatch.setattr(app_module, "captain_think", fake_captain_think)
    output = app_module.ask_worker("What is DEFCON?", context="ctx")

    assert output == "mocked-answer"
    assert "What is DEFCON?" in calls["prompt"]
    assert "ctx" in calls["prompt"]
    assert calls["system_role"] == ""
    assert calls["temperature"] == 0.3


def test_ask_worker_fallback_when_helper_returns_empty(monkeypatch: pytest.MonkeyPatch):
    """Verifies deterministic fallback message when centralized reasoning helper returns no content."""
    app_module = _import_app_isolated(monkeypatch)
    monkeypatch.setattr(app_module, "captain_think", lambda **_kwargs: "")
    assert app_module.ask_worker("ping") == "⚠️ Worker Silent."


def test_vectorize_text_uses_central_embedding_helper(monkeypatch: pytest.MonkeyPatch):
    """Verifies embedding path is routed through `muscle_embed` helper and not local direct posting."""
    app_module = _import_app_isolated(monkeypatch)
    monkeypatch.setattr(app_module, "muscle_embed", lambda text: [len(text)])
    assert app_module.vectorize_text("abc") == [3]


def test_vectorize_text_returns_none_on_helper_error(monkeypatch: pytest.MonkeyPatch):
    """Verifies embedding failures are safely contained and do not trigger external retries/network calls."""
    app_module = _import_app_isolated(monkeypatch)

    def raising_embed(_text):
        raise RuntimeError("embed failed")

    monkeypatch.setattr(app_module, "muscle_embed", raising_embed)
    assert app_module.vectorize_text("abc") is None


def test_get_financial_audit_df_avoids_real_filesystem_when_missing(monkeypatch: pytest.MonkeyPatch):
    """Verifies financial loader returns empty result when CSV is absent, preventing unsafe filesystem dependency."""
    app_module = _import_app_isolated(monkeypatch)
    monkeypatch.setattr(app_module.os.path, "isfile", lambda *_a, **_k: False)
    df, has_errors = app_module.get_financial_audit_df()
    assert df.empty
    assert has_errors is False


def test_module_has_no_requests_client_dependency(monkeypatch: pytest.MonkeyPatch):
    """Verifies governance move away from direct requests-post pattern by ensuring `requests` is not imported in app."""
    app_module = _import_app_isolated(monkeypatch)
    assert "requests" not in app_module.__dict__
