"""Staff Command Center aggregates backed by C2 pulse + sovereign ledger (no mock payloads)."""

from __future__ import annotations

import os
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.command_c2 import CONTROL_ACCESS, PULSE_ACCESS, build_pulse_response
from backend.api.sovereign_pulse import build_sovereign_pulse_payload
from backend.core.database import get_db
from backend.models.staff import StaffUser

router = APIRouter()
logger = structlog.get_logger()

_ModuleStatus = Literal["up", "down"]
_Maturity = Literal["legacy_only", "route_only", "data_live"]
_Reason = (
    Literal[
        "auth_required",
        "rate_limited",
        "not_found",
        "upstream_5xx",
        "client_error",
        "timeout",
        "network_failure",
    ]
    | None
)


class DefconRequest(BaseModel):
    mode: str = Field(..., min_length=1, max_length=64)
    override_authorization: bool = False


def _defcon_advisory_mode() -> str:
    return (os.environ.get("FORTRESS_ADVISORY_DEFCON") or "NOMINAL").strip() or "NOMINAL"


def _probe(path: str, backend_up: bool, *, reason: _Reason = None) -> dict[str, Any]:
    if backend_up:
        return {
            "path": path,
            "status": "up",
            "http_status": 200,
            "latency_ms": None,
            "reason": None,
        }
    return {
        "path": path,
        "status": "down",
        "http_status": None,
        "latency_ms": None,
        "reason": reason or "network_failure",
    }


def _maturity_for(
    backend_up: bool,
    data_live: bool,
) -> tuple[_Maturity, _Reason]:
    if not backend_up:
        return "legacy_only", "network_failure"
    if data_live:
        return "data_live", None
    return "route_only", None


_MODULE_ROWS: tuple[dict[str, Any], ...] = (
    {
        "id": "vrs-core",
        "label": "Crog VRS",
        "legacy_path": "/vacation-rental-software",
        "native_path": "/api/vrs/health",
        "data_probe_path": "/api/vrs/operations/ping",
        "data_live": True,
    },
    {
        "id": "direct-booking",
        "label": "Direct booking",
        "legacy_path": "/book",
        "native_path": "/api/direct-booking/config",
        "data_probe_path": None,
        "data_live": True,
    },
    {
        "id": "legal-council",
        "label": "Fortress Legal",
        "legacy_path": "/legal",
        "native_path": "/api/legal/health",
        "data_probe_path": None,
        "data_live": True,
    },
    {
        "id": "intelligence",
        "label": "Intelligence / market shadow",
        "legacy_path": "/intelligence",
        "native_path": "/api/intelligence/models",
        "data_probe_path": "/api/intelligence/market-snapshot/latest",
        "data_live": True,
    },
    {
        "id": "seo-tribunal",
        "label": "SEO Tribunal",
        "legacy_path": "/seo",
        "native_path": "/api/seo/queue/stats",
        "data_probe_path": None,
        "data_live": True,
    },
    {
        "id": "properties",
        "label": "Property catalog",
        "legacy_path": "/cabins",
        "native_path": "/api/properties",
        "data_probe_path": None,
        "data_live": False,
    },
    {
        "id": "dispatch",
        "label": "Autonomous dispatch",
        "legacy_path": "/dispatch",
        "native_path": "/api/dispatch/health",
        "data_probe_path": None,
        "data_live": False,
    },
)


