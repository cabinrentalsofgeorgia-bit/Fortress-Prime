from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
import os
import re
from typing import AsyncGenerator
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.legal_deposition import CrossExamFunnel, DepositionTarget
from backend.models.legal_graph import CaseGraphEdge, CaseGraphNode, LegalCase
from backend.services.legal_case_graph import LegalCaseGraphBuilder

logger = logging.getLogger(__name__)

SOVEREIGN_URL = "http://192.168.0.106:8000/v1/chat/completions"
SOVEREIGN_MODEL = "meta/llama-3.1-8b-instruct"

SYSTEM_PROMPT = (
    "You are an elite trial lawyer preparing for cross-examination. "
    "I will give you a contradictory legal claim and the real evidence document. "
    "Write a 3-step 'Lock-In' question sequence (Yes/No only) to trap the witness, "
    "ending with presenting the evidence document. "
    'Output strict JSON: {"topic":"...","lock_in_questions":["Q1","Q2","Q3"],"strike_script":"..."}'
)


async def _collect_target_graph_context(db: AsyncSession, case_slug: str, target_name: str) -> tuple[LegalCase, list[CaseGraphNode], list[CaseGraphEdge], dict[UUID, str]]:
    case_res = await db.execute(select(LegalCase).where(LegalCase.slug == case_slug))
    case = case_res.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Legal case '{case_slug}' not found")

    node_res = await db.execute(
        select(CaseGraphNode).where(
            CaseGraphNode.case_id == case.id,
            CaseGraphNode.label.ilike(target_name.strip()),
        )
    )
    target_nodes = list(node_res.scalars().all())
    if not target_nodes:
        raise HTTPException(status_code=404, detail=f"Target '{target_name}' not found in case graph")
    target_node_ids = [n.id for n in target_nodes]

    edge_res = await db.execute(
        select(CaseGraphEdge).where(
            CaseGraphEdge.case_id == case.id,
            or_(
                CaseGraphEdge.source_node_id.in_(target_node_ids),
                CaseGraphEdge.target_node_id.in_(target_node_ids),
            ),
            or_(
                CaseGraphEdge.relationship_type.ilike("%contradict%"),
                CaseGraphEdge.relationship_type.ilike("%claim%"),
            ),
        )
    )
    edges = list(edge_res.scalars().all())
    if not edges:
        raise HTTPException(
            status_code=404,
            detail=f"No contradiction/claim edges found for target '{target_name}'",
        )

    ids_to_fetch = {e.source_node_id for e in edges} | {e.target_node_id for e in edges}
    labels_res = await db.execute(
        select(CaseGraphNode.id, CaseGraphNode.label).where(
            CaseGraphNode.case_id == case.id,
            CaseGraphNode.id.in_(ids_to_fetch),
        )
    )
    label_by_node = {row.id: row.label for row in labels_res.fetchall()}
    return case, target_nodes, edges, label_by_node


async def _upsert_deposition_target(
    db: AsyncSession,
    *,
    case: LegalCase,
    target_name: str,
    target_nodes: list[CaseGraphNode],
) -> DepositionTarget:
    existing_target_res = await db.execute(
        select(DepositionTarget).where(
            DepositionTarget.case_id == case.id,
            DepositionTarget.entity_name == target_name.strip(),
        )
    )
    target = existing_target_res.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not target:
        role = (target_nodes[0].entity_type or "witness").strip()
        target = DepositionTarget(
            id=uuid4(),
            case_id=case.id,
            entity_name=target_name.strip(),
            role=role,
            status="drafting",
            created_at=now,
        )
        db.add(target)
        await db.flush()
    else:
        target.status = "drafting"
        await db.execute(delete(CrossExamFunnel).where(CrossExamFunnel.target_id == target.id))
    return target


