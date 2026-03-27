#!/usr/bin/env python3
"""
Seed sovereign marketing taxonomy and articles from a local JSON export.
"""
from __future__ import annotations

import argparse
import asyncio
import html
import importlib.util
import json
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

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]
DEFAULT_SOURCE_PATH = PROJECT_ROOT / "backend" / "data" / "area_guide.json"

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

from backend.core.database import close_db, get_session_factory

if TYPE_CHECKING:
    from backend.models.content import MarketingArticle as MarketingArticleModel
    from backend.models.content import TaxonomyCategory as TaxonomyCategoryModel


logger = logging.getLogger("seed_local_content")

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

SECTION_KEYS = ("sections", "categories", "data", "items", "groups")
ARTICLE_COLLECTION_KEYS = ("articles", "items", "entries", "posts", "guides", "content")
CATEGORY_NAME_KEYS = ("section_header", "sectionHeader", "header", "title", "name", "category")
ARTICLE_TITLE_KEYS = ("title", "headline", "name")
ARTICLE_BODY_KEYS = (
    "content_body_html",
    "content_body",
    "body_html",
    "body",
    "content",
    "html",
    "text",
    "description",
)
ARTICLE_SLUG_KEYS = ("slug", "archive_slug", "path", "url", "original_slug")
ARTICLE_AUTHOR_KEYS = ("author", "author_name", "byline", "writer")
ARTICLE_PUBLISHED_KEYS = ("published_date", "published_at", "updated_at", "created_at", "date")
CATEGORY_DESCRIPTION_KEYS = ("description", "summary", "intro", "body")
META_TITLE_KEYS = ("meta_title", "seo_title")
META_DESCRIPTION_KEYS = ("meta_description", "seo_description", "excerpt")


def _load_content_models() -> tuple[type["MarketingArticleModel"], type["TaxonomyCategoryModel"]]:
    module_path = PROJECT_ROOT / "backend" / "models" / "content.py"
    module_name = "fortress_seed_content_models"
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
class ArticleSeedPayload:
    title: str
    slug: str
    content_body_html: str
    author: str | None
    published_date: datetime | None
    category_slug: str


@dataclass(slots=True)
class CategorySeedPayload:
    name: str
    slug: str
    description: str | None
    meta_title: str | None
    meta_description: str | None
    articles: list[ArticleSeedPayload]


def configure_logging(*, verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed TaxonomyCategory and MarketingArticle from a local JSON export."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE_PATH,
        help=f"Path to the local JSON export. Defaults to {DEFAULT_SOURCE_PATH}.",
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


def _looks_like_html(value: str) -> bool:
    return bool(re.search(r"<[a-zA-Z][^>]*>", value))


def _to_html_body(value: Any) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    if _looks_like_html(text):
        return text
    paragraphs = [segment.strip() for segment in re.split(r"\n\s*\n", text) if segment.strip()]
    if not paragraphs:
        return None
    return "\n".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs)


