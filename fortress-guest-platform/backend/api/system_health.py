"""
Bare-metal system health for Command Center `/api/system-health` BFF.

Probes: Postgres (SQLAlchemy + pg_stat_user_tables), optional Qdrant HTTP,
local node vitals (psutil, /proc/uptime), NVIDIA via nvidia-smi (shared with C2 pulse),
systemd units instead of Docker-only service matrix.
"""

from __future__ import annotations

import asyncio
import os
import platform
import socket
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import psutil
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.command_c2 import PULSE_ACCESS, get_nvidia_vitals
from backend.core.database import get_db
from backend.models.staff import StaffUser

logger = structlog.get_logger()
router = APIRouter()

QDRANT_URL = os.getenv("QDRANT_HTTP_URL", "http://127.0.0.1:6333").rstrip("/")

_SYSTEMD_UNITS: tuple[tuple[str, int, str], ...] = (
    ("fortress-backend.service", 8100, "Fortress API"),
    ("fortress-frontend.service", 3001, "Command Center"),
    ("fortress-arq-worker.service", 0, "ARQ Worker"),
    ("fortress-sync-worker.service", 0, "Streamline Sync"),
    ("cloudflared.service", 0, "Cloudflare Tunnel"),
    ("postgresql.service", 5432, "PostgreSQL"),
)


def _proc_uptime_seconds() -> float:
    try:
        with open("/proc/uptime", encoding="utf-8") as f:
            line = f.readline()
            return float(line.split()[0])
    except Exception:
        return 0.0


def _systemd_is_active(unit: str) -> bool:
    try:
        import subprocess

        r = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return r.stdout.strip() == "active"
    except Exception:
        return False


async def _postgres_table_rows(db: AsyncSession) -> dict[str, int]:
    sql = text(
        """
        SELECT relname, COALESCE(n_live_tup::bigint, 0) AS n
        FROM pg_stat_user_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY n_live_tup DESC NULLS LAST
        LIMIT 16
        """
    )
    result = await db.execute(sql)
    rows = result.fetchall()
    return {str(r[0]): int(r[1]) for r in rows if r[0]}


async def _qdrant_collections() -> dict[str, dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{QDRANT_URL}/collections")
            if r.status_code != 200:
                return {}
            data = r.json()
            out: dict[str, dict[str, Any]] = {}
            for c in data.get("result", {}).get("collections", []) or []:
                name = c.get("name")
                if not name:
                    continue
                points = 0
                status = "unknown"
                try:
                    ci = await client.get(f"{QDRANT_URL}/collections/{name}")
                    if ci.status_code == 200:
                        info = ci.json().get("result", {}) or {}
                        status = str(info.get("status", "unknown"))
                        pts = info.get("points_count")
                        if pts is not None:
                            points = int(pts)
                except Exception:
                    pass
                out[str(name)] = {"points": points, "status": status}
            return out
    except Exception as exc:
        logger.warning("qdrant_health_skipped", error=str(exc))
        return {}


def _hostname() -> str:
    return socket.gethostname() or platform.node()


def _build_node_payload(
    *,
    postgres_ok: bool,
    gpu: Any,
) -> dict[str, Any]:
    hn = _hostname()
    load_1, load_5, load_15 = (0.0, 0.0, 0.0)
    try:
        load_1, load_5, load_15 = os.getloadavg()
    except OSError:
        pass

    cores = psutil.cpu_count(logical=True) or 1
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    used_mib = int(gpu.vram_used or 0)
    total_mib = int(gpu.vram_total or 1)
    pct = float(gpu.vram_percent or 0.0)
    temp_c = int(gpu.temp or 0)
    util_pct = int(gpu.utilization or 0)

    return {
        "name": hn,
        "ip": "127.0.0.1",
        "role": "dgx-spark",
        "online": postgres_ok,
        "gpu": {
            "temp_c": temp_c,
            "total_mib": total_mib,
            "used_mib": used_mib,
            "pct": round(pct, 1),
            "util_pct": util_pct,
            "power_w": 0,
            "pstate": "",
            "driver": "",
            "clock_mhz": 0,
            "clock_max_mhz": 0,
            "processes": [],
        },
        "cpu": {
            "load_1m": round(load_1, 2),
            "load_5m": round(load_5, 2),
            "load_15m": round(load_15, 2),
            "cores": cores,
            "usage_pct": round(psutil.cpu_percent(interval=None), 1),
        },
        "ram": {
            "total_gb": round(ram.total / (1024**3), 2),
            "used_gb": round(ram.used / (1024**3), 2),
            "free_gb": round(ram.free / (1024**3), 2),
            "avail_gb": round(ram.available / (1024**3), 2),
            "pct": round(ram.percent, 1),
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "avail_gb": round(disk.free / (1024**3), 2),
            "pct": str(round(disk.percent, 1)),
        },
    }


async def build_system_health_payload(db: AsyncSession) -> dict[str, Any]:
    """Collect bare-metal system health; shared by REST aggregate and telemetry WebSocket."""
    t0 = time.perf_counter()
    ts = datetime.now(timezone.utc).isoformat()

    postgres_ok = False
    pg_rows: dict[str, int] = {}
    try:
        await db.execute(text("SELECT 1"))
        postgres_ok = True
        pg_rows = await _postgres_table_rows(db)
    except Exception as exc:
        logger.warning("postgres_health_probe_failed", error=str(exc))

    qdrant_task = asyncio.create_task(_qdrant_collections())
    gpu_task = get_nvidia_vitals()

    gpu, qdrant = await asyncio.gather(gpu_task, qdrant_task)

    services_out: list[dict[str, Any]] = []
    for unit, port, label in _SYSTEMD_UNITS:
        active = _systemd_is_active(unit)
        services_out.append(
            {
                "name": label,
                "port": port,
                "status": "online" if active else "offline",
            }
        )

    node = _build_node_payload(postgres_ok=postgres_ok, gpu=gpu)
    nodes = {node["name"]: node}

    # Postgres is authoritative for "glass online"; GPU probe may fail on CPU-only dev hosts.
    status: str = "healthy" if postgres_ok else "degraded"

    collected_ms = int((time.perf_counter() - t0) * 1000)

    # Phase 2.5: model registry health snapshot
    try:
        from backend.services.model_registry import registry as _mr
        model_registry_snapshot = _mr.health_snapshot()
    except Exception:
        model_registry_snapshot = {"loaded": False, "nodes": []}

    return {
        "status": status,
        "service": "fortress_system_health",
        "uptime_seconds": int(_proc_uptime_seconds()),
        "timestamp": ts,
        "collected_in_ms": collected_ms,
        "nodes": nodes,
        "services": services_out,
        "databases": {
            "postgres": pg_rows if pg_rows else ({"connected": 1} if postgres_ok else {}),
            "qdrant": qdrant,
        },
        "model_registry": model_registry_snapshot,
    }


@router.get("/")
async def system_health_aggregate(
    _: StaffUser = Depends(PULSE_ACCESS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await build_system_health_payload(db)
