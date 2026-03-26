"""
Evidence Ingestion Engine — parses legal documents of any size and
extracts entities, relationships, and direct quotes into the Case
Graph and case_statements tables via the Resilient Router.

Massive documents are split into overlapping semantic chunks so each
Swarm call stays within token limits. Extracted entities from earlier
chunks are threaded into later chunk prompts for cross-reference.
A final deduplication pass prevents double-inserts.
"""
from __future__ import annotations

import json
import re
import structlog
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.legal_graph import CaseGraphEdge, CaseGraphNode, LegalCase
from backend.services.ai_router import execute_resilient_inference

logger = structlog.get_logger()
MAX_GRAPH_NODES = max(1, int(settings.LEGAL_GRAPH_MAX_NODES))

EXTRACTOR_SYSTEM_PROMPT = (
    "You are a Tier 0 Legal Evidence Extractor. Read the provided document chunk. "
    "Extract every discrete factual claim, critical date, and direct quote "
    "made by either party. Connect new facts to the existing known entities when relevant. "
    "Return a strict JSON object with exactly these keys:\n"
    '{\n'
    '  "new_nodes": [{"entity_type":"person|company|document|claim|date|exhibit","label":"...","metadata":{}}],\n'
    '  "new_edges": [{"source_label":"...","target_label":"...","relationship_type":"...","weight":0.9,"source_ref":"..."}],\n'
    '  "direct_statements": [{"entity_name":"...","quote_text":"...","source_ref":"...","stated_at":"YYYY-MM-DD or null"}]\n'
    '}'
)

DEFAULT_CHUNK_SIZE = 800
DEFAULT_OVERLAP = 150


