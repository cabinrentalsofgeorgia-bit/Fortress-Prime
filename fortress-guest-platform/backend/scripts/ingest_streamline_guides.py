#!/usr/bin/env python3
"""
Pull RueBaRue area guide content from the live vendor API into sovereign content tables.
"""
from __future__ import annotations

import argparse
import asyncio
import html
import importlib.util
import logging
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, TypeAlias, cast
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]

for candidate in (PROJECT_ROOT, REPO_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)


def load_environment() -> list[Path]:
    loaded_files: list[Path] = []
    env_files = [
        REPO_ROOT / ".env",
        PROJECT_ROOT / ".env",
        REPO_ROOT / ".env.security",
    ]
    for env_file in env_files:
        if env_file.exists():
            load_dotenv(env_file, override=True)
            loaded_files.append(env_file)
    return loaded_files


LOADED_ENV_FILES = load_environment()

from backend.core.database import AsyncSessionLocal, close_db

if TYPE_CHECKING:
    from backend.models.content import MarketingArticle as MarketingArticleModel
    from backend.models.content import TaxonomyCategory as TaxonomyCategoryModel


logger = logging.getLogger("ingest_streamline_guides")

RUEBARUE_DESTINATIONS_ENDPOINT_DEFAULT = "https://api.staging.ruebarue.com/beta/api/v2/destinations"
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


def _load_content_models() -> tuple[type["MarketingArticleModel"], type["TaxonomyCategoryModel"]]:
    module_path = PROJECT_ROOT / "backend" / "models" / "content.py"
    module_name = "fortress_content_models"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load content models from {module_path}.")
    module = cast(ModuleType, importlib.util.module_from_spec(spec))
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    marketing_article = getattr(module, "MarketingArticle", None)
    taxonomy_category = getattr(module, "TaxonomyCategory", None)
    if not isinstance(marketing_article, type) or not isinstance(taxonomy_category, type):
        raise RuntimeError("content.py did not expose MarketingArticle and TaxonomyCategory.")
    return (
        cast(type["MarketingArticleModel"], marketing_article),
        cast(type["TaxonomyCategoryModel"], taxonomy_category),
    )


MarketingArticle, TaxonomyCategory = _load_content_models()


@dataclass(slots=True)
class GuideCategoryPayload:
    name: str
    slug: str
    description: str | None
    meta_title: str | None
    meta_description: str | None


@dataclass(slots=True)
class GuideArticlePayload:
    title: str
    slug: str
    content_body_html: str
    author: str | None
    published_date: datetime | None
    category_slug: str


