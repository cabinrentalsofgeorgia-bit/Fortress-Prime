"""
DGX Swarm rewrite worker for SEO patches rejected by the God Head.

Consumes fortress:seo:rewrite_requests, generates an improved payload with the
swarm model, and posts it back into POST /api/seo/patches/{id}/rewrite.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.seo_patch import SEOPatch, SEORubric
from backend.services.swarm_service import submit_chat_completion
from backend.vrs.infrastructure.seo_event_bus import (
    SEOEventBus,
    SEO_QUEUE_REWRITE_REQUESTS,
    parse_swarm_event,
)

logger = logging.getLogger(__name__)

REWRITE_POST_TIMEOUT = httpx.Timeout(connect=10, read=45, write=15, pool=10)
DEFAULT_SEO_PATCH_API_BASE_URL = "http://127.0.0.1:8100"
SYSTEM_PROMPT = (
    "You are the Fortress Prime SEO rewrite swarm. "
    "You receive a failed SEO patch plus God Head feedback and must return ONLY "
    "a valid JSON object with keys: title, meta_description, og_title, "
    "og_description, jsonld_payload, canonical_url, h1_suggestion, alt_tags. "
    "Honor all rubric constraints exactly. Do not include markdown or commentary."
)

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


def _sanitize_model_text(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines.pop()
        text = "\n".join(lines).strip()

    json_prefix_match = re.match(r"^(json|JSON)\s*", text)
    if json_prefix_match:
        text = text[json_prefix_match.end() :].lstrip(": \n\t")

    return text


def _extract_balanced_json_object(raw_text: str) -> str:
    text = _sanitize_model_text(raw_text)
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in rewrite output")

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

    raise ValueError("No complete JSON object found in rewrite output")


def _repair_json_text(candidate: str) -> str:
    repaired = candidate.replace("\u201c", '"').replace("\u201d", '"')
    repaired = repaired.replace("\u2018", "'").replace("\u2019", "'")
    return _TRAILING_COMMA_RE.sub(r"\1", repaired)


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    candidate = _extract_balanced_json_object(raw_text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        parsed = json.loads(_repair_json_text(candidate))
    if not isinstance(parsed, dict):
        raise ValueError("Rewrite output must be a JSON object")
    return parsed


class SEORewriteSwarmWorker:
    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client
        self.event_bus = SEOEventBus(redis_client)
        self.running = False
        self.model = str(settings.seo_redirect_swarm_model or settings.swarm_model or "nemotron-3-super-120b").strip()
        self.backend_base_url = os.getenv("SEO_PATCH_API_BASE_URL", DEFAULT_SEO_PATCH_API_BASE_URL).rstrip("/")
        self.swarm_token = (settings.swarm_seo_api_key or settings.swarm_api_key or "").strip()

    async def start(self) -> None:
        self.running = True
        logger.info("SEO Rewrite Swarm: ONLINE. Listening for rewrite_requests.")

        while self.running:
            try:
                result = await self.redis.brpop([SEO_QUEUE_REWRITE_REQUESTS], timeout=5)
                if result:
                    _, message = result
                    await self._process_message(message)
            except asyncio.CancelledError:
                logger.info("SEO rewrite worker received cancellation signal. Shutting down.")
                self.running = False
            except Exception as exc:  # noqa: BLE001
                logger.error("SEO rewrite worker fatal loop error: %s", exc)
                await asyncio.sleep(5)

    def stop(self) -> None:
        self.running = False

    async def _push_dlq(
        self,
        *,
        message: str,
        error: str,
        task_id: UUID | None = None,
        context_refs: list[UUID] | None = None,
    ) -> None:
        resolved_task_id = task_id or uuid4()
        resolved_context_refs = context_refs or [resolved_task_id]
        await self.event_bus.publish_swarm_dlq(
            task_id=resolved_task_id,
            source_agent="seo_rewrite_swarm",
            failed_queue=SEO_QUEUE_REWRITE_REQUESTS,
            context_refs=resolved_context_refs,
            error=error,
            final_trace={
                "error_code": "rewrite_request_failed",
                "raw_message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
                "raw_message_length": len(message),
            },
        )

    async def _process_message(self, message: str) -> None:
        try:
            envelope = parse_swarm_event(
                message,
                expected_queue=SEO_QUEUE_REWRITE_REQUESTS,
                legacy_source_agent="seo_grading_service",
                legacy_status="failed",
            )
            patch_id = envelope.primary_context_ref
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.error("Malformed message on rewrite_requests → DLQ. Error: %s", exc)
            await self._push_dlq(message=message, error=str(exc))
            return

        async with AsyncSessionLocal() as db:
            patch = (await db.execute(select(SEOPatch).where(SEOPatch.id == patch_id))).scalar_one_or_none()
            if not patch:
                logger.error("Rewrite patch %s not found → DLQ.", patch_id)
                await self._push_dlq(
                    message=message,
                    error="patch not found",
                    task_id=envelope.task_id,
                    context_refs=[patch_id],
                )
                return

            if patch.status != "needs_rewrite":
                logger.info(
                    "Skipping stale rewrite request for patch %s in status %s.",
                    patch_id,
                    patch.status,
                )
                return

            rubric = None
            if patch.rubric_id:
                rubric = (await db.execute(select(SEORubric).where(SEORubric.id == patch.rubric_id))).scalar_one_or_none()
            if not rubric:
                logger.error("Rewrite patch %s missing rubric → DLQ.", patch_id)
                await self._push_dlq(
                    message=message,
                    error="rubric not found",
                    task_id=envelope.task_id,
                    context_refs=[patch_id],
                )
                return

            try:
                rewrite_feedback = patch.godhead_feedback if isinstance(patch.godhead_feedback, dict) else {}
                rewrite_payload = await self._generate_rewrite_payload(
                    patch=patch,
                    rubric=rubric,
                    feedback=rewrite_feedback,
                )
                await self._post_rewrite(patch.id, rewrite_payload)
                logger.info(
                    "SEO rewrite submitted for patch %s via model %s.",
                    patch.id,
                    rewrite_payload.get("swarm_model"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("SEO rewrite swarm failed for patch %s", patch.id)
                await self._push_dlq(
                    message=message,
                    error=str(exc),
                    task_id=envelope.task_id,
                    context_refs=[patch.id],
                )

    async def _generate_rewrite_payload(
        self,
        *,
        patch: SEOPatch,
        rubric: SEORubric,
        feedback: dict[str, Any],
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        prompt = json.dumps(
            {
                "task": "Rewrite the failed SEO patch so it satisfies the rubric and fixes all feedback.",
                "rubric": rubric.rubric_payload,
                "godhead_feedback": feedback,
                "current_patch": {
                    "page_path": patch.page_path,
                    "title": patch.title,
                    "meta_description": patch.meta_description,
                    "og_title": patch.og_title,
                    "og_description": patch.og_description,
                    "jsonld_payload": patch.jsonld_payload,
                    "canonical_url": patch.canonical_url,
                    "h1_suggestion": patch.h1_suggestion,
                    "alt_tags": patch.alt_tags,
                },
                "response_contract": {
                    "title": "string",
                    "meta_description": "string",
                    "og_title": "string_or_null",
                    "og_description": "string_or_null",
                    "jsonld_payload": "object",
                    "canonical_url": "string_or_null",
                    "h1_suggestion": "string_or_null",
                    "alt_tags": "object_or_null",
                },
            },
            ensure_ascii=True,
            default=str,
        )

        response = await submit_chat_completion(
            prompt=prompt,
            model=self.model,
            system_message=SYSTEM_PROMPT,
            timeout_s=180.0,
            extra_payload={"temperature": 0.1, "max_tokens": 1800},
        )
        parsed = _extract_json_object(_extract_message_content(response))

        generation_ms = max(1, int((time.perf_counter() - started_at) * 1000))
        return {
            "property_id": str(patch.property_id) if patch.property_id else None,
            "rubric_id": str(patch.rubric_id) if patch.rubric_id else None,
            "page_path": patch.page_path,
            "title": str(parsed.get("title") or patch.title or "").strip(),
            "meta_description": str(parsed.get("meta_description") or patch.meta_description or "").strip(),
            "og_title": str(parsed.get("og_title")).strip() if parsed.get("og_title") is not None else patch.og_title,
            "og_description": str(parsed.get("og_description")).strip() if parsed.get("og_description") is not None else patch.og_description,
            "jsonld_payload": parsed.get("jsonld_payload") if isinstance(parsed.get("jsonld_payload"), dict) else (patch.jsonld_payload or {}),
            "canonical_url": str(parsed.get("canonical_url")).strip() if parsed.get("canonical_url") is not None else patch.canonical_url,
            "h1_suggestion": str(parsed.get("h1_suggestion")).strip() if parsed.get("h1_suggestion") is not None else patch.h1_suggestion,
            "alt_tags": parsed.get("alt_tags") if isinstance(parsed.get("alt_tags"), dict) else (patch.alt_tags or {}),
            "swarm_model": self.model,
            "swarm_node": settings.node_ip,
            "generation_ms": generation_ms,
        }

    async def _post_rewrite(self, patch_id: UUID, payload: dict[str, Any]) -> None:
        headers = {"Content-Type": "application/json"}
        if self.swarm_token:
            headers["Authorization"] = f"Bearer {self.swarm_token}"

        async with httpx.AsyncClient(timeout=REWRITE_POST_TIMEOUT) as client:
            response = await client.post(
                f"{self.backend_base_url}/api/seo/patches/{patch_id}/rewrite",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
