from __future__ import annotations

import os
import sys

from sqlalchemy.dialects.postgresql import JSONB

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.models.property import Property
from backend.models.treasury import OTAProvider
from backend.services.competitive_sentinel import _authoritative_ota_links
from backend.services.competitive_sentinel import _provider_url_is_valid


def test_property_model_includes_ota_metadata_jsonb_column() -> None:
    column = Property.__table__.c.ota_metadata

    assert isinstance(column.type, JSONB)
    assert column.nullable is False


def test_authoritative_ota_links_extracts_supported_providers() -> None:
    links = _authoritative_ota_links(
        {
            "airbnb_url": " https://www.airbnb.com/rooms/1 ",
            "vrbo_url": "https://www.vrbo.com/2",
            "booking_com_url": "https://www.booking.com/hotel/us/3.html",
        }
    )

    assert links == {
        OTAProvider.AIRBNB: "https://www.airbnb.com/rooms/1",
        OTAProvider.VRBO: "https://www.vrbo.com/2",
        OTAProvider.BOOKING: "https://www.booking.com/hotel/us/3.html",
    }


def test_provider_url_is_valid_enforces_provider_domain() -> None:
    assert _provider_url_is_valid(OTAProvider.AIRBNB, "https://www.airbnb.com/rooms/1")
    assert _provider_url_is_valid(OTAProvider.VRBO, "https://www.vrbo.com/2")
    assert not _provider_url_is_valid(OTAProvider.AIRBNB, "https://www.vrbo.com/2")