def configure_logging(*, verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pull RueBaRue area guides from the live vendor API and upsert them into sovereign content tables."
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        help="Absolute https URL for the RueBaRue destinations endpoint. Defaults to the discovered /api/v2/destinations route.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    text = str(value).strip()
    return text or None


def _slugify(value: Any) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or None


def _extract_first(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _parse_datetime(value: Any) -> datetime | None:
    text = _normalize_text(value)
    if not text:
        return None

    candidates = (text, text.replace("Z", "+00:00"))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=UTC)
        except ValueError:
            continue

    raise ValueError(f"could not parse datetime value {text!r}")


def _normalize_json_object(value: Any, *, context: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a JSON object")
    normalized: JsonObject = {}
    for key, item in value.items():
        if isinstance(key, str):
            normalized[key] = item
    return normalized


def _resolve_guides_endpoint(endpoint_override: str | None = None) -> str:
    endpoint = (endpoint_override or "").strip() or os.getenv(
        "STREAMLINE_GUIDES_ENDPOINT",
        RUEBARUE_DESTINATIONS_ENDPOINT_DEFAULT,
    ).strip()
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("The guides endpoint must be an absolute http(s) URL.")
    return endpoint.rstrip("/")


def _derive_api_base(destinations_endpoint: str) -> str:
    marker = "/destinations"
    if marker not in destinations_endpoint:
        raise RuntimeError("The guides endpoint must target the RueBaRue /destinations resource.")
    return destinations_endpoint.split(marker, 1)[0]


def _ruebarue_credentials() -> tuple[str, str]:
    email = os.getenv("RUEBARUE_USERNAME", "").strip()
    password = os.getenv("RUEBARUE_PASSWORD", "").strip()
    if not email or not password:
        raise RuntimeError("RUEBARUE_USERNAME and RUEBARUE_PASSWORD must be set before ingestion.")
    return email, password


def _request_headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Origin": "https://app.ruebarue.com",
        "Referer": "https://app.ruebarue.com/",
    }


async def _authenticate(client: httpx.AsyncClient, api_base: str) -> JsonObject:
    email, password = _ruebarue_credentials()
    response = await client.post(
        f"{api_base}/auth/login",
        data={"email": email, "password": password},
    )
    if response.status_code == 401:
        raise RuntimeError("RueBaRue authentication failed: invalid email or password.")
    response.raise_for_status()

    token = client.cookies.get("api_token")
    if token:
        client.headers["Authorization"] = f"Bearer {token}"

    current_response = await client.get(f"{api_base}/auth/current")
    current_response.raise_for_status()
    return _normalize_json_object(current_response.json(), context="RueBaRue auth current response")


async def fetch_streamline_guides(endpoint_override: str | None = None) -> JsonObject:
    endpoint = _resolve_guides_endpoint(endpoint_override)
    api_base = _derive_api_base(endpoint)
    logger.info("Fetching from API...")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=True,
        headers=_request_headers(),
    ) as client:
        auth_current = await _authenticate(client, api_base)

        destinations_response = await client.get(endpoint)
        destinations_response.raise_for_status()
        destinations_payload = destinations_response.json()
        if not isinstance(destinations_payload, list):
            raise ValueError("RueBaRue /destinations did not return a list payload.")

        detailed_destinations: list[JsonObject] = []
        for raw_destination in destinations_payload:
            if not isinstance(raw_destination, Mapping):
                continue
            destination = _normalize_json_object(raw_destination, context="RueBaRue destination")
            destination_id = _extract_first(destination, ("destination_id", "id"))
            if destination_id is None:
                continue
            detail_response = await client.get(f"{endpoint}/{destination_id}")
            detail_response.raise_for_status()
            detail_payload = detail_response.json()
            if isinstance(detail_payload, Mapping):
                detailed_destinations.append(
                    _normalize_json_object(detail_payload, context=f"RueBaRue destination {destination_id}")
                )

    return {
        "auth_current": auth_current,
        "destinations": detailed_destinations,
    }


def _extract_destination_tabs(payload: JsonObject) -> dict[str, str]:
    user = payload.get("user")
    settings_container = user if isinstance(user, Mapping) else payload
    settings = settings_container.get("settings") if isinstance(settings_container, Mapping) else None
    if not isinstance(settings, Mapping):
        return {}

    tabs_raw = settings.get("destination_tabs")
    tab_order_raw = settings.get("destination", {})
    if isinstance(tab_order_raw, Mapping):
        order_value = _normalize_text(tab_order_raw.get("tab_order"))
        order = [item.strip() for item in order_value.split(",")] if order_value else []
    else:
        order = []

    tabs_by_type: dict[str, str] = {}
    if isinstance(tabs_raw, list):
        for raw_tab in tabs_raw:
            if not isinstance(raw_tab, Mapping):
                continue
            tab_type = _normalize_text(raw_tab.get("type"))
            label = _normalize_text(raw_tab.get("label"))
            if tab_type and label:
                tabs_by_type[tab_type] = label

    if not order:
        return tabs_by_type

    ordered_tabs: dict[str, str] = {}
    for tab_type in order:
        label = tabs_by_type.get(tab_type)
        if label:
            ordered_tabs[tab_type] = label
    for tab_type, label in tabs_by_type.items():
        ordered_tabs.setdefault(tab_type, label)
    return ordered_tabs


def _normalize_area_name(name: str) -> str:
    normalized = name.strip()
    normalized = re.sub(r",\s*ga$", "", normalized, flags=re.IGNORECASE)
    return normalized


def _format_text_html(value: str | None) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    if "<" in text and ">" in text:
        return text
    return f"<p>{html.escape(text)}</p>"


def _public_asset_url(value: str | None) -> str | None:
    url = _normalize_text(value)
    if not url:
        return None
    return (
        url.replace("http://uploads.ruebarue.com", "https://public.ruebarue.com")
        .replace("https://uploads.ruebarue.com", "https://public.ruebarue.com")
        .replace(
            "https://s3.us-east-2.amazonaws.com/uploads.ruebarue.com",
            "https://public.ruebarue.com",
        )
    )


