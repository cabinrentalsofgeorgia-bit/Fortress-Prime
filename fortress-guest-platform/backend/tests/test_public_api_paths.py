from __future__ import annotations

from backend.core.public_api_paths import is_public_api_path


def test_public_api_path_rejects_fast_quote_calculate_post() -> None:
    assert is_public_api_path("/api/quotes/calculate", "POST") is False


def test_public_api_path_rejects_fast_quote_calculate_get() -> None:
    assert is_public_api_path("/api/quotes/calculate", "GET") is False


def test_public_api_path_rejects_internal_fast_quote_post() -> None:
    assert is_public_api_path("/api/quote", "POST") is False


def test_public_api_path_allows_guest_quote_lookup() -> None:
    assert (
        is_public_api_path(
            "/api/quotes/123e4567-e89b-12d3-a456-426614174000",
            "GET",
        )
        is True
    )


def test_public_api_path_allows_guest_quote_checkout_lookup() -> None:
    assert (
        is_public_api_path(
            "/api/quotes/123e4567-e89b-12d3-a456-426614174000/checkout",
            "GET",
        )
        is True
    )


def test_public_api_path_allows_streamline_property_catalog() -> None:
    assert is_public_api_path("/api/quotes/streamline/properties", "GET") is True


def test_public_api_path_rejects_quote_collection_listing() -> None:
    assert is_public_api_path("/api/quotes/", "GET") is False


def test_public_api_path_rejects_non_public_quote_post() -> None:
    assert (
        is_public_api_path(
            "/api/quotes/123e4567-e89b-12d3-a456-426614174000/checkout",
            "POST",
        )
        is False
    )


def test_public_api_path_allows_seo_patch_ingest_post() -> None:
    assert is_public_api_path("/api/seo/patches", "POST") is True


def test_public_api_path_allows_seo_patch_ingest_compat_alias_post() -> None:
    assert is_public_api_path("/api/seo-patches/patches", "POST") is True


def test_public_api_path_allows_seo_grade_post() -> None:
    assert (
        is_public_api_path(
            "/api/seo/patches/123e4567-e89b-12d3-a456-426614174000/grade",
            "POST",
        )
        is True
    )


def test_public_api_path_allows_seo_grade_compat_alias_post() -> None:
    assert (
        is_public_api_path(
            "/api/seo-patches/patches/123e4567-e89b-12d3-a456-426614174000/grade",
            "POST",
        )
        is True
    )


def test_public_api_path_rejects_seo_queue_listing() -> None:
    assert is_public_api_path("/api/seo/queue", "GET") is False


def test_public_api_path_allows_local_streamline_swarm_test() -> None:
    assert is_public_api_path("/api/swarm/webhooks/streamline/test", "POST") is True
