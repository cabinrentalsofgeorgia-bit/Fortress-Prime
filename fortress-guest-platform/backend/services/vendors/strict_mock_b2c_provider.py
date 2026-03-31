"""
Deterministic mock B2C contact provider used to validate the Hermes pipeline
before live PropertyRadar/Trellis credentials are available.
"""
from __future__ import annotations

import re

from backend.services.vendors.base import B2CContactProvider, ContactRecord, ContactResult


def _normalize_apn(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _normalize_name(value: str) -> str:
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).split())


class StrictMockB2CProvider(B2CContactProvider):
    provider_name = "strict_mock_b2c_provider"

    async def resolve_contact(self, apn: str, owner_name: str) -> ContactResult:
        normalized_apn = _normalize_apn(apn)
        normalized_name = _normalize_name(owner_name)

        if normalized_apn == "0009017" and normalized_name == "MAGRUDER MICHAEL JAMES":
            return ContactResult(
                provider_name=self.provider_name,
                matched=True,
                contacts=[
                    ContactRecord(
                        contact_type="CELL",
                        contact_value="+15550109999",
                        source=self.provider_name,
                        confidence_score=0.99,
                    ),
                    ContactRecord(
                        contact_type="EMAIL",
                        contact_value="test_target@crog-ai.local",
                        source=self.provider_name,
                        confidence_score=0.99,
                    ),
                ],
                metadata={
                    "display_phone": "555-010-9999",
                    "owner_name": owner_name,
                    "apn": apn,
                    "mock_mode": True,
                },
            )

        return ContactResult(
            provider_name=self.provider_name,
            matched=False,
            contacts=[],
            metadata={
                "owner_name": owner_name,
                "apn": apn,
                "mock_mode": True,
            },
        )
