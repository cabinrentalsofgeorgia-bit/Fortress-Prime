"""
Deposition Kill-Sheet Generator — produces tactical deposition briefs
by cross-referencing the case graph with prior statements.

Routes through the Resilient Router with PII sanitization.
"""
from __future__ import annotations

import json
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.ai_router import execute_resilient_inference
from backend.services.legal_case_graph import get_case_graph_snapshot

logger = structlog.get_logger()

KILL_SHEET_SYSTEM_PROMPT = (
    "Draft a tactical deposition brief. Identify high-risk topics where the "
    "opponent's prior statements conflict with the evidence graph. "
    "Output a strict JSON object with exactly these keys: "
    '{"summary":"...","high_risk_topics'
    '":[{"topic":"...","conflict":"...","evidence_ref":"..."}],'
    '"suggested_lock_in_questions":["..."]}'
)


def _graph_to_text(snapshot: dict) -> str:
    nodes = snapshot.get("nodes") or []
    edges = snapshot.get("edges") or []
    label_by_id = {}
    lines = []
    for n in nodes:
        label = n.label if hasattr(n, "label") else n.get("label", "?")
        etype = n.entity_type if hasattr(n, "entity_type") else n.get("entity_type", "?")
        nid = str(n.id if hasattr(n, "id") else n.get("id", "?"))
        label_by_id[nid] = label
        lines.append(f"[{etype}] {label}")

    for e in edges:
        src = label_by_id.get(str(getattr(e, "source_node_id", None) or e.get("source_node_id", "?")), "?")
        tgt = label_by_id.get(str(getattr(e, "target_node_id", None) or e.get("target_node_id", "?")), "?")
        rel = getattr(e, "relationship_type", None) or e.get("relationship_type", "?")
        ref = getattr(e, "source_ref", None) or e.get("source_ref") or "n/a"
        lines.append(f"{src} --({rel})--> {tgt} [ref: {ref}]")

    return "\n".join(lines) if lines else "No evidence graph."


async def _gather_statements(db: AsyncSession, case_slug: str) -> str:
    try:
        r = await db.execute(
            text("""
                SELECT entity_name, quote_text, source_ref, stated_at
                FROM legal.case_statements
                WHERE case_slug = :slug
                ORDER BY stated_at DESC
                LIMIT 30
            """),
            {"slug": case_slug},
        )
        rows = r.fetchall()
        if not rows:
            return ""
        lines = []
        for row in rows:
            d = dict(row._mapping)
            lines.append(
                f"[{d.get('entity_name','?')}] \"{d.get('quote_text','')}\" "
                f"(ref: {d.get('source_ref','n/a')}, date: {d.get('stated_at','?')})"
            )
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("kill_sheet_statements_failed", error=str(exc)[:200])
        return ""


def _parse_kill_sheet(raw: str) -> dict:
    text_raw = (raw or "").strip()
    if text_raw.startswith("```"):
        text_raw = text_raw.strip("`")
        if text_raw.lower().startswith("json"):
            text_raw = text_raw[4:].strip()
    start = text_raw.find("{")
    end = text_raw.rfind("}")
    if start >= 0 and end > start:
        text_raw = text_raw[start : end + 1]
    return json.loads(text_raw)


async def generate_kill_sheet(db: AsyncSession, case_slug: str) -> dict:
    snapshot = await get_case_graph_snapshot(db, case_slug=case_slug)
    graph_text = _graph_to_text(snapshot)
    statements_text = await _gather_statements(db, case_slug)

    prompt = f"CASE EVIDENCE GRAPH:\n{graph_text}"
    if statements_text:
        prompt += f"\n\nPRIOR STATEMENTS ON RECORD:\n{statements_text}"

    result = await execute_resilient_inference(
        prompt=prompt,
        task_type="legal",
        system_message=KILL_SHEET_SYSTEM_PROMPT,
        max_tokens=1500,
        temperature=0.15,
        db=db,
        source_module="legal_deposition_prep",
    )

    kill_sheet: dict = {}
    try:
        kill_sheet = _parse_kill_sheet(result.text)
    except Exception as exc:
        logger.warning("kill_sheet_parse_failed", error=str(exc)[:200], raw=result.text[:300])
        kill_sheet = {
            "summary": result.text[:500] if result.text else "Kill-sheet generation produced no structured output.",
            "high_risk_topics": [],
            "suggested_lock_in_questions": [],
        }

    await db.commit()

    logger.info(
        "kill_sheet_generated",
        case_slug=case_slug,
        topics=len(kill_sheet.get("high_risk_topics", [])),
        questions=len(kill_sheet.get("suggested_lock_in_questions", [])),
        source=result.source,
    )

    return {
        "case_slug": case_slug,
        "kill_sheet": kill_sheet,
        "inference_source": result.source,
        "breaker_state": result.breaker_state,
        "latency_ms": result.latency_ms,
    }
