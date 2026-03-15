"""
Sanctions Tripwire daemon for legal contradiction sweeps.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any
from uuid import uuid4

import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.legal_case_graph import LegalCaseGraphBuilder

logger = structlog.get_logger()

TRIPWIRE_API_URL = os.getenv("LEGAL_TRIPWIRE_ANTHROPIC_URL", "https://api.anthropic.com/v1/messages")
TRIPWIRE_MODEL = os.getenv("LEGAL_TRIPWIRE_MODEL", "claude-3-5-sonnet-20241022")
TRIPWIRE_FALLBACK_MODEL = os.getenv("LEGAL_TRIPWIRE_FALLBACK_MODEL", "claude-sonnet-4-5-20250929")
TRIPWIRE_SYSTEM_PROMPT = (
    "You are a ruthless Georgia litigator. Analyze this Case Graph. Search for material contradictions between "
    "sworn statements/affidavits and timeline events or communications. If you find a severe contradiction, "
    "generate a Sanctions Alert for a Rule 11 Motion or a Spoliation letter. "
    'Output strict JSON: {{"alerts": [{{"alert_type": "RULE_11" or "SPOLIATION", '
    '"contradiction_summary": "...", "confidence_score": int}}]}}.'
)


def _to_serializable_graph(snapshot: dict) -> dict[str, Any]:
    nodes = []
    for n in snapshot.get("nodes") or []:
        nodes.append(
            {
                "id": str(getattr(n, "id", None) or n.get("id")),
                "entity_type": getattr(n, "entity_type", None) or n.get("entity_type"),
                "label": getattr(n, "label", None) or n.get("label"),
                "properties_json": getattr(n, "properties_json", None) or n.get("properties_json"),
            }
        )
    edges = []
    for e in snapshot.get("edges") or []:
        edges.append(
            {
                "id": str(getattr(e, "id", None) or e.get("id")),
                "source_node_id": str(getattr(e, "source_node_id", None) or e.get("source_node_id")),
                "target_node_id": str(getattr(e, "target_node_id", None) or e.get("target_node_id")),
                "relationship_type": getattr(e, "relationship_type", None) or e.get("relationship_type"),
                "weight": getattr(e, "weight", None) or e.get("weight"),
                "source_evidence_id": str(
                    getattr(e, "source_evidence_id", None) or e.get("source_evidence_id") or ""
                ),
            }
        )
    return {"nodes": nodes, "edges": edges}


def _parse_payload(content: str) -> dict[str, Any]:
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


class LegalSanctionsTripwire:
    @staticmethod
    async def run_sweep(case_slug: str, db: AsyncSession) -> dict:
        anthropic_api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if not anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured")

        snapshot = await LegalCaseGraphBuilder.get_graph_snapshot(case_slug=case_slug, db=db)
        graph_payload = _to_serializable_graph(snapshot)
        user_prompt = (
            f"CASE_SLUG: {case_slug}\n"
            "CASE_GRAPH_JSON:\n"
            f"{json.dumps(graph_payload, ensure_ascii=False)}\n\n"
            "Return strict JSON only."
        )

        model_candidates = [TRIPWIRE_MODEL, TRIPWIRE_FALLBACK_MODEL]
        model_candidates = [m for i, m in enumerate(model_candidates) if m and m not in model_candidates[:i]]

        model_used = TRIPWIRE_MODEL
        async with httpx.AsyncClient(timeout=90.0) as client:
            body = None
            last_exc: Exception | None = None
            for candidate_model in model_candidates:
                payload = {
                    "model": candidate_model,
                    "system": TRIPWIRE_SYSTEM_PROMPT,
                    "messages": [
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": "{"},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1400,
                }
                try:
                    resp = await client.post(
                        TRIPWIRE_API_URL,
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
                    if exc.response.status_code == 404 and "not_found_error" in (exc.response.text or ""):
                        last_exc = exc
                        continue
                    raise
            if body is None:
                if last_exc:
                    raise last_exc
                raise ValueError("Anthropic request failed without response payload")

        content_blocks = body.get("content") or []
        text_chunks = [
            str(block.get("text", ""))
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        parsed = _parse_payload("{" + "".join(text_chunks).strip())
        alerts = parsed.get("alerts") or []

        saved = 0
        normalized = []
        for alert in alerts:
            alert_type = str(alert.get("alert_type", "RULE_11")).strip().upper()
            if alert_type not in {"RULE_11", "SPOLIATION"}:
                alert_type = "RULE_11"
            contradiction_summary = str(alert.get("contradiction_summary", "")).strip()
            if not contradiction_summary:
                continue
            try:
                confidence_score = int(alert.get("confidence_score", 50))
            except Exception:
                confidence_score = 50
            confidence_score = max(1, min(100, confidence_score))

            await db.execute(
                text(
                    """
                    INSERT INTO legal.sanctions_alerts_v2
                        (id, case_slug, alert_type, contradiction_summary, confidence_score, status, created_at)
                    VALUES
                        (:id, :case_slug, :alert_type, :summary, :confidence, 'DRAFT', NOW())
                    """
                ),
                {
                    "id": str(uuid4()),
                    "case_slug": case_slug,
                    "alert_type": alert_type,
                    "summary": contradiction_summary[:4000],
                    "confidence": confidence_score,
                },
            )
            normalized.append(
                {
                    "alert_type": alert_type,
                    "contradiction_summary": contradiction_summary,
                    "confidence_score": confidence_score,
                }
            )
            saved += 1

        await db.commit()
        logger.info("tripwire_sweep_complete", case_slug=case_slug, alerts_found=len(alerts), saved=saved, model=model_used)
        return {
            "case_slug": case_slug,
            "model": model_used,
            "alerts_found": len(alerts),
            "saved": saved,
            "alerts": normalized,
        }


async def detect_material_contradictions(db: AsyncSession, case_slug: str) -> dict:
    """
    Backward-compatible wrapper for legacy callers.
    """
    return await LegalSanctionsTripwire.run_sweep(case_slug=case_slug, db=db)
