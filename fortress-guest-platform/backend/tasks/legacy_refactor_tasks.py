"""ARQ jobs for mirrored legacy HTML refactoring."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.functional_node import FunctionalNode
from backend.services.swarm_service import submit_chat_completion

logger = logging.getLogger("worker.legacy_refactor")

REFRACTOR_MODEL = (
    str(settings.gemini_model or "").strip()
    or str(settings.swarm_model or "").strip()
    or "gemini-2.5-flash"
)
REFRACTOR_SYSTEM_PROMPT = (
    "Act as a world-class SEO engineer refactoring legacy Drupal HTML into clean, "
    "high-performance markup for a Next.js storefront. "
    "Return ONLY refactored HTML. No markdown fences. No commentary. "
    "Rules:\n"
    "1. Strip Drupal-specific classes, ids, wrappers, and CMS artifacts.\n"
    "2. Remove inline styles, scripts, tracking markup, and editor debris.\n"
    "3. Preserve factual content, heading hierarchy, and useful links.\n"
    "4. Convert internal legacy links to sovereign storefront paths when the destination is obvious.\n"
    "5. Use semantic HTML5 tags with clean paragraphs, headings, lists, tables, figures, and anchors.\n"
    "6. Do not invent new claims, locations, amenities, or links.\n"
    "7. Keep external links intact when they are factual references.\n"
)

_CODE_FENCE_RE = re.compile(r"^```(?:html)?\s*|\s*```$", re.IGNORECASE)


def _extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                chunks.append(item["text"])
        return "\n".join(chunks).strip()
    return ""


def _sanitize_refactored_html(raw_text: str) -> str:
    text = (raw_text or "").strip()
    text = _CODE_FENCE_RE.sub("", text).strip()
    return text


async def refactor_legacy_html_task(ctx: dict[str, object], path: str) -> dict[str, str]:
    del ctx

    normalized_path = str(path or "").strip()
    if not normalized_path:
        raise RuntimeError("refactor_legacy_html_task requires a canonical path")

    async with AsyncSessionLocal() as db:
        node = (
            await db.execute(
                select(FunctionalNode).where(FunctionalNode.canonical_path == normalized_path)
            )
        ).scalar_one_or_none()

        if node is None:
            raise RuntimeError(f"Functional node not found for path={normalized_path}")
        if not (node.body_html or "").strip():
            raise RuntimeError(f"Functional node has no body_html for path={normalized_path}")

        user_prompt = (
            f"Refactor the following legacy HTML for canonical path '{normalized_path}'.\n\n"
            f"{node.body_html}"
        )
        response = await submit_chat_completion(
            prompt=user_prompt,
            model=REFRACTOR_MODEL,
            system_message=REFRACTOR_SYSTEM_PROMPT,
            timeout_s=120.0,
        )
        refactored_html = _sanitize_refactored_html(_extract_message_content(response))
        if not refactored_html:
            raise RuntimeError(f"Empty refactor output for path={normalized_path}")

        metadata = dict(node.source_metadata or {})
        metadata.update(
            {
                "refactor_model": REFRACTOR_MODEL,
                "refactored_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        node.body_html = refactored_html
        node.mirror_status = "completed"
        node.cutover_status = "sovereign"
        node.source_metadata = metadata
        await db.commit()

        logger.info("TASK_SUCCESS: %s is now SOVEREIGN.", normalized_path)
        return {
            "path": normalized_path,
            "cutover_status": node.cutover_status,
            "mirror_status": node.mirror_status,
        }
