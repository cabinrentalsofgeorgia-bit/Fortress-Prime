from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.scripts.generate_seo_migration_map import _build_single_testimonial_target, _generate_candidates


def test_testimonial_aliases_move_into_verified_archive_bucket() -> None:
    blueprint = {
        "menus": {},
        "taxonomy": {"terms": []},
        "url_aliases": {
            "records": [
                {
                    "source_path": "node/33",
                    "alias_path": "/testimonial/honeymoon-majestic-lake-cabin",
                }
            ],
            "by_source": {},
        },
        "nodes_by_type": {
            "testimonial": {
                "type_info": {"label": "Testimonial", "description": "node"},
                "nodes": [
                    {
                        "nid": 33,
                        "title": "Honeymoon at Majestic Lake Cabin",
                        "status": 1,
                        "source_path": "node/33",
                        "url_alias": "testimonial/honeymoon-majestic-lake-cabin",
                        "body": "A timeless testimonial body.",
                    }
                ],
            },
            "cabin": {
                "type_info": {"label": "Cabin", "description": "node"},
                "nodes": [
                    {
                        "nid": 99,
                        "title": "Majestic Lake Cabin",
                        "status": 1,
                        "source_path": "node/99",
                        "url_alias": "cabin/blue-ridge/majestic-lake-cabin",
                    }
                ],
            },
        },
    }

    candidates, archive_records, near_misses, orphan_report, metrics = _generate_candidates(
        blueprint,
        next_routes=["/", "/cabins", "/reviews/archive"],
        max_candidates=10,
        min_confidence=0.68,
        monitoring_threshold=0.4,
    )

    assert near_misses == []
    assert orphan_report["orphan_count"] == 0
    assert metrics["verified_archive_recovery"] == {"mapped": 1, "total": 1}
    assert len(candidates) == 1
    assert candidates[0].destination_path == "/reviews/archive/honeymoon-majestic-lake-cabin"
    assert candidates[0].strategy == "testimonial_archive_strategy"
    assert candidates[0].source_type == "testimonial_archive"

    assert len(archive_records) == 1
    record = archive_records[0].payload
    assert record["legacy_node_id"] == "33"
    assert record["original_slug"] == "/testimonial/honeymoon-majestic-lake-cabin"
    assert record["archive_path"] == "/reviews/archive/honeymoon-majestic-lake-cabin"
    assert record["related_property_slug"] == "majestic-lake-cabin"
    assert record["related_property_title"] == "Majestic Lake Cabin"
    assert record["body_status"] == "verified"
    assert record["hmac_signature"]


def test_single_slug_mode_returns_only_requested_testimonial() -> None:
    blueprint = {
        "menus": {},
        "taxonomy": {"terms": []},
        "url_aliases": {
            "records": [
                {
                    "source_path": "node/33",
                    "alias_path": "/testimonial/honeymoon-majestic-lake-cabin",
                },
                {
                    "source_path": "node/34",
                    "alias_path": "/testimonial/family-weekend-river-hideaway",
                },
            ],
            "by_source": {},
        },
        "nodes_by_type": {
            "testimonial": {
                "type_info": {"label": "Testimonial", "description": "node"},
                "nodes": [
                    {
                        "nid": 33,
                        "title": "Honeymoon at Majestic Lake Cabin",
                        "status": 1,
                        "source_path": "node/33",
                        "url_alias": "testimonial/honeymoon-majestic-lake-cabin",
                        "body": "A timeless testimonial body.",
                    },
                    {
                        "nid": 34,
                        "title": "Family weekend at River Hideaway",
                        "status": 1,
                        "source_path": "node/34",
                        "url_alias": "testimonial/family-weekend-river-hideaway",
                        "body": "A family getaway.",
                    },
                ],
            },
            "cabin": {
                "type_info": {"label": "Cabin", "description": "node"},
                "nodes": [
                    {
                        "nid": 99,
                        "title": "Majestic Lake Cabin",
                        "status": 1,
                        "source_path": "node/99",
                        "url_alias": "cabin/blue-ridge/majestic-lake-cabin",
                    }
                ],
            },
        },
    }

    target = _build_single_testimonial_target(blueprint, requested_slug="honeymoon-majestic-lake-cabin")

    assert target is not None
    candidate, archive_record = target
    assert candidate.source_path == "/testimonial/honeymoon-majestic-lake-cabin"
    assert candidate.destination_path == "/reviews/archive/honeymoon-majestic-lake-cabin"
    assert archive_record.slug == "honeymoon-majestic-lake-cabin"
    assert archive_record.payload["title"] == "Honeymoon at Majestic Lake Cabin"


def test_single_slug_mode_can_hydrate_from_global_alias_scan() -> None:
    blueprint = {
        "menus": {},
        "taxonomy": {"terms": []},
        "url_aliases": {
            "records": [
                {
                    "source_path": "node/77",
                    "alias_path": "/honeymoon-cabin",
                    "source_kind": "node",
                }
            ],
            "by_source": {},
        },
        "global_alias_scan": {
            "by_source": {
                "node/77": {
                    "source_kind": "node",
                    "canonical_alias": "/honeymoon-cabin",
                    "aliases": ["/honeymoon-cabin"],
                    "languages": ["und"],
                    "node": {
                        "nid": 77,
                        "title": "Honeymoon Cabin",
                        "status": 1,
                        "source_path": "node/77",
                        "node_type": "romance_story",
                        "body": "Recovered from the global alias scan.",
                    },
                }
            }
        },
        "nodes_by_type": {},
    }

    target = _build_single_testimonial_target(blueprint, requested_slug="honeymoon-cabin")

    assert target is not None
    candidate, archive_record = target
    assert candidate.source_path == "/honeymoon-cabin"
    assert candidate.strategy == "global_alias_archive_strategy"
    assert candidate.reason == "global_alias_hydration"
    assert candidate.node_type == "romance_story"
    assert archive_record.slug == "honeymoon-cabin"
    assert archive_record.payload["legacy_node_id"] == "77"
    assert archive_record.payload["content_body"] == "Recovered from the global alias scan."
