from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.services.sovereign_archive import build_signed_archive_record


def test_signed_archive_record_uses_canonical_payload_shape() -> None:
    record = build_signed_archive_record(
        legacy_node_id=33,
        original_slug="/testimonial/honeymoon-majestic-lake-cabin",
        content_body="A timeless testimonial body.",
        category_tags=["Lake Blue Ridge", "Blue Ridge"],
        title="Honeymoon at Majestic Lake Cabin",
        archive_slug="honeymoon-majestic-lake-cabin",
        archive_path="/reviews/archive/honeymoon-majestic-lake-cabin",
        source_ref="node/33",
        legacy_type="review",
        related_property_slug="majestic-lake-cabin",
        related_property_path="/cabins/majestic-lake-cabin",
        related_property_title="Majestic Lake Cabin",
        signed_at="2026-03-19T12:00:00Z",
        secret="spark-secret",
    )

    expected_payload = {
        "archive_path": "/reviews/archive/honeymoon-majestic-lake-cabin",
        "archive_slug": "honeymoon-majestic-lake-cabin",
        "body_status": "verified",
        "category_tags": ["Blue Ridge", "Lake Blue Ridge"],
        "content_body": "A timeless testimonial body.",
        "legacy_type": "review",
        "legacy_node_id": "33",
        "node_type": "testimonial",
        "original_slug": "/testimonial/honeymoon-majestic-lake-cabin",
        "related_property_path": "/cabins/majestic-lake-cabin",
        "related_property_slug": "majestic-lake-cabin",
        "related_property_title": "Majestic Lake Cabin",
        "signed_at": "2026-03-19T12:00:00Z",
        "source_ref": "node/33",
        "title": "Honeymoon at Majestic Lake Cabin",
    }
    expected_sig = hmac.new(
        b"spark-secret",
        json.dumps(expected_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert record == {**expected_payload, "hmac_signature": expected_sig}
