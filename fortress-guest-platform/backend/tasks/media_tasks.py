"""ARQ jobs for sovereign media ingestion."""

from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.core.database import AsyncSessionLocal
from backend.models.media import (
    PROPERTY_IMAGE_STATUS_FAILED,
    PROPERTY_IMAGE_STATUS_INGESTED,
    PropertyImage,
)
from backend.services.storage_service import upload_image_bytes

logger = structlog.get_logger(service="media_ingestion")


def _guess_extension(legacy_url: str, content_type: str) -> str:
    suffix = PurePosixPath(httpx.URL(legacy_url).path).suffix.lower()
    if suffix:
        return suffix
    guessed = mimetypes.guess_extension(content_type.partition(";")[0].strip().lower())
    return guessed or ".bin"


def _resolve_content_type(response: httpx.Response, legacy_url: str) -> str:
    header_value = response.headers.get("content-type", "").partition(";")[0].strip().lower()
    if header_value:
        return header_value
    guessed, _ = mimetypes.guess_type(legacy_url)
    return guessed or "application/octet-stream"


def _destination_key_for_image(image: PropertyImage, content_type: str) -> str:
    extension = _guess_extension(image.legacy_url, content_type)
    property_slug = (image.property.slug if image.property else str(image.property_id)).strip() or str(image.property_id)
    return (
        f"properties/{property_slug}/images/"
        f"{image.display_order:03d}-{image.id}{extension}"
    )


async def ingest_property_media(ctx: dict[str, object], image_id: str) -> dict[str, str]:
    del ctx

    try:
        parsed_image_id = UUID(str(image_id).strip())
    except ValueError as exc:
        raise RuntimeError(f"Invalid property image id: {image_id}") from exc

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PropertyImage)
            .options(selectinload(PropertyImage.property))
            .where(PropertyImage.id == parsed_image_id)
        )
        image = result.scalar_one_or_none()
        if image is None:
            raise RuntimeError(f"Property image {image_id} not found")

        if image.sovereign_url and image.status == PROPERTY_IMAGE_STATUS_INGESTED:
            return {
                "image_id": str(image.id),
                "status": image.status,
                "sovereign_url": image.sovereign_url,
            }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=15.0),
                follow_redirects=True,
            ) as client:
                response = await client.get(image.legacy_url)
                response.raise_for_status()

            content_type = _resolve_content_type(response, image.legacy_url)
            sovereign_url = await upload_image_bytes(
                response.content,
                _destination_key_for_image(image, content_type),
                content_type,
            )
            image.sovereign_url = sovereign_url
            image.status = PROPERTY_IMAGE_STATUS_INGESTED
            await db.commit()
            logger.info(
                "property_image_ingested",
                image_id=str(image.id),
                property_id=str(image.property_id),
                sovereign_url=sovereign_url,
            )
            return {
                "image_id": str(image.id),
                "status": image.status,
                "sovereign_url": sovereign_url,
            }
        except Exception:
            image.status = PROPERTY_IMAGE_STATUS_FAILED
            await db.commit()
            logger.exception(
                "property_image_ingestion_failed",
                image_id=str(image.id),
                property_id=str(image.property_id),
                legacy_url=image.legacy_url,
            )
            raise
