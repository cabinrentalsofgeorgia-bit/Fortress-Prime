#!/usr/bin/env python3
"""
Generate archive SEO patch proposals from signed testimonial JSON files.

This script reads archive review records, calls a DGX-hosted chat-completions
endpoint to draft SEO overlays, and emits queue-ready outputs in two forms:

1. Bulk proposal payload JSON for offline review or future archive migration work
2. SQL upserts for direct insertion into seo_patch_queue

The SEO queue currently uses ``status='proposed'`` as the human-review state.
This script therefore maps the requested HITL ``pending`` workflow to the
existing ``proposed`` queue status rather than inventing a new schema value.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env")

from backend.api.seo_patches import _source_hash
from backend.core.config import settings

DEFAULT_ARCHIVE_DIR = REPO_ROOT / "backend" / "data" / "archives" / "testimonials"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "backend" / "scripts" / "archive_seo_bulk_payloads.json"
DEFAULT_SQL_OUTPUT_PATH = REPO_ROOT / "backend" / "scripts" / "archive_seo_bulk_payloads.sql"
DEFAULT_API_BASE_URL = "http://127.0.0.1:8100"
DEFAULT_CHAT_BASE_URL = (
    os.getenv("SEO_ARCHIVE_CHAT_BASE_URL")
    or settings.nemoclaw_orchestrator_url
    or settings.dgx_reasoner_url
)
DEFAULT_MODEL = os.getenv("SEO_ARCHIVE_MODEL", "").strip()
DEFAULT_SYSTEM_MESSAGE = (
    "You are a high-precision SEO archivist for Cabin Rentals of Georgia. "
    "Return only valid JSON. Use only facts grounded in the supplied archive review. "
    "Do not invent amenities, prices, locations, ratings, dates, or review authors. "
    "Prefer concise, high-conversion metadata for a historical testimonial page. "
    "Keep title under 60 characters and meta_description under 160 characters. "
    "json_ld must be a schema.org Review object and should nest a VacationRental "
    "inside itemReviewed when a cabin/property name is available."
)
TITLE_LIMIT = 60
META_DESCRIPTION_LIMIT = 160
JSON_RESPONSE_FORMAT = {"type": "json_object"}
_CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


@dataclass(frozen=True)
class ArchiveRecord:
    source_file: Path
    legacy_node_id: str
    original_slug: str
    archive_slug: str
    archive_path: str
    title: str
    content_body: str
    body_status: str
    category_tags: list[str]
    node_type: str
    signed_at: str | None
    hmac_signature: str
    related_property_slug: str | None
    related_property_path: str | None
    related_property_title: str | None


@dataclass(frozen=True)
class GeneratorConfig:
    archive_dir: Path
    output_path: Path
    sql_output_path: Path
    api_base_url: str
    chat_completions_url: str
    model: str
    campaign: str
    rubric_version: str
    proposed_by: str
    run_id: str
    concurrency: int
    limit: int | None
    only_slug: str | None
    post_api: bool
    dry_run: bool
    swarm_api_key: str
    system_message: str
    temperature: float
    max_tokens: int
    client_cert: str | None
    client_key: str | None
    verify_ssl: bool
    force_json_response: bool
    disable_thinking: bool
    db_resume: bool
    write_db: bool
    connect_timeout_s: float
    read_timeout_s: float
    write_timeout_s: float
    pool_timeout_s: float


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_chat_completions_url(base_url: str) -> str:
    value = (base_url or "").strip().rstrip("/")
    if not value:
        raise ValueError("chat base URL is required")
    if value.endswith("/chat/completions"):
        return value
    if re.search(r"/v\d+$", value):
        return f"{value}/chat/completions"
    return f"{value}/v1/chat/completions"


def _normalize_slug(value: str | None) -> str | None:
    slug = (value or "").strip().lower()
    if not slug:
        return None
    return re.sub(r"[^a-z0-9-]+", "-", slug).strip("-") or None


def _strip_html(html: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", html or "", flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _truncate(text: str, limit: int) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    cutoff = limit - 3
    truncated = value[:cutoff].rstrip()
    if " " in truncated:
        word_safe = truncated.rsplit(" ", 1)[0].rstrip(" ,;:-")
        if word_safe and len(word_safe) >= max(8, cutoff // 2):
            truncated = word_safe
    truncated = truncated.rstrip(" ,;:-")
    if not truncated:
        truncated = value[:cutoff].rstrip()
    return truncated + "..."


def _sanitize_model_text(raw_text: str) -> str:
    text = (raw_text or "").strip().replace("\ufeff", "")
    fenced = _CODE_FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    if text.lower().startswith("json"):
        remainder = text[4:].lstrip()
        if remainder.startswith("{"):
            text = remainder
    return text


def _extract_balanced_json_object(raw_text: str) -> str:
    text = _sanitize_model_text(raw_text)
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model output")

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("No complete JSON object found in model output")


def _repair_json_text(candidate: str) -> str:
    repaired = candidate.replace("\u201c", '"').replace("\u201d", '"')
    repaired = repaired.replace("\u2018", "'").replace("\u2019", "'")
    return _TRAILING_COMMA_RE.sub(r"\1", repaired)


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    candidate = _extract_balanced_json_object(raw_text)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return json.loads(_repair_json_text(candidate))


def _default_target_keyword(record: ArchiveRecord) -> str:
    base = record.related_property_title or record.title or record.archive_slug.replace("-", " ")
    normalized = re.sub(r"[^a-z0-9 ]+", " ", base.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        normalized = record.archive_slug.replace("-", " ")
    return f"{normalized} guest review".strip()


def _default_review_schema(record: ArchiveRecord, review_body: str) -> dict[str, Any]:
    reviewed_name = (
        record.related_property_title
        or record.title
        or record.archive_slug.replace("-", " ").title()
    )
    return {
        "@context": "https://schema.org",
        "@type": "Review",
        "name": record.title or reviewed_name,
        "reviewBody": _truncate(review_body, 600),
        "itemReviewed": {
            "@type": "VacationRental",
            "name": reviewed_name,
        },
    }


def _normalize_faq(raw_value: Any) -> list[dict[str, str]]:
    if not isinstance(raw_value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in raw_value[:5]:
        if not isinstance(item, dict):
            continue
        question = _truncate(str(item.get("q") or item.get("question") or "").strip(), 300)
        answer = _truncate(str(item.get("a") or item.get("answer") or "").strip(), 1200)
        if question and answer:
            normalized.append({"q": question, "a": answer})
    return normalized


def _normalize_generated_proposal(raw: dict[str, Any], record: ArchiveRecord) -> dict[str, Any]:
    review_text = _strip_html(record.content_body)
    target_keyword = _truncate(
        str(raw.get("target_keyword") or _default_target_keyword(record)).strip(),
        255,
    )
    title = _truncate(
        str(raw.get("title") or f"{record.title} | Archived Guest Review").strip(),
        TITLE_LIMIT,
    )
    meta_description = _truncate(
        str(
            raw.get("meta_description")
            or f"Read this authentic historical guest review for {record.title or record.archive_slug.replace('-', ' ')}."
        ).strip(),
        META_DESCRIPTION_LIMIT,
    )
    h1 = _truncate(str(raw.get("h1") or record.title or record.archive_slug.replace("-", " ").title()).strip(), 255)
    intro = _truncate(
        str(
            raw.get("intro")
            or f"Verified historical testimonial preserved from the Cabin Rentals of Georgia archive for {record.title or record.archive_slug.replace('-', ' ')}."
        ).strip(),
        1200,
    )
    json_ld = raw.get("json_ld") if isinstance(raw.get("json_ld"), dict) else {}
    if not json_ld:
        json_ld = _default_review_schema(record, review_text)
    return {
        "target_keyword": target_keyword,
        "title": title,
        "meta_description": meta_description,
        "h1": h1,
        "intro": intro,
        "faq": _normalize_faq(raw.get("faq")),
        "json_ld": json_ld,
    }


def _build_source_snapshot(record: ArchiveRecord) -> dict[str, Any]:
    review_text = _strip_html(record.content_body)
    return {
        "archive_slug": record.archive_slug,
        "archive_path": record.archive_path,
        "original_slug": record.original_slug,
        "legacy_node_id": record.legacy_node_id,
        "title": record.title,
        "node_type": record.node_type,
        "body_status": record.body_status,
        "category_tags": record.category_tags,
        "signed_at": record.signed_at,
        "hmac_signature": record.hmac_signature,
        "related_property_slug": record.related_property_slug,
        "related_property_path": record.related_property_path,
        "related_property_title": record.related_property_title,
        "content_sha256": hashlib.sha256(review_text.encode("utf-8")).hexdigest(),
        "content_excerpt": _truncate(review_text, 500),
    }


def _compute_grading(record: ArchiveRecord, proposal: dict[str, Any]) -> dict[str, Any]:
    keyword = str(proposal["target_keyword"]).lower()
    title = str(proposal["title"]).lower()
    meta = str(proposal["meta_description"]).lower()
    h1 = str(proposal["h1"]).lower()
    intro = str(proposal["intro"]).lower()
    review_text = _strip_html(record.content_body).lower()
    keyword_alignment = 1.0 if keyword and keyword in f"{title} {meta} {h1}" else 0.72
    schema_quality = 1.0 if isinstance(proposal.get("json_ld"), dict) and proposal["json_ld"].get("@type") == "Review" else 0.7
    grounding = 0.95 if review_text and any(token in intro for token in review_text.split()[:8]) else 0.8
    ctr_strength = 0.9 if 40 <= len(proposal["title"]) <= 90 and 90 <= len(proposal["meta_description"]) <= 180 else 0.76
    breakdown = {
        "keyword_alignment": round(keyword_alignment, 3),
        "schema_quality": round(schema_quality, 3),
        "factual_grounding": round(grounding, 3),
        "ctr_strength": round(ctr_strength, 3),
    }
    overall = round(sum(breakdown.values()) / len(breakdown) * 100, 2)
    return {"overall": overall, "breakdown": breakdown}


def _build_api_request(record: ArchiveRecord, proposal: dict[str, Any], cfg: GeneratorConfig) -> dict[str, Any]:
    source_snapshot = _build_source_snapshot(record)
    return {
        "target_type": "archive_review",
        "target_slug": record.archive_slug,
        "target_keyword": proposal["target_keyword"],
        "campaign": cfg.campaign,
        "rubric_version": cfg.rubric_version,
        "source_snapshot": source_snapshot,
        "proposal": {
            "title": proposal["title"],
            "meta_description": proposal["meta_description"],
            "h1": proposal["h1"],
            "intro": proposal["intro"],
            "faq": proposal["faq"],
            "json_ld": proposal["json_ld"],
        },
        "grading": _compute_grading(record, proposal),
        "proposed_by": cfg.proposed_by,
        "proposal_run_id": cfg.run_id,
    }


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return "'" + encoded.replace("'", "''") + "'::jsonb"
    return "'" + str(value).replace("'", "''") + "'"


def _build_sql_upsert(request_body: dict[str, Any]) -> str:
    proposal = request_body["proposal"]
    grading = request_body["grading"]
    source_snapshot = request_body["source_snapshot"]
    source_hash = _source_hash(
        target_type=request_body["target_type"],
        target_slug=request_body["target_slug"],
        campaign=request_body["campaign"],
        rubric_version=request_body["rubric_version"],
        source_snapshot=source_snapshot,
    )
    return f"""INSERT INTO seo_patch_queue (
    id,
    target_type,
    target_slug,
    property_id,
    status,
    target_keyword,
    campaign,
    rubric_version,
    source_hash,
    proposed_title,
    proposed_meta_description,
    proposed_h1,
    proposed_intro,
    proposed_faq,
    proposed_json_ld,
    fact_snapshot,
    score_overall,
    score_breakdown,
    proposed_by,
    proposal_run_id,
    approved_payload,
    approved_at,
    deployed_at,
    created_at,
    updated_at
) VALUES (
    {_sql_literal(str(uuid4()))},
    {_sql_literal(request_body["target_type"])},
    {_sql_literal(request_body["target_slug"])},
    NULL,
    'proposed',
    {_sql_literal(request_body["target_keyword"])},
    {_sql_literal(request_body["campaign"])},
    {_sql_literal(request_body["rubric_version"])},
    {_sql_literal(source_hash)},
    {_sql_literal(proposal["title"])},
    {_sql_literal(proposal["meta_description"])},
    {_sql_literal(proposal["h1"])},
    {_sql_literal(proposal["intro"])},
    {_sql_literal(proposal["faq"])},
    {_sql_literal(proposal["json_ld"])},
    {_sql_literal(source_snapshot)},
    {_sql_literal(grading["overall"])},
    {_sql_literal(grading["breakdown"])},
    {_sql_literal(request_body["proposed_by"])},
    {_sql_literal(request_body["proposal_run_id"])},
    '{{}}'::jsonb,
    NULL,
    NULL,
    NOW(),
    NOW()
) ON CONFLICT (target_type, target_slug, campaign, source_hash) DO UPDATE SET
    status = 'proposed',
    target_keyword = EXCLUDED.target_keyword,
    rubric_version = EXCLUDED.rubric_version,
    proposed_title = EXCLUDED.proposed_title,
    proposed_meta_description = EXCLUDED.proposed_meta_description,
    proposed_h1 = EXCLUDED.proposed_h1,
    proposed_intro = EXCLUDED.proposed_intro,
    proposed_faq = EXCLUDED.proposed_faq,
    proposed_json_ld = EXCLUDED.proposed_json_ld,
    fact_snapshot = EXCLUDED.fact_snapshot,
    score_overall = EXCLUDED.score_overall,
    score_breakdown = EXCLUDED.score_breakdown,
    proposed_by = EXCLUDED.proposed_by,
    proposal_run_id = EXCLUDED.proposal_run_id,
    approved_payload = '{{}}'::jsonb,
    approved_at = NULL,
    deployed_at = NULL,
    updated_at = NOW();"""


def _parse_archive_record(path: Path) -> ArchiveRecord | None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    archive_slug = _normalize_slug(payload.get("archive_slug"))
    body_status = str(payload.get("body_status") or "").strip().lower()
    content_body = str(payload.get("content_body") or "").strip()
    if not archive_slug or not content_body or body_status not in {"verified", "cache_hit", "restored", "local_cache"}:
        return None
    return ArchiveRecord(
        source_file=path,
        legacy_node_id=str(payload.get("legacy_node_id") or archive_slug),
        original_slug=str(payload.get("original_slug") or ""),
        archive_slug=archive_slug,
        archive_path=str(payload.get("archive_path") or f"/reviews/archive/{archive_slug}"),
        title=str(payload.get("title") or archive_slug.replace("-", " ").title()).strip(),
        content_body=content_body,
        body_status=body_status,
        category_tags=[str(tag).strip() for tag in payload.get("category_tags", []) if str(tag).strip()],
        node_type=str(payload.get("node_type") or "testimonial").strip(),
        signed_at=str(payload.get("signed_at")).strip() if payload.get("signed_at") else None,
        hmac_signature=str(payload.get("hmac_signature") or "").strip(),
        related_property_slug=_normalize_slug(payload.get("related_property_slug")),
        related_property_path=str(payload.get("related_property_path")).strip() if payload.get("related_property_path") else None,
        related_property_title=str(payload.get("related_property_title")).strip() if payload.get("related_property_title") else None,
    )


def _load_archive_records(cfg: GeneratorConfig) -> list[ArchiveRecord]:
    paths = sorted(cfg.archive_dir.glob("*.json"))
    records: list[ArchiveRecord] = []
    for path in paths:
        record = _parse_archive_record(path)
        if record is None:
            continue
        if cfg.only_slug and record.archive_slug != cfg.only_slug:
            continue
        records.append(record)
        if cfg.limit is not None and len(records) >= cfg.limit:
            break
    return records


def _build_prompt(record: ArchiveRecord) -> str:
    review_text = _strip_html(record.content_body)
    return f"""Generate a JSON object with exactly these keys:
