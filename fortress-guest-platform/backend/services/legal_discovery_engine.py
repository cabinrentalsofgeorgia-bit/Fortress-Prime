"""
Legal Discovery Engine — drafts Rule 26 proportional discovery sets
using the Tier 0 Resilient Router with PII sanitization.

Supported pack types: interrogatory, rfp, admission.
Hard cap: 25 items per Fed. R. Civ. P. 33 / local proportionality rules.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import and_

from backend.models.legal_discovery import DiscoveryDraftItem, DiscoveryDraftPack
from backend.models.legal import DiscoveryDraftPack as DiscoveryDraftPackV2
from backend.models.legal import DiscoveryDraftItem as DiscoveryDraftItemV2
from backend.models.legal_graph import LegalCase
from backend.models.legal_phase2 import JurisdictionRule
from backend.services.ai_router import execute_resilient_inference
from backend.services.legal_case_graph import get_case_graph_snapshot
from backend.services.legal_case_graph import LegalCaseGraphBuilder
from backend.services.legal_hive_mind import get_approved_exemplars, inject_exemplars_into_prompt, get_godhead_exemplars

logger = logging.getLogger(__name__)

RULE_26_MAX_ITEMS = 25
DISCOVERY_CHAT_URL = os.getenv("LEGAL_DISCOVERY_CHAT_URL", "http://192.168.0.100/v1/chat/completions")
DISCOVERY_CHAT_MODEL = os.getenv("LEGAL_DISCOVERY_CHAT_MODEL", "qwen2.5:7b")


PACK_TYPE_TO_RULE_TYPE = {
    "interrogatory": "interrogatory_cap",
    "rfp": "rfp_cap",
    "admission": "admission_cap",
}


async def _get_jurisdiction_cap(
    db: AsyncSession,
    court: str,
    pack_type: str,
) -> int | None:
    """Look up the court-specific cap from legal.jurisdiction_rules."""
    rule_type = PACK_TYPE_TO_RULE_TYPE.get(pack_type)
    if not rule_type:
        return None
    result = await db.execute(
        select(JurisdictionRule.limit_value).where(
            and_(
                JurisdictionRule.court_name == court,
                JurisdictionRule.rule_type == rule_type,
            )
        ).limit(1)
    )
    return result.scalar_one_or_none()


def _graph_summary_text(snapshot: dict) -> str:
    nodes = list(snapshot.get("nodes") or [])
    edges = list(snapshot.get("edges") or [])
    if not nodes and not edges:
        return "No graph entities or edges are present."

    node_label_by_id = {str(node.id): node.label for node in nodes}
    node_lines = [
        f"- {node.label} [{node.entity_type}] metadata={json.dumps(node.node_metadata or {}, ensure_ascii=True)}"
        for node in nodes
    ]
    edge_lines = []
    for edge in edges:
        source_label = node_label_by_id.get(str(edge.source_node_id), str(edge.source_node_id))
        target_label = node_label_by_id.get(str(edge.target_node_id), str(edge.target_node_id))
        edge_lines.append(
            f"- {source_label} -> ({edge.relationship_type}, weight={float(edge.weight or 0.0):.2f}) -> {target_label}; source_ref={edge.source_ref or 'n/a'}"
        )

    return (
        "Nodes:\n"
        + ("\n".join(node_lines) if node_lines else "- none")
        + "\n\nEdges:\n"
        + ("\n".join(edge_lines) if edge_lines else "- none")
    )


def _extract_opposing_pii(snapshot: dict) -> dict:
    """Extract opposing party/counsel names from the graph for PII scrubbing."""
    pii: dict = {}
    nodes = list(snapshot.get("nodes") or [])
    for node in nodes:
        meta = node.node_metadata if hasattr(node, "node_metadata") else (node.get("metadata") or {})
        role = str(meta.get("role", "")).lower()
        label = str(node.label if hasattr(node, "label") else node.get("label", "")).strip()
        if not label:
            continue
        if "opposing" in role or "counsel" in role or "claimant" in role or "plaintiff" in role:
            if not pii.get("guest_name"):
                pii["guest_name"] = label
            else:
                pii["guest_name"] += f" {label}"
    return pii


def _fallback_discovery_items(snapshot: dict, pack_type: str, item_limit: int) -> list[str]:
    nodes = list(snapshot.get("nodes") or [])
    edges = list(snapshot.get("edges") or [])
    node_label_by_id = {str(node.id): node.label for node in nodes}
    items: list[str] = []

    for edge in edges:
        if len(items) >= item_limit:
            break
        source_label = node_label_by_id.get(str(edge.source_node_id), "Unknown Source")
        target_label = node_label_by_id.get(str(edge.target_node_id), "Unknown Target")
        if pack_type == "admission":
            items.append(
                f"Admit that your {edge.relationship_type} contention between {source_label} and {target_label} is based on the evidence referenced as '{edge.source_ref or 'n/a'}'."
            )
        elif pack_type == "rfp":
            items.append(
                f"Produce all documents and communications relating to {source_label}, {target_label}, and the '{edge.relationship_type}' relationship, including materials identified as '{edge.source_ref or 'n/a'}'."
            )
        else:
            items.append(
                f"Identify all facts, witnesses, and documents supporting your allegation that {source_label} {edge.relationship_type} {target_label}, including the evidence labeled '{edge.source_ref or 'n/a'}'."
            )

    while len(items) < item_limit:
        items.append(f"{pack_type.title()} {len(items)+1}: State every factual basis for your claim.")
    return items[:item_limit]


def _parse_llm_items(content: str, item_limit: int) -> list[str]:
    raw = (content or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("LLM output is not a JSON array")
    cleaned: list[str] = []
    for item in parsed:
        text_item = str(item).strip()
        if text_item:
            cleaned.append(text_item)
        if len(cleaned) >= item_limit:
            break
    if not cleaned:
        raise ValueError("LLM returned empty discovery items")
    return cleaned


async def generate_discovery_pack(
    db: AsyncSession,
    case_slug: str,
    pack_type: str,
    item_limit: int,
) -> dict:
    allowed_pack_types = {"interrogatory", "rfp", "admission"}
    normalized_pack_type = (pack_type or "").strip().lower()
    if normalized_pack_type not in allowed_pack_types:
        raise HTTPException(status_code=422, detail=f"Invalid pack_type '{pack_type}'")
    if item_limit < 1:
        raise HTTPException(status_code=422, detail="item_limit must be >= 1")

    case_res = await db.execute(select(LegalCase).where(LegalCase.slug == case_slug))
    legal_case = case_res.scalar_one_or_none()
    if not legal_case:
        raise HTTPException(status_code=404, detail=f"Legal case '{case_slug}' not found")

    jurisdiction_cap = await _get_jurisdiction_cap(db, legal_case.court, normalized_pack_type)
    effective_cap = min(
        int(item_limit),
        jurisdiction_cap if jurisdiction_cap is not None else RULE_26_MAX_ITEMS,
        RULE_26_MAX_ITEMS,
    )
    limited_count = max(effective_cap, 1)

    graph_snapshot = await get_case_graph_snapshot(db, case_slug=case_slug)
    graph_summary = _graph_summary_text(graph_snapshot)
    opposing_pii = _extract_opposing_pii(graph_snapshot)

    system_prompt = (
        f"Draft highly specific, Rule 26 proportional interrogatories based ONLY on the "
        f"provided evidence graph. Maximum {limited_count} items. Each item must be "
        f"hyper-specific and multi-part, driven by the case entities and dates. "
        f"Return a strict JSON array of strings."
    )
    if normalized_pack_type == "rfp":
        system_prompt = (
            f"Draft Rule 34 Requests for Production based ONLY on the provided evidence graph. "
            f"Maximum {limited_count} items. Each request must be hyper-specific, referencing "
            f"exact entities, date ranges, and document types from the graph. "
            f"Return a strict JSON array of strings."
        )
    elif normalized_pack_type == "admission":
        system_prompt = (
            f"Draft Rule 36 Requests for Admission based ONLY on the provided evidence graph. "
            f"Maximum {limited_count} items. Each admission must target a specific factual "
            f"assertion derived from the evidence graph. "
            f"Return a strict JSON array of strings."
        )

    exemplars = await get_approved_exemplars(db, pack_type=normalized_pack_type)
    system_prompt = inject_exemplars_into_prompt(exemplars, system_prompt)

    result = await execute_resilient_inference(
        prompt=graph_summary,
        task_type="legal",
        system_message=system_prompt,
        max_tokens=1024,
        temperature=0.1,
        db=db,
        source_module="legal_discovery_engine",
        pii_context=opposing_pii,
    )

    try:
        draft_items = _parse_llm_items(result.text, limited_count)
    except Exception as parse_exc:
        logger.warning("legal_discovery_parse_failed case_slug=%s error=%s", case_slug, str(parse_exc)[:240])
        draft_items = _fallback_discovery_items(graph_snapshot, normalized_pack_type, limited_count)

    now = datetime.now(timezone.utc)
    draft_pack = DiscoveryDraftPack(
        id=uuid4(),
        case_id=legal_case.id,
        pack_type=normalized_pack_type,
        status="draft",
        created_at=now,
    )
    db.add(draft_pack)
    await db.flush()

    for idx, item_text in enumerate(draft_items, start=1):
        db.add(
            DiscoveryDraftItem(
                id=uuid4(),
                pack_id=draft_pack.id,
                item_number=idx,
                content=item_text,
                relevance_score=1.0,
                proportionality_flag=False,
                created_at=now,
            )
        )

    await db.commit()
    return {
        "pack_id": str(draft_pack.id),
        "case_slug": case_slug,
        "pack_type": normalized_pack_type,
        "status": "draft",
        "items_generated": len(draft_items),
        "item_limit": limited_count,
        "items": draft_items,
        "inference_source": result.source,
        "breaker_state": result.breaker_state,
    }


async def validate_discovery_pack(db: AsyncSession, pack_id: UUID) -> dict:
    pack_res = await db.execute(
        select(DiscoveryDraftPack).where(DiscoveryDraftPack.id == pack_id)
    )
    pack = pack_res.scalar_one_or_none()
    if not pack:
        raise HTTPException(status_code=404, detail=f"Discovery draft pack '{pack_id}' not found")

    items_res = await db.execute(
        select(DiscoveryDraftItem).where(DiscoveryDraftItem.pack_id == pack.id).order_by(DiscoveryDraftItem.item_number.asc())
    )
    items = list(items_res.scalars().all())
    is_proportional = len(items) <= RULE_26_MAX_ITEMS
    for item in items:
        item.proportionality_flag = is_proportional

    await db.commit()
    return {
        "pack_id": str(pack.id),
        "items_count": len(items),
        "rule_26_limit": RULE_26_MAX_ITEMS,
        "proportionality_passed": is_proportional,
    }


class LegalDiscoveryEngine:
    @staticmethod
    async def draft_discovery_pack(
        case_slug: str,
        target_party: str,
        category: str,
        db: AsyncSession,
    ) -> dict:
        _ = target_party
        return await generate_discovery_pack(
            db=db,
            case_slug=case_slug,
            pack_type=category,
            item_limit=RULE_26_MAX_ITEMS,
        )

    @staticmethod
    async def generate_draft_pack(
        case_slug: str,
        target_entity: str,
        db: AsyncSession,
        max_items: int = 50,
    ) -> dict:
        if not case_slug.strip():
            raise HTTPException(status_code=422, detail="case_slug is required")
        if not target_entity.strip():
            raise HTTPException(status_code=422, detail="target_entity is required")
        if max_items < 1 or max_items > 100:
            raise HTTPException(status_code=422, detail="max_items must be between 1 and 100")

        graph_snapshot = await LegalCaseGraphBuilder.get_graph_snapshot(case_slug=case_slug, db=db)
        nodes = graph_snapshot.get("nodes", [])
        edges = graph_snapshot.get("edges", [])

        graph_context = {
            "case_slug": case_slug,
            "nodes": nodes,
            "edges": edges,
        }

        exemplars = await get_godhead_exemplars(
            db=db,
            categories=["INTERROGATORY", "RFP"],
            max_items=3,
        )
        exemplars_text = "\n\n".join(
            (
                f"[{example['category']}]\n"
                f"Rationale: {example['rationale_context']}\n"
                f"Output: {example['perfect_output']}"
            )
            for example in exemplars
        )

        if exemplars_text:
            rationale_hint = (
                "Use the provided case graph JSON (nodes, edges, contradiction links, and target entity context) "
                "as the controlling rationale."
            )
            system_prompt = (
                "You are a Tier 1 Georgia litigator. You must mimic the exact tone, structure, "
                "and taxonomy of these perfect examples.\n\n"
                f"### PERFECT EXEMPLARS ###\n{exemplars_text}\n\n"
                "### YOUR TASK ###\n"
                f"Based on the case graph rationale: {rationale_hint}, generate exactly {max_items} "
                f"new INTERROGATORY/RFP items targeting {target_entity}. "
                'Output strict JSON: {"items": [{"category": "...", "content": "...", "rationale": "..."}]}.'
            )
        else:
            system_prompt = (
                f"You are a Tier 1 corporate defense litigator in Georgia. Analyze the provided Case Graph. "
                f"Generate exactly {max_items} highly specific Interrogatories and Requests for Production "
                f"targeting {target_entity}. Do not use boilerplate. Base every question on the edges and "
                f"contradictions in the graph. Output strict JSON: "
                f'{{"items": [{{"category": "...", "content": "...", "rationale": "..."}}]}}.'
            )

        user_prompt = (
            "Case graph JSON:\n"
            f"{json.dumps(graph_context, ensure_ascii=True, default=str)}\n\n"
            f"Target entity: {target_entity}\n"
            f"Required item count: {max_items}\n"
            "Only return strict JSON."
        )

        llm_payload = {
            "model": DISCOVERY_CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 6000,
        }

        try:
            with httpx.Client(timeout=240.0) as client:
                resp = client.post(DISCOVERY_CHAT_URL, json=llm_payload)
                resp.raise_for_status()
                llm_data = resp.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Discovery inference failed at {DISCOVERY_CHAT_URL}: {str(exc)[:220]}",
            ) from exc

        try:
            content = llm_data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Invalid discovery model response: {str(exc)[:180]}") from exc

        parsed_items = LegalDiscoveryEngine._parse_items_payload(content=content, max_items=max_items)
        if len(parsed_items) < max_items:
            parsed_items.extend(
                LegalDiscoveryEngine._fallback_items_from_edges(
                    edges=edges,
                    target_entity=target_entity,
                    start_sequence=len(parsed_items) + 1,
                    needed=max_items - len(parsed_items),
                )
            )

        now = datetime.now(timezone.utc)
        pack = DiscoveryDraftPackV2(
            id=uuid4(),
            case_slug=case_slug,
            target_entity=target_entity,
            status="DRAFT",
            created_at=now,
        )
        db.add(pack)
        await db.flush()

        created_items: list[dict] = []
        for idx, item in enumerate(parsed_items[:max_items], start=1):
            category = str(item.get("category", "INTERROGATORY")).upper()
            if category not in {"INTERROGATORY", "RFP", "ADMISSION"}:
                category = "INTERROGATORY"
            content_text = str(item.get("content", "")).strip()
            rationale_text = str(item.get("rationale", "")).strip() or "Derived from case graph contradictions."
            if not content_text:
                continue
            row = DiscoveryDraftItemV2(
                id=uuid4(),
                pack_id=pack.id,
                category=category,
                content=content_text,
                rationale_from_graph=rationale_text,
                sequence_number=idx,
            )
            db.add(row)
            created_items.append(
                {
                    "category": category,
                    "content": content_text,
                    "rationale": rationale_text,
                    "sequence_number": idx,
                }
            )

        await db.commit()
        return {
            "pack_id": str(pack.id),
            "case_slug": case_slug,
            "target_entity": target_entity,
            "status": "DRAFT",
            "items_generated": len(created_items),
            "items": created_items,
            "model": DISCOVERY_CHAT_MODEL,
        }

    @staticmethod
    def _parse_items_payload(content: str, max_items: int) -> list[dict]:
        raw = (content or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start < 0 or end <= start:
                return []
            try:
                payload = json.loads(raw[start : end + 1])
            except Exception:
                return []

        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []

        normalized: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "category": str(item.get("category", "INTERROGATORY")).upper(),
                    "content": str(item.get("content", "")).strip(),
                    "rationale": str(item.get("rationale", "")).strip(),
                }
            )
            if len(normalized) >= max_items:
                break
        return normalized

    @staticmethod
    def _fallback_items_from_edges(edges: list[dict], target_entity: str, start_sequence: int, needed: int) -> list[dict]:
        results: list[dict] = []
        seq = start_sequence
        for edge in edges:
            if len(results) >= needed:
                break
            rel = edge.get("relationship_type", "RELATES_TO")
            rationale = (
                f"Graph edge {edge.get('source_node_id')} -> {edge.get('target_node_id')} "
                f"({rel}) weight={edge.get('weight')}"
            )
            if seq % 2 == 0:
                category = "RFP"
                content = (
                    f"Produce every document and communication reflecting how {target_entity} "
                    f"is connected by relationship '{rel}' in this case graph."
                )
            else:
                category = "INTERROGATORY"
                content = (
                    f"Identify all facts, witnesses, and documents supporting {target_entity}'s "
                    f"position tied to graph relationship '{rel}'."
                )
            results.append({"category": category, "content": content, "rationale": rationale})
            seq += 1
        while len(results) < needed:
            idx = start_sequence + len(results)
            results.append(
                {
                    "category": "INTERROGATORY",
                    "content": f"Identify each fact supporting {target_entity}'s disputed position number {idx}.",
                    "rationale": "Fallback generation when model output is incomplete.",
                }
            )
        return results
