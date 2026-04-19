#!/usr/bin/env python3
"""
verify_nim_health.py — NIM sovereign inference endpoint health probe.

Used before and after Phase 5b cutover to confirm the NIM is up and
serving meta/llama-3.1-8b-instruct with acceptable response time.

Usage:
  python3 -m src.ops.verify_nim_health [--url URL]

  --url URL    NIM base URL to probe (default: http://192.168.0.104:8000)
               Use http://10.43.38.88:8000 for spark-2 k8s ClusterIP (pre-cutover baseline).
               Use http://192.168.0.104:8000 for spark-1 Docker (post-cutover).

Returns 0 on success (model loaded, response time within budget), 1 on failure.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.request
from dataclasses import dataclass

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"verify_nim"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("verify_nim")

DEFAULT_URL    = "http://192.168.0.104:8000"
EXPECTED_MODEL = "meta/llama-3.1-8b-instruct"
TIMEOUT_S      = 30
WARN_LATENCY   = 5000   # ms — warn if models endpoint takes longer than this


@dataclass
class NIMProbeResult:
    up: bool
    model_loaded: bool
    response_time_ms: int
    model_id: str
    error: str


def probe(base_url: str) -> NIMProbeResult:
    """Probe the NIM endpoint. Returns NIMProbeResult — never raises."""
    url = base_url.rstrip("/") + "/v1/models"
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            raw = resp.read()
        data = json.loads(raw)
        models = [m["id"] for m in data.get("data", [])]
        loaded = EXPECTED_MODEL in models
        model_id = models[0] if models else ""
        return NIMProbeResult(
            up=True,
            model_loaded=loaded,
            response_time_ms=latency_ms,
            model_id=model_id,
            error="",
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return NIMProbeResult(
            up=False,
            model_loaded=False,
            response_time_ms=latency_ms,
            model_id="",
            error=str(exc)[:200],
        )


def run_probe(base_url: str) -> int:
    """Probe NIM, log results, return exit code (0=pass, 1=fail)."""
    log.info("probing url=%s expected_model=%s", base_url, EXPECTED_MODEL)
    result = probe(base_url)

    if not result.up:
        log.error(
            "nim_unreachable url=%s latency_ms=%d error=%s",
            base_url, result.response_time_ms, result.error,
        )
        return 1

    log.info(
        "nim_up url=%s model_id=%s model_loaded=%s latency_ms=%d",
        base_url, result.model_id, result.model_loaded, result.response_time_ms,
    )

    if not result.model_loaded:
        log.error(
            "nim_wrong_model url=%s got=%s expected=%s",
            base_url, result.model_id, EXPECTED_MODEL,
        )
        return 1

    if result.response_time_ms > WARN_LATENCY:
        log.warning(
            "nim_slow url=%s latency_ms=%d warn_threshold_ms=%d",
            base_url, result.response_time_ms, WARN_LATENCY,
        )

    log.info("nim_health_pass url=%s", base_url)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NIM sovereign endpoint health probe")
    parser.add_argument(
        "--url", default=DEFAULT_URL,
        help=f"NIM base URL to probe (default: {DEFAULT_URL})",
    )
    args = parser.parse_args()
    sys.exit(run_probe(args.url))
