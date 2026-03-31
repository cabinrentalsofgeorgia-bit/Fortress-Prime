"""
Deposition Kill-Sheet API.
"""
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.core.database import AsyncSessionLocal
from backend.core.security import require_manager_or_admin
from backend.services.legal_deposition_engine import LegalDepositionEngine

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])


class KillSheetRequest(BaseModel):
    deponent_entity: str = Field(..., min_length=1, max_length=255)


@router.post("/cases/{case_slug}/deposition/kill-sheet", summary="Generate deposition kill-sheet")
async def generate_deposition_kill_sheet(case_slug: str, body: KillSheetRequest):
    async with AsyncSessionLocal() as db:
        try:
            return await LegalDepositionEngine.generate_kill_sheet(
                case_slug=case_slug,
                deponent_entity=body.deponent_entity,
                db=db,
            )
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to generate kill-sheet: {str(exc)[:220]}") from exc


@router.get("/cases/{case_slug}/deposition/kill-sheets", summary="List deposition kill-sheets")
async def list_deposition_kill_sheets(case_slug: str):
    async with AsyncSessionLocal() as db:
        try:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT id, case_slug, deponent_entity, status, summary,
                               high_risk_topics_json, document_sequence_json, suggested_questions_json, created_at
                        FROM legal.deposition_kill_sheets_v2
                        WHERE case_slug = :case_slug
                        ORDER BY created_at DESC
                        """
                    ),
                    {"case_slug": case_slug},
                )
            ).mappings().all()

            kill_sheets = [
                {
                    "id": str(row["id"]),
                    "case_slug": row["case_slug"],
                    "deponent_entity": row["deponent_entity"],
                    "status": row["status"],
                    "summary": row["summary"],
                    "high_risk_topics": row["high_risk_topics_json"] or [],
                    "document_sequence": row["document_sequence_json"] or [],
                    "suggested_questions": row["suggested_questions_json"] or [],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
                for row in rows
            ]
            return {"case_slug": case_slug, "kill_sheets": kill_sheets, "total": len(kill_sheets)}
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to list kill-sheets: {str(exc)[:220]}") from exc


@router.get(
    "/cases/{case_slug}/deposition/kill-sheets/{sheet_id}/export",
    summary="Export deposition kill-sheet as markdown",
    response_class=PlainTextResponse,
)
async def export_deposition_kill_sheet(case_slug: str, sheet_id: str):
    async with AsyncSessionLocal() as db:
        try:
            row = (
                await db.execute(
                    text(
                        """
                        SELECT id, case_slug, deponent_entity, status, summary,
                               high_risk_topics_json, document_sequence_json, suggested_questions_json, created_at
                        FROM legal.deposition_kill_sheets_v2
                        WHERE case_slug = :case_slug AND id = CAST(:sheet_id AS uuid)
                        LIMIT 1
                        """
                    ),
                    {"case_slug": case_slug, "sheet_id": sheet_id},
                )
            ).mappings().first()

            if not row:
                raise HTTPException(status_code=404, detail="Kill-sheet not found")

            created_at = row["created_at"]
            if created_at is None:
                date_generated = "Unknown"
            else:
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                date_generated = created_at.isoformat()

            high_risk_topics = row["high_risk_topics_json"] if isinstance(row["high_risk_topics_json"], list) else []
            document_sequence = row["document_sequence_json"] if isinstance(row["document_sequence_json"], list) else []
            suggested_questions = row["suggested_questions_json"] if isinstance(row["suggested_questions_json"], list) else []

            topic_lines = "\n".join(
                f"- {str(topic).strip()}"
                for topic in high_risk_topics
                if str(topic).strip()
            ) or "- None captured."

            exhibit_lines = "\n".join(
                f"- **Exhibit [ __ ]** `{str(item.get('doc_name', 'Untitled Document')).strip()}`\n"
                f"  - Tactical Purpose: {str(item.get('tactical_purpose', 'No tactical purpose provided.')).strip()}"
                for item in document_sequence
                if isinstance(item, dict)
            ) or "- **Exhibit [ __ ]** `TBD`\n  - Tactical Purpose: Not available."

            question_lines = "\n".join(
                f"- [ ] {idx}. {str(question).strip()}"
                for idx, question in enumerate(suggested_questions, start=1)
                if str(question).strip()
            ) or "- [ ] 1. No suggested questions available."

            markdown = (
                "# DEPOSITION TACTICAL BRIEF\n\n"
                f"**Deponent:** {row['deponent_entity']}\n\n"
                f"**Case:** {row['case_slug']}\n\n"
                f"**Date Generated:** {date_generated}\n\n"
                "## Executive Summary\n\n"
                f"{row['summary']}\n\n"
                "## High-Risk Impeachment Topics\n\n"
                f"{topic_lines}\n\n"
                "## Exhibit & Document Sequence\n\n"
                f"{exhibit_lines}\n\n"
                "## The Lock-In Sequence (Suggested Questions)\n\n"
                f"{question_lines}\n"
            )
            return PlainTextResponse(content=markdown, media_type="text/markdown")
        except HTTPException:
            await db.rollback()
            raise
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to export kill-sheet: {str(exc)[:220]}") from exc
