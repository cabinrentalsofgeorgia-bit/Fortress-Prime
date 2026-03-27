"""
Redirect Vanguard — sync sovereign-ready cabin slugs to Cloudflare Workers KV.

Edge Worker performs O(1) lookup per /cabins/{slug} request; this module is called
from the SEO deploy consumer after a patch reaches deployed (post-revalidate success).
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from backend.core.config import settings

logger = logging.getLogger(__name__)

KV_VALUE = "1"
CF_API_BASE = "https://api.cloudflare.com/client/v4"


def cabin_slug_from_patch_targets(*, property_slug: str | None, page_path: str) -> str | None:
    """Resolve canonical cabin slug for KV key (lowercase, URL segment)."""
    ps = (property_slug or "").strip().lower()
    if ps:
        return ps
    pp = (page_path or "").strip()
    if not pp.startswith("/cabins/"):
        return None
    rest = pp[len("/cabins/") :].strip("/")
    if not rest or "/" in rest:
        return None
    return rest.lower()


def redirect_vanguard_kv_configured() -> bool:
    return bool(
        settings.cloudflare_api_token.strip()
        and settings.cloudflare_account_id.strip()
        and settings.cloudflare_kv_namespace_deployed_slugs.strip()
    )


def _kv_value_url(key: str) -> str:
    enc = quote(key, safe="")
    ns = settings.cloudflare_kv_namespace_deployed_slugs.strip()
    acct = settings.cloudflare_account_id.strip()
    return f"{CF_API_BASE}/accounts/{acct}/storage/kv/namespaces/{ns}/values/{enc}"


async def upsert_deployed_cabin_slug(slug: str, *, http_client: httpx.AsyncClient | None = None) -> bool:
    """
    Write slug to KV. Returns True on success.
    Best-effort: deploy pipeline must not fail if KV is down — callers treat False as warning.
    """
    normalized = (slug or "").strip().lower()
    if not normalized:
        return False
    if not redirect_vanguard_kv_configured():
        logger.debug("redirect_vanguard_kv_skip_unconfigured slug=%s", normalized)
        return False

    headers = {
        "Authorization": f"Bearer {settings.cloudflare_api_token.strip()}",
        "Content-Type": "text/plain",
    }
    url = _kv_value_url(normalized)

    try:
        if http_client is not None:
            resp = await http_client.put(url, content=KV_VALUE, headers=headers, timeout=15.0)
        else:
            async with httpx.AsyncClient() as client:
                resp = await client.put(url, content=KV_VALUE, headers=headers, timeout=15.0)
        if resp.status_code >= 400:
            logger.warning(
                "redirect_vanguard_kv_upsert_failed slug=%s status=%s body=%s",
                normalized,
                resp.status_code,
                (resp.text or "")[:300],
            )
            return False
        logger.info("redirect_vanguard_kv_upsert_ok slug=%s", normalized)
        return True
    except Exception as exc:
        logger.warning("redirect_vanguard_kv_upsert_error slug=%s err=%s", normalized, exc)
        return False


async def delete_deployed_cabin_slug(slug: str, *, http_client: httpx.AsyncClient | None = None) -> bool:
    """Remove slug from KV (rollback / decommission)."""
    normalized = (slug or "").strip().lower()
    if not normalized or not redirect_vanguard_kv_configured():
        return False
    headers = {"Authorization": f"Bearer {settings.cloudflare_api_token.strip()}"}
    url = _kv_value_url(normalized)
    try:
        if http_client is not None:
            resp = await http_client.delete(url, headers=headers, timeout=15.0)
        else:
            async with httpx.AsyncClient() as client:
                resp = await client.delete(url, headers=headers, timeout=15.0)
        if resp.status_code >= 400 and resp.status_code != 404:
            logger.warning(
                "redirect_vanguard_kv_delete_failed slug=%s status=%s",
                normalized,
                resp.status_code,
            )
            return False
        logger.info("redirect_vanguard_kv_delete_ok slug=%s", normalized)
        return True
    except Exception as exc:
        logger.warning("redirect_vanguard_kv_delete_error slug=%s err=%s", normalized, exc)
        return False
