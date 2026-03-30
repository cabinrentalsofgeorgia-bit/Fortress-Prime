"""Captain telemetry and command-and-control endpoints for internal operators."""

from __future__ import annotations

import asyncio
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.security import RoleChecker
from backend.models.staff import StaffRole, StaffUser

router = APIRouter()

PULSE_ACCESS = RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER, StaffRole.REVIEWER])
CONTROL_ACCESS = RoleChecker([StaffRole.SUPER_ADMIN, StaffRole.MANAGER])
C2_HOST_LABEL = "Captain-DGX"

VERIFY_SCRIPT_PATH = Path("/home/admin/Fortress-Prime/scripts/verify_captain_cloudflared.sh")
DOCKER_SERVICES = (
    "vllm-server",
    "qdrant-db",
    "fortress-backend",
    "fortress-worker",
)
RESTARTABLE_SERVICES = {
    "vllm-server": ("docker", "vllm-server"),
    "qdrant-db": ("docker", "qdrant-db"),
    "fortress-backend": ("docker", "fortress-backend"),
    "fortress-worker": ("docker", "fortress-worker"),
    "cloudflared": ("systemd", "cloudflared.service"),
}


class ServiceAction(BaseModel):
    service: str = Field(..., min_length=1)


class GPUMetrics(BaseModel):
    vram_used: int | None = None
    vram_total: int | None = None
    vram_percent: float | None = None
    temp: int | None = None
    utilization: int | None = None
    error: str | None = None
    details: str | None = None


class SystemVitals(BaseModel):
    ram_percent: float
    ram_gb_used: float
    disk_percent: float
    disk_gb_free: float


class RootResponse(BaseModel):
    status: str
    host: str
    node_name: str
    message: str
    timestamp: str
    endpoints: dict[str, str]


class PulseResponse(BaseModel):
    host: str
    node_name: str
    cpu_load: float
    system: SystemVitals
    gpu: GPUMetrics
    services: dict[str, str]
    uptime: str
    timestamp: str


class VerificationReport(BaseModel):
    status: str
    host: str
    node_name: str
    report: str
    timestamp: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/", response_model=RootResponse)
async def command_c2_root(
    _: StaffUser = Depends(PULSE_ACCESS),
) -> RootResponse:
    """Root endpoint to verify the C2 surface is reachable."""
    return RootResponse(
        status="online",
        host=C2_HOST_LABEL,
        node_name=platform.node(),
        message="Fortress Prime C2 Telemetry Active",
        timestamp=_utc_now_iso(),
        endpoints={
            "pulse": "/api/telemetry/pulse",
            "verify": "/api/telemetry/verify",
            "restart": "/api/telemetry/action/restart",
            "purge": "/api/telemetry/action/purge-cache",
        },
    )