def _build_recommendation_html(recommendation: Mapping[str, Any]) -> str | None:
    sections: list[str] = []

    body_html = _format_text_html(_extract_first(recommendation, ("body", "tip", "description")))
    if body_html:
        sections.append(body_html)

    address = _normalize_text(recommendation.get("address"))
    if address:
        sections.append(f"<p><strong>Address:</strong> {html.escape(address)}</p>")

    external_link = _normalize_text(recommendation.get("external_link"))
    if external_link:
        escaped_link = html.escape(external_link, quote=True)
        sections.append(
            f'<p><a href="{escaped_link}" target="_blank" rel="noopener noreferrer">{html.escape(external_link)}</a></p>'
        )

    start_date = _normalize_text(recommendation.get("start_date"))
    end_date = _normalize_text(recommendation.get("end_date"))
    if start_date or end_date:
        label = " - ".join(value for value in (start_date, end_date) if value)
        sections.append(f"<p><strong>Event Window:</strong> {html.escape(label)}</p>")

    attachments = recommendation.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, Mapping):
                continue
            attachment_type = _normalize_text(attachment.get("type"))
            attachment_url = _public_asset_url(_extract_first(attachment, ("url", "attachment_url")))
            if attachment_type == "image" and attachment_url:
                sections.append(
                    f'<p><img src="{html.escape(attachment_url, quote=True)}" alt="{html.escape(_normalize_text(recommendation.get("name")) or "Guide image")}" /></p>'
                )

    if not sections:
        return None
    return "\n".join(sections)


def parse_streamline_guides_payload(
    payload: JsonObject,
) -> tuple[list[GuideCategoryPayload], list[GuideArticlePayload]]:
    auth_current_raw = payload.get("auth_current")
    destinations_raw = payload.get("destinations")
    auth_current = (
        _normalize_json_object(auth_current_raw, context="RueBaRue auth payload")
        if isinstance(auth_current_raw, Mapping)
        else {}
    )
    if not isinstance(destinations_raw, list):
        raise ValueError("RueBaRue destinations payload is missing the destinations list.")

    tab_labels = _extract_destination_tabs(auth_current)
    categories_by_slug: dict[str, GuideCategoryPayload] = {}
    articles_by_slug: dict[str, GuideArticlePayload] = {}

    for raw_destination in destinations_raw:
        if not isinstance(raw_destination, Mapping):
            continue
        destination = _normalize_json_object(raw_destination, context="RueBaRue destination detail")
        destination_name = _normalize_text(_extract_first(destination, ("name", "title")))
        destination_id = _normalize_text(_extract_first(destination, ("destination_id", "id")))
        if not destination_name:
            continue

        normalized_destination_name = _normalize_area_name(destination_name)
        destination_slug = _slugify(normalized_destination_name) or _slugify(destination_id)
        if not destination_slug:
            continue

        destination_description = _normalize_text(_extract_first(destination, ("address", "description")))
        recommendations = destination.get("recommendations")
        if not isinstance(recommendations, list):
            continue

        for raw_recommendation in recommendations:
            if not isinstance(raw_recommendation, Mapping):
                continue
            recommendation = _normalize_json_object(
                raw_recommendation,
                context=f"RueBaRue recommendation for {destination_slug}",
            )
            title = _normalize_text(_extract_first(recommendation, ("name", "title", "headline")))
            if not title:
                continue

            tab_type = _normalize_text(_extract_first(recommendation, ("tab_id", "tab_type")))
            section_label = (
                tab_labels.get(tab_type or "")
                or _normalize_text(_extract_first(recommendation, ("section", "category", "display_as")))
                or "General"
            )
            section_slug = _slugify(section_label) or "general"
            category_name = f"{normalized_destination_name} {section_label}"
            category_slug = _slugify(f"{destination_slug}-{section_slug}") or section_slug

            categories_by_slug.setdefault(
                category_slug,
                GuideCategoryPayload(
                    name=category_name,
                    slug=category_slug,
                    description=destination_description,
                    meta_title=f"{category_name} | Cabin Rentals of Georgia",
                    meta_description=destination_description
                    or f"RueBaRue recommendations for {category_name}.",
                ),
            )

            content_body_html = _build_recommendation_html(recommendation)
            if not content_body_html:
                continue

            recommendation_id = _normalize_text(_extract_first(recommendation, ("recommendation_id", "id")))
            article_slug = (
                _slugify(f"{category_slug}-{title}")
                or _slugify(title)
                or recommendation_id
                or f"{category_slug}-guide"
            )
            if article_slug in articles_by_slug and recommendation_id:
                article_slug = f"{article_slug}-{recommendation_id}"

            updated_value = _extract_first(recommendation, ("updated_at", "created_at"))
            if updated_value is None:
                updated_value = _extract_first(destination, ("updated_at", "created_at"))
            try:
                published_date = _parse_datetime(updated_value)
            except ValueError:
                published_date = None

            articles_by_slug[article_slug] = GuideArticlePayload(
                title=title,
                slug=article_slug,
                content_body_html=content_body_html,
                author="RueBaRue",
                published_date=published_date,
                category_slug=category_slug,
            )

    if not categories_by_slug and not articles_by_slug:
        raise ValueError("RueBaRue payload did not expose any recognizable categories or guides.")

    return list(categories_by_slug.values()), list(articles_by_slug.values())


