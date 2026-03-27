"""
Internal admin surface for Redirect Vanguard KV (full sync, slug removal).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import RoleChecker
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch
from backend.models.staff import StaffRole, StaffUser
from backend.services.redirect_vanguard_kv import (
    cabin_slug_from_patch_targets,
    delete_deployed_cabin_slug,
    redirect_vanguard_kv_configured,
    upsert_deployed_cabin_slug,
)

router = APIRouter(prefix="/redirect-vanguard", tags=["Redirect Vanguard"])

_VANGUARD_ADMIN = RoleChecker([StaffRole.SUPER_ADMIN])


class KvFullSyncResponse(BaseModel):
    configured: bool
    upserted: int = Field(ge=0)
    skipped: int = Field(ge=0)
    slugs: list[str] = Field(default_factory=list)


@router.post("/kv/full-sync", response_model=KvFullSyncResponse)
async def kv_full_sync(
    db: AsyncSession = Depends(get_db),
    _user: StaffUser = Depends(_VANGUARD_ADMIN),
) -> KvFullSyncResponse:
    """
    Push every distinct sovereign-ready slug derived from deployed SEO patches to KV.
    Use after creating the namespace or recovering from drift.
    """
    if not redirect_vanguard_kv_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloudflare KV not configured (CLOUDFLARE_* env vars).",
        )

    stmt = (
        select(SEOPatch.page_path, Property.slug)
        .select_from(SEOPatch)
        .outerjoin(Property, SEOPatch.property_id == Property.id)
        .where(SEOPatch.status == "deployed")
    )
    result = await db.execute(stmt)
    slugs: set[str] = set()
    skipped = 0
    for page_path, prop_slug in result.all():
        slug = cabin_slug_from_patch_targets(property_slug=prop_slug, page_path=str(page_path or ""))
        if slug:
            slugs.add(slug)
        else:
            skipped += 1

    upserted = 0
    for slug in sorted(slugs):
        if await upsert_deployed_cabin_slug(slug):
            upserted += 1

    return KvFullSyncResponse(
        configured=True,
        upserted=upserted,
        skipped=skipped,
        slugs=sorted(slugs),
    )


@router.delete("/kv/slug/{slug:path}")
async def kv_delete_slug(
    slug: str,
    _user: StaffUser = Depends(_VANGUARD_ADMIN),
) -> dict[str, str | bool]:
    if not redirect_vanguard_kv_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloudflare KV not configured.",
        )
    ok = await delete_deployed_cabin_slug(slug)
    if not ok:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="KV delete failed")
    return {"status": "ok", "slug": slug.strip().lower()}
