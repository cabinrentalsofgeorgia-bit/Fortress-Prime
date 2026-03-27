#!/usr/bin/env python3
"""
Import legacy Drupal content exports into sovereign content tables.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import select


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
from backend.models.content import MarketingArticle, TaxonomyCategory


logger = logging.getLogger("import_legacy_content")

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None
Row = dict[str, Any]


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import sovereign content from Drupal CSV/JSON exports."
    )
    parser.add_argument(
        "--categories",
        type=Path,
        help="Path to category/taxonomy export (CSV or JSON).",
    )
    parser.add_argument(
        "--articles",
        type=Path,
        help="Path to article export (CSV or JSON).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()
    if args.categories is None and args.articles is None:
        parser.error("at least one of --categories or --articles is required")
    return args


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_slug(value: Any) -> str | None:
    text = _normalize_text(value)
    return text.lower() if text else None


def _read_json_records(path: Path) -> list[Row]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        for key in ("items", "rows", "categories", "articles", "data"):
            candidate = raw.get(key)
            if isinstance(candidate, list):
                items = candidate
                break
        else:
            raise ValueError(f"{path} JSON must contain a list payload or a known list key")
    else:
        raise ValueError(f"{path} JSON payload must be an object or list")

    records: list[Row] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            logger.warning("skipping non-object JSON row %s from %s", index, path)
            continue
        records.append(dict(item))
    return records


def _read_csv_records(path: Path) -> list[Row]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path} CSV is missing a header row")
        return [dict(row) for row in reader]


def load_records(path: Path) -> list[Row]:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist")
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _read_json_records(path)
    if suffix == ".csv":
        return _read_csv_records(path)
    raise ValueError(f"{path} must be .csv or .json")


def parse_datetime(value: Any) -> datetime | None:
    text = _normalize_text(value)
    if not text:
        return None

    candidate_values = [
        text,
        text.replace("Z", "+00:00"),
    ]
    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
    )

    for candidate in candidate_values:
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass

        for fmt in formats:
            try:
                parsed = datetime.strptime(candidate, fmt)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                continue

    raise ValueError(f"could not parse published_date value {text!r}")


async def load_category_map() -> dict[str, TaxonomyCategory]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(TaxonomyCategory))
        categories = result.scalars().all()
    return {category.slug: category for category in categories}


async def import_categories(path: Path) -> tuple[int, int, int]:
    records = load_records(path)
    created = 0
    updated = 0
    skipped = 0

    async with AsyncSessionLocal() as session:
        existing_categories = {
            category.slug: category
            for category in (await session.execute(select(TaxonomyCategory))).scalars().all()
        }

        for index, row in enumerate(records, start=1):
            slug = _normalize_slug(row.get("slug"))
            name = _normalize_text(row.get("name"))
            if not slug:
                skipped += 1
                logger.warning("skipping category row %s: missing slug", index)
                continue
            if not name:
                skipped += 1
                logger.warning("skipping category row %s (%s): missing name", index, slug)
                continue

            category = existing_categories.get(slug)
            if category is None:
                category = TaxonomyCategory(
                    name=name,
                    slug=slug,
                    description=_normalize_text(row.get("description")),
                    meta_title=_normalize_text(row.get("meta_title")),
                    meta_description=_normalize_text(row.get("meta_description")),
                )
                session.add(category)
                existing_categories[slug] = category
                created += 1
            else:
                category.name = name
                category.description = _normalize_text(row.get("description"))
                category.meta_title = _normalize_text(row.get("meta_title"))
                category.meta_description = _normalize_text(row.get("meta_description"))
                updated += 1

        await session.commit()

    logger.info(
        "category import complete from %s: created=%s updated=%s skipped=%s",
        path,
        created,
        updated,
        skipped,
    )
    return created, updated, skipped


async def import_articles(path: Path) -> tuple[int, int, int]:
    records = load_records(path)
    created = 0
    updated = 0
    skipped = 0

    async with AsyncSessionLocal() as session:
        categories_by_slug = {
            category.slug: category
            for category in (await session.execute(select(TaxonomyCategory))).scalars().all()
        }
        articles_by_slug = {
            article.slug: article
            for article in (await session.execute(select(MarketingArticle))).scalars().all()
        }

        for index, row in enumerate(records, start=1):
            slug = _normalize_slug(row.get("slug"))
            title = _normalize_text(row.get("title"))
            content_body_html = _normalize_text(row.get("content_body_html"))
            category_slug = _normalize_slug(row.get("category_slug"))

            if not slug:
                skipped += 1
                logger.warning("skipping article row %s: missing slug", index)
                continue
            if not title:
                skipped += 1
                logger.warning("skipping article row %s (%s): missing title", index, slug)
                continue
            if not content_body_html:
                skipped += 1
                logger.warning(
                    "skipping article row %s (%s): missing content_body_html",
                    index,
                    slug,
                )
                continue
            if not category_slug:
                skipped += 1
                logger.warning(
                    "skipping article row %s (%s): missing category_slug",
                    index,
                    slug,
                )
                continue

            category = categories_by_slug.get(category_slug)
            if category is None:
                skipped += 1
                logger.warning(
                    "skipping article row %s (%s): category_slug %s not found",
                    index,
                    slug,
                    category_slug,
                )
                continue

            try:
                published_date = parse_datetime(row.get("published_date"))
            except ValueError as exc:
                skipped += 1
                logger.warning("skipping article row %s (%s): %s", index, slug, exc)
                continue

            article = articles_by_slug.get(slug)
            if article is None:
                article = MarketingArticle(
                    title=title,
                    slug=slug,
                    content_body_html=content_body_html,
                    author=_normalize_text(row.get("author")),
                    published_date=published_date,
                    category_id=category.id,
                )
                session.add(article)
                articles_by_slug[slug] = article
                created += 1
            else:
                article.title = title
                article.content_body_html = content_body_html
                article.author = _normalize_text(row.get("author"))
                article.published_date = published_date
                article.category_id = category.id
                updated += 1

        await session.commit()

    logger.info(
        "article import complete from %s: created=%s updated=%s skipped=%s",
        path,
        created,
        updated,
        skipped,
    )
    return created, updated, skipped


async def amain(args: argparse.Namespace) -> int:
    if not os.getenv("POSTGRES_API_URI", "").strip():
        if not LOADED_ENV_FILES:
            raise RuntimeError(
                "POSTGRES_API_URI is not set and no environment files were loaded."
            )
        raise RuntimeError("POSTGRES_API_URI is not set after loading .env files.")

    if args.categories is not None:
        await import_categories(args.categories)

    if args.articles is not None:
        await import_articles(args.articles)

    return 0


def main() -> int:
    args = parse_args()
    configure_logging(verbose=bool(args.verbose))
    try:
        return asyncio.run(amain(args))
    finally:
        asyncio.run(close_db())


if __name__ == "__main__":
    raise SystemExit(main())
