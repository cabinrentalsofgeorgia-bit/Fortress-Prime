"""
Legal Case Graph Service — phase-2 graph engine anchored to
legal.case_statements, legal.case_graph_nodes, and legal.case_graph_edges.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.legal_phase2 import CaseGraphEdge, CaseGraphNode, CaseStatement

logger = logging.getLogger("Crog.GraphEngine")
MAX_GRAPH_NODES = max(1, int(settings.LEGAL_GRAPH_MAX_NODES))


class GraphNodePayload(BaseModel):
    entity_name: str = Field(min_length=1)
    entity_type: str = Field(min_length=1)
    pressure_score: int = Field(default=0, ge=0, le=100)


class GraphEdgePayload(BaseModel):
    source_entity_name: str = Field(min_length=1)
    target_entity_name: str = Field(min_length=1)
    relationship_type: str = Field(min_length=1)
    confidence_weight: int = Field(default=100, ge=0, le=100)
    source_statement_id: str | None = None


class GraphPayload(BaseModel):
    nodes: list[GraphNodePayload] = Field(default_factory=list)
    edges: list[GraphEdgePayload] = Field(default_factory=list)


GraphPayload.model_rebuild()


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    data = (raw_text or "").strip()
    if data.startswith("```"):
        first_newline = data.find("\n")
        data = data[first_newline + 1 :] if first_newline > -1 else data[3:]
    if data.endswith("```"):
        data = data[:-3]
    data = data.strip()
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        start = data.find("{")
        end = data.rfind("}")
        if start >= 0 and end > start:
            return json.loads(data[start : end + 1])
        raise


def _fallback_payload(statements: list[CaseStatement]) -> GraphPayload:
    nodes_by_name: dict[str, GraphNodePayload] = {}
    for statement in statements:
        name = (statement.entity_name or "").strip()
        if not name:
            continue
        if name not in nodes_by_name:
            nodes_by_name[name] = GraphNodePayload(
                entity_name=name,
                entity_type="witness",
                pressure_score=35,
            )

    # Conservative baseline: chain neighboring entities from statement chronology.
    edges: list[GraphEdgePayload] = []
    ordered_names: list[str] = []
    for statement in statements:
        name = (statement.entity_name or "").strip()
        if name:
            ordered_names.append(name)
    for idx in range(len(ordered_names) - 1):
        source_name = ordered_names[idx]
        target_name = ordered_names[idx + 1]
        if source_name == target_name:
            continue
        edges.append(
            GraphEdgePayload(
                source_entity_name=source_name,
                target_entity_name=target_name,
                relationship_type="related",
                confidence_weight=40,
                source_statement_id=str(statements[idx].id),
            )
        )

    return GraphPayload(nodes=list(nodes_by_name.values()), edges=edges)


def _truncate_payload_for_limit(payload: GraphPayload, limit: int) -> GraphPayload:
    if len(payload.nodes) <= limit:
        return payload

    # Keep highest-pressure entities when payload exceeds legal graph ceiling.
    selected_nodes = sorted(payload.nodes, key=lambda node: node.pressure_score, reverse=True)[:limit]
    allowed = {node.entity_name.strip().lower() for node in selected_nodes}
    selected_edges = [
        edge
        for edge in payload.edges
        if edge.source_entity_name.strip().lower() in allowed
        and edge.target_entity_name.strip().lower() in allowed
    ]
    return GraphPayload(nodes=selected_nodes, edges=selected_edges)


class GraphEngine:
    def __init__(self, llm_client: Any):
        self.llm = llm_client

    async def refresh_case_graph(self, session: AsyncSession, case_slug: str) -> dict[str, str]:
        """Rebuild the graph from extracted statements for one case slug."""
        logger.info("[GRAPH] Rebuilding neural map for %s...", case_slug)

        statement_result = await session.execute(
            select(CaseStatement)
            .where(CaseStatement.case_slug == case_slug)
            .order_by(CaseStatement.created_at.asc())
        )
        statements = statement_result.scalars().all()
        if not statements:
            return {"status": "insufficient_data"}

        evidence_context = "\n".join(
            f"- {s.entity_name}: {s.quote_text}" for s in statements if s.entity_name and s.quote_text
        )

        payload = _fallback_payload(statements)
        if self.llm is not None and evidence_context:
            prompt = (
                "Analyze these case statements and return JSON with keys "
                "`nodes` and `edges`. Nodes: entity_name, entity_type, pressure_score(0-100). "
                "Edges: source_entity_name, target_entity_name, relationship_type, confidence_weight(0-100), "
                "source_statement_id(optional UUID).\n\n"
                f"Context:\n{evidence_context}"
            )
            try:
                response = await self.llm.generate(prompt=prompt, response_format="json")
                parsed = response if isinstance(response, dict) else _extract_json_object(getattr(response, "text", ""))
                payload = GraphPayload.model_validate(parsed)
            except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
                logger.warning("[GRAPH] Invalid LLM graph payload for %s, using fallback: %s", case_slug, str(exc)[:240])

        if len(payload.nodes) > MAX_GRAPH_NODES:
            logger.warning(
                "[GRAPH] Node ceiling hit for %s (requested=%d limit=%d); truncating payload.",
                case_slug,
                len(payload.nodes),
                MAX_GRAPH_NODES,
            )
            payload = _truncate_payload_for_limit(payload, MAX_GRAPH_NODES)

        await session.execute(delete(CaseGraphEdge).where(CaseGraphEdge.case_slug == case_slug))
        await session.execute(delete(CaseGraphNode).where(CaseGraphNode.case_slug == case_slug))
        await session.flush()

        statement_lookup = {str(s.id): s.id for s in statements}
        node_id_by_name: dict[str, Any] = {}
        now = datetime.now(timezone.utc)

        for node in payload.nodes:
            key = node.entity_name.strip().lower()
            if not key:
                continue
            if key in node_id_by_name:
                continue
            model_node = CaseGraphNode(
                case_slug=case_slug,
                entity_name=node.entity_name.strip(),
                entity_type=node.entity_type.strip().lower(),
                pressure_score=node.pressure_score,
                created_at=now,
            )
            session.add(model_node)
            await session.flush()
            node_id_by_name[key] = model_node.id

        for edge in payload.edges:
            source_key = edge.source_entity_name.strip().lower()
            target_key = edge.target_entity_name.strip().lower()
            source_node_id = node_id_by_name.get(source_key)
            target_node_id = node_id_by_name.get(target_key)
            if not source_node_id or not target_node_id:
                continue
            source_statement_id = statement_lookup.get(edge.source_statement_id or "")
            model_edge = CaseGraphEdge(
                case_slug=case_slug,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                relationship_type=edge.relationship_type.strip(),
                confidence_weight=edge.confidence_weight,
                source_statement_id=source_statement_id,
                created_at=now,
            )
            session.add(model_edge)

        await session.commit()
        logger.info("[GRAPH] Neural map refreshed for %s.", case_slug)
        return {"status": "success"}

    async def get_graph_snapshot(self, session: AsyncSession, case_slug: str) -> dict[str, Any]:
        """Return strict JSON payload for frontend graph rendering."""
        nodes_result = await session.execute(
            select(CaseGraphNode)
            .where(CaseGraphNode.case_slug == case_slug)
            .order_by(CaseGraphNode.created_at.asc())
        )
        edges_result = await session.execute(
            select(CaseGraphEdge)
            .where(CaseGraphEdge.case_slug == case_slug)
            .order_by(CaseGraphEdge.created_at.asc())
        )

        nodes = [
            {
                "id": str(node.id),
                "case_slug": node.case_slug,
                "entity_name": node.entity_name,
                "entity_type": node.entity_type,
                "label": node.entity_name,
                "content": node.entity_name,
                "pressure_score": int(node.pressure_score or 0),
            }
            for node in nodes_result.scalars().all()
        ]
        edges = [
            {
                "id": str(edge.id),
                "case_slug": edge.case_slug,
                "source_node_id": str(edge.source_node_id),
                "target_node_id": str(edge.target_node_id),
                "relationship_type": edge.relationship_type,
                "weight": float((edge.confidence_weight or 0) / 100.0),
                "confidence_weight": int(edge.confidence_weight or 0),
                "source_statement_id": str(edge.source_statement_id) if edge.source_statement_id else None,
                "source_ref": edge.relationship_type,
            }
            for edge in edges_result.scalars().all()
        ]
        return {"case_slug": case_slug, "nodes": nodes, "edges": edges}


async def trigger_graph_refresh(db: AsyncSession, case_slug: str) -> None:
    engine = GraphEngine(llm_client=None)
    await engine.refresh_case_graph(db, case_slug=case_slug)


async def get_case_graph_snapshot(db: AsyncSession, case_slug: str) -> dict[str, Any]:
    engine = GraphEngine(llm_client=None)
    return await engine.get_graph_snapshot(db, case_slug=case_slug)


class LegalCaseGraphService:
    @staticmethod
    async def get_graph_snapshot(case_slug: str, db: AsyncSession) -> dict[str, Any]:
        return await get_case_graph_snapshot(db, case_slug=case_slug)

    @staticmethod
    async def refresh_case_graph(case_slug: str, db: AsyncSession) -> dict[str, str]:
        await trigger_graph_refresh(db, case_slug=case_slug)
        return {"status": "graph_refreshed", "case_slug": case_slug}


class LegalCaseGraphBuilder:
    """Compatibility facade retained for existing callers."""

    @staticmethod
    async def build_baseline_graph(case_slug: str, db: AsyncSession) -> dict[str, Any]:
        result = await GraphEngine(llm_client=None).refresh_case_graph(db, case_slug=case_slug)
        return {
            "status": "graph_built",
            "case_slug": case_slug,
            "refresh_status": result.get("status", "unknown"),
        }

    @staticmethod
    async def get_graph_snapshot(case_slug: str, db: AsyncSession) -> dict[str, Any]:
        return await GraphEngine(llm_client=None).get_graph_snapshot(db, case_slug=case_slug)


async def get_case_snapshot(case_slug: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await get_case_graph_snapshot(db, case_slug=case_slug)