target_keyword, title, meta_description, h1, intro, faq, json_ld

Constraints:
- target_keyword: <=255 chars
- title: <=60 chars
- meta_description: <=160 chars
- h1: <=255 chars
- intro: 1 short paragraph grounded in the archive review
- faq: array of 0-3 items with keys q and a
- json_ld: schema.org Review with nested VacationRental in itemReviewed when possible
- Do not invent facts not present in the review or record metadata

Archive metadata:
- archive_slug: {record.archive_slug}
- archive_path: {record.archive_path}
- title: {record.title}
- related_property_title: {record.related_property_title or ""}
- related_property_slug: {record.related_property_slug or ""}
- category_tags: {", ".join(record.category_tags) if record.category_tags else "none"}

Historical testimonial:
{review_text[:5000]}
"""


def _extract_model_text(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices")
    if isinstance(choices, list) and choices:
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    if isinstance(response_json.get("response"), str):
        return response_json["response"].strip()
    message = response_json.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"].strip()
    raise ValueError("Unrecognized chat completion response payload")


async def _generate_for_record(
    client: httpx.AsyncClient,
    cfg: GeneratorConfig,
    record: ArchiveRecord,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": cfg.system_message},
            {"role": "user", "content": _build_prompt(record)},
        ],
        "stream": False,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }
    if cfg.disable_thinking:
        payload["think"] = False
    attempts = [payload]
    if cfg.force_json_response:
        attempts = [{**payload, "response_format": JSON_RESPONSE_FORMAT}, payload]

    last_error: Exception | None = None
    model_text = ""
    for attempt_index, attempt_payload in enumerate(attempts):
        try:
            response = await client.post(cfg.chat_completions_url, json=attempt_payload)
            response.raise_for_status()
            model_text = _extract_model_text(response.json())
            break
        except httpx.HTTPStatusError as exc:
            last_error = exc
            unsupported_response_format = (
                "response_format" in attempt_payload and exc.response.status_code in {400, 404, 415, 422, 500, 501}
            )
            if unsupported_response_format and attempt_index < len(attempts) - 1:
                continue
            raise
    else:
        raise last_error or RuntimeError(f"Generation failed for slug '{record.archive_slug}'")

    proposal = _normalize_generated_proposal(_extract_json_object(model_text), record)
    return _build_api_request(record, proposal, cfg)


async def _post_bulk_proposals(
    _client: httpx.AsyncClient,
    _cfg: GeneratorConfig,
    _items: list[dict[str, Any]],
) -> dict[str, Any]:
    raise RuntimeError(
        "Archive bulk proposal API posting has been retired. "
        "Archive SEO still relies on the legacy read-through bridge until a canonical SEOPatch archive ingest contract exists."
    )


async def _load_completed_slugs(cfg: GeneratorConfig) -> set[str]:
    import asyncpg

    conn = await asyncpg.connect(settings.database_url)
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT target_slug
            FROM seo_patch_queue
            WHERE target_type = 'archive_review'
              AND campaign = $1
            """,
            cfg.campaign,
        )
    finally:
        await conn.close()
    return {
        str(row["target_slug"]).strip().lower()
        for row in rows
        if row["target_slug"]
    }


