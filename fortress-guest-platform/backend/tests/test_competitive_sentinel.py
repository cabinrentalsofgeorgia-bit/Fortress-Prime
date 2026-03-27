from __future__ import annotations

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.models.treasury import OTAProvider
from backend.services.competitive_sentinel import (
    CompetitiveSentinelQuote,
    CompetitiveSentinelService,
    _booking_quote_from_probe_result,
    _canonicalize_url,
)


def test_canonicalize_url_normalizes_trailing_slash_and_case() -> None:
    assert _canonicalize_url("HTTPS://Example.com/path/") == "https://example.com/path"


def test_generate_dedupe_hash_is_stable_for_same_window() -> None:
    service = CompetitiveSentinelService()

    first = service._generate_dedupe_hash(
        "00000000-0000-0000-0000-000000000001",
        "airbnb",
        "2026-04-23",
        "2026-04-26",
    )
    second = service._generate_dedupe_hash(
        "00000000-0000-0000-0000-000000000001",
        "airbnb",
        "2026-04-23",
        "2026-04-26",
    )

    assert first == second


def test_normalize_platform_maps_known_aliases() -> None:
    service = CompetitiveSentinelService()

    assert service._normalize_platform("airbnb") == OTAProvider.AIRBNB
    assert service._normalize_platform("homeaway") == OTAProvider.VRBO
    assert service._normalize_platform("booking.com") == OTAProvider.BOOKING
    assert service._normalize_platform("unknown") is None


def test_compute_savings_prefers_after_tax_when_available() -> None:
    service = CompetitiveSentinelService()
    quote = CompetitiveSentinelQuote(
        platform="airbnb",
        nightly=225.0,
        platform_fee=45.0,
        cleaning_fee=120.0,
        total_before_tax=840.0,
        total_after_tax=910.0,
    )

    savings = service._compute_savings(
        sovereign_total_after_tax=Decimal("875.00"),
        sovereign_total_before_tax=Decimal("810.00"),
        ota_quote=quote,
    )

    assert savings == Decimal("35.00")


def test_compute_savings_falls_back_to_before_tax_when_needed() -> None:
    service = CompetitiveSentinelService()
    quote = CompetitiveSentinelQuote(
        platform="vrbo",
        nightly=225.0,
        platform_fee=45.0,
        cleaning_fee=120.0,
        total_before_tax=840.0,
        total_after_tax=None,
    )

    savings = service._compute_savings(
        sovereign_total_after_tax=Decimal("875.00"),
        sovereign_total_before_tax=Decimal("810.00"),
        ota_quote=quote,
    )

    assert savings == Decimal("30.00")


def test_booking_quote_from_probe_result_parses_price_breakdown() -> None:
    quote = _booking_quote_from_probe_result(
        {
            "slug": "peace-heaven",
            "provider": "booking_com",
            "source_url": "https://www.booking.com/hotel/us/example.html",
            "price_signals": [
                "$244 per night $1,194 Price $1,194 3 nights Included: US$ 75.9 Resort fee per stay, US$ 258.5 Cleaning fee per stay, 17.27 % Service charge Excluded: 11.75 % TAX",
            ],
        },
        nights=3,
    )

    assert quote is not None
    assert quote.platform == OTAProvider.BOOKING.value
    assert quote.nightly == 244.0
    assert quote.cleaning_fee == 258.5
    assert quote.platform_fee == 203.5
    assert quote.total_before_tax == 1194.0
    assert quote.total_after_tax == 1334.3


def test_booking_quote_from_probe_result_parses_richer_fragment_without_currency_markers() -> None:
    quote = _booking_quote_from_probe_result(
        {
            "slug": "peace-heaven",
            "provider": "booking_com",
            "source_url": "https://www.booking.com/hotel/us/example.html",
            "price_signals": [
                "Just a Price: $1,194.00",
                "Total Price: US$ 1,194.00 120.00 per night 150.00 Cleaning fee Excluded: 15.0 % Tax",
            ],
        },
        nights=5,
    )

    assert quote is not None
    assert quote.nightly == 120.0
    assert quote.cleaning_fee == 150.0
    assert quote.platform_fee == 444.0
    assert quote.total_before_tax == 1194.0
    assert quote.total_after_tax == 1373.1


def test_booking_quote_from_probe_result_accepts_missing_provider_and_legacy_alias_fields() -> None:
    quote = _booking_quote_from_probe_result(
        {
            "price_signals": [
                "Price: US$ 1,194.00",
                "120.00 per night",
                "150.00 Cleaning fee",
                "Excluded: 15.0 % Tax",
            ],
        },
        nights=5,
    )

    assert quote is not None
    assert quote.observed_total_before_tax == Decimal("1194.00")
    assert quote.nightly_rate == Decimal("120.00")
    assert quote.cleaning_fee == 150.0
    assert quote.platform_fee == 444.0


def test_booking_quote_from_probe_result_accepts_comma_formatted_amounts() -> None:
    quote = _booking_quote_from_probe_result(
        {
            "slug": "peace-heaven",
            "provider": "booking_com",
            "source_url": "https://www.booking.com/hotel/us/example.html",
            "price_signals": [
                "$1,244.50 per night Price $4,992.00 Excluded: 11.75 % TAX US$ 258.50 Cleaning fee per stay",
            ],
        },
        nights=3,
    )

    assert quote is not None
    assert quote.nightly == 1244.5
    assert quote.cleaning_fee == 258.5
    assert quote.platform_fee == 1000.0
    assert quote.total_before_tax == 4992.0
    assert quote.total_after_tax == 5578.56


def test_booking_quote_from_probe_result_rejects_non_positive_nights() -> None:
    quote = _booking_quote_from_probe_result(
        {
            "slug": "peace-heaven",
            "provider": "booking_com",
            "price_signals": [
                "$244 per night Price $1,194 Excluded: 11.75 % TAX",
            ],
        },
        nights=0,
    )

    assert quote is None
