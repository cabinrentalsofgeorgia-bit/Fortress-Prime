"""
Bare-metal system health for Command Center `/api/system-health` BFF.

Probes: Postgres (SQLAlchemy + pg_stat_user_tables), optional Qdrant HTTP,
local node vitals (psutil, /proc/uptime), NVIDIA via nvidia-smi (shared with C2 pulse),
systemd units instead of Docker-only service matrix.
"""

from __future__ import annotations

import asyncio
import ast
import os
import platform
import re
import socket
import subprocess
import time
from collections import Counter
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
    ("fortress-backend.service", 8000, "Fortress API"),
    ("crog-ai-frontend.service", 3005, "Command Center"),
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


def _recent_unit_lines(unit: str, *, lines: int = 120) -> list[str]:
    try:
        r = subprocess.run(
            ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "cat"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        logger.warning("journalctl_probe_failed", unit=unit, error=str(exc)[:200])
        return []
    if r.returncode != 0:
        logger.warning("journalctl_probe_unavailable", unit=unit, error=r.stderr[:200])
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def _streamline_method_from_log(line: str) -> str | None:
    match = re.search(r"\bmethod=([A-Za-z0-9_]+)", line)
    return match.group(1) if match else None


def _streamline_sync_health() -> dict[str, Any]:
    unit = "fortress-sync-worker.service"
    active = _systemd_is_active(unit)
    lines = _recent_unit_lines(unit)
    recent_circuit_lines = [
        line for line in lines if "streamline_circuit_open" in line
    ]
    last_sync_line = next((line for line in reversed(lines) if "sync_complete" in line), None)
    last_cycle_line = next((line for line in reversed(lines) if "sync_cycle_complete" in line), None)
    method_counts = Counter(
        method
        for line in recent_circuit_lines
        if (method := _streamline_method_from_log(line))
    )
    recent_circuit_methods = [
        {"method": method, "count": count}
        for method, count in method_counts.most_common(6)
    ]
    primary_circuit_method = recent_circuit_methods[0]["method"] if recent_circuit_methods else None

    error_count: int | None = None
    reservation_errors: int | None = None
    properties_updated: int | None = None
    reservations_updated: int | None = None
    elapsed_seconds: float | None = None
    error_categories: dict[str, int] = {}

    if last_sync_line:
        match = re.search(r"errors=(\d+)", last_sync_line)
        if match:
            error_count = int(match.group(1))
        match = re.search(r"properties_updated=(\d+)", last_sync_line)
        if match:
            properties_updated = int(match.group(1))
        match = re.search(r"error_categories=(\{.*?\})(?:\s+\w+=|$)", last_sync_line)
        if match:
            try:
                parsed = ast.literal_eval(match.group(1))
                if isinstance(parsed, dict):
                    error_categories = {
                        str(key): int(value)
                        for key, value in parsed.items()
                        if isinstance(value, int)
                    }
            except (SyntaxError, ValueError):
                error_categories = {}

    if last_cycle_line:
        match = re.search(r"reservations=\{[^}]*'updated':\s*(\d+)", last_cycle_line)
        if match:
            reservations_updated = int(match.group(1))
        match = re.search(r"reservations=\{[^}]*'errors':\s*(\d+)", last_cycle_line)
        if match:
            reservation_errors = int(match.group(1))
        match = re.search(r"elapsed_seconds=([0-9.]+)", last_cycle_line)
        if match:
            elapsed_seconds = float(match.group(1))

    degraded = bool(recent_circuit_lines or (error_count is not None and error_count > 0))
    if not active:
        status = "offline"
    elif degraded:
        status = "degraded"
    else:
        status = "online"

    latest_circuit_line = recent_circuit_lines[-1] if recent_circuit_lines else None
    return {
        "service": "streamline",
        "unit": unit,
        "status": status,
        "worker_active": active,
        "circuit_open_recent": bool(recent_circuit_lines),
        "stale_data_fallback": bool(
            latest_circuit_line and "Serving stale data from local DB" in latest_circuit_line
        ),
        "recent_circuit_events": len(recent_circuit_lines),
        "recent_circuit_methods": recent_circuit_methods,
        "primary_circuit_method": primary_circuit_method,
        "last_error_count": error_count,
        "last_error_categories": error_categories,
        "last_reservation_errors": reservation_errors,
        "last_properties_updated": properties_updated,
        "last_reservations_updated": reservations_updated,
        "last_elapsed_seconds": elapsed_seconds,
        "last_sync_summary": last_sync_line,
        "last_cycle_summary": last_cycle_line,
        "latest_circuit_summary": latest_circuit_line,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


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


async def _table_exists(db: AsyncSession, table_name: str) -> bool:
    result = await db.execute(text("SELECT to_regclass(:table_name)"), {"table_name": table_name})
    return result.scalar_one_or_none() is not None


async def _fetch_count(db: AsyncSession, sql: str, params: dict[str, Any] | None = None) -> int:
    result = await db.execute(text(sql), params or {})
    value = result.scalar_one_or_none()
    return int(value or 0)


async def _fetch_iso(db: AsyncSession, sql: str, params: dict[str, Any] | None = None) -> str | None:
    result = await db.execute(text(sql), params or {})
    value = result.scalar_one_or_none()
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


async def _operational_health(db: AsyncSession) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    channex = {
        "status": "unknown",
        "pending": 0,
        "failed": 0,
        "processed_24h": 0,
        "last_event_at": None,
    }
    checkout_holds = {
        "status": "unknown",
        "active": 0,
        "expired": 0,
        "converted_24h": 0,
        "stale_active": 0,
    }
    twilio = {
        "status": "unknown",
        "outbound_24h": 0,
        "inbound_24h": 0,
        "failed_24h": 0,
        "needs_review": 0,
    }
    queues = {
        "status": "unknown",
        "queued": 0,
        "running": 0,
        "failed_24h": 0,
        "vrs_queued": 0,
        "vrs_failed_24h": 0,
    }
    quote_checkout = {
        "status": "unknown",
        "guest_pending": 0,
        "guest_accepted_24h": 0,
        "guest_created_24h": 0,
        "stale_pending": 0,
        "taylor_pending_approval": 0,
        "parity_checks_24h": 0,
        "parity_drifts_24h": 0,
        "empty_streamline_prices_24h": 0,
        "unresolved_empty_streamline_prices_24h": 0,
        "holds_missing_payment_intent": 0,
        "last_quote_at": None,
    }

    if await _table_exists(db, "channex_webhook_events"):
        channex["pending"] = await _fetch_count(
            db,
            "SELECT COUNT(*) FROM channex_webhook_events WHERE processing_status = 'pending'",
        )
        channex["failed"] = await _fetch_count(
            db,
            "SELECT COUNT(*) FROM channex_webhook_events WHERE processing_status = 'failed'",
        )
        channex["processed_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM channex_webhook_events
            WHERE processing_status IN ('processed', 'succeeded')
              AND created_at >= NOW() - INTERVAL '24 hours'
            """,
        )
        channex["last_event_at"] = await _fetch_iso(
            db,
            "SELECT MAX(created_at) FROM channex_webhook_events",
        )
        channex["status"] = "degraded" if channex["failed"] or channex["pending"] > 25 else "online"

    if await _table_exists(db, "reservation_holds"):
        checkout_holds["active"] = await _fetch_count(
            db,
            "SELECT COUNT(*) FROM reservation_holds WHERE status = 'active'",
        )
        checkout_holds["expired"] = await _fetch_count(
            db,
            "SELECT COUNT(*) FROM reservation_holds WHERE status = 'expired'",
        )
        checkout_holds["converted_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM reservation_holds
            WHERE status IN ('converted', 'confirmed')
              AND updated_at >= NOW() - INTERVAL '24 hours'
            """,
        )
        checkout_holds["stale_active"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM reservation_holds
            WHERE status = 'active'
              AND expires_at < NOW()
            """,
        )
        quote_checkout["holds_missing_payment_intent"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM reservation_holds
            WHERE status = 'active'
              AND payment_intent_id IS NULL
            """,
        )
        checkout_holds["status"] = "degraded" if checkout_holds["stale_active"] else "online"

    quote_tables_seen = False
    if await _table_exists(db, "guest_quotes"):
        quote_tables_seen = True
        quote_checkout["guest_pending"] = await _fetch_count(
            db,
            "SELECT COUNT(*) FROM guest_quotes WHERE status = 'pending'",
        )
        quote_checkout["guest_accepted_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM guest_quotes
            WHERE status = 'accepted'
              AND accepted_at >= NOW() - INTERVAL '24 hours'
            """,
        )
        quote_checkout["guest_created_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM guest_quotes
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            """,
        )
        quote_checkout["stale_pending"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM guest_quotes
            WHERE status = 'pending'
              AND expires_at < NOW()
            """,
        )
        quote_checkout["last_quote_at"] = await _fetch_iso(
            db,
            "SELECT MAX(created_at) FROM guest_quotes",
        )

    if await _table_exists(db, "taylor_quote_requests"):
        quote_tables_seen = True
        quote_checkout["taylor_pending_approval"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM taylor_quote_requests
            WHERE status = 'pending_approval'
            """,
        )
        if not quote_checkout["last_quote_at"]:
            quote_checkout["last_quote_at"] = await _fetch_iso(
                db,
                "SELECT MAX(created_at) FROM taylor_quote_requests",
            )

    if await _table_exists(db, "parity_audits"):
        quote_tables_seen = True
        quote_checkout["parity_checks_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM parity_audits
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            """,
        )
        quote_checkout["parity_drifts_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM parity_audits
            WHERE created_at >= NOW() - INTERVAL '24 hours'
              AND LOWER(status) != 'skipped_empty_streamline_price'
              AND NOT (
                LOWER(status) = 'discrepancy'
                AND streamline_total = 0
                AND local_total > 0
              )
              AND (
                COALESCE(ABS(delta), 0) > 0.01
                OR LOWER(status) NOT IN ('pass', 'passed', 'ok', 'matched', 'in_parity', 'confirmed')
              )
            """,
        )
        quote_checkout["empty_streamline_prices_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM parity_audits
            WHERE created_at >= NOW() - INTERVAL '24 hours'
              AND LOWER(status) IN ('discrepancy', 'skipped_empty_streamline_price')
              AND streamline_total = 0
              AND local_total > 0
            """,
        )
        quote_checkout["unresolved_empty_streamline_prices_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM parity_audits
            WHERE created_at >= NOW() - INTERVAL '24 hours'
              AND LOWER(status) = 'discrepancy'
              AND streamline_total = 0
              AND local_total > 0
            """,
        )

    if quote_tables_seen:
        quote_checkout["status"] = (
            "degraded"
            if (
                quote_checkout["stale_pending"]
                or quote_checkout["taylor_pending_approval"] > 20
                or quote_checkout["parity_drifts_24h"]
                or quote_checkout["unresolved_empty_streamline_prices_24h"]
                or quote_checkout["holds_missing_payment_intent"]
            )
            else "online"
        )

    if await _table_exists(db, "messages"):
        twilio["outbound_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM messages
            WHERE provider = 'twilio'
              AND direction = 'outbound'
              AND created_at >= NOW() - INTERVAL '24 hours'
            """,
        )
        twilio["inbound_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM messages
            WHERE provider = 'twilio'
              AND direction = 'inbound'
              AND created_at >= NOW() - INTERVAL '24 hours'
            """,
        )
        twilio["failed_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM messages
            WHERE provider = 'twilio'
              AND status = 'failed'
              AND created_at >= NOW() - INTERVAL '24 hours'
            """,
        )
        twilio["needs_review"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM messages
            WHERE requires_human_review IS TRUE
              AND human_reviewed_at IS NULL
            """,
        )
        twilio["status"] = "degraded" if twilio["failed_24h"] else "online"

    if await _table_exists(db, "async_job_runs"):
        queues["queued"] = await _fetch_count(
            db,
            "SELECT COUNT(*) FROM async_job_runs WHERE status = 'queued'",
        )
        queues["running"] = await _fetch_count(
            db,
            "SELECT COUNT(*) FROM async_job_runs WHERE status = 'running'",
        )
        queues["failed_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM async_job_runs
            WHERE status = 'failed'
              AND updated_at >= NOW() - INTERVAL '24 hours'
            """,
        )
        queues["vrs_queued"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM async_job_runs
            WHERE status = 'queued'
              AND job_name = 'process_streamline_event'
            """,
        )
        queues["vrs_failed_24h"] = await _fetch_count(
            db,
            """
            SELECT COUNT(*)
            FROM async_job_runs
            WHERE status = 'failed'
              AND job_name = 'process_streamline_event'
              AND updated_at >= NOW() - INTERVAL '24 hours'
            """,
        )
        queues["status"] = "degraded" if queues["failed_24h"] or queues["queued"] > 100 else "online"

    overall = "online"
    health_items = (channex, checkout_holds, quote_checkout, twilio, queues)
    if any(item["status"] == "degraded" for item in health_items):
        overall = "degraded"
    if all(item["status"] == "unknown" for item in health_items):
        overall = "unknown"

    return {
        "status": overall,
        "checked_at": checked_at,
        "channex": channex,
        "checkout_holds": checkout_holds,
        "quote_checkout": quote_checkout,
        "twilio": twilio,
        "queues": queues,
    }


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

    integrations = {
        "streamline_sync": _streamline_sync_health(),
        "operations": await _operational_health(db),
    }
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
        "integrations": integrations,
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