async def _run(cfg: GeneratorConfig) -> int:
    source_records = _load_archive_records(replace(cfg, limit=None))
    completed_slugs: set[str] = set()
    if cfg.db_resume:
        completed_slugs = await _load_completed_slugs(cfg)
    records = [record for record in source_records if record.archive_slug not in completed_slugs]
    if cfg.limit is not None:
        records = records[: cfg.limit]
    print(
        f"Resume preflight: total={len(source_records)} completed={len(completed_slugs)} delta={len(records)} "
        f"campaign={cfg.campaign}"
    )
    if not records:
        print("No archive records remain after database resume filtering.")
        return 0

    cert = None
    if cfg.client_cert and cfg.client_key:
        cert = (cfg.client_cert, cfg.client_key)

    timeout = httpx.Timeout(
        connect=cfg.connect_timeout_s,
        read=cfg.read_timeout_s,
        write=cfg.write_timeout_s,
        pool=cfg.pool_timeout_s,
    )
    limits = httpx.Limits(max_connections=max(cfg.concurrency, 1), max_keepalive_connections=max(cfg.concurrency, 1))
    semaphore = asyncio.Semaphore(max(cfg.concurrency, 1))
    db_lock = asyncio.Lock()
    errors: list[dict[str, str]] = []

    db_conn = None
    if cfg.write_db:
        import asyncpg

        db_conn = await asyncpg.connect(settings.database_url)

    async with httpx.AsyncClient(timeout=timeout, limits=limits, verify=cfg.verify_ssl, cert=cert) as client:
        async def worker(record: ArchiveRecord) -> dict[str, Any] | None:
            async with semaphore:
                try:
                    item = await _generate_for_record(client, cfg, record)
                    if db_conn is not None:
                        async with db_lock:
                            await db_conn.execute(_build_sql_upsert(item))
                    return item
                except Exception as exc:
                    errors.append({"archive_slug": record.archive_slug, "error": str(exc)})
                    print(f"ERROR [{record.archive_slug}]: {exc}")
                    return None

        generated = await asyncio.gather(*(worker(record) for record in records))
        items = [item for item in generated if item is not None]

        api_result = None
        if cfg.post_api and not cfg.dry_run:
            api_result = await _post_bulk_proposals(client, cfg, items)

    if db_conn is not None:
        await db_conn.close()

    if not items:
        print("No archive SEO proposals were generated successfully.")
        return 1

    json_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "generate_archive_seo_payloads",
        "chat_completions_url": cfg.chat_completions_url,
        "model": cfg.model,
        "campaign": cfg.campaign,
        "rubric_version": cfg.rubric_version,
        "run_id": cfg.run_id,
        "requested_hitl_status": "pending",
        "persisted_queue_status": "proposed",
        "item_count": len(items),
        "archive_dir": str(cfg.archive_dir),
        "items": items,
        "errors": errors,
        "api_result": api_result,
    }
    cfg.output_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.output_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=True), encoding="utf-8")

    sql_lines = [
        "-- Archive SEO bulk payloads",
        "-- Requested HITL state: pending",
        "-- Persisted queue state: proposed (current seo_patch_queue workflow value)",
        "",
    ]
    sql_lines.extend(_build_sql_upsert(item) for item in items)
    sql_lines.append("")
    cfg.sql_output_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.sql_output_path.write_text("\n\n".join(sql_lines), encoding="utf-8")

    print(f"Archive records processed: {len(records)}")
    print(f"Payload JSON written: {cfg.output_path}")
    print(f"SQL written: {cfg.sql_output_path}")
    if cfg.write_db:
        print(f"Direct DB upserts applied: {len(items)} item(s)")
    if api_result is not None:
        print(f"Bulk proposal API posted: {len(items)} item(s)")
    else:
        print("Bulk proposal API posting skipped.")
    if errors:
        print(f"Generation completed with {len(errors)} error(s).")
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate SEO payloads for archive testimonial pages.")
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--sql-output", type=Path, default=DEFAULT_SQL_OUTPUT_PATH)
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--chat-base-url", default=DEFAULT_CHAT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--campaign", default=os.getenv("SEO_ARCHIVE_CAMPAIGN", "archive_restore_2026"))
    parser.add_argument("--rubric-version", default=os.getenv("SEO_ARCHIVE_RUBRIC_VERSION", "nemotron_archive_v1"))
    parser.add_argument("--proposed-by", default=os.getenv("SEO_ARCHIVE_PROPOSED_BY", "dgx-nemotron"))
    parser.add_argument("--run-id", default=os.getenv("SEO_ARCHIVE_RUN_ID", f"archive-seo-{uuid4().hex[:12]}"))
    parser.add_argument("--concurrency", type=int, default=int(os.getenv("SEO_ARCHIVE_CONCURRENCY", "4")))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--slug", default=None, help="Restrict generation to one archive slug.")
    parser.add_argument(
        "--post-api",
        action="store_true",
        help="Retired. Archive bulk proposal posting is disabled until canonical /api/seo archive ingest exists.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Generate files only; do not POST to the API.")
    parser.add_argument("--swarm-api-key", default=os.getenv("SWARM_API_KEY", settings.swarm_api_key))
    parser.add_argument("--system-message", default=DEFAULT_SYSTEM_MESSAGE)
    parser.add_argument("--temperature", type=float, default=float(os.getenv("SEO_ARCHIVE_TEMPERATURE", "0.2")))
    parser.add_argument("--max-tokens", type=int, default=int(os.getenv("SEO_ARCHIVE_MAX_TOKENS", "1800")))
    parser.add_argument("--connect-timeout", type=float, default=float(os.getenv("SEO_ARCHIVE_CONNECT_TIMEOUT", "15")))
    parser.add_argument("--read-timeout", type=float, default=float(os.getenv("SEO_ARCHIVE_READ_TIMEOUT", "300")))
    parser.add_argument("--write-timeout", type=float, default=float(os.getenv("SEO_ARCHIVE_WRITE_TIMEOUT", "30")))
    parser.add_argument("--pool-timeout", type=float, default=float(os.getenv("SEO_ARCHIVE_POOL_TIMEOUT", "30")))
    parser.add_argument("--client-cert", default=os.getenv("SEO_ARCHIVE_CLIENT_CERT", "").strip() or None)
    parser.add_argument("--client-key", default=os.getenv("SEO_ARCHIVE_CLIENT_KEY", "").strip() or None)
    parser.add_argument("--verify-ssl", action="store_true", default=_bool_env("SEO_ARCHIVE_VERIFY_SSL", False))
    parser.add_argument(
        "--disable-db-resume",
        action="store_true",
        default=False,
        help="Do not subtract already-persisted target_slug values for the selected campaign.",
    )
    parser.add_argument(
        "--write-db",
        action="store_true",
        default=_bool_env("SEO_ARCHIVE_WRITE_DB", False),
        help="Apply per-item SQL upserts directly to seo_patch_queue during generation.",
    )
    parser.add_argument(
        "--disable-thinking",
        action="store_true",
        default=_bool_env("SEO_ARCHIVE_DISABLE_THINKING", False),
        help="Send think=false for Ollama reasoning models that otherwise omit message.content.",
    )
    parser.add_argument(
        "--disable-json-response-format",
        action="store_true",
        help="Do not request response_format={type: json_object} from the chat endpoint.",
    )
    return parser.parse_args()