def _run_command(
    args: list[str],
    *,
    timeout: int = 15,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def _run_command_output(args: list[str], *, timeout: int = 15) -> str:
    return _run_command(args, timeout=timeout).stdout.strip()


async def _run_command_async(
    args: list[str],
    *,
    timeout: int = 15,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return await asyncio.to_thread(_run_command, args, timeout=timeout, check=check)


async def _run_command_output_async(args: list[str], *, timeout: int = 15) -> str:
    return (await _run_command_async(args, timeout=timeout)).stdout.strip()


async def get_nvidia_vitals() -> GPUMetrics:
    """Extracts VRAM, temperature, and utilization via nvidia-smi."""
    try:
        output = await _run_command_output_async(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu",
                "--format=csv,nounits,noheader",
            ],
            timeout=10,
        )
        first_row = output.splitlines()[0].strip()
        used, total, temp, util = [segment.strip() for segment in first_row.split(",")]
        used_int = int(used)
        total_int = int(total)
        temp_int = int(temp)
        util_int = int(util)
        return GPUMetrics(
            vram_used=used_int,
            vram_total=total_int,
            vram_percent=round((used_int / total_int) * 100, 1) if total_int else 0.0,
            temp=temp_int,
            utilization=util_int,
        )
    except Exception as exc:
        return GPUMetrics(error="NVIDIA_SMI_OFFLINE", details=str(exc))


def get_docker_status() -> dict[str, str]:
    """Checks the health of critical local AI stack containers."""
    statuses: dict[str, str] = {}
    for service in DOCKER_SERVICES:
        try:
            statuses[service] = _run_command_output(
                ["docker", "inspect", "-f", "{{.State.Status}}", service],
                timeout=10,
            )
        except Exception:
            statuses[service] = "missing"
    return statuses


def get_system_vitals() -> SystemVitals:
    """Collects host-level RAM and disk usage."""
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return SystemVitals(
        ram_percent=ram.percent,
        ram_gb_used=round(ram.used / (1024**3), 2),
        disk_percent=disk.percent,
        disk_gb_free=round(disk.free / (1024**3), 2),
    )


async def build_pulse_response() -> PulseResponse:
    """Host vitals used by C2 `/pulse` and staff dashboard aggregates."""
    gpu = await get_nvidia_vitals()
    services = await asyncio.to_thread(get_docker_status)
    system = await asyncio.to_thread(get_system_vitals)
    uptime = await _run_command_output_async(["uptime", "-p"], timeout=10)
    cpu_load = await asyncio.to_thread(psutil.cpu_percent)
    return PulseResponse(
        host=C2_HOST_LABEL,
        node_name=platform.node(),
        cpu_load=cpu_load,
        system=system,
        gpu=gpu,
        services=services,
        uptime=uptime,
        timestamp=_utc_now_iso(),
    )


@router.get("/pulse", response_model=PulseResponse)
async def get_pulse(
    _: StaffUser = Depends(PULSE_ACCESS),
) -> PulseResponse:
    """Unified endpoint for mobile C2 monitoring."""
    return await build_pulse_response()


@router.get("/verify", response_model=VerificationReport)
async def run_verification(
    _: StaffUser = Depends(PULSE_ACCESS),
) -> VerificationReport:
    """Executes the Captain cloudflared verification script and returns the report."""
    if not VERIFY_SCRIPT_PATH.exists():
        raise HTTPException(status_code=404, detail="Verification script not found at configured path.")

    try:
        result = await _run_command_async([str(VERIFY_SCRIPT_PATH)], timeout=30)
        return VerificationReport(
            status="success",
            host=C2_HOST_LABEL,
            node_name=platform.node(),
            report=result.stdout,
            timestamp=_utc_now_iso(),
        )
    except subprocess.CalledProcessError as exc:
        report = (exc.stdout or "") + (exc.stderr or "")
        return VerificationReport(
            status="error",
            host=C2_HOST_LABEL,
            node_name=platform.node(),
            report=report.strip(),
            timestamp=_utc_now_iso(),
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Verification timed out after {exc.timeout}s",
        ) from exc


@router.post("/action/restart")
async def restart_service(
    action: ServiceAction,
    _: StaffUser = Depends(CONTROL_ACCESS),
) -> dict[str, str]:
    """Restarts an approved local service."""
    service = action.service.strip()
    target = RESTARTABLE_SERVICES.get(service)
    if target is None:
        raise HTTPException(status_code=400, detail="Invalid service target.")

    kind, name = target
    try:
        if kind == "systemd":
            await _run_command_async(["sudo", "-n", "systemctl", "restart", name], timeout=30)
        else:
            await _run_command_async(["docker", "restart", name], timeout=30)
        return {"status": "executed", "message": f"Restarted {service}"}
    except subprocess.CalledProcessError as exc:
        detail = ((exc.stdout or "") + (exc.stderr or "")).strip() or str(exc)
        raise HTTPException(status_code=500, detail=detail) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Restart timed out after {exc.timeout}s",
        ) from exc


@router.post("/action/purge-cache")
async def purge_cache(
    _: StaffUser = Depends(CONTROL_ACCESS),
) -> dict[str, str]:
    """Placeholder command surface for future cache invalidation."""
    return {
        "status": "placeholder",
        "message": "Purge logic is currently restricted. Manual override required.",
    }
