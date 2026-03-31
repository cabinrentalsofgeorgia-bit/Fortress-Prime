"""
Vendor provider contracts and implementations for acquisition enrichment.
"""

from backend.services.vendors.base import B2CContactProvider, ContactRecord, ContactResult
from backend.services.vendors.strict_mock_b2c_provider import StrictMockB2CProvider

__all__ = [
    "B2CContactProvider",
    "ContactRecord",
    "ContactResult",
    "StrictMockB2CProvider",
]