def _chunk_document(
    text_body: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    if len(text_body) <= chunk_size:
        return [text_body]

    min_step = chunk_size - overlap
    sentence_breaks = list(re.finditer(r'(?<=[.!?\n])\s+', text_body))

    chunks: list[str] = []
    start = 0

    while start < len(text_body):
        end = min(start + chunk_size, len(text_body))

        if end < len(text_body):
            best_break = end
            for m in sentence_breaks:
                pos = m.start()
                if start + min_step <= pos <= end:
                    best_break = pos
                elif pos > end:
                    break
            end = best_break

        chunk_text = text_body[start:end].strip()
        if chunk_text:
            chunks.append(chunk_text)

        next_start = start + max(min_step, end - start - overlap)
        if next_start <= start:
            next_start = start + min_step
        if next_start >= len(text_body):
            break
        start = next_start

    return chunks


def _parse_extraction(raw: str) -> dict:
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


def _dedup_nodes(nodes: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for node in nodes:
        key = str(node.get("label", "")).strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(node)
    return result


def _dedup_edges(edges: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for edge in edges:
        key = (
            str(edge.get("source_label", "")).strip().lower()
            + "|" + str(edge.get("target_label", "")).strip().lower()
            + "|" + str(edge.get("relationship_type", "")).strip().lower()
        )
        if key not in seen:
            seen.add(key)
            result.append(edge)
    return result


def _dedup_statements(stmts: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for stmt in stmts:
        key = str(stmt.get("quote_text", "")).strip().lower()[:200]
        if key and key not in seen:
            seen.add(key)
            result.append(stmt)
    return result


async def ingest_document_to_graph(
    db: AsyncSession,
    case_slug: str,
    document_text: str,
    source_ref: str,
) -> dict:
    case_res = await db.execute(select(LegalCase).where(LegalCase.slug == case_slug))
    case = case_res.scalar_one_or_none()
    if not case:
        raise ValueError(f"Legal case '{case_slug}' not found")
    case_id = case.id

    existing_nodes_r = await db.execute(
        select(CaseGraphNode).where(CaseGraphNode.case_id == case_id)
    )
    existing_labels = {n.label for n in existing_nodes_r.scalars().all()}

    chunks = _chunk_document(document_text)
    total_chunks = len(chunks)

    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    all_statements: list[dict] = []
    running_labels = set(existing_labels)
    total_latency = 0
    last_source = "none"

    logger.info(
        "evidence_ingestion_chunked_start",
        case_slug=case_slug,
        source_ref=source_ref,
        doc_length=len(document_text),
        chunks=total_chunks,
    )

    for idx, chunk in enumerate(chunks, 1):
        known_entities = ", ".join(sorted(running_labels)) if running_labels else "none"
        prompt = (
            f"SOURCE DOCUMENT: {source_ref}\n"
            f"CHUNK {idx}/{total_chunks}\n"
            f"EXISTING KNOWN ENTITIES: {known_entities}\n\n"
            f"DOCUMENT TEXT:\n{chunk}"
        )

        result = await execute_resilient_inference(
            prompt=prompt,
            task_type="legal",
            system_message=EXTRACTOR_SYSTEM_PROMPT,
            max_tokens=2000,
            temperature=0.1,
            db=db,
            source_module="legal_evidence_ingestion",
        )
        total_latency += result.latency_ms
        last_source = result.source

        try:
            parsed = _parse_extraction(result.text)
        except Exception as exc:
            logger.warning(
                "evidence_chunk_parse_failed",
                chunk=idx,
                error=str(exc)[:200],
            )
            continue

        chunk_nodes = parsed.get("new_nodes") or []
        chunk_edges = parsed.get("new_edges") or []
        chunk_stmts = parsed.get("direct_statements") or []

        all_nodes.extend(chunk_nodes)
        all_edges.extend(chunk_edges)
        all_statements.extend(chunk_stmts)

        for n in chunk_nodes:
            label = str(n.get("label", "")).strip()
            if label:
                running_labels.add(label)

        logger.info(
            "evidence_chunk_processed",
            chunk=idx,
            total_chunks=total_chunks,
            nodes=len(chunk_nodes),
            edges=len(chunk_edges),
            stmts=len(chunk_stmts),
            source=result.source,
        )

    all_nodes = _dedup_nodes(all_nodes)
    all_edges = _dedup_edges(all_edges)
    all_statements = _dedup_statements(all_statements)

    now = datetime.now(timezone.utc)
    label_to_id: dict[str, UUID] = {}
    for n in (await db.execute(select(CaseGraphNode).where(CaseGraphNode.case_id == case_id))).scalars().all():
        label_to_id[n.label] = n.id

    nodes_created = 0
    existing_count = len(label_to_id)
    remaining_node_budget = max(MAX_GRAPH_NODES - existing_count, 0)
    if remaining_node_budget == 0:
        logger.warning(
            "evidence_ingestion_node_limit_reached",
            case_slug=case_slug,
            existing_nodes=existing_count,
            limit=MAX_GRAPH_NODES,
        )
    for node in all_nodes:
        if remaining_node_budget <= 0:
            break
        label = str(node.get("label", "")).strip()
        if not label or label in label_to_id:
            continue
        entity_type = str(node.get("entity_type", "claim")).strip()
        metadata = node.get("metadata") or {}
        metadata["source_ref"] = source_ref
        new_node = CaseGraphNode(
            id=uuid4(), case_id=case_id,
            entity_type=entity_type, label=label,
            node_metadata=metadata, created_at=now,
        )
        db.add(new_node)
        await db.flush()
        label_to_id[label] = new_node.id
        nodes_created += 1
        remaining_node_budget -= 1

    edges_created = 0
    for edge in all_edges:
        src_label = str(edge.get("source_label", "")).strip()
        tgt_label = str(edge.get("target_label", "")).strip()
        if src_label not in label_to_id or tgt_label not in label_to_id:
            continue
        new_edge = CaseGraphEdge(
            id=uuid4(), case_id=case_id,
            source_node_id=label_to_id[src_label],
            target_node_id=label_to_id[tgt_label],
            relationship_type=str(edge.get("relationship_type", "related")).strip(),
            weight=float(edge.get("weight", 0.7)),
            source_ref=str(edge.get("source_ref") or source_ref)[:500],
            created_at=now,
        )
        db.add(new_edge)
        edges_created += 1

    statements_created = 0
    for stmt in all_statements:
        entity_name = str(stmt.get("entity_name", "")).strip()
        quote_text = str(stmt.get("quote_text", "")).strip()
        if not quote_text:
            continue
        stated_at = stmt.get("stated_at")
        try:
            await db.execute(
                text("""
                    INSERT INTO legal.case_statements
                        (case_slug, entity_name, quote_text, source_ref, doc_id, stated_at)
                    VALUES (:slug, :entity, :quote, :ref, :doc, :stated)
                """),
                {
                    "slug": case_slug,
                    "entity": entity_name[:255],
                    "quote": quote_text[:2000],
                    "ref": source_ref[:500],
                    "doc": source_ref[:255],
                    "stated": stated_at,
                },
            )
            statements_created += 1
        except Exception as exc:
            logger.warning("evidence_statement_save_failed", error=str(exc)[:200])

    await db.commit()

    logger.info(
        "evidence_ingestion_complete",
        case_slug=case_slug,
        source_ref=source_ref,
        chunks_processed=total_chunks,
        nodes_created=nodes_created,
        edges_created=edges_created,
        statements_created=statements_created,
        inference_source=last_source,
        total_latency_ms=total_latency,
    )

    return {
        "case_slug": case_slug,
        "source_ref": source_ref,
        "chunks_processed": total_chunks,
        "nodes_created": nodes_created,
        "edges_created": edges_created,
        "statements_created": statements_created,
        "inference_source": last_source,
        "breaker_state": "n/a",
        "latency_ms": total_latency,
    }
