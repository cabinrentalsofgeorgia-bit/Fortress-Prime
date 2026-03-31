"""Tests for Fireclaw serial output parsing (loads module without backend.services __init__)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]


def _load_fireclaw_serial():
    path = _BACKEND / "services" / "fireclaw_serial.py"
    spec = importlib.util.spec_from_file_location("_fireclaw_serial_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_fc = _load_fireclaw_serial()
parse_fireclaw_serial_output = _fc.parse_fireclaw_serial_output
FIRECLAW_PREFIX = _fc.FIRECLAW_PREFIX


def test_parse_fireclaw_result_line() -> None:
    raw = """[    0.000000] Linux version ...
FIRECLAW_RESULT{"exit_code": 0, "stdout": "ok\\n", "stderr": ""}
"""
    out = parse_fireclaw_serial_output(raw)
    assert out["exit_code"] == 0
    assert out["stdout"] == "ok\n"
    assert out["stderr"] == ""


def test_parse_prefers_last_fireclaw_line() -> None:
    raw = f"{FIRECLAW_PREFIX}" + '{"exit_code":1,"stdout":"","stderr":"old"}\n'
    raw += f"{FIRECLAW_PREFIX}" + '{"exit_code":0,"stdout":"x","stderr":""}\n'
    out = parse_fireclaw_serial_output(raw)
    assert out["exit_code"] == 0
    assert out["stdout"] == "x"


def test_parse_interrogate_json_fallback() -> None:
    raw = 'kernel noise\n{"status": "success", "finding": "ok"}\n'
    out = parse_fireclaw_serial_output(raw)
    assert out["exit_code"] == 0
    assert "success" in out["stdout"]


def test_parse_empty() -> None:
    out = parse_fireclaw_serial_output("")
    assert out["exit_code"] == -1
    assert "empty" in (out.get("error") or "").lower()
