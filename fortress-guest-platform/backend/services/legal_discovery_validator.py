"""
Legal Discovery Validation & Triage Engine.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALIDATOR_CHAT_URL = os.getenv("LEGAL_DISCOVERY_VALIDATOR_URL", "https://api.anthropic.com/v1/messages")
VALIDATOR_MODEL = os.getenv("LEGAL_DISCOVERY_VALIDATOR_MODEL", "claude-3-5-sonnet-20241022")
VALIDATOR_FALLBACK_MODEL = os.getenv("LEGAL_DISCOVERY_VALIDATOR_FALLBACK_MODEL", "claude-sonnet-4-5-20250929")


class LegalDiscoveryValidator:
    @staticmethod
    async def validate_and_score_pack(pack_id: str, case_slug: str, db: AsyncSession) -> dict:
        anthropic_api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if not anthropic_api_key:
            raise HTTPException(
                status_code=500,
                detail="ANTHROPIC_API_KEY is not configured. Set it in /home/admin/Fortress-Prime/.env before running validation.",
            )

        pack = (
            await db.execute(
                text(
                    """
                    SELECT id, case_slug, target_entity
                    FROM legal.discovery_draft_packs_v2
                    WHERE id = CAST(:pack_id AS uuid) AND case_slug = :case_slug
                    LIMIT 1
                    """
                ),
                {"pack_id": pack_id, "case_slug": case_slug},
            )
        ).mappings().first()
        if not pack:
            raise HTTPException(status_code=404, detail=f"Discovery pack not found: {pack_id}")

        items = (
            await db.execute(
                text(
                    """
                    SELECT id, category, content, rationale_from_graph, sequence_number
                    FROM legal.discovery_draft_items_v2
                    WHERE pack_id = CAST(:pack_id AS uuid)
                    ORDER BY sequence_number ASC
                    """
                ),
                {"pack_id": pack_id},
            )
        ).mappings().all()
        if not items:
            raise HTTPException(status_code=404, detail=f"No discovery items found for pack: {pack_id}")

        updated = 0
        failed = 0
        model_used = VALIDATOR_MODEL
        async with httpx.AsyncClient(timeout=75.0) as client:
            for item in items:
                system_prompt = (
                    "You are a senior Georgia contract litigator auditing a junior associate's draft. The draft is legally flawed.\n\n"
                    "RULE 1: If the category is INTERROGATORY, you MUST rewrite it as a direct question requiring a sworn written answer "
                    "(e.g., 'Identify all individuals...', 'State the factual basis for...'). You MUST NOT use the words 'produce', "
                    "'provide', or 'documents'.\n"
                    "RULE 2: If the category is RFP, you MUST demand the production of specific materials.\n\n"
                    "Score the draft for lethality and proportionality (1-100), explain your corrections in correction_notes, and output the "
                    'flawless rewritten_content in strict JSON format: {{"lethality_score": int, "proportionality_score": int, '
                    '"correction_notes": "...", "rewritten_content": "..."}}.'
                )
                user_prompt = (
                    f"Category: {item['category']}\n"
                    f"Draft content: {item['content']}\n"
                    f"Rationale from graph: {item['rationale_from_graph']}\n\n"
                    "Return strict JSON only (no markdown, no prose, no code fences)."
                )
                model_candidates = [VALIDATOR_MODEL, VALIDATOR_FALLBACK_MODEL]
                model_candidates = [m for i, m in enumerate(model_candidates) if m and m not in model_candidates[:i]]

                try:
                    body = None
                    last_exc: Exception | None = None
                    for candidate_model in model_candidates:
                        payload = {
                            "model": candidate_model,
                            "system": system_prompt,
                            "messages": [
                                {"role": "user", "content": user_prompt},
                                {"role": "assistant", "content": "{"},
                            ],
                            "temperature": 0.1,
                            "max_tokens": 1200,
                        }
                        try:
                            resp = await client.post(
                                VALIDATOR_CHAT_URL,
                                json=payload,
                                headers={
                                    "x-api-key": anthropic_api_key,
                                    "anthropic-version": "2023-06-01",
                                    "content-type": "application/json",
                                },
                            )
                            resp.raise_for_status()
                            body = resp.json()
                            model_used = candidate_model
                            break
                        except httpx.HTTPStatusError as exc:
                            # If the requested model is unavailable for this key/account, try fallback.
                            if exc.response.status_code == 404 and "not_found_error" in (exc.response.text or ""):
                                last_exc = exc
                                continue
                            raise
                    if body is None:
                        if last_exc:
                            raise last_exc
                        raise ValueError("Anthropic call failed without response body")

                    content_blocks = body.get("content") or []
                    text_chunks = [
                        str(block.get("text", ""))
                        for block in content_blocks
                        if isinstance(block, dict) and block.get("type") == "text"
                    ]
                    content = "".join(text_chunks).strip()
                    parsed = LegalDiscoveryValidator._parse_validator_payload("{" + content)
                    lethality = LegalDiscoveryValidator._clamp_score(parsed.get("lethality_score"))
                    proportionality = LegalDiscoveryValidator._clamp_score(parsed.get("proportionality_score"))
                    notes = str(parsed.get("correction_notes", "")).strip()[:2000]
                    rewritten = str(parsed.get("rewritten_content", "")).strip()
                    if not rewritten:
                        raise ValueError("rewritten_content is empty")

                    await db.execute(
                        text(
                            """
                            UPDATE legal.discovery_draft_items_v2
                            SET lethality_score = :lethality,
                                proportionality_score = :proportionality,
                                correction_notes = :notes,
                                content = :rewritten
                            WHERE id = CAST(:item_id AS uuid)
                            """
                        ),
                        {
                            "lethality": lethality,
                            "proportionality": proportionality,
                            "notes": notes,
                            "rewritten": rewritten,
                            "item_id": str(item["id"]),
                        },
                    )
                    updated += 1
                except Exception as exc:
                    failed += 1
                    await db.execute(
                        text(
                            """
                            UPDATE legal.discovery_draft_items_v2
                            SET correction_notes = :notes
                            WHERE id = CAST(:item_id AS uuid)
                            """
                        ),
                        {
                            "notes": f"Validation failed: {str(exc)[:1900]}",
                            "item_id": str(item["id"]),
                        },
                    )

        await db.commit()
        return {
            "pack_id": str(pack["id"]),
            "case_slug": pack["case_slug"],
            "target_entity": pack["target_entity"],
            "items_total": len(items),
            "items_updated": updated,
            "items_failed": failed,
            "model": model_used,
        }

    @staticmethod
    def _parse_validator_payload(content: str) -> dict[str, Any]:
        raw = (content or "").strip()
        if raw.startswith("{{"):
            raw = raw[1:]
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start : end + 1])
            raise

    @staticmethod
    def _clamp_score(value: Any) -> int:
        try:
            score = int(value)
        except Exception:
            score = 50
        return max(1, min(100, score))

