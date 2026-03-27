"""Property media sync endpoints."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.queue import get_arq_pool
from backend.core.security import require_manager_or_admin
from backend.integrations.streamline_vrs import StreamlineVRS
from backend.models import Property
from backend.models.media import PROPERTY_IMAGE_STATUS_INGESTED, PROPERTY_IMAGE_STATUS_PENDING, PropertyImage
from backend.models.staff import StaffUser
from backend.schemas.media import PropertyImageResponse, PropertyMediaSyncResponse

router = APIRouter()


def _default_alt_text(property_name: str, display_order: int, *, is_hero: bool) -> str:
    if is_hero:
        return f"{property_name} hero image"
    return f"{property_name} image {display_order + 1}"


def _extract_legacy_urls(detail: dict[str, object], gallery: Iterable[object]) -> list[str]:
    urls: list[str] = []

    def _append(url: object) -> None:
        value = str(url or "").strip()
        if value and value not in urls:
            urls.append(value)

    _append(detail.get("default_image_path"))
    for item in gallery:
        if not isinstance(item, dict):
            continue
        _append(item.get("image_path") or item.get("original_path") or item.get("thumbnail_path"))
    return urls


async def _load_property(db: AsyncSession, property_id: UUID) -> Property | None:
    result = await db.execute(
        select(Property)
        .execution_options(populate_existing=True)
        .options(selectinload(Property.images))
        .where(Property.id == property_id)
    )
    return result.scalar_one_or_none()


@router.post("/sync/{property_id}", response_model=PropertyMediaSyncResponse)
async def sync_property_media(
    property_id: UUID,
    db: AsyncSession = Depends(get_db),
    arq_redis: ArqRedis = Depends(get_arq_pool),
    _user: StaffUser = Depends(require_manager_or_admin),
) -> PropertyMediaSyncResponse:
    property_record = await _load_property(db, property_id)
    if property_record is None:
        raise HTTPException(status_code=404, detail="Property not found")

    streamline_property_id = str(property_record.streamline_property_id or "").strip()
    if not streamline_property_id:
        raise HTTPException(status_code=409, detail="Property is missing streamline_property_id")

    try:
        streamline_unit_id = int(streamline_property_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Property streamline_property_id is invalid") from exc

    client = StreamlineVRS()
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="Streamline VRS is not configured")

    try:
        detail = await client.fetch_property_detail(streamline_unit_id)
        gallery = await client.fetch_property_gallery(streamline_unit_id)
    finally:
        await client.close()

    legacy_urls = _extract_legacy_urls(detail, gallery)
    existing_by_url = {image.legacy_url: image for image in property_record.images}
    created_records = 0

    for display_order, legacy_url in enumerate(legacy_urls):
        is_hero = display_order == 0
        existing = existing_by_url.get(legacy_url)
        if existing is None:
            db.add(
                PropertyImage(
                    property_id=property_record.id,
                    legacy_url=legacy_url,
                    display_order=display_order,
                    alt_text=_default_alt_text(property_record.name, display_order, is_hero=is_hero),
                    is_hero=is_hero,
                    status=PROPERTY_IMAGE_STATUS_PENDING,
                )
            )
            created_records += 1
            continue

        existing.display_order = display_order
        existing.is_hero = is_hero
        if not existing.alt_text:
            existing.alt_text = _default_alt_text(property_record.name, display_order, is_hero=is_hero)
        if existing.status != PROPERTY_IMAGE_STATUS_INGESTED:
            existing.status = PROPERTY_IMAGE_STATUS_PENDING

    await db.commit()
    property_record = await _load_property(db, property_id)
    if property_record is None:
        raise HTTPException(status_code=404, detail="Property not found after media sync")

    pending_images = [image for image in property_record.images if image.status == PROPERTY_IMAGE_STATUS_PENDING]
    for image in pending_images:
        await arq_redis.enqueue_job(
            "ingest_property_media",
            str(image.id),
            _queue_name=settings.arq_queue_name,
        )

    return PropertyMediaSyncResponse(
        property_id=property_record.id,
        property_name=property_record.name,
        discovered_legacy_urls=len(legacy_urls),
        created_records=created_records,
        pending_records=len(pending_images),
        enqueued_jobs=len(pending_images),
        images=[PropertyImageResponse.model_validate(image) for image in property_record.images],
    )
