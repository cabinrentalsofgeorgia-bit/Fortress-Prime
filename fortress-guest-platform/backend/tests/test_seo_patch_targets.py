from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.api.seo_patches import SeoProposalRequest, _source_hash


def _proposal_kwargs() -> dict:
    return {
        "target_keyword": "blue ridge cabin rentals",
        "proposal": {
            "title": "Optimized Title",
            "meta_description": "Optimized description",
            "h1": "Optimized H1",
            "intro": "Optimized intro",
            "faq": [],
            "json_ld": {},
        },
        "grading": {
            "overall": 92,
            "breakdown": {"ctr": 90},
        },
    }


def test_archive_review_request_requires_target_slug_and_normalizes_fields() -> None:
    request = SeoProposalRequest(
        target_type="ARCHIVE_REVIEW",
        target_slug="Honeymoon-Majestic-Lake-Cabin",
        **_proposal_kwargs(),
    )

    assert request.target_type == "archive_review"
    assert request.target_slug == "honeymoon-majestic-lake-cabin"
    assert request.property_id is None


def test_property_request_accepts_target_slug_alias() -> None:
    request = SeoProposalRequest(
        target_type="property",
        target_slug="Majestic-Lake-Cabin",
        **_proposal_kwargs(),
    )

    assert request.target_type == "property"
    assert request.target_slug == "majestic-lake-cabin"


def test_source_hash_includes_target_identity() -> None:
    source_snapshot = {"facts": ["verified"]}

    property_hash = _source_hash(
        target_type="property",
        target_slug="majestic-lake-cabin",
        campaign="default",
        rubric_version="v1",
        source_snapshot=source_snapshot,
    )
    archive_hash = _source_hash(
        target_type="archive_review",
        target_slug="majestic-lake-cabin",
        campaign="default",
        rubric_version="v1",
        source_snapshot=source_snapshot,
    )

    assert property_hash != archive_hash
