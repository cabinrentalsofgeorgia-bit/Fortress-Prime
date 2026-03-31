"""
Legal Document Generation API — POST /api/internal/legal/document/draft
===============================================================
Accepts the Council's consensus + case brief, generates a court-formatted
DOCX (Answer and Affirmative Defenses), and returns the binary file.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Any

from backend.core.security import require_manager_or_admin
from backend.services.legal_docgen import generate_answer_and_defenses

logger = structlog.get_logger()

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])


class DocGenRequest(BaseModel):
    case_brief: str = Field(
        ..., min_length=10, description="The case brief used for deliberation"
    )
    consensus: dict[str, Any] = Field(
        ..., description="The Council's consensus result object"
    )


@router.post(
    "/document/draft",
    summary="Generate court-formatted DOCX pleading",
    description="Generates a Georgia Superior Court Answer and Affirmative Defenses document.",
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}
            },
            "description": "DOCX file download",
        }
    },
)
async def generate_draft(request: DocGenRequest):
    logger.info(
        "legal_docgen_request",
        brief_len=len(request.case_brief),
        signal=request.consensus.get("consensus_signal"),
    )
    try:
        docx_bytes = generate_answer_and_defenses(
            case_brief=request.case_brief,
            consensus=request.consensus,
        )
        case_num = "SUV2026000013"
        filename = f"Answer_and_Defenses_{case_num}.docx"

        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(docx_bytes)),
            },
        )
    except Exception as exc:
        logger.error("legal_docgen_error", error=str(exc)[:500], exc_info=True)
        raise HTTPException(
            status_code=502,
            detail={
                "type": "https://fortress/errors/docgen",
                "title": "Document Generation Failed",
                "status": 502,
                "detail": f"DocGen failed: {str(exc)[:200]}",
            },
        )