def _load_config(args: argparse.Namespace) -> GeneratorConfig:
    if not args.model:
        raise SystemExit(
            "ERROR: No DGX model configured. Pass --model or set SEO_ARCHIVE_MODEL to the deployed Nemotron alias."
        )
    if args.post_api and args.write_db:
        raise SystemExit("ERROR: Choose either --post-api or --write-db, not both.")
    only_slug = _normalize_slug(args.slug)
    return GeneratorConfig(
        archive_dir=args.archive_dir,
        output_path=args.output,
        sql_output_path=args.sql_output,
        api_base_url=str(args.api_base_url).rstrip("/"),
        chat_completions_url=_normalize_chat_completions_url(str(args.chat_base_url)),
        model=str(args.model).strip(),
        campaign=str(args.campaign).strip(),
        rubric_version=str(args.rubric_version).strip(),
        proposed_by=str(args.proposed_by).strip(),
        run_id=str(args.run_id).strip(),
        concurrency=max(1, int(args.concurrency)),
        limit=max(1, int(args.limit)) if args.limit else None,
        only_slug=only_slug,
        post_api=bool(args.post_api),
        dry_run=bool(args.dry_run),
        swarm_api_key=str(args.swarm_api_key or "").strip(),
        system_message=str(args.system_message).strip(),
        temperature=float(args.temperature),
        max_tokens=max(256, int(args.max_tokens)),
        client_cert=args.client_cert,
        client_key=args.client_key,
        verify_ssl=bool(args.verify_ssl),
        force_json_response=not bool(args.disable_json_response_format),
        disable_thinking=bool(args.disable_thinking),
        db_resume=not bool(args.disable_db_resume),
        write_db=bool(args.write_db),
        connect_timeout_s=float(args.connect_timeout),
        read_timeout_s=float(args.read_timeout),
        write_timeout_s=float(args.write_timeout),
        pool_timeout_s=float(args.pool_timeout),
    )


def main() -> int:
    args = _parse_args()
    cfg = _load_config(args)
    return asyncio.run(_run(cfg))


if __name__ == "__main__":
    raise SystemExit(main())
