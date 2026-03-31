"""
Strictly typed B2C contact provider contract for acquisition enrichment.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_type: Literal["EMAIL", "CELL", "LANDLINE"]
    contact_value: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=100)
    confidence_score: float = Field(ge=0.0, le=1.0)


class ContactResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(min_length=1, max_length=100)
    matched: bool
    contacts: list[ContactRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class B2CContactProvider(ABC):
    provider_name: str

    @abstractmethod
    async def resolve_contact(self, apn: str, owner_name: str) -> ContactResult:
        """Resolve B2C owner contact data for a parcel and deeded owner."""
