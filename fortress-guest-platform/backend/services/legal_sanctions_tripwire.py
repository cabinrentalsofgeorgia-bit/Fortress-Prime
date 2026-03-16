"""
Sanctions Tripwire daemon for legal contradiction sweeps.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
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
TRIPWIRE_ADVISORY_LOCK_KEY = int(os.getenv("LEGAL_TRIPWIRE_LOCK_KEY", "98110417"))


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
    async def _ensure_run_schema(db: AsyncSession) -> None:
        await db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS legal.sanctions_tripwire_runs_v2 (
                    id uuid PRIMARY KEY,
                    case_slug varchar(255) NOT NULL,
                    trigger_source varchar(64) NOT NULL DEFAULT 'cron',
                    status varchar(32) NOT NULL DEFAULT 'running',
                    model_used varchar(128),
                    alerts_found integer NOT NULL DEFAULT 0,
                    alerts_saved integer NOT NULL DEFAULT 0,
                    error_detail text,
                    started_at timestamptz NOT NULL DEFAULT NOW(),
                    completed_at timestamptz NULL
                )
                """
            )
        )
        await db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_sanctions_tripwire_runs_v2_case_started
                ON legal.sanctions_tripwire_runs_v2 (case_slug, started_at DESC)
                """
            )
        )
        await db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_sanctions_tripwire_runs_v2_status_started
                ON legal.sanctions_tripwire_runs_v2 (status, started_at DESC)
                """
            )
        )

    @staticmethod
    async def _acquire_daemon_lock(db: AsyncSession) -> bool:
        row = (
            await db.execute(
                text("SELECT pg_try_advisory_lock(:k) AS locked"),
                {"k": TRIPWIRE_ADVISORY_LOCK_KEY},
            )
        ).mappings().first()
        return bool(row and row.get("locked"))

    @staticmethod
    async def _release_daemon_lock(db: AsyncSession) -> None:
        await db.execute(
            text("SELECT pg_advisory_unlock(:k)"),
            {"k": TRIPWIRE_ADVISORY_LOCK_KEY},
        )

    @staticmethod
    async def _discover_case_slugs(db: AsyncSession, limit: int, include_closed: bool) -> list[str]:
        params: dict[str, Any] = {"limit": max(1, min(limit, 500))}
        if include_closed:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT slug
                        FROM legal.legal_cases
                        ORDER BY created_at DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                )
            ).mappings().all()
        else:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT slug
                        FROM legal.legal_cases
                        WHERE COALESCE(status, 'open') NOT IN ('closed', 'resolved', 'archived')
                        ORDER BY created_at DESC
                        LIMIT :limit
                        """
                    ),
                    params,
                )
            ).mappings().all()

        slugs = [str(r.get("slug", "")).strip() for r in rows if str(r.get("slug", "")).strip()]
        if slugs:
            return slugs

        fallback = (
            await db.execute(
                text(
                    """
                    SELECT DISTINCT case_slug
                    FROM legal.case_graph_nodes_v2
                    WHERE case_slug IS NOT NULL AND case_slug <> ''
                    ORDER BY case_slug
                    LIMIT :limit
                    """
                ),
                params,
            )
        ).mappings().all()
        return [str(r.get("case_slug", "")).strip() for r in fallback if str(r.get("case_slug", "")).strip()]

    @staticmethod
    async def _infer_alerts(case_slug: str, db: AsyncSession) -> tuple[str, list[dict[str, Any]]]:
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

            normalized.append(
                {
                    "alert_type": alert_type,
                    "contradiction_summary": contradiction_summary,
                    "confidence_score": confidence_score,
                }
            )
        return model_used, normalized

    @staticmethod
    async def run_sweep(case_slug: str, db: AsyncSession, trigger_source: str = "api") -> dict:
        await LegalSanctionsTripwire._ensure_run_schema(db)
        run_id = str(uuid4())
        await db.execute(
            text(
                """
                INSERT INTO legal.sanctions_tripwire_runs_v2
                    (id, case_slug, trigger_source, status, started_at)
                VALUES
                    (:id, :case_slug, :trigger_source, 'running', NOW())
                """
            ),
            {
                "id": run_id,
                "case_slug": case_slug,
                "trigger_source": trigger_source[:64],
            },
        )
        await db.commit()

        try:
            model_used, alerts = await LegalSanctionsTripwire._infer_alerts(case_slug=case_slug, db=db)

            saved = 0
            for alert in alerts:
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
                        "alert_type": alert["alert_type"],
                        "summary": alert["contradiction_summary"][:4000],
                        "confidence": alert["confidence_score"],
                    },
                )
                saved += 1

            await db.execute(
                text(
                    """
                    UPDATE legal.sanctions_tripwire_runs_v2
                    SET status = 'completed',
                        model_used = :model,
                        alerts_found = :alerts_found,
                        alerts_saved = :alerts_saved,
                        completed_at = NOW()
                    WHERE id = :id
                    """
                ),
                {
                    "id": run_id,
                    "model": model_used,
                    "alerts_found": len(alerts),
                    "alerts_saved": saved,
                },
            )
            await db.commit()

            logger.info(
                "tripwire_sweep_complete",
                case_slug=case_slug,
                alerts_found=len(alerts),
                saved=saved,
                model=model_used,
                run_id=run_id,
                trigger_source=trigger_source,
            )
            return {
                "run_id": run_id,
                "case_slug": case_slug,
                "model": model_used,
                "alerts_found": len(alerts),
                "saved": saved,
                "alerts": alerts,
                "status": "completed",
            }
        except Exception as exc:
            await db.rollback()
            try:
                await db.execute(
                    text(
                        """
                        UPDATE legal.sanctions_tripwire_runs_v2
                        SET status = 'failed',
                            error_detail = :error_detail,
                            completed_at = NOW()
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": run_id,
                        "error_detail": str(exc)[:4000],
                    },
                )
                await db.commit()
            except Exception:
                await db.rollback()
            raise

    @staticmethod
    async def run_cron_sweep(
        db: AsyncSession,
        *,
        case_slug: str | None = None,
        limit: int = 25,
        include_closed: bool = False,
        trigger_source: str = "cron",
    ) -> dict:
        await LegalSanctionsTripwire._ensure_run_schema(db)

        if case_slug:
            result = await LegalSanctionsTripwire.run_sweep(
                case_slug=case_slug,
                db=db,
                trigger_source=trigger_source,
            )
            return {
                "mode": "single_case",
                "trigger_source": trigger_source,
                "results": [result],
                "total_cases": 1,
                "success_count": 1,
                "failure_count": 0,
            }

        acquired = await LegalSanctionsTripwire._acquire_daemon_lock(db)
        await db.commit()
        if not acquired:
            return {
                "mode": "batch",
                "trigger_source": trigger_source,
                "status": "skipped_lock",
                "message": "Tripwire cron is already running in another process.",
                "total_cases": 0,
                "success_count": 0,
                "failure_count": 0,
                "results": [],
            }

        try:
            case_slugs = await LegalSanctionsTripwire._discover_case_slugs(
                db=db,
                limit=limit,
                include_closed=include_closed,
            )
            await db.commit()

            if not case_slugs:
                return {
                    "mode": "batch",
                    "trigger_source": trigger_source,
                    "status": "no_cases",
                    "total_cases": 0,
                    "success_count": 0,
                    "failure_count": 0,
                    "results": [],
                }

            results: list[dict[str, Any]] = []
            success_count = 0
            failure_count = 0

            for slug in case_slugs:
                try:
                    res = await LegalSanctionsTripwire.run_sweep(
                        case_slug=slug,
                        db=db,
                        trigger_source=trigger_source,
                    )
                    results.append(res)
                    success_count += 1
                except Exception as exc:
                    await db.rollback()
                    failure_count += 1
                    err = {
                        "case_slug": slug,
                        "status": "failed",
                        "error": str(exc)[:320],
                    }
                    logger.error("tripwire_case_failed", **err)
                    results.append(err)

            return {
                "mode": "batch",
                "trigger_source": trigger_source,
                "status": "completed",
                "total_cases": len(case_slugs),
                "success_count": success_count,
                "failure_count": failure_count,
                "results": results,
            }
        finally:
            try:
                await LegalSanctionsTripwire._release_daemon_lock(db)
                await db.commit()
            except Exception:
                await db.rollback()

    @staticmethod
    async def list_recent_runs(db: AsyncSession, limit: int = 50) -> list[dict[str, Any]]:
        await LegalSanctionsTripwire._ensure_run_schema(db)
        rows = (
            await db.execute(
                text(
                    """
                    SELECT id, case_slug, trigger_source, status, model_used,
                           alerts_found, alerts_saved, error_detail,
                           started_at, completed_at
                    FROM legal.sanctions_tripwire_runs_v2
                    ORDER BY started_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": max(1, min(limit, 500))},
            )
        ).mappings().all()
        return [
            {
                "id": str(row["id"]),
                "case_slug": row["case_slug"],
                "trigger_source": row["trigger_source"],
                "status": row["status"],
                "model_used": row["model_used"],
                "alerts_found": row["alerts_found"],
                "alerts_saved": row["alerts_saved"],
                "error_detail": row["error_detail"],
                "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
            }
            for row in rows
        ]


async def detect_material_contradictions(db: AsyncSession, case_slug: str) -> dict:
    """
    Backward-compatible wrapper for legacy callers.
    """
    return await LegalSanctionsTripwire.run_sweep(case_slug=case_slug, db=db)
