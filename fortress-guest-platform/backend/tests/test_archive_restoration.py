from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.services.archive_restoration as archive_restoration_module
from backend.core.database import close_db
from backend.services.archive_restoration import (
    ArchiveRecordNotFound,
    ArchiveRestorationService,
)


def _write_blueprint(path: Path) -> None:
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
                    "source_path": "node/358",
                    "alias_path": "/about-us",
                },
                {
                    "source_path": "node/715",
                    "alias_path": "/faq",
                },
                {
                    "source_path": "node/9001",
                    "alias_path": "/blog/2018/blue-ridge-fall-specials",
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
            "page": {
                "type_info": {"label": "Page", "description": "node"},
                "nodes": [
                    {
                        "nid": 358,
                        "title": "About Us",
                        "status": 1,
                        "created": 1711111111,
                        "changed": 1712222222,
                        "uid": 7,
                        "language": "en",
                        "source_path": "node/358",
                        "url_alias": "/about-us",
                        "body": "A preserved company history page.",
                    },
                    {
                        "nid": 715,
                        "title": "FAQ",
                        "status": 1,
                        "created": 1713333333,
                        "changed": 1714444444,
                        "uid": 11,
                        "language": "en",
                        "source_path": "node/715",
                        "url_alias": "/faq",
                        "body": "Frequently asked questions from the legacy Drupal site.",
                    },
                ],
            },
            "blog": {
                "type_info": {"label": "Blog", "description": "node"},
                "nodes": [
                    {
                        "nid": 9001,
                        "title": "Blue Ridge Fall Specials",
                        "status": 1,
                        "created": 1600000000,
                        "changed": 1600001234,
                        "uid": 4,
                        "language": "en",
                        "source_path": "node/9001",
                        "url_alias": "/blog/2018/blue-ridge-fall-specials",
                        "body": "Seasonal specials from the legacy blog archive.",
                    }
                ],
            },
        },
    }
    path.write_text(json.dumps(blueprint), encoding="utf-8")


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _dispose_shared_db_engine():
    yield
    _run(close_db())


@pytest.fixture(autouse=True)
def _stub_archive_audit_writes(monkeypatch: pytest.MonkeyPatch):
    async def _noop_record_audit_event(**kwargs):
        return None

    monkeypatch.setattr(archive_restoration_module, "record_audit_event", _noop_record_audit_event)


