"""
Multi-tenant middleware and utilities.

Strategy: Row-Level Security via PostgreSQL session variable `app.current_tenant_id`.
Each request sets this variable based on the JWT tenant claim or subdomain.
"""

from typing import Optional
from fastapi import Request, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from backend.core.database import get_db

logger = structlog.get_logger()

# Paths that don't require tenant context
PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json", "/ws"}


def _extract_tenant_id(request: Request) -> Optional[str]:
    """Extract tenant_id from JWT claims or query param."""
    # 1. From JWT payload (set by auth middleware)
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return str(tenant_id)

    # 2. From X-Tenant-Id header (for service-to-service calls)
    header = request.headers.get("x-tenant-id")
    if header:
        return header

    return None


class TenantMiddleware(BaseHTTPMiddleware):
    """Extracts tenant_id and stores on request.state for downstream use."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in PUBLIC_PATHS):
            return await call_next(request)

        tenant_id = _extract_tenant_id(request)
        request.state.tenant_id = tenant_id

        response = await call_next(request)
        return response


async def set_tenant_scope(db: AsyncSession, tenant_id: Optional[str]):
    """Set the PostgreSQL session variable for RLS enforcement."""
    if tenant_id:
        await db.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": tenant_id},
        )


async def get_tenant_db(request: Request, db: AsyncSession = Depends(get_db)):
    """Dependency that returns a DB session scoped to the current tenant."""
    tenant_id = getattr(request.state, "tenant_id", None)
    await set_tenant_scope(db, tenant_id)
    yield db
