"""
God Head SEO Grading Worker — BRPOP consumer for fortress:seo:grade_requests.

Hydrates patch + rubric from Postgres, masks sovereign data before any Tier 1
evaluation, ships the grading request to the LiteLLM gateway, and routes the
result: pass -> pending_human, fail -> rewrite, or abort -> swarm DLQ.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any
from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.property import Property
from backend.models.seo_patch import SEOPatch, SEORubric
from backend.services.privacy_router import sanitize_for_cloud
from backend.vrs.infrastructure.seo_event_bus import (
    SEOEventBus,
    SEO_QUEUE_GRADE_REQUESTS,
    SwarmEventEnvelope,
    parse_swarm_event,
)

logger = structlog.get_logger(service="seo_grading_service")

LITELLM_TIMEOUT = httpx.Timeout(connect=10, read=300, write=10, pool=10)

SYSTEM_PROMPT = (
    "You are the God Head SEO Evaluator. Evaluate the provided SEO payload "
    "against the strict rubric. Return ONLY a JSON object containing two keys: "
    "'score' (float between 0.0 and 1.0) and 'feedback' (structured dict "
    "detailing failures or praise)."
)

ALLOWED_RUBRIC_KEYS = frozenset(
    {
        "title_rules",
        "meta_rules",
        "h1_rules",
        "jsonld_requirements",
        "schema_requirements",
        "canonical_rules",
        "alt_tag_rules",
        "scoring_dimensions",
        "content_constraints",
        "quality_checks",
        "required_terms",
        "forbidden_terms",
    }
)


class FrontierRoute:
    """Resolved LiteLLM route for a Tier 1 evaluator request."""

    def __init__(self, provider: str, model_name: str, reason: str) -> None:
        self.provider = provider
        self.model_name = model_name
        self.reason = reason


class SEOGradingWorker:
    """
    Background consumer that evaluates DGX Swarm-generated SEO patches
    against God Head rubrics via the LiteLLM gateway.
    """

    SOURCE_AGENT = "seo_grading_service"

    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client
        self.event_bus = SEOEventBus(redis_client)
        self.running = False
        self.max_attempts: int = settings.seo_max_rewrite_attempts
        self.min_score: float = settings.seo_godhead_min_score

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self.running = True
        logger.info("seo_grading_worker_started", queue=SEO_QUEUE_GRADE_REQUESTS)

        while self.running:
            try:
                result = await self.redis.brpop([SEO_QUEUE_GRADE_REQUESTS], timeout=5)
                if result:
                    _, message = result
                    await self._process_message(message)
            except asyncio.CancelledError:
                logger.info("seo_grading_worker_cancelled")
                self.running = False
            except Exception as exc:
                logger.error("seo_grading_worker_loop_error", error=str(exc)[:400])
                await asyncio.sleep(5)

    def stop(self) -> None:
        self.running = False

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    async def _process_message(self, message: str) -> None:
        try:
            envelope = parse_swarm_event(
                message,
                expected_queue=SEO_QUEUE_GRADE_REQUESTS,
                legacy_source_agent="seo_extraction_service",
                legacy_status="drafted",
            )
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("seo_grading_malformed_message", error=str(exc)[:400])
            await self._push_dlq_for_raw_message(message, error=str(exc))
            return

        async with AsyncSessionLocal() as db:
            await self._execute_grading_cycle(db, envelope)

    async def _execute_grading_cycle(
        self,
        db: AsyncSession,
        envelope: SwarmEventEnvelope,
    ) -> None:
        patch_id = envelope.primary_context_ref
        patch = (await db.execute(select(SEOPatch).where(SEOPatch.id == patch_id))).scalar_one_or_none()

        if not patch or not patch.rubric_id:
            logger.error("seo_grading_patch_or_rubric_missing", patch_id=str(patch_id))
            await self._publish_dlq(
                task_id=envelope.task_id,
                context_refs=[patch_id],
                error="patch or rubric missing",
                final_trace={"source_agent": envelope.source_agent},
            )
            return

        rubric = (await db.execute(select(SEORubric).where(SEORubric.id == patch.rubric_id))).scalar_one_or_none()

        if not rubric:
            logger.error("seo_grading_rubric_not_found", patch_id=str(patch.id), rubric_id=str(patch.rubric_id))
            await self._publish_dlq(
                task_id=envelope.task_id,
                context_refs=[patch.id],
                error="rubric not found",
                final_trace={"rubric_id": str(patch.rubric_id)},
            )
            return

        effective_min_score = max(self.min_score, float(rubric.min_pass_score))
        if patch.grade_attempts >= self.max_attempts:
            await self._escalate_patch_to_pending_human(
                db,
                patch=patch,
                threshold=effective_min_score,
                route=None,
            )
            logger.warning(
                "seo_grading_max_attempts_already_reached",
                patch_id=str(patch_id),
                threshold=effective_min_score,
                grade_attempts=patch.grade_attempts,
            )
            return

        property_record = await db.get(Property, patch.property_id) if patch.property_id else None
        patch.status = "grading"
        await db.commit()
        await db.refresh(patch)
        route = self._resolve_frontier_route(patch=patch, rubric=rubric)
        score, feedback = await self._call_godhead(
            patch=patch,
            rubric=rubric,
            property_record=property_record,
            route=route,
        )

        if score is None:
            await self._publish_dlq(
                task_id=envelope.task_id,
                context_refs=[patch.id],
                error="frontier consensus evaluation returned no score",
                final_trace={"route": route.model_name},
            )
            return

        patch.grade_attempts += 1
        patch.godhead_score = score
        patch.godhead_feedback = feedback
        patch.godhead_model = route.model_name

        if score >= effective_min_score:
            patch.status = "pending_human"
            logger.info(
                "seo_grading_passed",
                patch_id=str(patch_id),
                score=score,
                threshold=effective_min_score,
                grade_attempts=patch.grade_attempts,
                route=route.model_name,
            )
        elif patch.grade_attempts < self.max_attempts:
            patch.status = "needs_rewrite"
            logger.warning(
                "seo_grading_needs_rewrite",
                patch_id=str(patch_id),
                score=score,
                threshold=effective_min_score,
                grade_attempts=patch.grade_attempts,
                route=route.model_name,
            )
            await db.commit()
            await self.event_bus.publish_rewrite_request(
                patch.id,
                feedback,
                source_agent=self.SOURCE_AGENT,
                task_id=envelope.task_id,
            )
            return
        else:
            await self._escalate_patch_to_pending_human(
                db,
                patch=patch,
                threshold=effective_min_score,
                route=route,
                score=score,
            )
            logger.warning(
                "seo_grading_escalated_to_human",
                patch_id=str(patch_id),
                score=score,
                threshold=effective_min_score,
                grade_attempts=patch.grade_attempts,
                route=route.model_name,
            )

        await db.commit()

    async def _escalate_patch_to_pending_human(
        self,
        db: AsyncSession,
        *,
        patch: SEOPatch,
        threshold: float,
        route: FrontierRoute | None,
        score: float | None = None,
    ) -> None:
        patch.status = "pending_human"
        warning_payload = {
            "warning": {
                "max_rewrite_attempts_reached": True,
                "grade_attempts": patch.grade_attempts,
                "threshold": threshold,
                "score": score if score is not None else patch.godhead_score,
                "route": route.model_name if route is not None else patch.godhead_model,
            }
        }
        merged_feedback = patch.godhead_feedback if isinstance(patch.godhead_feedback, dict) else {}
        patch.godhead_feedback = {**merged_feedback, **warning_payload}
        await db.commit()

    # ------------------------------------------------------------------
    # LiteLLM gateway call
    # ------------------------------------------------------------------

    async def _call_godhead(
        self,
        patch: SEOPatch,
        rubric: SEORubric,
        property_record: Property | None,
        route: FrontierRoute,
    ) -> tuple[float | None, dict[str, Any]]:
        """Ship evaluation to the local gateway; fall back to deterministic grading if unavailable."""
        masked_payload, external_safe = self._build_masked_evaluation_payload(
            patch=patch,
            rubric=rubric,
            property_record=property_record,
        )
        if route.provider != "local" and not external_safe:
            logger.warning(
                "Frontier safety gate forcing local grading route for patch %s.",
                patch.id,
            )
            route = FrontierRoute("local", settings.seo_godhead_model, "frontier safety gate")
        user_prompt = json.dumps(
            masked_payload,
            default=str,
            ensure_ascii=True,
        )

        base_url = settings.litellm_base_url.rstrip("/")
        request_payload = {
            "model": route.model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }
        headers = {
            "Authorization": f"Bearer {settings.litellm_master_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=LITELLM_TIMEOUT) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    json=request_payload,
                    headers=headers,
                )
                resp.raise_for_status()

            raw_eval = _extract_message_content(resp.json())
            evaluation = _extract_json_object(raw_eval)

            feedback = _normalize_feedback(evaluation.get("feedback"))
            feedback.setdefault("frontier_provider", route.provider)
            feedback.setdefault("frontier_model", route.model_name)
            feedback.setdefault("route_reason", route.reason)
            return float(evaluation.get("score", 0.0)), feedback

        except Exception:
            logger.warning(
                "LiteLLM God Head evaluation failed for %s via %s. Falling back to deterministic grading.",
                patch.id,
                route.model_name,
            )
            return _simulate_godhead_evaluation(patch, rubric, route)

    async def _push_dlq_for_raw_message(self, message: str, *, error: str) -> None:
        task_id = uuid4()
        context_refs: list[UUID] = [task_id]
        try:
            payload = json.loads(message)
            if isinstance(payload, dict):
                raw_task_id = payload.get("task_id")
                raw_patch_id = payload.get("patch_id")
                if raw_task_id:
                    task_id = UUID(str(raw_task_id))
                    context_refs = [task_id]
                if raw_patch_id:
                    context_refs = [UUID(str(raw_patch_id))]
        except Exception:
            pass

        await self._publish_dlq(
            task_id=task_id,
            context_refs=context_refs,
            error=error,
            final_trace={
                "error_code": "malformed_grade_request",
                "raw_message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
                "raw_message_length": len(message),
            },
        )

    async def _publish_dlq(
        self,
        *,
        task_id: UUID,
        context_refs: list[UUID],
        error: str,
        final_trace: dict[str, Any],
    ) -> None:
        await self.event_bus.publish_swarm_dlq(
            task_id=task_id,
            source_agent=self.SOURCE_AGENT,
            failed_queue=SEO_QUEUE_GRADE_REQUESTS,
            context_refs=context_refs,
            error=error,
            final_trace=final_trace,
        )

    def _resolve_frontier_route(self, *, patch: SEOPatch, rubric: SEORubric) -> FrontierRoute:
        rubric_payload = rubric.rubric_payload if isinstance(rubric.rubric_payload, dict) else {}
        explicit_route = str(
            rubric_payload.get("frontier_route") or rubric_payload.get("preferred_frontier_model") or ""
        ).strip().lower()
        prompt_size = len(json.dumps(rubric_payload, default=str)) + len(patch.meta_description or "")

        if explicit_route in {"gemini", "google"} and settings.gemini_model:
            return FrontierRoute("google", settings.gemini_model, "rubric route override")
        if explicit_route in {"xai", "grok"} and settings.xai_model:
            return FrontierRoute("xai", settings.xai_model, "rubric route override")
        if explicit_route in {"anthropic", "claude"} and settings.anthropic_model:
            return FrontierRoute("anthropic", settings.anthropic_model, "rubric route override")
        if explicit_route in {"openai", "gpt-4o", "gpt4o"} and settings.openai_model:
            return FrontierRoute("openai", settings.openai_model, "rubric route override")
        if explicit_route in {"local", "nemotron", "nemotron-3-super-120b"} and settings.seo_godhead_model:
            return FrontierRoute("local", settings.seo_godhead_model, "rubric route override")
        if prompt_size >= 12000 and settings.gemini_model:
            return FrontierRoute("google", settings.gemini_model, "large masked context")

        rubric_text = json.dumps(rubric_payload, default=str).lower()
        if "schema" in rubric_text and settings.xai_model:
            return FrontierRoute("xai", settings.xai_model, "schema adherence bias")
        if settings.anthropic_model:
            return FrontierRoute("anthropic", settings.anthropic_model, "default strategic reviewer")
        if settings.openai_model:
            return FrontierRoute("openai", settings.openai_model, "default strategic reviewer")
        return FrontierRoute("local", settings.seo_godhead_model, "local fallback route")

    def _build_masked_evaluation_payload(
        self,
        *,
        patch: SEOPatch,
        rubric: SEORubric,
        property_record: Property | None,
    ) -> tuple[dict[str, Any], bool]:
        payload = {
            "rubric_contract": self._build_rubric_contract(rubric, property_record),
            "proposed_payload": {
                "title": self._scrub_frontier_text(patch.title, property_record),
                "meta_description": self._scrub_frontier_text(patch.meta_description, property_record),
                "og_title": self._scrub_frontier_text(patch.og_title, property_record),
                "og_description": self._scrub_frontier_text(patch.og_description, property_record),
                "h1_suggestion": self._scrub_frontier_text(patch.h1_suggestion, property_record),
                "jsonld_summary": self._summarize_jsonld_payload(patch.jsonld_payload, property_record),
                "canonical_present": bool((patch.canonical_url or "").strip()),
                "alt_tags": {
                    str(key): self._scrub_frontier_text(value, property_record)
                    for key, value in (patch.alt_tags or {}).items()
                }
                if isinstance(patch.alt_tags, dict)
                else {},
            },
        }
        privacy_decision = sanitize_for_cloud(payload)
        redacted_payload = privacy_decision.redacted_payload if isinstance(privacy_decision.redacted_payload, dict) else payload
        redacted_payload["safety_contract"] = {
            "external_payload_class": "masked_minimum_necessary",
            "redaction_status": privacy_decision.redaction_status,
            "redaction_count": privacy_decision.redaction_count,
            "removed_fields": privacy_decision.removed_fields,
        }
        return redacted_payload, self._is_external_frontier_payload_safe(redacted_payload, property_record)

    def _build_rubric_contract(
        self,
        rubric: SEORubric,
        property_record: Property | None,
    ) -> dict[str, Any]:
        rubric_payload = rubric.rubric_payload if isinstance(rubric.rubric_payload, dict) else {}
        allowed_payload = {
            key: self._sanitize_frontier_value(value, property_record)
            for key, value in rubric_payload.items()
            if key in ALLOWED_RUBRIC_KEYS
        }
        return {
            "rubric_id": str(rubric.id),
            "min_pass_score": float(rubric.min_pass_score),
            "evaluation_rules": allowed_payload,
        }

    def _summarize_jsonld_payload(
        self,
        payload: dict[str, Any] | None,
        property_record: Property | None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"present": False, "schema_types": [], "field_presence": {}}

        schema_types = payload.get("@type")
        if isinstance(schema_types, list):
            normalized_types = [self._scrub_frontier_text(item, property_record) for item in schema_types if str(item).strip()]
        elif schema_types:
            normalized_types = [self._scrub_frontier_text(schema_types, property_record)]
        else:
            normalized_types = []

        field_presence = {
            "name": bool(payload.get("name")),
            "description": bool(payload.get("description")),
            "address": bool(payload.get("address")),
            "geo": bool(payload.get("geo")),
            "amenityFeature": bool(payload.get("amenityFeature")),
            "image": bool(payload.get("image")),
            "url": bool(payload.get("url")),
        }
        return {
            "present": True,
            "schema_types": normalized_types,
            "field_presence": field_presence,
        }

    def _sanitize_frontier_value(self, value: Any, property_record: Property | None) -> Any:
        if isinstance(value, dict):
            return {key: self._sanitize_frontier_value(child, property_record) for key, child in value.items()}
        if isinstance(value, list):
            return [self._sanitize_frontier_value(item, property_record) for item in value]
        if isinstance(value, str):
            return self._scrub_frontier_text(value, property_record)
        return value

    def _scrub_frontier_text(self, value: Any, property_record: Property | None) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        replacements = [
            ((property_record.name if property_record else None), "[PROPERTY_NAME]"),
            ((property_record.slug if property_record else None), "[PROPERTY_SLUG]"),
            ((property_record.address if property_record else None), "[PROPERTY_ADDRESS]"),
            ((property_record.owner_name if property_record else None), "[OWNER_NAME]"),
        ]
        for raw_value, replacement in replacements:
            token = str(raw_value or "").strip()
            if token:
                text = re.sub(re.escape(token), replacement, text, flags=re.IGNORECASE)

        if "https://" in text or "http://" in text:
            text = re.sub(r"https?://\S+", "[MASKED_URL]", text)

        return text

    def _is_external_frontier_payload_safe(
        self,
        payload: dict[str, Any],
        property_record: Property | None,
    ) -> bool:
        serialized = json.dumps(payload, ensure_ascii=True, default=str).lower()
        sensitive_tokens = [
            str(property_record.name or "").strip().lower() if property_record else "",
            str(property_record.slug or "").strip().lower() if property_record else "",
            str(property_record.address or "").strip().lower() if property_record else "",
            str(property_record.owner_name or "").strip().lower() if property_record else "",
        ]
        return not any(token and len(token) >= 4 and token in serialized for token in sensitive_tokens)


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


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in God Head output.")
    parsed = json.loads(raw_text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("God Head output must decode to a JSON object.")
    return parsed


def _normalize_feedback(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _simulate_godhead_evaluation(
    patch: SEOPatch,
    rubric: SEORubric,
    route: FrontierRoute,
) -> tuple[float, dict[str, Any]]:
    """
    Deterministic local fallback when the chat-completions endpoint is unavailable.
    """
    checks: list[tuple[str, bool, str]] = [
        ("title", bool((patch.title or "").strip()), "Missing title"),
        ("meta_description", bool((patch.meta_description or "").strip()), "Missing meta description"),
        ("h1_suggestion", bool((patch.h1_suggestion or "").strip()), "Missing H1 suggestion"),
        ("canonical_url", bool((patch.canonical_url or "").strip()), "Missing canonical URL"),
        ("jsonld_payload", isinstance(patch.jsonld_payload, dict) and bool(patch.jsonld_payload), "Missing JSON-LD payload"),
        ("alt_tags", isinstance(patch.alt_tags, dict) and bool(patch.alt_tags), "Missing alt tags"),
    ]

    failures = [message for _, passed, message in checks if not passed]
    passed_checks = sum(1 for _, passed, _ in checks if passed)
    score = round(passed_checks / len(checks), 4)
    feedback: dict[str, Any] = {
        "mode": "deterministic_fallback",
        "rubric_id": str(rubric.id),
        "frontier_provider": route.provider,
        "frontier_model": route.model_name,
        "route_reason": route.reason,
        "passed_checks": passed_checks,
        "total_checks": len(checks),
        "failures": failures,
    }
    if failures:
        feedback["summary"] = "Patch failed one or more deterministic God Head checks."
    else:
        feedback["summary"] = "Patch passed deterministic God Head checks."
    return score, feedback