def _extract_first(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _as_json_object(value: Any, *, context: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a JSON object")
    normalized: JsonObject = {}
    for key, item in value.items():
        if isinstance(key, str):
            normalized[key] = item
    return normalized


def _as_object_list(value: Any) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    items: list[JsonObject] = []
    for item in value:
        if isinstance(item, Mapping):
            items.append(_as_json_object(item, context="JSON list entry"))
    return items


def _extract_leaf_slug(value: Any) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    stripped = text.strip("/")
    if not stripped:
        return None
    leaf = stripped.rsplit("/", 1)[-1]
    return _slugify(leaf)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)

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

    logger.warning("Unable to parse datetime value %r; storing null", value)
    return None


def _iter_section_objects(payload: JsonValue) -> list[JsonObject]:
    if isinstance(payload, list):
        return _as_object_list(payload)

    if not isinstance(payload, Mapping):
        raise ValueError("area guide payload must be a JSON object or list")

    root = _as_json_object(payload, context="area guide payload")

    for key in SECTION_KEYS:
        nested_list = _as_object_list(root.get(key))
        if nested_list:
            return nested_list

    keyed_sections: list[JsonObject] = []
    for key, value in root.items():
        if key in SECTION_KEYS:
            continue
        articles = _as_object_list(value)
        if articles:
            keyed_sections.append({"section_header": key, "items": articles})
            continue
        if isinstance(value, Mapping):
            nested = _as_json_object(value, context=f"section {key}")
            nested_articles = _as_object_list(_extract_first(nested, ARTICLE_COLLECTION_KEYS))
            if nested_articles:
                nested.setdefault("section_header", key)
                keyed_sections.append(nested)

    if keyed_sections:
        return keyed_sections

    raise ValueError("area guide payload did not expose recognizable section groupings")


def _build_article_payload(
    article_object: JsonObject,
    *,
    category_name: str,
    category_slug: str,
    duplicate_guard: set[str],
) -> ArticleSeedPayload | None:
    title = _normalize_text(_extract_first(article_object, ARTICLE_TITLE_KEYS))
    if not title:
        logger.warning("Skipping article with missing title in category %s", category_name)
        return None

    content_body_html = _to_html_body(_extract_first(article_object, ARTICLE_BODY_KEYS))
    if not content_body_html:
        logger.warning("Skipping article %s: missing body content", title)
        return None

    preferred_slug = _extract_leaf_slug(_extract_first(article_object, ARTICLE_SLUG_KEYS))
    base_slug = preferred_slug or _slugify(title)
    if not base_slug:
        logger.warning("Skipping article %s: unable to derive slug", title)
        return None

    slug = base_slug
    if slug in duplicate_guard:
        slug = _slugify(f"{category_slug}-{title}") or base_slug
    if slug in duplicate_guard:
        suffix = 2
        while f"{slug}-{suffix}" in duplicate_guard:
            suffix += 1
        slug = f"{slug}-{suffix}"
    duplicate_guard.add(slug)

    return ArticleSeedPayload(
        title=title,
        slug=slug,
        content_body_html=content_body_html,
        author=_normalize_text(_extract_first(article_object, ARTICLE_AUTHOR_KEYS)),
        published_date=_parse_datetime(_extract_first(article_object, ARTICLE_PUBLISHED_KEYS)),
        category_slug=category_slug,
    )


def parse_seed_payload(source_path: Path) -> list[CategorySeedPayload]:
    if not source_path.exists():
        raise FileNotFoundError(f"Local content export not found: {source_path}")

    raw = json.loads(source_path.read_text(encoding="utf-8"))
    section_objects = _iter_section_objects(raw)
    payloads: list[CategorySeedPayload] = []
    seen_article_slugs: set[str] = set()

    for section_object in section_objects:
        category_name = _normalize_text(_extract_first(section_object, CATEGORY_NAME_KEYS))
        if not category_name:
            logger.warning("Skipping section with missing header/name")
            continue

        category_slug = _slugify(category_name)
        if not category_slug:
            logger.warning("Skipping section %r: unable to derive slug", category_name)
            continue

        raw_articles = _extract_first(section_object, ARTICLE_COLLECTION_KEYS)
        article_objects = _as_object_list(raw_articles)
        if not article_objects and isinstance(raw_articles, Mapping):
            article_objects = _as_object_list(list(_as_json_object(raw_articles, context=category_name).values()))
        if not article_objects:
            logger.warning("Skipping category %s: no articles found", category_name)
            continue

        articles: list[ArticleSeedPayload] = []
        for article_object in article_objects:
            article_payload = _build_article_payload(
                article_object,
                category_name=category_name,
                category_slug=category_slug,
                duplicate_guard=seen_article_slugs,
            )
            if article_payload is not None:
                articles.append(article_payload)

        if not articles:
            logger.warning("Skipping category %s: all articles were invalid", category_name)
            continue

        description = _normalize_text(_extract_first(section_object, CATEGORY_DESCRIPTION_KEYS))
        meta_title = _normalize_text(_extract_first(section_object, META_TITLE_KEYS)) or category_name
        meta_description = _normalize_text(_extract_first(section_object, META_DESCRIPTION_KEYS)) or description

        payloads.append(
            CategorySeedPayload(
                name=category_name,
                slug=category_slug,
                description=description,
                meta_title=meta_title,
                meta_description=meta_description,
                articles=articles,
            )
        )

    if not payloads:
        raise ValueError(f"No valid categories or articles were found in {source_path}")
    return payloads


async def upsert_categories(
    session: AsyncSession,
    categories: Iterable[CategorySeedPayload],
) -> dict[str, TaxonomyCategory]:
    existing_categories = {
        category.slug: category
        for category in (await session.execute(select(TaxonomyCategory))).scalars().all()
    }

    for payload in categories:
        logger.info("Processing category %s", payload.name)
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


async def upsert_articles(
    session: AsyncSession,
    categories: Sequence[CategorySeedPayload],
    categories_by_slug: Mapping[str, TaxonomyCategory],
) -> tuple[int, int]:
    articles_by_slug = {
        article.slug: article
        for article in (await session.execute(select(MarketingArticle))).scalars().all()
    }
    created = 0
    updated = 0

    for category_payload in categories:
        category = categories_by_slug.get(category_payload.slug)
        if category is None:
            raise RuntimeError(
                f"Article upsert cannot continue because category {category_payload.slug!r} is missing."
            )

        for article_payload in category_payload.articles:
            logger.info("Processing article %s", article_payload.title)
            article = articles_by_slug.get(article_payload.slug)
            if article is None:
                article = MarketingArticle(
                    title=article_payload.title,
                    slug=article_payload.slug,
                    content_body_html=article_payload.content_body_html,
                    author=article_payload.author,
                    published_date=article_payload.published_date,
                    category_id=category.id,
                )
                session.add(article)
                articles_by_slug[article_payload.slug] = article
                created += 1
                continue

            article.title = article_payload.title
            article.content_body_html = article_payload.content_body_html
            article.author = article_payload.author
            article.published_date = article_payload.published_date
            article.category_id = category.id
            updated += 1

    await session.flush()
    return created, updated


async def seed_local_content(source_path: Path) -> int:
    if not os.getenv("POSTGRES_API_URI", "").strip():
        if not LOADED_ENV_FILES:
            raise RuntimeError(
                "POSTGRES_API_URI is not set and no environment files were loaded."
            )
        raise RuntimeError("POSTGRES_API_URI is not set after loading .env files.")

    payloads = parse_seed_payload(source_path)
    session_factory: async_sessionmaker[AsyncSession] = get_session_factory()

    async with session_factory() as session:
        categories_by_slug = await upsert_categories(session, payloads)
        created_articles, updated_articles = await upsert_articles(
            session,
            payloads,
            categories_by_slug,
        )
        await session.commit()

    logger.info(
        "Database seeding complete: categories=%s articles=%s created=%s updated=%s",
        len(payloads),
        sum(len(category.articles) for category in payloads),
        created_articles,
        updated_articles,
    )
    return 0


async def amain(args: argparse.Namespace) -> int:
    try:
        return await seed_local_content(args.source)
    finally:
        await close_db()


def main() -> int:
    args = parse_args()
    configure_logging(verbose=bool(args.verbose))
    return asyncio.run(amain(args))


if __name__ == "__main__":
    raise SystemExit(main())
