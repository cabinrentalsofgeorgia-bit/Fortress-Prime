"""Public grounded concierge chat endpoint."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.concierge_agent import ConciergeAgent
from backend.core.database import get_db

router = APIRouter(prefix="/api/chat")
concierge_agent = ConciergeAgent()


class ConciergeChatRequest(BaseModel):
    property_id: UUID
    message: str = Field(min_length=1, max_length=4000)


class ConciergeChatResponse(BaseModel):
    response: str
    context_chunks_used: int


@router.post(
    "/concierge",
    response_model=ConciergeChatResponse,
    status_code=status.HTTP_200_OK,
)
async def concierge_chat(
    body: ConciergeChatRequest,
    db: AsyncSession = Depends(get_db),
) -> ConciergeChatResponse:
    try:
        answer = await concierge_agent.answer_query(
            db,
            property_id=body.property_id,
            guest_message=body.message,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if detail == "Property not found" else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return ConciergeChatResponse(
        response=answer.response,
        context_chunks_used=len(answer.context_chunks),
    )
