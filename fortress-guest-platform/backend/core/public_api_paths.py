"""
Explicit public API path rules for GlobalAuthMiddleware.
"""

from __future__ import annotations

import re

PUBLIC_PATH_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
    "/ws",
    "/webhooks/",
    "/dashboard",
    "/guestbook",
    "/portal/",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/sso",
    "/api/auth/command-center-url",
    "/api/auth/owner/request-magic-link",
    "/api/auth/owner/verify-magic-link",
    "/api/auth/owner/logout",
    "/api/guest-portal/",
    "/api/guestbook/",
    "/api/agreements/public/",
    "/api/direct-booking/availability",
    "/api/direct-booking/quote",
    "/api/direct-booking/signed-quote",
    "/api/direct-booking/properties",
    "/api/quotes/streamline/properties",
    "/api/seo/live/",
    "/api/seo-patches/live/",
    "/api/seo-remaps/grade-results",
    "/api/checkout/",
    "/api/copilot-queue/",
    "/api/vrs/automations/",
    "/api/direct-booking/property/",
    "/api/direct-booking/fleet/",
    "/api/direct-booking/book",
    "/api/direct-booking/confirm-hold",
    "/api/direct-booking/config",
    "/api/system/health/",
    "/api/system/nodes/",
    "/api/vrs/system-pulse",
    "/api/vrs/leads/",
    "/api/webhooks/",
    "/api/dispatch/",
    "/api/internal/deck-key",
    "/api/intelligence/projection/",
    "/api/v1/history/restore/",
    "/api/swarm/financial/",
    "/api/swarm/webhooks/streamline/test",
    "/api/paperclip/",
    "/api/chat/concierge",
    "/api/content/",
    "/api/storefront/intent/",
    "/api/storefront/concierge/",
)

_UUID_PATH_SEGMENT = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_PUBLIC_QUOTE_PATTERNS = (
    re.compile(rf"^/api/quotes/{_UUID_PATH_SEGMENT}$"),
    re.compile(rf"^/api/quotes/{_UUID_PATH_SEGMENT}/checkout$"),
)
_PUBLIC_METHOD_PATTERNS = (
    ("POST", re.compile(r"^/api/seo/patches$")),
    ("POST", re.compile(r"^/api/seo-patches/patches$")),
    ("POST", re.compile(rf"^/api/seo/patches/{_UUID_PATH_SEGMENT}/rewrite$")),
    ("POST", re.compile(rf"^/api/seo-patches/patches/{_UUID_PATH_SEGMENT}/rewrite$")),
    ("POST", re.compile(rf"^/api/seo/patches/{_UUID_PATH_SEGMENT}/grade$")),
    ("POST", re.compile(rf"^/api/seo-patches/patches/{_UUID_PATH_SEGMENT}/grade$")),
    ("GET", re.compile(r"^/api/seo/rubrics$")),
    ("POST", re.compile(r"^/api/seo/rubrics$")),
    ("GET", re.compile(r"^/api/seo-patches/rubrics$")),
    ("POST", re.compile(r"^/api/seo-patches/rubrics$")),
)


def is_public_api_path(path: str, method: str) -> bool:
    if any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES):
        return True

    if any(public_method == method and pattern.match(path) for public_method, pattern in _PUBLIC_METHOD_PATTERNS):
        return True

    if method == "GET":
        return any(pattern.match(path) for pattern in _PUBLIC_QUOTE_PATTERNS)

    return False