def test_restore_testimonial_generates_and_caches_archive(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "blueprint.json"
    archive_dir = tmp_path / "archives"
    _write_blueprint(blueprint_path)

    service = ArchiveRestorationService(
        blueprint_path=blueprint_path,
        archive_output_dir=archive_dir,
    )

    async def _exercise():
        restored = await service.restore_testimonial("honeymoon-majestic-lake-cabin")
        cached = await service.restore_testimonial("honeymoon-majestic-lake-cabin")
        return restored, cached

    restored, cached = _run(_exercise())

    assert restored.status == "restored"
    assert restored.lookup_backend == "json_blueprint"
    assert restored.persisted is True
    assert restored.record["archive_path"] == "/reviews/archive/honeymoon-majestic-lake-cabin"
    assert restored.record["legacy_type"] == "review"
    assert restored.record["hmac_signature"]

    assert cached.status == "cache_hit"
    assert cached.lookup_backend == "cache"
    assert cached.persisted is False
    assert (archive_dir / "honeymoon-majestic-lake-cabin.json").exists()


def test_force_sign_rewrites_existing_archive_payload(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "blueprint.json"
    archive_dir = tmp_path / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    _write_blueprint(blueprint_path)

    stale_path = archive_dir / "honeymoon-majestic-lake-cabin.json"
    stale_path.write_text(
        json.dumps(
            {
                "archive_path": "/reviews/archive/honeymoon-majestic-lake-cabin",
                "content_body": "stale",
            }
        ),
        encoding="utf-8",
    )

    service = ArchiveRestorationService(
        blueprint_path=blueprint_path,
        archive_output_dir=archive_dir,
    )

    restored = _run(service.restore_testimonial("honeymoon-majestic-lake-cabin", force_sign=True))
    payload = json.loads(stale_path.read_text(encoding="utf-8"))

    assert restored.status == "restored"
    assert restored.persisted is True
    assert payload["content_body"] == "A timeless testimonial body."
    assert payload["hmac_signature"]


def test_restore_testimonial_uses_global_alias_scan_for_non_testimonial_node(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "blueprint.json"
    archive_dir = tmp_path / "archives"
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
    blueprint_path.write_text(json.dumps(blueprint), encoding="utf-8")

    service = ArchiveRestorationService(
        blueprint_path=blueprint_path,
        archive_output_dir=archive_dir,
    )

    restored = _run(service.restore_testimonial("honeymoon-cabin", force_sign=True))

    assert restored.status == "restored"
    assert restored.record["legacy_node_id"] == "77"
    assert restored.record["content_body"] == "Recovered from the global alias scan."
    assert restored.record["archive_path"] == "/reviews/archive/honeymoon-cabin"
    assert restored.record["legacy_type"] == "page"
    assert (archive_dir / "honeymoon-cabin.json").exists()


def test_restore_archive_scans_all_blueprint_node_types(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "blueprint.json"
    archive_dir = tmp_path / "archives"
    _write_blueprint(blueprint_path)

    service = ArchiveRestorationService(
        blueprint_path=blueprint_path,
        archive_output_dir=archive_dir,
    )

    async def _exercise():
        about = await service.restore_archive("about-us", force_sign=True)
        faq = await service.restore_archive("faq", force_sign=True)
        return about, faq

    about, faq = _run(_exercise())

    assert about.status == "restored"
    assert about.record["legacy_node_id"] == "358"
    assert about.record["title"] == "About Us"
    assert about.record["original_slug"] == "/about-us"
    assert about.record["node_type"] == "page"
    assert about.record["legacy_type"] == "page"
    assert about.record["legacy_created_at"] == 1711111111
    assert about.record["legacy_updated_at"] == 1712222222
    assert about.record["legacy_author_id"] == "7"
    assert about.record["legacy_language"] == "en"
    assert about.record["content_body"] == "A preserved company history page."

    assert faq.status == "restored"
    assert faq.record["legacy_node_id"] == "715"
    assert faq.record["title"] == "FAQ"
    assert faq.record["original_slug"] == "/faq"
    assert faq.record["node_type"] == "page"
    assert faq.record["legacy_type"] == "page"
    assert faq.record["legacy_created_at"] == 1713333333
    assert faq.record["legacy_updated_at"] == 1714444444
    assert faq.record["legacy_author_id"] == "11"
    assert faq.record["legacy_language"] == "en"
    assert faq.record["content_body"] == "Frequently asked questions from the legacy Drupal site."
    assert (archive_dir / "%2Fabout-us.json").exists()
    assert (archive_dir / "%2Ffaq.json").exists()


def test_restore_archive_requires_exact_full_path_for_nested_aliases(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "blueprint.json"
    archive_dir = tmp_path / "archives"
    _write_blueprint(blueprint_path)

    service = ArchiveRestorationService(
        blueprint_path=blueprint_path,
        archive_output_dir=archive_dir,
    )

    restored = _run(service.restore_archive("blog/2018/blue-ridge-fall-specials", force_sign=True))

    assert restored.status == "restored"
    assert restored.record["legacy_node_id"] == "9001"
    assert restored.record["node_type"] == "blog"
    assert restored.record["legacy_type"] == "blog_post"
    assert restored.record["original_slug"] == "/blog/2018/blue-ridge-fall-specials"
    assert (archive_dir / "%2Fblog%2F2018%2Fblue-ridge-fall-specials.json").exists()

    try:
        _run(service.restore_archive("blue-ridge-fall-specials", force_sign=True))
        raise AssertionError("restore_archive should require an exact full path match")
    except ArchiveRecordNotFound:
        pass


def test_restore_testimonial_emits_signed_historical_audit_event(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "blueprint.json"
    archive_dir = tmp_path / "archives"
    _write_blueprint(blueprint_path)

    events: list[dict[str, object]] = []

    async def _fake_record_audit_event(**kwargs):
        events.append(kwargs)
        return None

    original = archive_restoration_module.record_audit_event
    archive_restoration_module.record_audit_event = _fake_record_audit_event
    try:
        service = ArchiveRestorationService(
            blueprint_path=blueprint_path,
            archive_output_dir=archive_dir,
        )
        restored = _run(service.restore_testimonial("honeymoon-majestic-lake-cabin"))
    finally:
        archive_restoration_module.record_audit_event = original

    assert restored.status == "restored"
    assert len(events) == 1
    event = events[0]
    assert event["resource_type"] == "historical_archive"
    assert event["outcome"] == "restored"
    assert event["resource_id"] == "honeymoon-majestic-lake-cabin"
    assert event["metadata_json"]["signature_valid"] is True
    assert event["metadata_json"]["legacy_node_id"] == "33"


def test_restore_testimonial_records_soft_landed_loss_when_slug_missing(tmp_path: Path) -> None:
    blueprint_path = tmp_path / "blueprint.json"
    archive_dir = tmp_path / "archives"
    _write_blueprint(blueprint_path)

    events: list[dict[str, object]] = []

    async def _fake_record_audit_event(**kwargs):
        events.append(kwargs)
        return None

    original = archive_restoration_module.record_audit_event
    archive_restoration_module.record_audit_event = _fake_record_audit_event
    try:
        service = ArchiveRestorationService(
            blueprint_path=blueprint_path,
            archive_output_dir=archive_dir,
        )
        try:
            _run(service.restore_testimonial("not-in-blueprint"))
            raise AssertionError("restore_testimonial should have raised ArchiveRecordNotFound")
        except ArchiveRecordNotFound:
            pass
    finally:
        archive_restoration_module.record_audit_event = original

    assert len(events) == 1
    event = events[0]
    assert event["resource_type"] == "historical_archive"
    assert event["outcome"] == "soft_landed"
    assert event["resource_id"] == "not-in-blueprint"
    assert event["metadata_json"]["signature_valid"] is False
