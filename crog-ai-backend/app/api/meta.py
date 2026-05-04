"""Read-only service metadata endpoints."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {
        "status": "ok",
        "env": os.environ.get("ENV", "unknown"),
        "service": "crog-ai-backend",
    }


@router.get("/version")
def version() -> dict[str, str]:
    return {
        "commit": os.environ.get("COMMIT_SHA", "unknown"),
        "branch": os.environ.get("GIT_BRANCH", "unknown"),
        "build_time": os.environ.get("BUILD_TIME", datetime.now(tz=UTC).isoformat()),
    }
