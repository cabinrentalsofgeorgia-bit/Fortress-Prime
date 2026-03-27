"""
Lazy restoration helpers for historical Drupal archive content.
"""
from __future__ import annotations

from dataclasses import dataclass
import hmac
import json
from pathlib import Path
import re
import sqlite3
from typing import Any
from urllib.parse import quote

from backend.core.config import settings
from backend.services.openshell_audit import record_audit_event
from backend.services.sovereign_archive import (
    build_canonical_archive_payload,
    build_signed_archive_record,
    sign_archive_payload,
)
from backend.scripts.generate_seo_migration_map import (
    ARCHIVE_OUTPUT_DIR,
    ArchiveRecord,
    BLUEPRINT_PATH,
    _build_single_testimonial_target,
    _normalize_requested_slug,
    _persist_archive_records,
)

_SAFE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ArchiveBlueprintUnavailable(RuntimeError):
    """Raised when no readable blueprint source is configured."""


class ArchiveRecordNotFound(LookupError):
    """Raised when a requested archive slug cannot be restored."""


@dataclass(slots=True)
class ArchiveRestorationResult:
    slug: str
    status: str
    lookup_backend: str
    persisted: bool
    cache_path: str
    archive_path: str
    record: dict[str, Any]


def _normalize_path(path: str) -> str:
    raw = (path or "").strip()
    if not raw:
        return "/"
    raw = re.sub(r"^https?://[^/]+", "", raw, flags=re.IGNORECASE)
    if not raw.startswith("/"):
        raw = f"/{raw}"
    raw = re.sub(r"/{2,}", "/", raw)
    if len(raw) > 1 and raw.endswith("/"):
        raw = raw[:-1]
    return raw


def _slug_from_path(path: str) -> str:
    normalized = _normalize_path(path)
    return normalized.strip("/").split("/")[-1] if normalized not in {"/", ""} else ""


def _normalize_requested_path(value: str) -> str:
    normalized = _normalize_path(value)
    if normalized == "/":
        raise ArchiveRecordNotFound(f"invalid legacy path: {value}")
    return normalized


def _build_cache_key(value: str) -> str:
    return quote(_normalize_requested_path(value), safe="")


def _legacy_type_from_node_type(node_type: str | None) -> str:
    normalized = str(node_type or "").strip().lower()
    if normalized in {"testimonial", "review"}:
        return "review"
    if normalized in {"article", "blog", "blog_post", "news", "post"}:
        return "blog_post"
    return "page"


