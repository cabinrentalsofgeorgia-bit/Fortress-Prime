"""
Admin Channex API — property inventory sync and mapping controls.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import require_admin
from backend.models.staff import StaffUser
from backend.services.channex_attention import emit_channex_attention_signal_if_needed
from backend.services.channex_history import ChannexHistoryResponse, get_channex_remediation_history
from backend.services.channex_health import ChannexHealthResponse, channex_health_snapshot
from backend.services.channex_remediation import (
    ChannexRemediationRequest,
    ChannexRemediationResponse,
    remediate_channex_fleet,
)
from backend.services.channex_sync import (
    ChannexSyncInventoryRequest,
    ChannexSyncInventoryResponse,
    sync_inventory_to_channex,
)
from backend.services.openshell_audit import record_audit_event

logger = structlog.get_logger(service="admin_channex_api")

router = APIRouter()


@router.get("/channex/health", response_model=ChannexHealthResponse)
async def channex_health(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_admin),
):
    snapshot = await channex_health_snapshot(db)
    await emit_channex_attention_signal_if_needed(
        db,
        actor_id=str(user.id),
        actor_email=user.email,
        request_id=request.headers.get("x-request-id"),
        snapshot=snapshot,
    )
    return snapshot


@router.get("/channex/history", response_model=ChannexHistoryResponse)
async def channex_history(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(require_admin),
):
    return await get_channex_remediation_history(db, limit=limit)


@router.post("/channex/remediate", response_model=ChannexRemediationResponse)
async def remediate_channex(
    payload: ChannexRemediationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_admin),
):
    response = await remediate_channex_fleet(db, payload)
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="admin.channex.remediate",
        resource_type="channex_inventory",
        purpose="repair channex shell/catalog/ari drift",
        outcome="success" if response.failed_count == 0 else "partial_failure",
        request_id=request.headers.get("x-request-id"),
        metadata_json={
            "property_count": response.property_count,
            "remediated_count": response.remediated_count,
            "failed_count": response.failed_count,
            "property_ids": payload.property_ids or [],
            "ari_window_days": payload.ari_window_days,
            "results": [
                {
                    "property_id": row.property_id,
                    "slug": row.slug,
                    "property_name": row.property_name,
                    "shell_action": row.shell_action,
                    "catalog_action": row.catalog_action,
                    "ari_action": row.ari_action,
                    "error": row.error,
                }
                for row in response.results
            ],
        },
    )
    logger.info(
        "admin_channex_remediation_completed",
        actor_id=str(user.id),
        property_count=response.property_count,
        remediated_count=response.remediated_count,
        failed_count=response.failed_count,
    )
    return response


@router.post("/channex/sync-inventory", response_model=ChannexSyncInventoryResponse)
async def sync_channex_inventory(
    payload: ChannexSyncInventoryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: StaffUser = Depends(require_admin),
):
    response = await sync_inventory_to_channex(db, payload)
    await record_audit_event(
        actor_id=str(user.id),
        actor_email=user.email,
        action="admin.channex.sync_inventory",
        resource_type="channex_inventory",
        purpose="sync upstream property inventory and mappings",
        outcome="success" if response.failed_count == 0 else "partial_failure",
        request_id=request.headers.get("x-request-id"),
        metadata_json={
            "dry_run": payload.dry_run,
            "scanned_count": response.scanned_count,
            "mapped_count": response.mapped_count,
            "created_count": response.created_count,
            "failed_count": response.failed_count,
            "property_ids": payload.property_ids or [],
        },
    )
    logger.info(
        "admin_channex_sync_completed",
        actor_id=str(user.id),
        dry_run=payload.dry_run,
        scanned_count=response.scanned_count,
        mapped_count=response.mapped_count,
        created_count=response.created_count,
        failed_count=response.failed_count,
    )
    return response
