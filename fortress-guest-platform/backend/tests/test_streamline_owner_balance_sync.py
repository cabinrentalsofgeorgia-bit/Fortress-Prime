from __future__ import annotations

from backend.integrations.streamline_vrs import is_streamline_circuit_placeholder


def test_is_streamline_circuit_placeholder_detects_open_circuit_payload() -> None:
    payload = {"data": {}, "_circuit_open": True, "_stale": True}
    assert is_streamline_circuit_placeholder(payload) is True


def test_is_streamline_circuit_placeholder_ignores_normal_payloads() -> None:
    assert is_streamline_circuit_placeholder({"owner_balance": 123.45}) is False
    assert is_streamline_circuit_placeholder({}) is False
    assert is_streamline_circuit_placeholder(None) is False
