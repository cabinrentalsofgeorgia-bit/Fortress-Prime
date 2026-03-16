"""
Historic Omni-Search Engine — semantic search across case evidence,
correspondence, and property logs using the Resilient Router.
"""
from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.ai_router import execute_resilient_inference

logger = structlog.get_logger()

SEARCH_SYSTEM_PROMPT = (
    "You are a Tier 0 Legal Analyst. Review the provided historic database records "
    "and answer the user's query with brutal precision. Cite specific dates and "
    "document references. If a contradiction exists in the historic record, "
    "highlight it aggressively."
)

MAX_EVIDENCE_ROWS = 30


async def _gather_case_records(db: AsyncSession, case_slug: str) -> str:
    blocks: list[str] = []

    try:
        case_r = await db.execute(
            text("SELECT id FROM legal.legal_cases WHERE slug = :slug"),
            {"slug": case_slug},
        )
        case_row = case_r.fetchone()
        if not case_row:
            return ""
        case_id = str(case_row[0])
    except Exception as exc:
        logger.warning("omni_search_case_lookup_failed", error=str(exc)[:200])
        return ""

    try:
        node_result = await db.execute(
            text("""
                SELECT id, entity_type, label, metadata::text AS meta, created_at
                FROM legal.case_graph_nodes
                WHERE case_id = :cid
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"cid": case_id, "lim": MAX_EVIDENCE_ROWS},
        )
        for row in node_result.fetchall():
            d = dict(row._mapping)
            parts = [f"[Entity {d.get('entity_type','?')}] {d.get('label','')}"]
            if d.get("meta"):
                parts.append(f"metadata: {str(d['meta'])[:300]}")
            if d.get("created_at"):
                parts.append(f"date: {d['created_at']}")
            blocks.append(" | ".join(parts))
    except Exception as exc:
        await db.rollback()
        logger.warning("omni_search_nodes_failed", error=str(exc)[:200])

    try:
        edge_result = await db.execute(
            text("""
                SELECT e.relationship_type, e.weight, e.source_ref,
                       s.label AS source_label, t.label AS target_label
                FROM legal.case_graph_edges e
                JOIN legal.case_graph_nodes s ON s.id = e.source_node_id
                JOIN legal.case_graph_nodes t ON t.id = e.target_node_id
                WHERE e.case_id = :cid
                ORDER BY e.weight DESC
                LIMIT :lim
            """),
            {"cid": case_id, "lim": MAX_EVIDENCE_ROWS},
        )
        for row in edge_result.fetchall():
            d = dict(row._mapping)
            blocks.append(
                f"[Relationship] {d.get('source_label','')} -> ({d.get('relationship_type','')}) -> "
                f"{d.get('target_label','')} | weight={d.get('weight',0)} | ref: {d.get('source_ref','n/a')}"
            )
    except Exception as exc:
        await db.rollback()
        logger.warning("omni_search_edges_failed", error=str(exc)[:200])

    try:
        disc_result = await db.execute(
            text("""
                SELECT dp.pack_type, dp.status, di.item_number, di.content
                FROM legal.discovery_draft_items di
                JOIN legal.discovery_draft_packs dp ON dp.id = di.pack_id
                WHERE dp.case_id = :cid
                ORDER BY dp.created_at DESC, di.item_number ASC
                LIMIT :lim
            """),
            {"cid": case_id, "lim": MAX_EVIDENCE_ROWS},
        )
        for row in disc_result.fetchall():
            d = dict(row._mapping)
            blocks.append(
                f"[Discovery {d.get('pack_type','')} #{d.get('item_number','')}] "
                f"{str(d.get('content',''))[:400]}"
            )
    except Exception as exc:
        await db.rollback()
        logger.warning("omni_search_discovery_failed", error=str(exc)[:200])

    return "\n".join(blocks) if blocks else ""


async def synthesize_historic_search(
    db: AsyncSession,
    query: str,
    case_slug: str,
) -> dict:
    raw_records = await _gather_case_records(db, case_slug)

    if not raw_records.strip():
        return {
            "answer": "No historic records found for this case. Upload evidence or correspondence first.",
            "records_searched": 0,
            "inference_source": "none",
        }

    record_count = raw_records.count("\n") + 1
    user_prompt = (
        f"QUERY: {query}\n\n"
        f"HISTORIC RECORDS ({record_count} entries):\n"
        f"{raw_records}"
    )

    result = await execute_resilient_inference(
        prompt=user_prompt,
        task_type="legal",
        system_message=SEARCH_SYSTEM_PROMPT,
        max_tokens=1024,
        temperature=0.2,
        db=db,
        source_module="legal_search_engine",
    )

    return {
        "answer": result.text or "Search produced no synthesized answer.",
        "records_searched": record_count,
        "inference_source": result.source,
        "breaker_state": result.breaker_state,
        "latency_ms": result.latency_ms,
    }
