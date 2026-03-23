from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SEOPatchCreate(BaseModel):
    property_id: Optional[UUID] = None
    rubric_id: Optional[UUID] = None
    page_path: str = Field(..., description="Legacy Drupal path or Next.js route")
    title: str = Field(..., max_length=70)
    meta_description: str = Field(..., max_length=320)
    og_title: Optional[str] = Field(None, max_length=95)
    og_description: Optional[str] = Field(None, max_length=200)
    jsonld_payload: Optional[dict[str, Any]] = None
    canonical_url: Optional[str] = None
    h1_suggestion: Optional[str] = None
    alt_tags: Optional[dict[str, Any]] = None
    swarm_model: str = Field(..., description="The DGX model that generated this payload")
    swarm_node: str = Field(..., description="The DGX node IP")
    generation_ms: int
