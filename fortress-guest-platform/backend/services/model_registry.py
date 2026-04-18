"""
model_registry.py — Sovereign model registry with health-aware routing.

Phase 2.5 of Iron Dome. Replaces hardcoded ollama_base_url in ai_router
with a live-probed, latency-ranked endpoint selector.

Architecture:
  - Loaded from fortress_atlas.yaml cluster.nodes section at startup
  - Background thread probes each node's /api/tags every 30s
  - get_endpoint_for_model() returns the healthiest URL for a given model
  - Raises NoHealthyEndpoint when no node is available (triggers cloud fallback)

Safety contract:
  - Module import never raises — logs error, falls back to empty registry
  - Health probe exceptions are caught and counted as failures
  - No crash can propagate from probe thread to request path
"""
from __future__ import annotations

import logging
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import yaml

log = logging.getLogger("model_registry")

_ATLAS_PATH = Path(os.getenv(
    "FORTRESS_ATLAS_PATH",
    str(Path(__file__).resolve().parents[3] / "fortress_atlas.yaml"),
))

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class NoHealthyEndpoint(Exception):
    """Raised when no healthy node hosts the requested model."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EndpointState:
    node_id:              str
    ollama_url:           str
    models:               list[str]      # model names this node has
    tier_affinity:        list[str]      # which tiers this node serves
    reachable:            bool           = False
    consecutive_failures: int            = 0
    last_latency_ms:      float          = 9999.0
    last_success_at:      Optional[datetime] = None
    latency_history:      list[float]    = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return self.reachable and self.consecutive_failures < _FAILURE_THRESHOLD

    @property
    def rolling_latency_ms(self) -> float:
        if not self.latency_history:
            return self.last_latency_ms
        return statistics.mean(self.latency_history[-20:])

    def record_success(self, latency_ms: float) -> None:
        self.reachable = True
        self.consecutive_failures = 0
        self.last_latency_ms = latency_ms
        self.last_success_at = datetime.now(tz=timezone.utc)
        self.latency_history.append(latency_ms)
        if len(self.latency_history) > 100:
            self.latency_history = self.latency_history[-100:]

    def record_failure(self) -> None:
        self.reachable = False
        self.consecutive_failures += 1


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PROBE_INTERVAL   = 30   # seconds
_PROBE_TIMEOUT    = 3    # seconds
_FAILURE_THRESHOLD = 3   # consecutive failures → unhealthy

class ModelRegistry:
    def __init__(self) -> None:
        self._endpoints: list[EndpointState] = []
        self._tier_routing: dict[str, list[str]] = {}  # tier → [node_id priority order]
        self._lock = threading.Lock()
        self._probe_thread: Optional[threading.Thread] = None
        self._loaded = False

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def load_from_atlas(self, atlas_path: Path = _ATLAS_PATH) -> None:
        """
        Parse fortress_atlas.yaml cluster section and populate the registry.
        Never raises — logs error and leaves registry empty (cloud-only fallback).
        """
        try:
            with open(atlas_path) as f:
                atlas = yaml.safe_load(f)
        except FileNotFoundError:
            log.warning("model_registry: atlas not found at %s — running empty (cloud fallback)", atlas_path)
            return
        except yaml.YAMLError as exc:
            log.error("model_registry: atlas parse error: %s — running empty", exc)
            return

        try:
            cluster = (atlas or {}).get("fortress_prime", {}).get("cluster", {})
            nodes_cfg = cluster.get("nodes", [])
            tier_routing_cfg = cluster.get("tier_routing", {})

            global _PROBE_INTERVAL, _PROBE_TIMEOUT, _FAILURE_THRESHOLD
            _PROBE_INTERVAL    = cluster.get("probe_interval_seconds", _PROBE_INTERVAL)
            _PROBE_TIMEOUT     = cluster.get("probe_timeout_seconds", _PROBE_TIMEOUT)
            _FAILURE_THRESHOLD = cluster.get("healthy_failure_threshold", _FAILURE_THRESHOLD)

            endpoints: list[EndpointState] = []
            for node in nodes_cfg:
                node_id = node["id"]
                tiers_for_node = [
                    tier for tier, node_ids in tier_routing_cfg.items()
                    if node_id in node_ids
                ]
                endpoints.append(EndpointState(
                    node_id=node_id,
                    ollama_url=node["ollama_url"],
                    models=[m["name"] for m in node.get("models", [])],
                    tier_affinity=tiers_for_node,
                ))

            with self._lock:
                self._endpoints = endpoints
                self._tier_routing = tier_routing_cfg
                self._loaded = True

            log.info("model_registry: loaded %d nodes from %s", len(endpoints), atlas_path)
        except Exception as exc:
            log.error("model_registry: atlas structure error: %s — running empty", exc)

    def start_probe_thread(self) -> None:
        """Start background health probe thread (daemon — dies with main process)."""
        if self._probe_thread and self._probe_thread.is_alive():
            return
        t = threading.Thread(target=self._probe_loop, daemon=True, name="model-registry-probe")
        t.start()
        self._probe_thread = t
        log.info("model_registry: probe thread started (interval=%ds)", _PROBE_INTERVAL)

    # ------------------------------------------------------------------
    # Health probing
    # ------------------------------------------------------------------

    def _probe_loop(self) -> None:
        while True:
            try:
                self._probe_all()
            except Exception as exc:
                log.error("model_registry: probe_loop error: %s", exc)
            time.sleep(_PROBE_INTERVAL)

    def _probe_all(self) -> None:
        with self._lock:
            endpoints = list(self._endpoints)
        for ep in endpoints:
            self._probe_one(ep)

    def _probe_one(self, ep: EndpointState) -> None:
        """Probe a single endpoint's /api/tags. Update state in-place (thread-safe)."""
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=_PROBE_TIMEOUT) as client:
                resp = client.get(f"{ep.ollama_url.rstrip('/')}/api/tags")
                resp.raise_for_status()
                # Optionally refresh model list from live response
                data = resp.json()
                live_models = [m["name"] for m in data.get("models", [])]
                latency_ms = (time.perf_counter() - t0) * 1000

            with self._lock:
                ep.record_success(latency_ms)
                if live_models:
                    ep.models = live_models

            log.debug("probe ok node=%s latency=%.0fms models=%d",
                      ep.node_id, latency_ms, len(ep.models))

        except Exception as exc:
            with self._lock:
                ep.record_failure()
            log.warning("probe failed node=%s failures=%d error=%s",
                        ep.node_id, ep.consecutive_failures, str(exc)[:80])

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def get_endpoint_for_model(
        self,
        model_name: str,
        tier: Optional[str] = None,
    ) -> str:
        """
        Return the Ollama URL of the healthiest node that has model_name.

        If tier is provided, prefer nodes in the tier's routing order.
        Among healthy nodes, pick the one with lowest rolling latency.

        Raises NoHealthyEndpoint if no healthy node has the model.
        """
        with self._lock:
            candidates = [
                ep for ep in self._endpoints
                if ep.healthy and model_name in ep.models
            ]
            tier_order = self._tier_routing.get(tier or "", []) if tier else []

        if not candidates:
            raise NoHealthyEndpoint(
                f"No healthy node has model '{model_name}' "
                f"(tier={tier}, checked {len(self._endpoints)} nodes)"
            )

        # Sort: first by tier affinity order, then by rolling latency
        def _rank(ep: EndpointState) -> tuple[int, float]:
            try:
                priority = tier_order.index(ep.node_id)
            except ValueError:
                priority = 999  # not in preferred list → lowest priority
            return (priority, ep.rolling_latency_ms)

        best = min(candidates, key=_rank)
        log.debug("routed model=%s tier=%s → node=%s latency=%.0fms",
                  model_name, tier, best.node_id, best.rolling_latency_ms)
        return best.ollama_url

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def health_snapshot(self) -> dict:
        """Return JSON-serialisable health state for /api/v1/system-health."""
        with self._lock:
            endpoints = list(self._endpoints)
        return {
            "loaded": self._loaded,
            "nodes": [
                {
                    "id": ep.node_id,
                    "url": ep.ollama_url,
                    "healthy": ep.healthy,
                    "reachable": ep.reachable,
                    "consecutive_failures": ep.consecutive_failures,
                    "rolling_latency_ms": round(ep.rolling_latency_ms, 1),
                    "last_success_at": (
                        ep.last_success_at.isoformat() if ep.last_success_at else None
                    ),
                    "models": ep.models,
                }
                for ep in endpoints
            ],
        }


# ---------------------------------------------------------------------------
# Module-level singleton (lazy-initialised in lifespan)
# ---------------------------------------------------------------------------

registry = ModelRegistry()


def initialise(atlas_path: Path = _ATLAS_PATH) -> None:
    """Call once from FastAPI lifespan startup."""
    registry.load_from_atlas(atlas_path)
    registry.start_probe_thread()