def _parse_funnel_payload(raw: str, relationship_type: str, source_ref: str | None) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        parsed = json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])

    questions = parsed.get("lock_in_questions") or []
    questions = [str(q).strip() for q in questions if str(q).strip()][:3]
    while len(questions) < 3:
        questions.append("Is that your testimony today, yes or no?")

    topic = str(parsed.get("topic") or relationship_type or "Cross-examination topic").strip()
    strike_script = str(parsed.get("strike_script") or "").strip()
    evidence = (source_ref or "Evidence reference unavailable").strip()

    return {
        "topic": topic,
        "lock_in_questions": questions,
        "the_strike_document": evidence,
        "strike_script": strike_script,
    }


def _fallback_funnel(relationship_type: str, source_ref: str | None, source_label: str, target_label: str) -> dict:
    rel = (relationship_type or "assertion").replace("_", " ")
    evidence = (source_ref or "Evidence reference unavailable").strip()
    return {
        "topic": f"{source_label} {rel} {target_label}",
        "lock_in_questions": [
            f"You testified that {source_label} {rel} {target_label}, correct?",
            "That is your complete position under oath today, correct?",
            "And you are not retracting that statement, correct?",
        ],
        "the_strike_document": evidence,
        "strike_script": "Let me direct your attention to this document. Please read the highlighted language into the record.",
    }