async def upsert_categories(
    session: AsyncSession,
    categories: Iterable[GuideCategoryPayload],
) -> dict[str, TaxonomyCategory]:
    existing_categories = {
        category.slug: category
        for category in (await session.execute(select(TaxonomyCategory))).scalars().all()
    }

    for payload in categories:
        logger.info("Upserting Category %s", payload.slug)
        category = existing_categories.get(payload.slug)
        if category is None:
            category = TaxonomyCategory(
                name=payload.name,
                slug=payload.slug,
                description=payload.description,
                meta_title=payload.meta_title,
                meta_description=payload.meta_description,
            )
            session.add(category)
            existing_categories[payload.slug] = category
            await session.flush()
            continue

        category.name = payload.name
        category.description = payload.description
        category.meta_title = payload.meta_title
        category.meta_description = payload.meta_description

    await session.flush()
    return existing_categories


async def upsert_guides(
    session: AsyncSession,
    guides: Iterable[GuideArticlePayload],
    categories_by_slug: Mapping[str, TaxonomyCategory],
) -> tuple[int, int]:
    articles_by_slug = {
        article.slug: article
        for article in (await session.execute(select(MarketingArticle))).scalars().all()
    }

    created = 0
    updated = 0
    for payload in guides:
        category = categories_by_slug.get(payload.category_slug)
        if category is None:
            raise RuntimeError(
                f"Guide {payload.slug} references unknown category slug {payload.category_slug!r}."
            )

        article = articles_by_slug.get(payload.slug)
        if article is None:
            article = MarketingArticle(
                title=payload.title,
                slug=payload.slug,
                content_body_html=payload.content_body_html,
                author=payload.author,
                published_date=payload.published_date,
                category_id=category.id,
            )
            session.add(article)
            articles_by_slug[payload.slug] = article
            created += 1
            continue

        article.title = payload.title
        article.content_body_html = payload.content_body_html
        article.author = payload.author
        article.published_date = payload.published_date
        article.category_id = category.id
        updated += 1

    await session.flush()
    return created, updated


async def ingest_streamline_guides(endpoint_override: str | None = None) -> int:
    if not os.getenv("POSTGRES_API_URI", "").strip():
        if not LOADED_ENV_FILES:
            raise RuntimeError(
                "POSTGRES_API_URI is not set and no environment files were loaded."
            )
        raise RuntimeError("POSTGRES_API_URI is not set after loading .env files.")

    payload = await fetch_streamline_guides(endpoint_override)
    categories, guides = parse_streamline_guides_payload(payload)

    async with AsyncSessionLocal() as session:
        categories_by_slug = await upsert_categories(session, categories)
        created, updated = await upsert_guides(session, guides, categories_by_slug)
        await session.commit()

    logger.info(
        "Complete. categories=%s guides=%s created=%s updated=%s",
        len(categories),
        len(guides),
        created,
        updated,
    )
    return 0


async def amain(args: argparse.Namespace) -> int:
    try:
        return await ingest_streamline_guides(args.endpoint)
    finally:
        await close_db()


def main() -> int:
    args = parse_args()
    configure_logging(verbose=bool(args.verbose))
    return asyncio.run(amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
