"""Disaggregated admin control-plane endpoints (hot reload)."""

from __future__ import annotations

import os
import secrets
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.core.security import decode_token

router = APIRouter()

_RELOAD_LOCK = threading.Lock()
_RELOAD_BY_ID: dict[str, dict] = {}
_RELOAD_BY_SHA: dict[str, str] = {}
_ACTIVE_ADAPTER = os.getenv("DISAGG_ACTIVE_ADAPTER", "baseline")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_admin(request: Request) -> dict:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")
    payload = decode_token(auth[7:])
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload


def _require_reload_token(request: Request) -> None:
    expected = os.getenv("DISAGG_RELOAD_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Reload token is not configured")
    token = request.headers.get("x-reload-token", "")
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid reload token")


class DisaggHotReloadRequest(BaseModel):
    adapter_uri: str = Field(..., min_length=1, max_length=1024)
    adapter_sha256: Optional[str] = Field(default=None, min_length=8, max_length=128)
    model_id: Optional[str] = Field(default=None, max_length=255)
    rollout_mode: str = Field(default="atomic_flip", max_length=64)


@router.post("/hot-reload", status_code=status.HTTP_202_ACCEPTED)
async def disagg_hot_reload(request: Request, body: DisaggHotReloadRequest):
    global _ACTIVE_ADAPTER

    actor = _require_admin(request)
    _require_reload_token(request)

    with _RELOAD_LOCK:
        if body.adapter_sha256 and body.adapter_sha256 in _RELOAD_BY_SHA:
            existing = _RELOAD_BY_SHA[body.adapter_sha256]
            rec = _RELOAD_BY_ID[existing]
            return {
                "status": "duplicate",
                "reload_id": existing,
                "state_url": f"/api/disagg/admin/hot-reload/{existing}",
                "active_adapter": _ACTIVE_ADAPTER,
                "record": rec,
            }

        reload_id = str(uuid.uuid4())
        rec = {
            "reload_id": reload_id,
            "status": "queued",
            "adapter_uri": body.adapter_uri,
            "adapter_sha256": body.adapter_sha256,
            "model_id": body.model_id,
            "rollout_mode": body.rollout_mode,
            "requested_by": actor.get("email") or actor.get("sub") or "admin",
            "queued_at": _utc_iso(),
            "completed_at": _utc_iso(),
        }
        _RELOAD_BY_ID[reload_id] = rec
        if body.adapter_sha256:
            _RELOAD_BY_SHA[body.adapter_sha256] = reload_id
        _ACTIVE_ADAPTER = body.adapter_uri

    return {
        "status": "queued",
        "reload_id": reload_id,
        "state_url": f"/api/disagg/admin/hot-reload/{reload_id}",
        "active_adapter": _ACTIVE_ADAPTER,
    }


@router.get("/hot-reload/{reload_id}")
async def disagg_hot_reload_status(reload_id: str, request: Request):
    _require_admin(request)
    _require_reload_token(request)

    with _RELOAD_LOCK:
        rec = _RELOAD_BY_ID.get(reload_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Reload id not found")
        return rec
