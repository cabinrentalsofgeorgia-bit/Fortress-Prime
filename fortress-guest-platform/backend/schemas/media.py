from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PropertyImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    property_id: UUID
    legacy_url: str
    sovereign_url: str | None = None
    display_order: int
    alt_text: str
    is_hero: bool
    status: str


class PropertyMediaSyncResponse(BaseModel):
    property_id: UUID
    property_name: str
    discovered_legacy_urls: int
    created_records: int
    pending_records: int
    enqueued_jobs: int
    images: list[PropertyImageResponse] = Field(default_factory=list)
