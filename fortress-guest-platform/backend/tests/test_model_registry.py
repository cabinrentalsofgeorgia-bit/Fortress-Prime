"""Tests for model_registry.py — Phase 2.5."""
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from backend.services.model_registry import (
    EndpointState,
    ModelRegistry,
    NoHealthyEndpoint,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ep(node_id: str, models: list[str], healthy: bool = True,
             latency: float = 50.0, failures: int = 0) -> EndpointState:
    ep = EndpointState(
        node_id=node_id,
        ollama_url=f"http://192.168.0.10{node_id[-1]}:11434",
        models=models,
        tier_affinity=["fast", "deep"],
    )
    if healthy:
        ep.reachable = True
        ep.consecutive_failures = failures
        ep.last_latency_ms = latency
        ep.latency_history = [latency]
        ep.last_success_at = datetime.now(tz=timezone.utc)
    else:
        ep.reachable = False
        ep.consecutive_failures = 5  # over threshold
    return ep


def _make_registry(*endpoints: EndpointState, tier_routing: dict | None = None) -> ModelRegistry:
    r = ModelRegistry()
    r._endpoints = list(endpoints)
    r._tier_routing = tier_routing or {}
    r._loaded = True
    return r


# ---------------------------------------------------------------------------
# EndpointState
# ---------------------------------------------------------------------------

class TestEndpointState:
    def test_healthy_when_reachable_and_low_failures(self):
        ep = _make_ep("spark-1", ["qwen2.5:7b"], healthy=True, failures=0)
        assert ep.healthy is True

    def test_unhealthy_when_consecutive_failures_at_threshold(self):
        ep = _make_ep("spark-1", ["qwen2.5:7b"], healthy=True, failures=3)
        assert ep.healthy is False  # 3 >= threshold of 3

    def test_unhealthy_when_unreachable(self):
        ep = _make_ep("spark-1", ["qwen2.5:7b"], healthy=False)
        assert ep.healthy is False

    def test_record_success_clears_failures(self):
        ep = _make_ep("spark-1", ["qwen2.5:7b"], healthy=False)
        ep.consecutive_failures = 5
        ep.record_success(42.0)
        assert ep.consecutive_failures == 0
        assert ep.reachable is True
        assert ep.last_success_at is not None

    def test_record_failure_increments(self):
        ep = _make_ep("spark-1", ["qwen2.5:7b"])
        ep.record_failure()
        ep.record_failure()
        assert ep.consecutive_failures == 2

    def test_rolling_latency_uses_history(self):
        # _make_ep seeds history with [50.0], then we add 100 and 200 → [50, 100, 200] mean=116.7
        ep = _make_ep("spark-1", ["qwen2.5:7b"], latency=50.0)
        ep.record_success(100.0)
        ep.record_success(200.0)
        assert ep.rolling_latency_ms == pytest.approx((50.0 + 100.0 + 200.0) / 3, abs=1.0)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

class TestGetEndpointForModel:
    def test_returns_healthy_endpoint(self):
        ep = _make_ep("spark-1", ["qwen2.5:7b"])
        r = _make_registry(ep)
        url = r.get_endpoint_for_model("qwen2.5:7b")
        assert "192.168" in url

    def test_raises_when_model_not_in_registry(self):
        ep = _make_ep("spark-1", ["qwen2.5:7b"])
        r = _make_registry(ep)
        with pytest.raises(NoHealthyEndpoint):
            r.get_endpoint_for_model("deepseek-r1:70b")

    def test_raises_when_all_unhealthy(self):
        ep1 = _make_ep("spark-1", ["deepseek-r1:70b"], healthy=False)
        ep2 = _make_ep("spark-4", ["deepseek-r1:70b"], healthy=False)
        r = _make_registry(ep1, ep2)
        with pytest.raises(NoHealthyEndpoint):
            r.get_endpoint_for_model("deepseek-r1:70b")

    def test_raises_when_registry_empty(self):
        r = ModelRegistry()
        with pytest.raises(NoHealthyEndpoint):
            r.get_endpoint_for_model("qwen2.5:7b")

    def test_picks_lowest_latency_among_healthy(self):
        slow = _make_ep("spark-1", ["deepseek-r1:70b"], latency=300.0)
        fast = _make_ep("spark-4", ["deepseek-r1:70b"], latency=80.0)
        r = _make_registry(slow, fast)
        url = r.get_endpoint_for_model("deepseek-r1:70b")
        # fast (spark-4) has lower latency and no tier preference → should win
        assert url == fast.ollama_url

    def test_tier_routing_overrides_latency_within_preference(self):
        # spark-1 is preferred by tier but slower; spark-4 faster but not preferred
        spark1 = _make_ep("spark-1", ["deepseek-r1:70b"], latency=200.0)
        spark4 = _make_ep("spark-4", ["deepseek-r1:70b"], latency=50.0)
        routing = {"deep": ["spark-1", "spark-4"]}
        r = _make_registry(spark1, spark4, tier_routing=routing)
        # With tier="deep": spark-1 gets priority=0, spark-4 gets priority=1
        url = r.get_endpoint_for_model("deepseek-r1:70b", tier="deep")
        assert url == spark1.ollama_url

    def test_unhealthy_skipped_even_if_tier_preferred(self):
        # spark-1 preferred but unhealthy — should fall to spark-4
        spark1 = _make_ep("spark-1", ["deepseek-r1:70b"], healthy=False)
        spark4 = _make_ep("spark-4", ["deepseek-r1:70b"], latency=50.0)
        routing = {"deep": ["spark-1", "spark-4"]}
        r = _make_registry(spark1, spark4, tier_routing=routing)
        url = r.get_endpoint_for_model("deepseek-r1:70b", tier="deep")
        assert url == spark4.ollama_url

    def test_consecutive_failures_threshold(self):
        # At threshold (3) → unhealthy
        ep = _make_ep("spark-1", ["qwen2.5:7b"], healthy=True, failures=3)
        r = _make_registry(ep)
        with pytest.raises(NoHealthyEndpoint):
            r.get_endpoint_for_model("qwen2.5:7b")

    def test_recovery_after_success(self):
        ep = _make_ep("spark-1", ["qwen2.5:7b"], healthy=False)
        ep.consecutive_failures = 5
        ep.record_success(30.0)
        r = _make_registry(ep)
        url = r.get_endpoint_for_model("qwen2.5:7b")
        assert url == ep.ollama_url


# ---------------------------------------------------------------------------
# Atlas loading
# ---------------------------------------------------------------------------

class TestLoadFromAtlas:
    def test_loads_nodes_from_valid_atlas(self, tmp_path: Path):
        atlas = {
            "fortress_prime": {
                "cluster": {
                    "nodes": [
                        {
                            "id": "spark-2",
                            "ollama_url": "http://192.168.0.100:11434",
                            "models": [
                                {"name": "qwen2.5:7b", "tier": "fast"},
                            ],
                        }
                    ],
                    "tier_routing": {"fast": ["spark-2"]},
                }
            }
        }
        p = tmp_path / "atlas.yaml"
        p.write_text(yaml.dump(atlas))
        r = ModelRegistry()
        r.load_from_atlas(p)
        assert r._loaded is True
        assert len(r._endpoints) == 1
        assert r._endpoints[0].node_id == "spark-2"

    def test_missing_atlas_leaves_registry_empty(self, tmp_path: Path):
        r = ModelRegistry()
        r.load_from_atlas(tmp_path / "nonexistent.yaml")
        assert r._loaded is False
        assert r._endpoints == []

    def test_malformed_atlas_leaves_registry_empty(self, tmp_path: Path):
        p = tmp_path / "bad.yaml"
        p.write_text(": invalid: yaml: [")
        r = ModelRegistry()
        r.load_from_atlas(p)
        assert r._loaded is False


# ---------------------------------------------------------------------------
# Iron Dome v6 — vrs_fast tier routing
# ---------------------------------------------------------------------------

class TestVrsFastTier:
    """Registry must route vrs_fast tier to spark-4 first, generic fast to spark-2."""

    def _make_v6_registry(self) -> ModelRegistry:
        spark2 = _make_ep("spark-2", ["qwen2.5:7b"], latency=50.0)
        spark4 = _make_ep("spark-4", ["qwen2.5:7b"], latency=28.0)
        return _make_registry(
            spark2, spark4,
            tier_routing={
                "fast":     ["spark-2"],
                "vrs_fast": ["spark-4", "spark-2"],
            },
        )

    def test_vrs_fast_tier_picks_spark4_first(self):
        r = self._make_v6_registry()
        url = r.get_endpoint_for_model("qwen2.5:7b", tier="vrs_fast")
        assert "192.168.0.104" in url  # spark-4 mock URL ends in node_id[-1]="4"

    def test_fast_tier_picks_spark2_not_spark4(self):
        r = self._make_v6_registry()
        url = r.get_endpoint_for_model("qwen2.5:7b", tier="fast")
        assert "192.168.0.102" in url  # spark-2 mock URL ends in "2"

    def test_vrs_fast_falls_back_to_spark2_when_spark4_unhealthy(self):
        spark2 = _make_ep("spark-2", ["qwen2.5:7b"], latency=50.0)
        spark4 = _make_ep("spark-4", ["qwen2.5:7b"], healthy=False)
        r = _make_registry(
            spark2, spark4,
            tier_routing={"vrs_fast": ["spark-4", "spark-2"]},
        )
        url = r.get_endpoint_for_model("qwen2.5:7b", tier="vrs_fast")
        assert "192.168.0.102" in url  # falls back to spark-2


class TestTierForTask:
    """_tier_for_task must map vrs_concierge to vrs_fast, everything else to fast or deep."""

    def test_vrs_concierge_maps_to_vrs_fast(self):
        from backend.services.ai_router import _tier_for_task
        assert _tier_for_task("vrs_concierge") == "vrs_fast"

    def test_generic_maps_to_fast(self):
        from backend.services.ai_router import _tier_for_task
        assert _tier_for_task("generic") == "fast"

    def test_legal_maps_to_deep(self):
        from backend.services.ai_router import _tier_for_task
        assert _tier_for_task("legal") == "deep"

    def test_unknown_maps_to_fast(self):
        from backend.services.ai_router import _tier_for_task
        assert _tier_for_task("code_generation") == "fast"


# ---------------------------------------------------------------------------
# Hydra fleet autofix — qwen2.5:32b replaces unloaded qwen3:32b for seats 4/6
# ---------------------------------------------------------------------------

class TestHydra32bModelName:
    """HYDRA_MODEL_32B default must be qwen2.5:32b (loaded on spark-1 and spark-4).
    qwen3:32b is not loaded on any node; routing to it caused seats 4+6 to fall
    through the full fallback chain to SWARM on every request."""

    def test_hydra_model_32b_default_is_qwen_25(self):
        from backend.services.crog_concierge_engine import HYDRA_MODEL_32B
        assert HYDRA_MODEL_32B == "qwen2.5:32b", (
            f"HYDRA_MODEL_32B should be qwen2.5:32b (loaded on spark-1+spark-4), "
            f"got {HYDRA_MODEL_32B!r}"
        )

    def test_hydra_32b_routes_to_loaded_model(self):
        """Registry: seats 4 and 6 should find a healthy node for qwen2.5:32b."""
        spark1 = _make_ep("spark-1", ["qwen2.5:32b"], latency=30.0)
        spark4 = _make_ep("spark-4", ["qwen2.5:32b"], latency=28.0)
        r = _make_registry(spark1, spark4,
                           tier_routing={"mid": ["spark-1", "spark-4"]})
        url = r.get_endpoint_for_model("qwen2.5:32b")
        assert "192.168" in url  # resolves to a cluster node

    def test_qwen3_32b_not_default(self):
        """Regression: qwen3:32b must NOT be the default (unloaded everywhere)."""
        from backend.services.crog_concierge_engine import HYDRA_MODEL_32B
        assert HYDRA_MODEL_32B != "qwen3:32b", (
            "HYDRA_MODEL_32B reverted to qwen3:32b — model is not loaded on any node"
        )
