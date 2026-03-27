#!/usr/bin/env python3
"""
Observer Swarm bootstrap: crawl the legacy blueprint and ledger non-cabin functional nodes.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from sqlalchemy.dialects.postgresql import insert as pg_insert


SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[2]
REPO_ROOT = SCRIPT_PATH.parents[3]
BLUEPRINT_PATH = SCRIPT_PATH.parent / "drupal_granular_blueprint.json"
LEGACY_BASE_URL = "https://cabin-rentals-of-georgia.com"
IGNORED_NODE_TYPES = {"cabin", "testimonial", "review", "slideshow_image"}

for candidate in (PROJECT_ROOT, REPO_ROOT):
    candidate_str = str(candidate)
    if candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)


def load_environment() -> list[Path]:
    loaded_files: list[Path] = []
    for env_file in (
        REPO_ROOT / ".env",
        PROJECT_ROOT / ".env",
        REPO_ROOT / ".env.security",
    ):
        if env_file.exists():
            load_dotenv(env_file, override=True)
            loaded_files.append(env_file)
    return loaded_files


LOADED_ENV_FILES = load_environment()

from backend.core.database import AsyncSessionLocal, close_db
from backend.models.functional_node import FunctionalNode
from backend.services.worker_hardening import require_legacy_host_active


@dataclass
class ReconNode:
    legacy_node_id: int | None
    source_path: str
    canonical_path: str
    title: str
    node_type: str
    body_html: str
    body_text_preview: str
    taxonomy_terms: list[str]
    media_refs: list[str]
    source_metadata: dict[str, Any]
    content_category: str
    functional_complexity: str
    priority_tier: int
    form_fields: dict[str, Any]
    http_status: int | None
    last_crawled_at: datetime | None
    is_published: bool
    source_hash: str


class FormHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self._current_form: dict[str, Any] | None = None
        self._current_label: dict[str, str | None] | None = None
        self._label_text_parts: list[str] = []
        self._labels_by_for: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value for key, value in attrs}
        if tag == "form":
            self._current_form = {
                "action": attr_map.get("action") or "",
                "method": (attr_map.get("method") or "get").lower(),
                "id": attr_map.get("id") or "",
                "class": attr_map.get("class") or "",
                "fields": [],
            }
            return
        if tag == "label":
            self._current_label = {"for": attr_map.get("for"), "text": None}
            self._label_text_parts = []
            return
        if self._current_form is None:
            return
        if tag not in {"input", "textarea", "select"}:
            return

        field_type = (attr_map.get("type") or ("textarea" if tag == "textarea" else "select" if tag == "select" else "text")).lower()
        if field_type in {"hidden", "submit", "button", "reset", "image"}:
            return

        field_id = attr_map.get("id") or ""
        label = self._labels_by_for.get(field_id) if field_id else None
        if label is None and self._current_label is not None:
            label = " ".join(self._label_text_parts).strip() or None
        self._current_form["fields"].append(
            {
                "name": attr_map.get("name") or "",
                "id": field_id,
                "type": field_type,
                "label": label,
                "required": "required" in attr_map or attr_map.get("aria-required") == "true",
                "placeholder": attr_map.get("placeholder") or "",
            }
        )

    def handle_endtag(self, tag: str) -> None:
        if tag == "label" and self._current_label is not None:
            label_text = " ".join(self._label_text_parts).strip()
            target = self._current_label.get("for")
            if target and label_text:
                self._labels_by_for[target] = label_text
            self._current_label = None
            self._label_text_parts = []
            return
        if tag == "form" and self._current_form is not None:
            if self._current_form["fields"]:
                self.forms.append(self._current_form)
            self._current_form = None

    def handle_data(self, data: str) -> None:
        if self._current_label is not None:
            cleaned = re.sub(r"\s+", " ", data).strip()
            if cleaned:
                self._label_text_parts.append(cleaned)


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _normalize_path(value: str) -> str:
    path = _normalize_text(value)
    if not path:
        return "/"
    path = re.sub(r"^https?://[^/]+", "", path, flags=re.IGNORECASE)
    if not path.startswith("/"):
        path = "/" + path
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _strip_html(value: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", value or "", flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&rsquo;", "'")
        .replace("&ldquo;", '"')
        .replace("&rdquo;", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def _extract_media_refs(html: str) -> list[str]:
    refs = re.findall(r"""<(?:img|source)[^>]+(?:src|srcset)=["']([^"']+)["']""", html or "", flags=re.IGNORECASE)
    ordered: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        normalized = _normalize_text(ref)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered[:25]


def _extract_form_fields(html: str) -> dict[str, Any]:
    parser = FormHTMLParser()
    parser.feed(html or "")
    return {
        "forms": parser.forms,
        "form_count": len(parser.forms),
    }


def _collect_aliases(blueprint: dict[str, Any], source_path: str, fallback_alias: str | None) -> tuple[str, list[str], list[str]]:
    by_source = ((blueprint.get("global_alias_scan") or {}).get("by_source") or {})
    alias_payload = by_source.get(source_path) if isinstance(by_source, dict) else None
    aliases: list[str] = []
    languages: list[str] = []
    canonical_alias = ""
    if isinstance(alias_payload, dict):
        canonical_alias = _normalize_path(str(alias_payload.get("canonical_alias") or ""))
        aliases = [_normalize_path(str(item)) for item in alias_payload.get("aliases", []) if _normalize_text(item)]
        languages = [_normalize_text(item) for item in alias_payload.get("languages", []) if _normalize_text(item)]

    if not canonical_alias and fallback_alias:
        canonical_alias = _normalize_path(fallback_alias)
    if canonical_alias and canonical_alias not in aliases:
        aliases.insert(0, canonical_alias)
    aliases = [alias for alias in aliases if alias and alias != "/"]
    return canonical_alias, aliases, languages


def _classify_node(node_type: str, canonical_path: str, title: str) -> tuple[str, str, int]:
    route_haystack = " ".join([node_type.lower(), canonical_path.lower(), title.lower()])
    if node_type.lower() == "webform" or any(
        token in route_haystack
        for token in (
            "contact-us",
            "contact us",
            "contact",
            "inquiry",
            "request-info",
            "property-management",
            "property management contact",
        )
    ):
        return "form", "form_medium", 10
    if any(token in route_haystack for token in ("privacy", "policy", "terms", "faq", "accessibility")):
        return "policy_page", "static_text", 15
    if node_type.lower() == "activity":
        return "area_guide", "content_rich", 25
    if node_type.lower() == "blog":
        return "blog_article", "content_rich", 35
    if node_type.lower() in {"landing_page", "micro_site"}:
        return "marketing_page", "content_rich", 30
    if node_type.lower() == "event":
        return "event_page", "content_rich", 35
    if re.search(r"(gallery|photo|images?)", route_haystack):
        return "gallery_page", "gallery", 35
    return "static_page", "static_text", 40


def _should_fetch_live_html(content_category: str, priority_tier: int) -> bool:
    return content_category in {"form", "policy_page"} or priority_tier <= 20


async def _fetch_live_html(client: httpx.AsyncClient, canonical_path: str) -> tuple[int | None, str, datetime | None]:
    url = f"{LEGACY_BASE_URL.rstrip('/')}{canonical_path}"
    try:
        response = await client.get(url, follow_redirects=True)
        return response.status_code, response.text, datetime.now(timezone.utc)
    except Exception:
        return None, "", datetime.now(timezone.utc)


def _build_source_hash(node: dict[str, Any], html: str) -> str:
    payload = json.dumps({"node": node, "html": html[:5000]}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iter_public_nodes(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    nodes_by_type = blueprint.get("nodes_by_type") or {}
    rows: list[dict[str, Any]] = []
    for node_type, payload in nodes_by_type.items():
        if str(node_type).lower() in IGNORED_NODE_TYPES:
            continue
        nodes = payload.get("nodes", []) if isinstance(payload, dict) else []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if str(node_type).lower() != "webform" and int(node.get("status") or 0) != 1:
                continue
            node_copy = dict(node)
            node_copy["node_type"] = node_type
            rows.append(node_copy)
    return rows


async def _build_recon_rows(blueprint: dict[str, Any]) -> list[ReconNode]:
    nodes = _iter_public_nodes(blueprint)
    candidates: list[dict[str, Any]] = []
    for node in nodes:
        source_path = _normalize_text(node.get("source_path"))
        if not source_path:
            continue
        fallback_alias = _normalize_text(node.get("url_alias"))
        canonical_alias, aliases, languages = _collect_aliases(blueprint, source_path, fallback_alias)
        canonical_path = canonical_alias or _normalize_path("/" + source_path)
        title = _normalize_text(node.get("title")) or canonical_path.strip("/") or source_path
        body_html = _normalize_text(node.get("body"))
        content_category, functional_complexity, priority_tier = _classify_node(
            _normalize_text(node.get("node_type")),
            canonical_path,
            title,
        )
        candidates.append(
            {
                "legacy_node_id": int(node["nid"]) if node.get("nid") is not None else None,
                "source_path": source_path,
                "canonical_path": canonical_path,
                "title": title,
                "node_type": _normalize_text(node.get("node_type")) or "unknown",
                "body_html": body_html,
                "taxonomy_terms": [],
                "media_refs": _extract_media_refs(body_html),
                "source_metadata": {
                    "aliases": aliases,
                    "languages": languages,
                    "body_summary": _normalize_text(node.get("body_summary")),
                    "body_format": _normalize_text(node.get("body_format")),
                    "legacy_title": _normalize_text(node.get("title")),
                },
                "content_category": content_category,
                "functional_complexity": functional_complexity,
                "priority_tier": priority_tier,
                "is_published": bool(int(node.get("status") or 0)),
            }
        )

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), headers={"User-Agent": "Fortress-Observer-Swarm/1.0"}) as client:
        for candidate in candidates:
            live_html = ""
            http_status = None
            crawled_at = None
            if _should_fetch_live_html(candidate["content_category"], int(candidate["priority_tier"])):
                http_status, live_html, crawled_at = await _fetch_live_html(client, candidate["canonical_path"])
            effective_html = live_html or candidate["body_html"]
            body_text_preview = _strip_html(effective_html)[:2000]
            if candidate["content_category"] == "form":
                form_fields = _extract_form_fields(effective_html)
                if form_fields["form_count"] == 0:
                    form_fields["notes"] = ["No live HTML form fields detected; inspect Drupal node/webform config."]
            else:
                form_fields = {"forms": [], "form_count": 0}

            candidate["http_status"] = http_status
            candidate["last_crawled_at"] = crawled_at
            candidate["body_html"] = effective_html
            candidate["body_text_preview"] = body_text_preview
            candidate["form_fields"] = form_fields
            candidate["media_refs"] = _extract_media_refs(effective_html)
            candidate["source_hash"] = _build_source_hash(candidate, effective_html)

    rows: list[ReconNode] = []
    for candidate in candidates:
        rows.append(
            ReconNode(
                legacy_node_id=candidate["legacy_node_id"],
                source_path=candidate["source_path"],
                canonical_path=candidate["canonical_path"],
                title=candidate["title"],
                node_type=candidate["node_type"],
                body_html=candidate["body_html"],
                body_text_preview=candidate["body_text_preview"],
                taxonomy_terms=candidate["taxonomy_terms"],
                media_refs=candidate["media_refs"],
                source_metadata=candidate["source_metadata"],
                content_category=candidate["content_category"],
                functional_complexity=candidate["functional_complexity"],
                priority_tier=candidate["priority_tier"],
                form_fields=candidate["form_fields"],
                http_status=candidate["http_status"],
                last_crawled_at=candidate["last_crawled_at"],
                is_published=candidate["is_published"],
                source_hash=candidate["source_hash"],
            )
        )
    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed the functional_nodes ledger from the Drupal blueprint and legacy storefront crawl.",
    )
    parser.add_argument(
        "--blueprint-path",
        type=Path,
        default=BLUEPRINT_PATH,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview recon counts without committing.",
    )
    return parser.parse_args()


async def _run() -> int:
    require_legacy_host_active("ignite_recon_swarm legacy fetch")
    args = _parse_args()
    blueprint_path = Path(args.blueprint_path).expanduser().resolve()
    blueprint = json.loads(blueprint_path.read_text(encoding="utf-8"))
    rows = await _build_recon_rows(blueprint)
    category_counts: dict[str, int] = {}
    for row in rows:
        category_counts[row.content_category] = category_counts.get(row.content_category, 0) + 1

    print("[observer-swarm] functional node recon")
    print(f"blueprint_path={blueprint_path}")
    print(f"loaded_env_files={len(LOADED_ENV_FILES)}")
    print(f"legacy_base_url={LEGACY_BASE_URL}")
    print(f"functional_nodes_discovered={len(rows)}")
    print("category_counts=" + json.dumps(dict(sorted(category_counts.items())), sort_keys=True))

    preview_rows = [row for row in rows if row.content_category in {"form", "policy_page"}][:20]
    if preview_rows:
        print("priority_preview_begin")
        for row in preview_rows:
            print(
                " | ".join(
                    [
                        f"path={row.canonical_path}",
                        f"title={row.title}",
                        f"category={row.content_category}",
                        f"complexity={row.functional_complexity}",
                        f"http_status={row.http_status if row.http_status is not None else '-'}",
                        f"form_count={int(row.form_fields.get('form_count') or 0)}",
                    ]
                )
            )
        print("priority_preview_end")

    values = [
        {
            "legacy_node_id": row.legacy_node_id,
            "source_path": row.source_path,
            "canonical_path": row.canonical_path,
            "title": row.title,
            "node_type": row.node_type,
            "content_category": row.content_category,
            "functional_complexity": row.functional_complexity,
            "crawl_status": "discovered",
            "mirror_status": "pending",
            "cutover_status": "legacy",
            "priority_tier": row.priority_tier,
            "is_published": row.is_published,
            "http_status": row.http_status,
            "body_html": row.body_html or None,
            "body_text_preview": row.body_text_preview or None,
            "form_fields": row.form_fields,
            "taxonomy_terms": row.taxonomy_terms,
            "media_refs": row.media_refs,
            "source_metadata": row.source_metadata,
            "source_hash": row.source_hash,
            "last_crawled_at": row.last_crawled_at,
        }
        for row in rows
    ]

    async with AsyncSessionLocal() as session:
        stmt = pg_insert(FunctionalNode.__table__).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[FunctionalNode.__table__.c.source_path],
            set_={
                "legacy_node_id": stmt.excluded.legacy_node_id,
                "canonical_path": stmt.excluded.canonical_path,
                "title": stmt.excluded.title,
                "node_type": stmt.excluded.node_type,
                "content_category": stmt.excluded.content_category,
                "functional_complexity": stmt.excluded.functional_complexity,
                "priority_tier": stmt.excluded.priority_tier,
                "is_published": stmt.excluded.is_published,
                "http_status": stmt.excluded.http_status,
                "body_html": stmt.excluded.body_html,
                "body_text_preview": stmt.excluded.body_text_preview,
                "form_fields": stmt.excluded.form_fields,
                "taxonomy_terms": stmt.excluded.taxonomy_terms,
                "media_refs": stmt.excluded.media_refs,
                "source_metadata": stmt.excluded.source_metadata,
                "source_hash": stmt.excluded.source_hash,
                "last_crawled_at": stmt.excluded.last_crawled_at,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        await session.execute(stmt)
        if args.dry_run:
            await session.rollback()
            print("[dry-run] recon ledger plan prepared")
        else:
            await session.commit()
            print("[ok] recon ledger committed")
    return 0


async def amain() -> int:
    try:
        return await _run()
    finally:
        await close_db()


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
