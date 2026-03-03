"""Unit tests for Fortress root config governance and routing behavior."""

from __future__ import annotations

import importlib
import sys
import types

import pytest


def _load_config_with_env(monkeypatch: pytest.MonkeyPatch, **env: str):
    """Load `config` with controlled env and a fake OpenAI client."""
    tracked = [
        "FORTRESS_DEFCON",
        "SPARK_01_IP",
        "SPARK_02_IP",
        "SPARK_03_IP",
        "SPARK_04_IP",
        "FABRIC_CAPTAIN",
        "ALLOW_CLOUD_LLM",
        "GOOGLE_AI_API_KEY",
        "OPENAI_API_KEY",
    ]
    for key in tracked:
        monkeypatch.delenv(key, raising=False)
    # Keep cloud key tests deterministic even if local .env provides keys.
    monkeypatch.setenv("GOOGLE_AI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    class FakeOpenAI:
        """Captures constructor args to verify routing policy."""

        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_openai_module = types.SimpleNamespace(OpenAI=FakeOpenAI)
    monkeypatch.setitem(sys.modules, "openai", fake_openai_module)
    monkeypatch.delitem(sys.modules, "config", raising=False)
    return importlib.import_module("config")


def test_swarm_default_routes_to_local_nim(monkeypatch: pytest.MonkeyPatch):
    """Verifies NIM-first default: SWARM routes to local SPARK endpoint with local auth mode."""
    cfg = _load_config_with_env(monkeypatch, SPARK_01_IP="192.168.0.100")
    client, model = cfg.get_inference_client()
    assert client.kwargs["base_url"] == "http://192.168.0.100/v1"
    assert client.kwargs["api_key"] == "not-needed"
    assert model == cfg.SWARM_MODEL


def test_hydra_mode_uses_nim_lane(monkeypatch: pytest.MonkeyPatch):
    """Verifies HYDRA mode stays on the local NIM lane and never requires cloud keys."""
    cfg = _load_config_with_env(monkeypatch, FORTRESS_DEFCON="HYDRA", SPARK_01_IP="192.168.0.104")
    client, model = cfg.get_inference_client("HYDRA")
    assert client.kwargs["base_url"] == "http://192.168.0.104/v1"
    assert client.kwargs["api_key"] == "not-needed"
    assert model == cfg.HYDRA_MODEL


def test_titan_mode_uses_fabric_endpoint(monkeypatch: pytest.MonkeyPatch):
    """Verifies TITAN routing uses the fabric path for sovereign deep reasoning."""
    cfg = _load_config_with_env(monkeypatch, FORTRESS_DEFCON="TITAN", FABRIC_CAPTAIN="10.10.10.9")
    client, model = cfg.get_inference_client("TITAN")
    assert client.kwargs["base_url"] == "http://10.10.10.9:8080/v1"
    assert client.kwargs["api_key"] == "not-needed"
    assert model == cfg.TITAN_MODEL


def test_architect_mode_blocked_without_approval(monkeypatch: pytest.MonkeyPatch):
    """Verifies cloud ARCHITECT mode is denied unless explicit governance approval flag is enabled."""
    cfg = _load_config_with_env(monkeypatch, ALLOW_CLOUD_LLM="false")
    with pytest.raises(RuntimeError, match="ARCHITECT mode blocked"):
        cfg.get_inference_client("ARCHITECT")


def test_architect_mode_requires_google_key(monkeypatch: pytest.MonkeyPatch):
    """Verifies ARCHITECT mode enforces API key presence when cloud mode is approved."""
    cfg = _load_config_with_env(monkeypatch, ALLOW_CLOUD_LLM="true")
    with pytest.raises(RuntimeError, match="GOOGLE_AI_API_KEY"):
        cfg.get_inference_client("ARCHITECT")


def test_architect_mode_uses_google_endpoint_when_approved(monkeypatch: pytest.MonkeyPatch):
    """Verifies approved ARCHITECT traffic routes through the centralized Gemini-compatible endpoint."""
    cfg = _load_config_with_env(
        monkeypatch,
        ALLOW_CLOUD_LLM="true",
        GOOGLE_AI_API_KEY="g-key",
    )
    client, model = cfg.get_inference_client("ARCHITECT")
    assert client.kwargs["base_url"] == cfg.ARCHITECT_ENDPOINT
    assert client.kwargs["api_key"] == "g-key"
    assert model == cfg.ARCHITECT_MODEL


def test_godhead_mode_requires_openai_key(monkeypatch: pytest.MonkeyPatch):
    """Verifies GODHEAD mode remains blocked without an explicit OpenAI key even when cloud mode is enabled."""
    cfg = _load_config_with_env(monkeypatch, ALLOW_CLOUD_LLM="true")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        cfg.get_inference_client("GODHEAD")


def test_inference_url_switches_by_defcon(monkeypatch: pytest.MonkeyPatch):
    """Verifies helper URL routing changes between SWARM management path and TITAN fabric path."""
    cfg_swarm = _load_config_with_env(monkeypatch, FORTRESS_DEFCON="SWARM", SPARK_01_IP="192.168.0.100")
    assert cfg_swarm.get_inference_url() == "http://192.168.0.100/v1/chat/completions"

    cfg_titan = _load_config_with_env(monkeypatch, FORTRESS_DEFCON="TITAN", FABRIC_CAPTAIN="10.10.10.42")
    assert cfg_titan.get_inference_url() == "http://10.10.10.42:8080/v1/chat/completions"


def test_swarm_endpoints_alias_is_consistent(monkeypatch: pytest.MonkeyPatch):
    """Verifies legacy endpoint alias stays consistent with centralized swarm endpoint helper."""
    cfg = _load_config_with_env(
        monkeypatch,
        SPARK_01_IP="192.168.0.100",
        SPARK_02_IP="192.168.0.104",
        SPARK_03_IP="192.168.0.105",
        SPARK_04_IP="192.168.0.106",
    )
    assert cfg.get_ollama_endpoints() == cfg.get_swarm_node_endpoints()


def test_blocklist_matching_is_case_insensitive(monkeypatch: pytest.MonkeyPatch):
    """Verifies sender filtering logic enforces governance spam-block policy in a case-insensitive way."""
    cfg = _load_config_with_env(monkeypatch)
    assert cfg.is_sender_blocked("Notify@Twitter.com")
    assert not cfg.is_sender_blocked("owner@trusted-vendor.com")