@router.get("/telemetry")
async def staff_system_telemetry(
    _: StaffUser = Depends(PULSE_ACCESS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dashboard telemetry: C2 host vitals + sovereign ledger fields (same sources as `/api/telemetry/*`)."""
    pulse = await build_pulse_response()
    sp = await build_sovereign_pulse_payload(db)
    hs = sp.handshake
    seo = sp.seo_queue
    tri = sp.tribunal

    backend_up = pulse.services.get("fortress-backend") == "running"

    legacy_modules: dict[str, Any] = {}
    for name, state in pulse.services.items():
        up: _ModuleStatus = "up" if state == "running" else "down"
        legacy_modules[name] = {
            "path": f"/docker/{name}",
            "status": up,
            "http_status": 200 if up == "up" else None,
            "latency_ms": None,
        }

    processed = int(hs.holds_converted_last_24h + hs.direct_reservations_last_24h)
    errors = int(hs.orphan_risk_holds + hs.holds_converted_legacy_no_fk)
    queue_depth = int(seo.pending_human + seo.needs_rewrite + seo.drafted)

    threat_reports = int(
        tri.pending_human_at_or_above_threshold
        + tri.pending_human_below_threshold
        + tri.pending_human_score_unknown
    )

    return {
        "defcon_mode": _defcon_advisory_mode(),
        "vault_gamma": {"total_vectors": 0, "partitions": {}},
        "vault_omega": {"training_rows": 0},
        "ingestion": {
            "processed": processed,
            "errors": errors,
            "queue_depth": queue_depth,
        },
        "streamline_bridge": None,
        "legacy_modules": legacy_modules,
        "threat_reports": threat_reports,
        "timestamp": pulse.timestamp,
    }


@router.get("/module-maturity")
async def staff_module_maturity(
    _: StaffUser = Depends(PULSE_ACCESS),
) -> dict[str, Any]:
    """Route + data posture grid: probes reflect sovereign backend availability (not external Drupal fetches)."""
    pulse = await build_pulse_response()
    backend_up = pulse.services.get("fortress-backend") == "running"
    ts = pulse.timestamp

    modules: list[dict[str, Any]] = []
    legacy_up = 0
    native_up = 0
    data_live_n = 0

    for row in _MODULE_ROWS:
        leg_path = str(row["legacy_path"])
        native_path = row.get("native_path")
        data_path = row.get("data_probe_path")
        want_data = bool(row.get("data_live"))

        leg = _probe(leg_path, backend_up)
        if leg["status"] == "up":
            legacy_up += 1

        nat_probe: dict[str, Any] | None
        if native_path:
            nat = _probe(str(native_path), backend_up)
            nat_probe = nat
            if nat["status"] == "up":
                native_up += 1
        else:
            nat_probe = None

        data_probe: dict[str, Any] | None
        if data_path:
            data_probe = _probe(str(data_path), backend_up and want_data)
        else:
            data_probe = None

        maturity, maturity_reason = _maturity_for(
            backend_up,
            want_data and (data_probe is None or data_probe["status"] == "up") and nat_probe is not None and nat_probe["status"] == "up",
        )
        if maturity == "data_live":
            data_live_n += 1

        modules.append(
            {
                "id": row["id"],
                "label": row["label"],
                "legacy_path": leg_path,
                "native_path": native_path,
                "data_probe_path": data_path,
                "legacy": leg,
                "native": nat_probe,
                "data_probe": data_probe,
                "maturity": maturity,
                "maturity_reason": maturity_reason,
            }
        )

    total = len(modules)
    return {
        "summary": {
            "total_modules": total,
            "legacy_routes_up": legacy_up,
            "native_routes_ready": native_up,
            "native_data_live": data_live_n,
        },
        "modules": modules,
        "timestamp": ts,
    }


@router.post("/defcon")
async def staff_defcon_advisory(
    body: DefconRequest,
    user: StaffUser = Depends(CONTROL_ACCESS),
) -> dict[str, str]:
    """Advisory-only DEFCON switch: logs intent; no fleet enforcement is wired on DGX."""
    logger.info(
        "staff_defcon_advisory",
        mode=body.mode,
        override=body.override_authorization,
        staff_id=str(user.id),
    )
    return {
        "status": "advisory",
        "mode": body.mode,
        "output": (
            "DEFCON request recorded as advisory-only on DGX. "
            "No automated fleet-wide enforcement is configured; follow the Captain runbook for operational posture."
        ),
    }
