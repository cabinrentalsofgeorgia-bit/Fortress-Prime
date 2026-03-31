"""
Fireclaw — microVM interrogation (admin-only).

POST /api/sandbox/fireclaw/interrogate accepts a file; the host helper copies it onto
the guest payload volume as the sole file and runs /opt/agent/interrogate.py (no user_code.py).
"""

from __future__ import annotations

import json
import secrets
import shutil
import uuid
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.core.config import settings
from backend.core.database import AsyncSession, get_db
from backend.core.security import get_current_user
from backend.models.staff import StaffUser
from backend.services.fireclaw_runner import run_firecracker_interrogate

logger = structlog.get_logger()

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)


def _safe_filename(name: str) -> str:
    base = Path(name or "payload.bin").name
    return "".join(c if c.isalnum() or c in (".", "-", "_") else "_" for c in base)[:200] or "payload.bin"


async def require_fireclaw_access(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> StaffUser | str:
    internal_token = settings.internal_api_bearer_token
    if creds is not None and (creds.scheme or "").lower() == "bearer" and internal_token:
        token = creds.credentials.strip()
        if token and secrets.compare_digest(token, internal_token):
            return "internal_service"

    user = await get_current_user(creds=creds, db=db)
    if user.role not in ("admin", "super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


@router.post(
    "/interrogate",
    summary="Run Fireclaw interrogation on an uploaded file (microVM)",
    description=(
        "Boots a Firecracker guest with the file as the only payload entry; guest runs "
        "interrogate.py and returns JSON on the serial console. Requires SANDBOX_RUNTIME=firecracker "
        "and a root-capable helper on the host."
    ),
)
async def fireclaw_interrogate(
    file: UploadFile = File(...),
    _access: StaffUser | str = Depends(require_fireclaw_access),
):
    max_bytes = int(settings.sandbox_interrogate_max_mb) * 1024 * 1024
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Empty file")
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds sandbox_interrogate_max_mb ({settings.sandbox_interrogate_max_mb} MiB)",
        )

    work_root = (settings.sandbox_work_dir or "").strip() or "/var/lib/fortress/fireclaw"
    staging = Path(work_root) / "interrogate-staging" / str(uuid.uuid4())
    staging.mkdir(parents=True, exist_ok=True)
    dest = staging / _safe_filename(file.filename or "payload.pdf")

    try:
        dest.write_bytes(raw)
        dest.chmod(0o644)
        result = run_firecracker_interrogate(dest, timeout_seconds=120)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    guest_json = None
    if result.stdout:
        try:
            guest_json = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            guest_json = None

    logger.info(
        "fireclaw_interrogate_api",
        exit_code=result.exit_code,
        filename=file.filename,
        size_bytes=len(raw),
        parsed=bool(guest_json),
    )

    return {
        "exit_code": result.exit_code,
        "guest": guest_json,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error_class": result.error_class or None,
    }
