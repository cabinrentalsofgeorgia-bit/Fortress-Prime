#!/usr/bin/env python3
"""
Seed seo_rubrics with the Fortress Prime starter rubric set.

Run from fortress-guest-platform/:
    .uv-venv/bin/python3 backend/scripts/seed_seo_rubrics.py

This is idempotent: existing rubrics with matching keyword_cluster are left
untouched (no overwrite unless --force is passed).

Rubrics seeded:
  1. cabin-rentals-blue-ridge-georgia  (canonical property cluster, active)
  2. vacation-rental-north-georgia     (secondary regional cluster, active)

Rules enforced in the rubric_payload:
  - title_rules:       50–65 chars, must include property name + "Blue Ridge"
  - meta_rules:        130–155 chars, must include location signal
  - h1_rules:          unique H1 per page, must include property name
  - content_constraints:  description min 300 words, no thin content
  - alt_tag_rules:     all images must have descriptive alt text ≤ 110 chars
  - jsonld_requirements:  VacationRental + LodgingBusiness schema types required
  - schema_requirements:  LocalBusiness with address, telephone, priceRange
  - canonical_rules:   self-referencing canonical required on every property page
  - quality_checks:    no duplicate meta across properties, no keyword stuffing
  - scoring_dimensions: see weights below
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

load_dotenv()
load_dotenv(REPO_ROOT / ".env")

import argparse
import structlog
from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.models.seo_patch import SEORubric

logger = structlog.get_logger(service="seed_seo_rubrics")

# ---------------------------------------------------------------------------
# Rubric definitions
# ---------------------------------------------------------------------------

RUBRICS = [
    {
        "keyword_cluster": "cabin-rentals-blue-ridge-georgia",
        "source_model": "fortress-seed-v1",
        "min_pass_score": 0.80,
        "status": "active",
        "rubric_payload": {
            "title_rules": {
                "min_chars": 50,
                "max_chars": 65,
                "must_include_signals": ["Blue Ridge", "Georgia"],
                "must_include_property_name": True,
                "forbidden_patterns": ["Cabin Rental Cabin Rental", "Vacation Rental Vacation"],
                "note": "Target keyword must appear within first 30 characters.",
            },
            "meta_rules": {
                "min_chars": 130,
                "max_chars": 155,
                "must_include_location": True,
                "required_location_signals": ["Blue Ridge", "North Georgia", "Georgia"],
                "cta_required": True,
                "cta_examples": ["Book now", "Reserve today", "Check availability"],
                "note": "Must read naturally and include guest benefit statement.",
            },
            "h1_rules": {
                "unique_per_page": True,
                "must_include_property_name": True,
                "max_chars": 80,
                "note": "H1 should differ from title tag.",
            },
            "content_constraints": {
                "description_min_words": 300,
                "description_min_chars": 1500,
                "thin_content_threshold_words": 150,
                "required_sections": [
                    "property overview",
                    "amenities highlights",
                    "location & surroundings",
                    "booking information",
                ],
                "no_duplicate_paragraphs": True,
                "reading_level": "grade 8-10",
                "note": "300-word minimum is a hard requirement. "
                        "Thin content below 150 words triggers automatic rejection.",
            },
            "alt_tag_rules": {
                "required": True,
                "max_chars": 110,
                "must_be_descriptive": True,
                "forbidden_patterns": ["image of", "photo of", "picture of"],
                "note": "Every property image must have a unique, descriptive alt tag.",
            },
            "jsonld_requirements": {
                "required_types": ["VacationRental", "LodgingBusiness"],
                "required_properties": [
                    "name", "description", "image", "address", "priceRange",
                    "numberOfRooms", "amenityFeature", "url",
                ],
                "optional": ["telephone", "checkinTime", "checkoutTime", "petsAllowed"],
                "note": "Schema must be valid JSON-LD, embedded in <script> tags.",
            },
            "schema_requirements": {
                "LocalBusiness": {
                    "required": True,
                    "required_properties": ["name", "address", "telephone", "priceRange"],
                    "address_format": "PostalAddress with streetAddress, addressLocality, addressRegion, postalCode",
                },
                "BreadcrumbList": {
                    "required": True,
                    "note": "For all property detail pages.",
                },
            },
            "canonical_rules": {
                "self_referencing": True,
                "required": True,
                "note": "Every property page must include a self-referencing canonical URL.",
            },
            "quality_checks": {
                "no_duplicate_meta": True,
                "no_keyword_stuffing": True,
                "keyword_density_max_percent": 3.0,
                "no_exact_duplicate_titles": True,
                "no_generic_titles": True,
                "generic_title_patterns": ["Cabin Rental", "Vacation Rental", "Property"],
            },
            "scoring_dimensions": {
                "title_quality": {"weight": 0.20, "pass_threshold": 0.80},
                "meta_quality": {"weight": 0.20, "pass_threshold": 0.80},
                "content_depth": {"weight": 0.25, "pass_threshold": 0.75},
                "schema_completeness": {"weight": 0.20, "pass_threshold": 0.75},
                "alt_tag_coverage": {"weight": 0.10, "pass_threshold": 0.70},
                "uniqueness": {"weight": 0.05, "pass_threshold": 0.90},
            },
            "required_terms": [
                "Blue Ridge",
                "Georgia",
                "cabin",
            ],
            "forbidden_terms": [
                "cheap", "affordable" , "discount",
                "click here", "learn more",
            ],
            "frontier_route": "claude-opus-4-6",
            "preferred_frontier_model": "claude-opus-4-6",
        },
    },
    {
        "keyword_cluster": "vacation-rental-north-georgia",
        "source_model": "fortress-seed-v1",
        "min_pass_score": 0.78,
        "status": "active",
        "rubric_payload": {
            "title_rules": {
                "min_chars": 48,
                "max_chars": 65,
                "must_include_signals": ["North Georgia", "Georgia"],
                "must_include_property_name": True,
            },
            "meta_rules": {
                "min_chars": 130,
                "max_chars": 155,
                "must_include_location": True,
                "required_location_signals": ["North Georgia", "Georgia", "mountains"],
                "cta_required": True,
            },
            "h1_rules": {
                "unique_per_page": True,
                "must_include_property_name": True,
                "max_chars": 80,
            },
            "content_constraints": {
                "description_min_words": 300,
                "description_min_chars": 1500,
                "thin_content_threshold_words": 150,
                "no_duplicate_paragraphs": True,
            },
            "alt_tag_rules": {
                "required": True,
                "max_chars": 110,
                "must_be_descriptive": True,
            },
            "jsonld_requirements": {
                "required_types": ["VacationRental", "LodgingBusiness"],
                "required_properties": [
                    "name", "description", "image", "address", "priceRange",
                ],
            },
            "schema_requirements": {
                "LocalBusiness": {"required": True},
            },
            "canonical_rules": {"self_referencing": True, "required": True},
            "quality_checks": {
                "no_duplicate_meta": True,
                "no_keyword_stuffing": True,
                "keyword_density_max_percent": 3.0,
            },
            "scoring_dimensions": {
                "title_quality": {"weight": 0.20, "pass_threshold": 0.78},
                "meta_quality": {"weight": 0.20, "pass_threshold": 0.78},
                "content_depth": {"weight": 0.25, "pass_threshold": 0.73},
                "schema_completeness": {"weight": 0.20, "pass_threshold": 0.73},
                "alt_tag_coverage": {"weight": 0.10, "pass_threshold": 0.68},
                "uniqueness": {"weight": 0.05, "pass_threshold": 0.88},
            },
            "required_terms": ["North Georgia", "cabin"],
            "forbidden_terms": ["cheap", "affordable", "discount", "click here"],
            "frontier_route": "claude-opus-4-6",
            "preferred_frontier_model": "claude-opus-4-6",
        },
    },
]


async def seed(*, force: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        for rubric_def in RUBRICS:
            cluster = rubric_def["keyword_cluster"]

            existing = (
                await db.execute(
                    select(SEORubric).where(SEORubric.keyword_cluster == cluster)
                )
            ).scalar_one_or_none()

            if existing and not force:
                logger.info(
                    "seo_rubric_already_exists",
                    keyword_cluster=cluster,
                    id=str(existing.id),
                    status=existing.status,
                )
                continue

            if existing and force:
                existing.rubric_payload = rubric_def["rubric_payload"]  # type: ignore[assignment]
                existing.source_model = rubric_def["source_model"]  # type: ignore[assignment]
                existing.min_pass_score = rubric_def["min_pass_score"]  # type: ignore[assignment]
                existing.status = rubric_def["status"]  # type: ignore[assignment]
                logger.info("seo_rubric_updated", keyword_cluster=cluster, id=str(existing.id))
            else:
                rubric = SEORubric(
                    keyword_cluster=rubric_def["keyword_cluster"],
                    source_model=rubric_def["source_model"],
                    min_pass_score=rubric_def["min_pass_score"],
                    status=rubric_def["status"],
                    rubric_payload=rubric_def["rubric_payload"],
                )
                db.add(rubric)
                logger.info("seo_rubric_created", keyword_cluster=cluster)

        await db.commit()
        logger.info("seo_rubrics_seeded", count=len(RUBRICS))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed SEO rubrics into fortress_shadow.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing rubrics with matching keyword_cluster.",
    )
    args = parser.parse_args()
    asyncio.run(seed(force=args.force))


if __name__ == "__main__":
    main()