class ArchiveRestorationService:
    def __init__(
        self,
        *,
        blueprint_path: Path | None = None,
        blueprint_db_path: Path | None = None,
        archive_output_dir: Path | None = None,
    ) -> None:
        configured_blueprint_path = (settings.historian_blueprint_path or "").strip()
        configured_blueprint_db_path = (settings.historian_blueprint_db_path or "").strip()
        configured_archive_output_dir = (settings.historian_archive_output_dir or "").strip()

        self.blueprint_path = (
            blueprint_path
            or (Path(configured_blueprint_path).expanduser() if configured_blueprint_path else BLUEPRINT_PATH)
        )
        self.blueprint_db_path = (
            blueprint_db_path
            or (Path(configured_blueprint_db_path).expanduser() if configured_blueprint_db_path else None)
        )
        self.archive_output_dir = (
            archive_output_dir
            or (Path(configured_archive_output_dir).expanduser() if configured_archive_output_dir else ARCHIVE_OUTPUT_DIR)
        )

    async def restore_archive(self, slug: str, *, force_sign: bool = False) -> ArchiveRestorationResult:
        normalized_path = _normalize_requested_path(slug)
        cache_key = _build_cache_key(normalized_path)
        lookup_id = normalized_path.lstrip("/")
        cache_path = self.archive_output_dir / f"{cache_key}.json"
        if cache_path.exists() and not force_sign:
            with cache_path.open("r", encoding="utf-8") as handle:
                cached_record = json.load(handle)
            result = ArchiveRestorationResult(
                slug=lookup_id,
                status="cache_hit",
                lookup_backend="cache",
                persisted=False,
                cache_path=str(cache_path),
                archive_path=str(cached_record.get("archive_path") or f"/reviews/archive/{_slug_from_path(normalized_path)}"),
                record=cached_record,
            )
            await self._emit_recovery_event(result=result)
            return result

        try:
            blueprint, lookup_backend = self._load_blueprint()
        except ArchiveBlueprintUnavailable:
            await self._emit_recovery_event(
                result=ArchiveRestorationResult(
                    slug=lookup_id,
                    status="blueprint_unavailable",
                    lookup_backend="unavailable",
                    persisted=False,
                    cache_path=str(cache_path),
                    archive_path=f"/reviews/archive/{_slug_from_path(normalized_path)}",
                    record={},
                )
            )
            raise
        archive_record = self._build_archive_record(blueprint, requested_path=normalized_path)
        if archive_record is None:
            await self._emit_recovery_event(
                result=ArchiveRestorationResult(
                    slug=lookup_id,
                    status="soft_landed",
                    lookup_backend=lookup_backend,
                    persisted=False,
                    cache_path=str(cache_path),
                    archive_path=f"/reviews/archive/{_slug_from_path(normalized_path)}",
                    record={},
                )
            )
            raise ArchiveRecordNotFound(f"historical archive path not found: {normalized_path}")

        self.archive_output_dir.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as handle:
            json.dump(archive_record.payload, handle, indent=2, ensure_ascii=True)
        result = ArchiveRestorationResult(
            slug=lookup_id,
            status="restored",
            lookup_backend=lookup_backend,
            persisted=True,
            cache_path=str(cache_path),
            archive_path=str(archive_record.payload.get("archive_path") or f"/reviews/archive/{_slug_from_path(normalized_path)}"),
            record=archive_record.payload,
        )
        await self._emit_recovery_event(result=result)
        return result

    async def restore_testimonial(self, slug: str, *, force_sign: bool = False) -> ArchiveRestorationResult:
        normalized_slug = _normalize_requested_slug(slug)
        if not _SAFE_SLUG_RE.fullmatch(normalized_slug):
            raise ArchiveRecordNotFound(f"invalid slug: {slug}")

        cache_path = self.archive_output_dir / f"{normalized_slug}.json"
        if cache_path.exists() and not force_sign:
            with cache_path.open("r", encoding="utf-8") as handle:
                cached_record = json.load(handle)
            result = ArchiveRestorationResult(
                slug=normalized_slug,
                status="cache_hit",
                lookup_backend="cache",
                persisted=False,
                cache_path=str(cache_path),
                archive_path=str(cached_record.get("archive_path") or f"/reviews/archive/{normalized_slug}"),
                record=cached_record,
            )
            await self._emit_recovery_event(result=result)
            return result

        try:
            blueprint, lookup_backend = self._load_blueprint()
        except ArchiveBlueprintUnavailable:
            await self._emit_recovery_event(
                result=ArchiveRestorationResult(
                    slug=normalized_slug,
                    status="blueprint_unavailable",
                    lookup_backend="unavailable",
                    persisted=False,
                    cache_path=str(cache_path),
                    archive_path=f"/reviews/archive/{normalized_slug}",
                    record={},
                )
            )
            raise

        target = _build_single_testimonial_target(blueprint, requested_slug=normalized_slug)
        if target is None:
            await self._emit_recovery_event(
                result=ArchiveRestorationResult(
                    slug=normalized_slug,
                    status="soft_landed",
                    lookup_backend=lookup_backend,
                    persisted=False,
                    cache_path=str(cache_path),
                    archive_path=f"/reviews/archive/{normalized_slug}",
                    record={},
                )
            )
            raise ArchiveRecordNotFound(f"testimonial slug not found: {normalized_slug}")

        candidate, archive_record = target
        resigned_payload = self._resign_archive_record(
            archive_record.payload,
            legacy_type=_legacy_type_from_node_type(candidate.node_type or archive_record.payload.get("node_type")),
        )
        archive_record = ArchiveRecord(slug=archive_record.slug, payload=resigned_payload)
        written = _persist_archive_records(
            [archive_record],
            self.archive_output_dir,
            overwrite_existing=True,
        )
        result = ArchiveRestorationResult(
            slug=normalized_slug,
            status="restored",
            lookup_backend=lookup_backend,
            persisted=written > 0,
            cache_path=str(self.archive_output_dir / f"{normalized_slug}.json"),
            archive_path=str(archive_record.payload.get("archive_path") or f"/reviews/archive/{normalized_slug}"),
            record=archive_record.payload,
        )
        await self._emit_recovery_event(result=result)
        return result

    async def _emit_recovery_event(self, *, result: ArchiveRestorationResult) -> None:
        metadata = self._build_audit_metadata(result)
        await record_audit_event(
            action="historical_archive.recovery",
            resource_type="historical_archive",
            resource_id=result.slug,
            purpose="historical_recovery_probe",
            tool_name="archive_restoration.restore_archive",
            redaction_status="not_applicable",
            model_route=result.lookup_backend,
            outcome=result.status,
            metadata_json=metadata,
        )

    def _build_audit_metadata(self, result: ArchiveRestorationResult) -> dict[str, Any]:
        record = result.record or {}
        signature_valid = self._verify_archive_signature(record) if record else False
        metadata: dict[str, Any] = {
            "slug": result.slug,
            "recovery_status": result.status,
            "lookup_backend": result.lookup_backend,
            "persisted": result.persisted,
            "cache_path": result.cache_path,
            "archive_path": result.archive_path,
            "signature_valid": signature_valid,
            "signature_present": bool(record.get("hmac_signature")),
        }
        for key in (
            "legacy_node_id",
            "legacy_type",
            "legacy_created_at",
            "legacy_updated_at",
            "legacy_author_id",
            "legacy_language",
            "node_type",
            "original_slug",
            "body_status",
            "signed_at",
            "archive_slug",
            "hmac_signature",
        ):
            value = record.get(key)
            if value:
                metadata[key] = value
        return metadata

    @staticmethod
    def _verify_archive_signature(record: dict[str, Any]) -> bool:
        signature = str(record.get("hmac_signature") or "").strip()
        if not signature:
            return False
        try:
            payload = build_canonical_archive_payload(
                legacy_node_id=str(record.get("legacy_node_id") or ""),
                original_slug=str(record.get("original_slug") or ""),
                content_body=str(record.get("content_body") or ""),
                category_tags=[
                    str(tag)
                    for tag in (record.get("category_tags") or [])
                    if str(tag).strip()
                ],
                title=str(record.get("title")) if record.get("title") is not None else None,
                archive_slug=str(record.get("archive_slug")) if record.get("archive_slug") is not None else None,
                archive_path=str(record.get("archive_path")) if record.get("archive_path") is not None else None,
                source_ref=str(record.get("source_ref")) if record.get("source_ref") is not None else None,
                node_type=str(record.get("node_type") or "testimonial"),
                legacy_type=str(record.get("legacy_type")) if record.get("legacy_type") is not None else None,
                legacy_created_at=(
                    int(record.get("legacy_created_at"))
                    if record.get("legacy_created_at") is not None
                    else None
                ),
                legacy_updated_at=(
                    int(record.get("legacy_updated_at"))
                    if record.get("legacy_updated_at") is not None
                    else None
                ),
                legacy_author_id=(
                    str(record.get("legacy_author_id"))
                    if record.get("legacy_author_id") is not None
                    else None
                ),
                legacy_language=(
                    str(record.get("legacy_language"))
                    if record.get("legacy_language") is not None
                    else None
                ),
                related_property_slug=(
                    str(record.get("related_property_slug"))
                    if record.get("related_property_slug") is not None
                    else None
                ),
                related_property_path=(
                    str(record.get("related_property_path"))
                    if record.get("related_property_path") is not None
                    else None
                ),
                related_property_title=(
                    str(record.get("related_property_title"))
                    if record.get("related_property_title") is not None
                    else None
                ),
                body_status=str(record.get("body_status") or "verified"),
                signed_at=str(record.get("signed_at") or ""),
            )
        except (TypeError, ValueError):
            return False

        expected_signature = sign_archive_payload(payload)
        return hmac.compare_digest(signature, expected_signature)

    def _build_archive_record(self, blueprint: dict[str, Any], *, requested_path: str) -> ArchiveRecord | None:
        node_lookup = self._build_node_lookup(blueprint)
        aliases = ((blueprint.get("url_aliases") or {}).get("records") or [])
        for alias in aliases:
            if not isinstance(alias, dict):
                continue
            alias_path = _normalize_path(str(alias.get("alias_path") or ""))
            if alias_path != requested_path:
                continue

            source_ref = str(alias.get("source_path") or "").strip().lstrip("/")
            if not source_ref.startswith("node/"):
                continue

            node_info = node_lookup.get(source_ref)
            if not isinstance(node_info, dict) or not node_info:
                continue

            return self._build_generic_archive_record(
                slug=_slug_from_path(requested_path),
                original_slug=alias_path,
                source_ref=source_ref,
                node_info=node_info,
            )
        return None

    @staticmethod
    def _build_node_lookup(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
        content_types = blueprint.get("content_types") or blueprint.get("nodes_by_type") or {}
        by_source: dict[str, dict[str, Any]] = {}
        if isinstance(content_types, dict):
            for node_type, payload in content_types.items():
                nodes = payload.get("nodes", []) if isinstance(payload, dict) else []
                for node in nodes:
                    if not isinstance(node, dict):
                        continue
                    source = str(node.get("source_path") or "").strip().lstrip("/")
                    if not source:
                        continue
                    node_copy = dict(node)
                    node_copy["source_path"] = source
                    node_copy["node_type"] = str(node_copy.get("node_type") or node_type or "unknown")
                    by_source[source] = node_copy

        global_alias_sources = ((blueprint.get("global_alias_scan") or {}).get("by_source") or {})
        if isinstance(global_alias_sources, dict):
            for source, payload in global_alias_sources.items():
                if not isinstance(payload, dict):
                    continue
                node_payload = payload.get("node")
                if not isinstance(node_payload, dict):
                    continue
                source_ref = str(source or "").strip().lstrip("/")
                if not source_ref:
                    continue
                existing = by_source.get(source_ref, {})
                node_copy = {**existing, **node_payload}
                node_copy["source_path"] = source_ref
                node_copy["node_type"] = str(
                    node_copy.get("node_type")
                    or payload.get("node_type")
                    or "unknown"
                )
                canonical_alias = payload.get("canonical_alias")
                if canonical_alias and not node_copy.get("url_alias"):
                    node_copy["url_alias"] = canonical_alias
                by_source[source_ref] = node_copy

        return by_source

    def _build_generic_archive_record(
        self,
        *,
        slug: str,
        original_slug: str,
        source_ref: str,
        node_info: dict[str, Any],
    ) -> ArchiveRecord:
        node_type = str(node_info.get("node_type") or "unknown").strip() or "unknown"
        payload = build_signed_archive_record(
            legacy_node_id=str(node_info.get("nid") or source_ref.rsplit("/", 1)[-1] or slug),
            original_slug=original_slug,
            content_body=str(node_info.get("body") or "").strip(),
            category_tags=[],
            title=str(node_info.get("title") or "").strip() or None,
            archive_slug=slug,
            archive_path=f"/reviews/archive/{slug}",
            source_ref=source_ref or None,
            node_type=node_type,
            legacy_type=_legacy_type_from_node_type(node_type),
            legacy_created_at=int(node_info.get("created")) if node_info.get("created") is not None else None,
            legacy_updated_at=int(node_info.get("changed")) if node_info.get("changed") is not None else None,
            legacy_author_id=str(node_info.get("uid")) if node_info.get("uid") is not None else None,
            legacy_language=str(node_info.get("language")) if node_info.get("language") is not None else None,
            body_status="verified" if str(node_info.get("body") or "").strip() else "missing_in_blueprint",
        )
        return ArchiveRecord(slug=slug, payload=payload)

    @staticmethod
    def _resign_archive_record(record: dict[str, Any], *, legacy_type: str | None = None) -> dict[str, Any]:
        node_type = str(record.get("node_type") or "testimonial").strip() or "testimonial"
        payload = build_signed_archive_record(
            legacy_node_id=str(record.get("legacy_node_id") or ""),
            original_slug=str(record.get("original_slug") or ""),
            content_body=str(record.get("content_body") or ""),
            category_tags=[
                str(tag)
                for tag in (record.get("category_tags") or [])
                if str(tag).strip()
            ],
            title=str(record.get("title")) if record.get("title") is not None else None,
            archive_slug=str(record.get("archive_slug")) if record.get("archive_slug") is not None else None,
            archive_path=str(record.get("archive_path")) if record.get("archive_path") is not None else None,
            source_ref=str(record.get("source_ref")) if record.get("source_ref") is not None else None,
            node_type=node_type,
            legacy_type=legacy_type or str(record.get("legacy_type") or _legacy_type_from_node_type(node_type)),
            legacy_created_at=(
                int(record.get("legacy_created_at"))
                if record.get("legacy_created_at") is not None
                else None
            ),
            legacy_updated_at=(
                int(record.get("legacy_updated_at"))
                if record.get("legacy_updated_at") is not None
                else None
            ),
            legacy_author_id=(
                str(record.get("legacy_author_id"))
                if record.get("legacy_author_id") is not None
                else None
            ),
            legacy_language=(
                str(record.get("legacy_language"))
                if record.get("legacy_language") is not None
                else None
            ),
            related_property_slug=(
                str(record.get("related_property_slug"))
                if record.get("related_property_slug") is not None
                else None
            ),
            related_property_path=(
                str(record.get("related_property_path"))
                if record.get("related_property_path") is not None
                else None
            ),
            related_property_title=(
                str(record.get("related_property_title"))
                if record.get("related_property_title") is not None
                else None
            ),
            body_status=str(record.get("body_status") or "verified"),
            signed_at=str(record.get("signed_at") or ""),
        )
        return payload

    def _load_blueprint(self) -> tuple[dict[str, Any], str]:
        if self.blueprint_db_path and self.blueprint_db_path.exists():
            blueprint = self._load_blueprint_from_sqlite(self.blueprint_db_path)
            if blueprint is not None:
                return blueprint, "sqlite_blueprint"

        if self.blueprint_path.exists():
            with self.blueprint_path.open("r", encoding="utf-8") as handle:
                return json.load(handle), "json_blueprint"

        raise ArchiveBlueprintUnavailable("no readable blueprint source is configured")

    def _load_blueprint_from_sqlite(self, database_path: Path) -> dict[str, Any] | None:
        connection = sqlite3.connect(str(database_path))
        try:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name ASC"
                ).fetchall()
            ]
            for table_name in tables:
                text_columns = self._sqlite_text_columns(connection, table_name)
                for column_name in text_columns:
                    query = f'SELECT "{column_name}" FROM "{table_name}" LIMIT 25'
                    try:
                        rows = connection.execute(query).fetchall()
                    except sqlite3.DatabaseError:
                        continue
                    for row in rows:
                        candidate = self._parse_blueprint_document(row[0] if row else None)
                        if candidate is not None:
                            return candidate
        finally:
            connection.close()
        return None

    @staticmethod
    def _sqlite_text_columns(connection: sqlite3.Connection, table_name: str) -> list[str]:
        try:
            rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        except sqlite3.DatabaseError:
            return []

        columns: list[str] = []
        for row in rows:
            if len(row) < 3:
                continue
            column_name = str(row[1])
            column_type = str(row[2] or "").upper()
            if any(token in column_type for token in ("CHAR", "TEXT", "CLOB", "JSON")):
                columns.append(column_name)
        return columns

    @staticmethod
    def _parse_blueprint_document(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text.startswith("{"):
            return None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        if "url_aliases" not in payload:
            return None
        if "content_types" not in payload and "nodes_by_type" not in payload:
            return None
        return payload
