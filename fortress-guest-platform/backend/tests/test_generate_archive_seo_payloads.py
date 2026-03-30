from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.scripts.generate_archive_seo_payloads import (
    ArchiveRecord,
    GeneratorConfig,
    _build_api_request,
    _build_sql_upsert,
    _extract_json_object,
    _normalize_chat_completions_url,
    _normalize_generated_proposal,
)


def _record() -> ArchiveRecord:
    return ArchiveRecord(
        source_file=Path("/tmp/honeymoon.json"),
        legacy_node_id="33",
        original_slug="/testimonial/honeymoon-majestic-lake-cabin",
        archive_slug="honeymoon-majestic-lake-cabin",
        archive_path="/reviews/archive/honeymoon-majestic-lake-cabin",
        title="Honeymoon at Majestic Lake Cabin",
        content_body="<p>We loved the view from Majestic Lake Cabin and cannot wait to return.</p>",
        body_status="verified",
        category_tags=["Lake Blue Ridge"],
        node_type="testimonial",
        signed_at="2026-03-20T02:08:03Z",
        hmac_signature="abc123",
        related_property_slug="blue-ridge-lake-retreat",
        related_property_path="/cabins/blue-ridge-lake-retreat",
        related_property_title="Blue Ridge Lake Retreat",
    )


def _config() -> GeneratorConfig:
    return GeneratorConfig(
        archive_dir=Path("/tmp"),
        output_path=Path("/tmp/out.json"),
        sql_output_path=Path("/tmp/out.sql"),
        api_base_url="http://127.0.0.1:8100",
        chat_completions_url="http://127.0.0.1:9000/v1/chat/completions",
        model="nemotron-test",
        campaign="archive_restore_2026",
        rubric_version="nemotron_archive_v1",
        proposed_by="dgx-nemotron",
        run_id="run-123",
        concurrency=2,
        limit=1,
        only_slug="honeymoon-majestic-lake-cabin",
        post_api=False,
        dry_run=True,
        swarm_api_key="",
        system_message="system",
        temperature=0.2,
        max_tokens=1800,
        client_cert=None,
        client_key=None,
        verify_ssl=False,
        force_json_response=True,
        disable_thinking=False,
        db_resume=False,
        write_db=False,
        connect_timeout_s=10.0,
        read_timeout_s=60.0,
        write_timeout_s=60.0,
        pool_timeout_s=60.0,
    )


def test_normalize_chat_completions_url_appends_expected_suffix() -> None:
    assert _normalize_chat_completions_url("http://127.0.0.1:9000/v1") == "http://127.0.0.1:9000/v1/chat/completions"
    assert _normalize_chat_completions_url("http://127.0.0.1:9000") == "http://127.0.0.1:9000/v1/chat/completions"
    assert _normalize_chat_completions_url("http://127.0.0.1:9000/v1/chat/completions") == "http://127.0.0.1:9000/v1/chat/completions"


def test_normalize_generated_proposal_falls_back_to_review_schema() -> None:
    proposal = _normalize_generated_proposal(
        {
            "title": "Honeymoon at Majestic Lake Cabin | Archived Review with extra overflow words",
            "meta_description": (
                "Authentic honeymoon archive review for Majestic Lake Cabin with extra context "
                "that should be truncated safely before it can exceed the stricter description limit."
            ),
            "h1": "Honeymoon at Majestic Lake Cabin",
            "intro": "Historical honeymoon testimonial from the archive.",
            "faq": [{"question": "Is this real?", "answer": "Yes, this is a preserved guest testimonial."}],
            "json_ld": {},
        },
        _record(),
    )

    assert proposal["json_ld"]["@type"] == "Review"
    assert proposal["json_ld"]["itemReviewed"]["@type"] == "VacationRental"
    assert proposal["faq"][0]["q"] == "Is this real?"
    assert len(proposal["title"]) <= 60
    assert len(proposal["meta_description"]) <= 160


def test_extract_json_object_repairs_common_wrapper_noise() -> None:
    payload = _extract_json_object(
        """```json
        {
          "title": "Archive review",
          "meta_description": "Historical testimonial summary",
          "json_ld": {
            "@context": "https://schema.org",
            "@type": "Review",
          },
        }
        ```"""
    )

    assert payload["title"] == "Archive review"
    assert payload["json_ld"]["@type"] == "Review"


def test_build_sql_upsert_uses_proposed_status_for_hitl_queue() -> None:
    api_request = _build_api_request(
        _record(),
        _normalize_generated_proposal(
            {
                "target_keyword": "majestic lake cabin guest review",
                "title": "Honeymoon at Majestic Lake Cabin | Archived Review",
                "meta_description": "Authentic honeymoon archive review for Majestic Lake Cabin.",
                "h1": "Honeymoon at Majestic Lake Cabin",
                "intro": "Historical honeymoon testimonial from the archive.",
                "faq": [],
                "json_ld": {"@context": "https://schema.org", "@type": "Review"},
            },
            _record(),
        ),
        _config(),
    )

    sql = _build_sql_upsert(api_request)

    assert "INSERT INTO seo_patch_queue" in sql
    assert "'proposed'" in sql
    assert "archive_review" in sql
    assert "ON CONFLICT (target_type, target_slug, campaign, source_hash)" in sql
