"""
Sovereign system health for Command Center `/api/system-health` BFF and telemetry WebSocket.

Collectors: PostgreSQL 16 (connections + liveness), NVML multi-GPU, optional Qdrant HTTP,
SNMP interface rates (MikroTik CRS / IF-MIB), Synology (or any) mount usage + /proc/diskstats IOPS.
"""

from __future__ import annotations

import asyncio
import os
import platform
import socket
import time
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.command_c2 import PULSE_ACCESS
from backend.core.config import settings
from backend.core.database import get_db
from backend.models.staff import StaffUser
from backend.services.sovereign_hardware_metrics import (
    collect_nvml_gpus,
    collect_snmp_network,
    collect_storage,
    host_cpu_ram_load,
)

logger = structlog.get_logger()

QDRANT_URL = os.getenv("QDRANT_HTTP_URL", "http://127.0.0.1:6333").rstrip("/")


class GpuMetricOut(BaseModel):
    id: int = Field(..., ge=0)
    utilization_pct: int = Field(..., ge=0, le=100)
    memory_used_mb: int = Field(..., ge=0)
    memory_total_mb: int = Field(..., ge=0)
    temperature_c: int = Field(..., ge=0, le=150)


class NetworkMetricOut(BaseModel):
    interface: str = Field(..., min_length=1)
    rx_bytes_sec: int = Field(..., ge=0)
    tx_bytes_sec: int = Field(..., ge=0)
    dropped_packets: int = Field(..., ge=0)


class StorageMetricOut(BaseModel):
    volume: str = Field(..., min_length=1)
    mount_path: str = Field(..., min_length=1)
    capacity_pct: float = Field(..., ge=0.0, le=100.0)
    iops: int = Field(..., ge=0)


SystemHealthStatus = Literal["NOMINAL", "WARNING", "DEGRADED"]


class SystemHealthPayload(BaseModel):
    """Strict REST/WebSocket body (before optional `pulse` merge on WS)."""

    status: SystemHealthStatus
    gpus: list[GpuMetricOut]
    network: list[NetworkMetricOut]
    database_connections: int = Field(..., ge=0)
    postgres_ok: bool
    storage: list[StorageMetricOut]
    hostname: str = Field(..., min_length=1)
    host_cpu_usage_pct: float = Field(..., ge=0.0, le=100.0)
    host_ram_pct: float = Field(..., ge=0.0, le=100.0)
    host_load_1m: float = Field(..., ge=0.0)
    service: str = Field(default="fortress_system_health")
    timestamp: str
    collected_in_ms: int = Field(..., ge=0)
    uptime_seconds: int = Field(..., ge=0)
    qdrant_reachable: bool = False


def _proc_uptime_seconds() -> float:
    try:
        with open("/proc/uptime", encoding="utf-8") as f:
            line = f.readline()
            return float(line.split()[0])
    except Exception:
        return 0.0


async def _postgres_connection_count(db: AsyncSession) -> int:
    row = await db.execute(
        text("SELECT count(*)::bigint FROM pg_stat_activity WHERE state = 'active'")
    )
    val = row.scalar_one()
    return int(val or 0)


async def _qdrant_ping() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{QDRANT_URL}/readyz")
            return r.status_code == 200
    except Exception as exc:
        logger.warning("qdrant_health_skipped", error=str(exc))
        return False


def _hostname() -> str:
    return socket.gethostname() or platform.node()


async def build_system_health_payload(db: AsyncSession) -> dict[str, Any]:
    """Collect sovereign hardware health; shared by REST aggregate and telemetry WebSocket."""
    t0 = time.perf_counter()
    ts = datetime.now(timezone.utc).isoformat()

    postgres_ok = False
    db_conns = 0
    try:
        await db.execute(text("SELECT 1"))
        postgres_ok = True
        db_conns = await _postgres_connection_count(db)
    except Exception as exc:
        logger.warning("postgres_health_probe_failed", error=str(exc))

    qdrant_task = asyncio.create_task(_qdrant_ping())
    gpu_task = asyncio.to_thread(collect_nvml_gpus)
    snmp_task = asyncio.to_thread(collect_snmp_network, settings)
    storage_task = asyncio.to_thread(collect_storage, settings)
    host_task = asyncio.to_thread(host_cpu_ram_load)

    gpus_raw, network_raw, storage_raw, host_tuple, qdrant_ok = await asyncio.gather(
        gpu_task,
        snmp_task,
        storage_task,
        host_task,
        qdrant_task,
    )

    cpu_pct, ram_pct, load_1 = host_tuple

    gpus = [
        GpuMetricOut(
            id=g.gpu_id,
            utilization_pct=g.utilization_pct,
            memory_used_mb=g.memory_used_mb,
            memory_total_mb=g.memory_total_mb,
            temperature_c=g.temperature_c,
        )
        for g in gpus_raw
    ]

    network = [
        NetworkMetricOut(
            interface=n.interface,
            rx_bytes_sec=n.rx_bytes_sec,
            tx_bytes_sec=n.tx_bytes_sec,
            dropped_packets=n.dropped_packets,
        )
        for n in network_raw
    ]

    storage = [
        StorageMetricOut(
            volume=s.volume,
            mount_path=s.mount_path,
            capacity_pct=s.capacity_pct,
            iops=s.iops,
        )
        for s in storage_raw
    ]

    temp_warn = any(g.temperature_c >= 85 for g in gpus)
    storage_warn = any(s.capacity_pct >= 90.0 for s in storage)

    if not postgres_ok:
        status: SystemHealthStatus = "DEGRADED"
    elif temp_warn or storage_warn:
        status = "WARNING"
    else:
        status = "NOMINAL"

    collected_ms = int((time.perf_counter() - t0) * 1000)

    payload = SystemHealthPayload(
        status=status,
        gpus=gpus,
        network=network,
        database_connections=db_conns,
        postgres_ok=postgres_ok,
        storage=storage,
        hostname=_hostname(),
        host_cpu_usage_pct=cpu_pct,
        host_ram_pct=ram_pct,
        host_load_1m=load_1,
        timestamp=ts,
        collected_in_ms=collected_ms,
        uptime_seconds=int(_proc_uptime_seconds()),
        qdrant_reachable=bool(qdrant_ok),
    )
    return payload.model_dump(mode="json")


router = APIRouter()


@router.get("/", response_model=SystemHealthPayload)
async def system_health_aggregate(
    _: StaffUser = Depends(PULSE_ACCESS),
    db: AsyncSession = Depends(get_db),
) -> SystemHealthPayload:
    return SystemHealthPayload.model_validate(await build_system_health_payload(db))