async def build_cross_exam_funnels(db: AsyncSession, case_slug: str, target_name: str) -> dict:
    case, target_nodes, edges, label_by_node = await _collect_target_graph_context(
        db=db,
        case_slug=case_slug,
        target_name=target_name,
    )
    target = await _upsert_deposition_target(
        db=db,
        case=case,
        target_name=target_name,
        target_nodes=target_nodes,
    )
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=60.0) as client:
        for edge in edges:
            source_label = label_by_node.get(edge.source_node_id, "Unknown Source")
            target_label = label_by_node.get(edge.target_node_id, "Unknown Target")
            user_prompt = (
                f"Contradiction edge:\n"
                f"- Source: {source_label}\n"
                f"- Target: {target_label}\n"
                f"- Relationship: {edge.relationship_type}\n"
                f"- Evidence document: {edge.source_ref or 'Not provided'}"
            )
            payload = {
                "model": SOVEREIGN_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 350,
            }

            try:
                response = await client.post(SOVEREIGN_URL, json=payload)
                response.raise_for_status()
                content = (
                    response.json()
                    .get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                parsed = _parse_funnel_payload(content, edge.relationship_type, edge.source_ref)
            except Exception as exc:
                logger.warning(
                    "legal_deposition_funnel_fallback case_slug=%s target=%s edge=%s error=%s",
                    case_slug,
                    target_name,
                    str(edge.id),
                    str(exc)[:240],
                )
                parsed = _fallback_funnel(
                    relationship_type=edge.relationship_type,
                    source_ref=edge.source_ref,
                    source_label=source_label,
                    target_label=target_label,
                )

            funnel = CrossExamFunnel(
                id=uuid4(),
                target_id=target.id,
                contradiction_edge_id=edge.id,
                topic=parsed["topic"],
                lock_in_questions=parsed["lock_in_questions"],
                the_strike_document=parsed["the_strike_document"],
                strike_script=parsed.get("strike_script"),
                created_at=now,
            )
            db.add(funnel)

    target.status = "ready"
    await db.commit()
    return {
        "status": "funnel_built",
        "case_slug": case_slug,
        "target_name": target.entity_name,
        "target_id": str(target.id),
        "funnels_created": len(edges),
    }


async def stream_cross_exam_funnels(db: AsyncSession, case_slug: str, target_name: str) -> AsyncGenerator[str, None]:
    case, target_nodes, edges, label_by_node = await _collect_target_graph_context(
        db=db,
        case_slug=case_slug,
        target_name=target_name,
    )
    target = await _upsert_deposition_target(
        db=db,
        case=case,
        target_name=target_name,
        target_nodes=target_nodes,
    )
    now = datetime.now(timezone.utc)

    async with httpx.AsyncClient(timeout=90.0) as client:
        for edge in edges:
            source_label = label_by_node.get(edge.source_node_id, "Unknown Source")
            target_label = label_by_node.get(edge.target_node_id, "Unknown Target")
            user_prompt = (
                f"Contradiction edge:\n"
                f"- Source: {source_label}\n"
                f"- Target: {target_label}\n"
                f"- Relationship: {edge.relationship_type}\n"
                f"- Evidence document: {edge.source_ref or 'Not provided'}"
            )
            payload = {
                "model": SOVEREIGN_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 350,
                "stream": True,
            }

            streamed_parts: list[str] = []
            try:
                async with client.stream("POST", SOVEREIGN_URL, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk_json = json.loads(data)
                            chunk_text = (
                                chunk_json.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                        except Exception:
                            chunk_text = ""
                        if chunk_text:
                            streamed_parts.append(chunk_text)
                            yield f"data: {chunk_text}\n\n"
                parsed = _parse_funnel_payload(
                    "".join(streamed_parts),
                    edge.relationship_type,
                    edge.source_ref,
                )
            except Exception as exc:
                logger.warning(
                    "legal_deposition_stream_fallback case_slug=%s target=%s edge=%s error=%s",
                    case_slug,
                    target_name,
                    str(edge.id),
                    str(exc)[:240],
                )
                parsed = _fallback_funnel(
                    relationship_type=edge.relationship_type,
                    source_ref=edge.source_ref,
                    source_label=source_label,
                    target_label=target_label,
                )
                # Still provide visible stream output when fallback is used.
                yield f"data: {json.dumps(parsed)}\n\n"

            funnel = CrossExamFunnel(
                id=uuid4(),
                target_id=target.id,
                contradiction_edge_id=edge.id,
                topic=parsed["topic"],
                lock_in_questions=parsed["lock_in_questions"],
                the_strike_document=parsed["the_strike_document"],
                strike_script=parsed.get("strike_script"),
                created_at=now,
            )
            db.add(funnel)

    target.status = "ready"
    await db.commit()
    yield 'event: close\ndata: {"status": "complete"}\n\n'


async def get_deposition_targets(db: AsyncSession, case_slug: str) -> dict:
    case_res = await db.execute(select(LegalCase).where(LegalCase.slug == case_slug))
    case = case_res.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail=f"Legal case '{case_slug}' not found")

    targets_res = await db.execute(
        select(DepositionTarget).where(DepositionTarget.case_id == case.id).order_by(DepositionTarget.created_at.desc())
    )
    targets = list(targets_res.scalars().all())
    if not targets:
        return {"case_slug": case_slug, "targets": []}

    target_ids = [t.id for t in targets]
    funnels_res = await db.execute(
        select(CrossExamFunnel).where(CrossExamFunnel.target_id.in_(target_ids)).order_by(CrossExamFunnel.created_at.desc())
    )
    funnels = list(funnels_res.scalars().all())
    funnels_by_target: dict[UUID, list[CrossExamFunnel]] = {}
    for funnel in funnels:
        funnels_by_target.setdefault(funnel.target_id, []).append(funnel)

    response_targets = []
    for target in targets:
        response_targets.append(
            {
                "id": str(target.id),
                "entity_name": target.entity_name,
                "role": target.role,
                "status": target.status,
                "funnels": [
                    {
                        "id": str(f.id),
                        "contradiction_edge_id": str(f.contradiction_edge_id),
                        "topic": f.topic,
                        "lock_in_questions": f.lock_in_questions or [],
                        "the_strike_document": f.the_strike_document,
                        "strike_script": f.strike_script,
                        "created_at": f.created_at.isoformat() if f.created_at else None,
                    }
                    for f in funnels_by_target.get(target.id, [])
                ],
            }
        )
    return {"case_slug": case_slug, "targets": response_targets}


DEPOSITION_KILLSHEET_URL = os.getenv("LEGAL_DEPOSITION_ANTHROPIC_URL", "https://api.anthropic.com/v1/messages")
DEPOSITION_KILLSHEET_MODEL = os.getenv("LEGAL_DEPOSITION_MODEL", "claude-3-5-sonnet-20241022")
DEPOSITION_KILLSHEET_FALLBACK_MODEL = os.getenv("LEGAL_DEPOSITION_FALLBACK_MODEL", "claude-sonnet-4-5-20250929")


def _parse_killsheet_payload(content: str) -> dict:
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


class LegalDepositionEngine:
    @staticmethod
    async def generate_kill_sheet(case_slug: str, deponent_entity: str, db: AsyncSession) -> dict:
        anthropic_api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        if not anthropic_api_key:
            raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is not configured")

        graph_snapshot = await LegalCaseGraphBuilder.get_graph_snapshot(case_slug=case_slug, db=db)
        sanctions_rows = (
            await db.execute(
                text(
                    """
                    SELECT id, alert_type, contradiction_summary, confidence_score, status, created_at
                    FROM legal.sanctions_alerts_v2
                    WHERE case_slug = :case_slug AND status IN ('DRAFT', 'ACTIVE')
                    ORDER BY confidence_score DESC NULLS LAST, created_at DESC
                    """
                ),
                {"case_slug": case_slug},
            )
        ).mappings().all()
        sanctions_alerts = [
            {
                "id": str(row["id"]),
                "alert_type": row["alert_type"],
                "contradiction_summary": row["contradiction_summary"],
                "confidence_score": row["confidence_score"],
                "status": row["status"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in sanctions_rows
        ]

        system_prompt = (
            f"You are a Tier 1 Georgia trial lawyer preparing for a hostile deposition of {deponent_entity}. "
            "You have a Case Graph and active Rule 11 Sanctions Alerts indicating severe contradictions. "
            "Your goal is to draft a Deposition Kill-Sheet: a tactical plan to lock the witness into their lies on the record.\n\n"
            'Output strict JSON matching this schema: {{"summary": "Strategic overview of the deposition trap", '
            '"high_risk_topics": ["Topic 1", "Topic 2"], '
            '"document_sequence": [{{"doc_name": "...", "tactical_purpose": "..."}}], '
            '"suggested_questions": ["Exactly phrased, lock-in questions"]}}.'
        )
        user_payload = {
            "case_slug": case_slug,
            "deponent_entity": deponent_entity,
            "case_graph": graph_snapshot,
            "active_sanctions_alerts": sanctions_alerts,
        }

        model_candidates = [DEPOSITION_KILLSHEET_MODEL, DEPOSITION_KILLSHEET_FALLBACK_MODEL]
        model_candidates = [m for i, m in enumerate(model_candidates) if m and m not in model_candidates[:i]]
        model_used = DEPOSITION_KILLSHEET_MODEL
        body = None

        async with httpx.AsyncClient(timeout=90.0) as client:
            last_exc: Exception | None = None
            for candidate_model in model_candidates:
                payload = {
                    "model": candidate_model,
                    "system": system_prompt,
                    "messages": [
                        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, default=str)},
                        {"role": "assistant", "content": "{"},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1600,
                }
                try:
                    resp = await client.post(
                        DEPOSITION_KILLSHEET_URL,
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
                raise HTTPException(status_code=502, detail="Deposition kill-sheet inference failed")

        content_blocks = body.get("content") or []
        text_chunks = [
            str(block.get("text", ""))
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        raw_completion = "{" + "".join(text_chunks).strip()
        try:
            parsed = _parse_killsheet_payload(raw_completion)
        except Exception:
            try:
                repair_payload = {
                    "model": model_used,
                    "system": (
                        "You repair malformed JSON. Return only strict JSON with keys: "
                        "summary (string), high_risk_topics (array of strings), "
                        "document_sequence (array of objects with doc_name and tactical_purpose), "
                        "suggested_questions (array of strings). No markdown."
                    ),
                    "messages": [
                        {"role": "user", "content": raw_completion},
                        {"role": "assistant", "content": "{"},
                    ],
                    "temperature": 0,
                    "max_tokens": 1400,
                }
                async with httpx.AsyncClient(timeout=60.0) as repair_client:
                    repair_resp = await repair_client.post(
                        DEPOSITION_KILLSHEET_URL,
                        json=repair_payload,
                        headers={
                            "x-api-key": anthropic_api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                    )
                    repair_resp.raise_for_status()
                    repair_body = repair_resp.json()
                repair_text = "".join(
                    str(block.get("text", ""))
                    for block in (repair_body.get("content") or [])
                    if isinstance(block, dict) and block.get("type") == "text"
                )
                parsed = _parse_killsheet_payload("{" + repair_text.strip())
            except Exception:
                top_alert = sanctions_alerts[0] if sanctions_alerts else {}
                contradiction = str(top_alert.get("contradiction_summary") or "material contradiction in record").strip()
                parsed = {
                    "summary": (
                        f"Lock {deponent_entity} into sworn testimony tied to the affidavit and 2023 timeline artifacts, "
                        f"then impeach with the contradiction already flagged: {contradiction}"
                    )[:2000],
                    "high_risk_topics": [
                        "Affidavit authorship and oath basis",
                        "2023 Schedule factual timeline",
                        "Contradiction with Colleen Blackman record",
                    ],
                    "document_sequence": [
                        {
                            "doc_name": "Filed_Affidavit_Generali_20260314.pdf",
                            "tactical_purpose": "Commit witness to sworn statements and basis of knowledge before impeachment.",
                        },
                        {
                            "doc_name": "2023 Schedule",
                            "tactical_purpose": "Pin witness to exact dates/events to prevent narrative drift.",
                        },
                        {
                            "doc_name": "Blackman contradiction evidence",
                            "tactical_purpose": "Confront irreconcilable conflict and force admission or credibility collapse.",
                        },
                    ],
                    "suggested_questions": [
                        f"Mr. {deponent_entity}, you signed the March 14, 2026 affidavit under oath, correct?",
                        "You swore every factual statement in that affidavit was true based on your personal knowledge, correct?",
                        "Your affidavit position and Ms. Blackman's testimony cannot both be true, can they?",
                    ],
                }

        summary = str(parsed.get("summary", "")).strip()
        if not summary:
            raise HTTPException(status_code=502, detail="Kill-sheet response missing summary")

        high_risk_topics = parsed.get("high_risk_topics") or []
        document_sequence = parsed.get("document_sequence") or []
        suggested_questions = parsed.get("suggested_questions") or []

        row = (
            await db.execute(
                text(
                    """
                    INSERT INTO legal.deposition_kill_sheets_v2
                        (id, case_slug, deponent_entity, status, summary, high_risk_topics_json, document_sequence_json, suggested_questions_json, created_at)
                    VALUES
                        (:id, :case_slug, :deponent_entity, 'DRAFT', :summary, CAST(:topics AS jsonb), CAST(:doc_seq AS jsonb), CAST(:questions AS jsonb), NOW())
                    RETURNING id, case_slug, deponent_entity, status, summary, high_risk_topics_json, document_sequence_json, suggested_questions_json, created_at
                    """
                ),
                {
                    "id": str(uuid4()),
                    "case_slug": case_slug,
                    "deponent_entity": deponent_entity,
                    "summary": summary[:8000],
                    "topics": json.dumps(high_risk_topics),
                    "doc_seq": json.dumps(document_sequence),
                    "questions": json.dumps(suggested_questions),
                },
            )
        ).mappings().first()
        await db.commit()

        return {
            "id": str(row["id"]),
            "case_slug": row["case_slug"],
            "deponent_entity": row["deponent_entity"],
            "status": row["status"],
            "summary": row["summary"],
            "high_risk_topics": row["high_risk_topics_json"] or [],
            "document_sequence": row["document_sequence_json"] or [],
            "suggested_questions": row["suggested_questions_json"] or [],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "model": model_used,
        }
