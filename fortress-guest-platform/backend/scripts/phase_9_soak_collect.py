"""Phase 9 soak metric collector.

Runs hourly via cron (see /etc/cron.d/phase-9-soak). Writes one JSONL line per
metric per run to /mnt/fortress_nas/audits/phase-9-soak/<YYYY-MM-DD>.log.

Metrics (per Phase 9 brief §8.1):
  - Endpoint availability (TP=2 frontier health)
  - Per-alias mean latency (LiteLLM gateway sample probe)
  - Per-alias error rate (LiteLLM gateway sample probe)
  - spark-3 + spark-4 unified-memory utilization (`free -h`)
  - spark-3 + spark-4 GPU temp (`nvidia-smi`, may return N/A on GB10)
  - tcp_bbr health (sysctl tcp_congestion_control)

NCCL fabric throughput (`nccl-tests`) and KV cache utilization (vLLM logs)
are NOT included in the hourly cadence — too expensive / log-parse-fragile.
Run those manually if a halt trigger fires (see §8.3 of brief).

Halt triggers (any one fires → P0 incident, mark aliases unhealthy at gateway):
  - endpoint availability < 99% over 24h rolling
  - format-compliance regression (sampled output spot-check, separate cron)
  - sustained NCCL fabric error (manual probe; not in this collector)
  - GPU OOM kill (separate journalctl spot-check, not here)

Output JSONL schema:
  {
    "ts": "<UTC ISO 8601>",
    "metric": "<one of: endpoint_health, alias_probe, node_memory, node_gpu_temp, sysctl_bbr>",
    "host": "<spark-3|spark-4|spark-2|null>",
    "alias": "<one of legal-reasoning|legal-drafting|legal-summarization|null>",
    "value": <number|string|bool>,
    "ok": <bool>,
    "ms": <number|null>     # latency for HTTP probes
  }

Usage:
    python3 phase_9_soak_collect.py

Environment:
    LITELLM_MASTER_KEY  required for alias probes (sourced from
                        /etc/fortress/secrets.env via cron-d entry)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUT_DIR = Path("/mnt/fortress_nas/audits/phase-9-soak")
ENDPOINT_HEALTH = "http://10.10.10.3:8000/health"  # vLLM health endpoint (NOT /v1/health/ready — that's NIM-style)
LITELLM_BASE = "http://127.0.0.1:8002/v1/chat/completions"
ALIASES = ("legal-reasoning", "legal-drafting", "legal-summarization")
NODES = (("spark-3", "192.168.0.105"), ("spark-4", "192.168.0.106"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(out_fp, metric: str, host: str | None, alias: str | None,
          value: Any, ok: bool, ms: float | None) -> None:
    line = {
        "ts": _now(),
        "metric": metric,
        "host": host,
        "alias": alias,
        "value": value,
        "ok": ok,
        "ms": ms,
    }
    out_fp.write(json.dumps(line) + "\n")
    out_fp.flush()


def _http_probe(url: str, timeout: int = 10, body: dict | None = None,
                headers: dict | None = None) -> tuple[bool, int | str, float]:
    import urllib.request
    import urllib.error

    start = time.monotonic()
    req_kwargs: dict = {"method": "POST" if body else "GET"}
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=req_kwargs["method"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ms = (time.monotonic() - start) * 1000
            return True, resp.status, ms
    except urllib.error.HTTPError as e:
        ms = (time.monotonic() - start) * 1000
        return False, e.code, ms
    except Exception as e:
        ms = (time.monotonic() - start) * 1000
        return False, str(e)[:200], ms


def collect_endpoint_health(out_fp) -> None:
    ok, code, ms = _http_probe(ENDPOINT_HEALTH, timeout=10)
    _emit(out_fp, "endpoint_health", "spark-3", None,
          value=code if not ok else "ready", ok=ok, ms=round(ms, 1))


def collect_alias_probe(out_fp, mk: str) -> None:
    headers = {
        "Authorization": f"Bearer {mk}",
        "Content-Type": "application/json",
    }
    body_template = {
        "messages": [{"role": "user", "content": "Reply with only PONG."}],
        "max_tokens": 400,
    }
    for alias in ALIASES:
        body = {**body_template, "model": alias}
        ok, code, ms = _http_probe(
            LITELLM_BASE, timeout=120, body=body, headers=headers
        )
        _emit(out_fp, "alias_probe", "spark-2", alias,
              value=code, ok=ok, ms=round(ms, 1))


def _ssh_run(host_ip: str, cmd: str, timeout: int = 15) -> str:
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
             f"admin@{host_ip}", cmd],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        return proc.stdout.strip()
    except Exception as e:
        return f"ERROR: {e}"


def collect_node_memory(out_fp) -> None:
    for host, ip in NODES:
        out = _ssh_run(ip, "free -b | awk 'NR==2 {print $2,$3,$7}'")
        try:
            total, used, available = map(int, out.split())
            pct = round(used / total * 100, 2)
            _emit(out_fp, "node_memory", host, None,
                  value={"total_gib": round(total / (1 << 30), 2),
                         "used_gib": round(used / (1 << 30), 2),
                         "available_gib": round(available / (1 << 30), 2),
                         "used_pct": pct}, ok=True, ms=None)
        except Exception as e:
            _emit(out_fp, "node_memory", host, None,
                  value=f"ERROR: {out!r} {e}", ok=False, ms=None)


def collect_node_gpu_temp(out_fp) -> None:
    for host, ip in NODES:
        out = _ssh_run(ip, "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader")
        # GB10 may return [N/A] (unified memory; no discrete GPU temp sensor)
        ok = out.strip().isdigit() if out else False
        _emit(out_fp, "node_gpu_temp", host, None,
              value=out.strip() or "empty", ok=ok, ms=None)


def collect_sysctl_bbr(out_fp) -> None:
    for host, ip in NODES:
        out = _ssh_run(ip, "sysctl -n net.ipv4.tcp_congestion_control")
        _emit(out_fp, "sysctl_bbr", host, None,
              value=out, ok=(out == "bbr"), ms=None)


def _read_master_key_fallback() -> str:
    """Cron-friendly fallback: read master_key directly from litellm config."""
    cfg = Path("/home/admin/Fortress-Prime/litellm_config.yaml")
    if not cfg.exists():
        return ""
    for line in cfg.read_text().splitlines():
        s = line.strip()
        if s.startswith("master_key:"):
            return s.split(":", 1)[1].strip()
    return ""


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    mk = os.environ.get("LITELLM_MASTER_KEY", "") or _read_master_key_fallback()
    if not mk:
        print("ERROR: LITELLM_MASTER_KEY not set in env and not found in /home/admin/Fortress-Prime/litellm_config.yaml",
              file=sys.stderr)
        return 2

    with out_path.open("a") as out_fp:
        collect_endpoint_health(out_fp)
        collect_alias_probe(out_fp, mk)
        collect_node_memory(out_fp)
        collect_node_gpu_temp(out_fp)
        collect_sysctl_bbr(out_fp)

    return 0


if __name__ == "__main__":
    sys.exit(main())
