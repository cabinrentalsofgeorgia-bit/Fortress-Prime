"""
LEGAL COUNCIL OF 9 — FastAPI Streaming Router
===============================================

POST /council/deliberate  — Start a council deliberation (SSE stream)
GET  /council/session/{id} — Get session state (poll fallback)
GET  /council/personas      — List all 9 legal personas

SSE Event Protocol (text/event-stream):
    {"type": "status",           "message": "..."}
    {"type": "persona_start",    "seat": N, "name": "...", "slug": "..."}
    {"type": "persona_complete", "seat": N, "opinion": {...}, ...}
    {"type": "consensus",        "consensus_signal": "...", ...}
    {"type": "done",             ...full result...}
"""

import asyncio
import json
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.services.legal_council import (
    get_session,
    list_personas_summary,
    run_council_deliberation,
)

logger = structlog.get_logger()
router = APIRouter()


class DeliberationRequest(BaseModel):
    case_brief: str = Field(
        ...,
        min_length=10,
        description="The case brief or legal question for the Council to analyze",
    )
    context: str = Field(
        default="",
        description="Additional context (evidence, emails, contract excerpts)",
    )


def _sse(data: dict) -> str:
    """Format a dict as an SSE data frame with strict JSON safety.

    Uses ensure_ascii to escape all non-ASCII into \\uXXXX sequences,
    and default=str to handle any stray non-serializable types (datetime, Enum).
    """
    try:
        payload = json.dumps(data, ensure_ascii=True, default=str)
    except (TypeError, ValueError) as exc:
        payload = json.dumps({"type": "error", "message": f"Serialization error: {exc}"})
    return f"data: {payload}\n\n"


@router.post("/council/deliberate")
async def deliberate(request: Request, body: DeliberationRequest):
    """
    Start a Legal Council of 9 deliberation session.
    Returns an SSE stream with real-time persona opinions and consensus.
    """
    session_id = str(uuid.uuid4())

    async def generate():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_progress(event: dict):
            await queue.put(event)

        task = asyncio.create_task(
            run_council_deliberation(
                session_id=session_id,
                case_brief=body.case_brief,
                context=body.context,
                progress_callback=on_progress,
            )
        )

        yield _sse({
            "type": "session_start",
            "session_id": session_id,
        })

        try:
            while True:
                if await request.is_disconnected():
                    task.cancel()
                    logger.info("council_client_disconnected", session_id=session_id)
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield _sse(event)

                    if event.get("type") == "done":
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    if task.done():
                        exc = task.exception()
                        if exc:
                            yield _sse({
                                "type": "error",
                                "message": f"Council error: {exc}",
                            })
                        break
        except asyncio.CancelledError:
            task.cancel()
            raise
        except Exception as exc:
            logger.exception("council_stream_error", error=str(exc))
            yield _sse({
                "type": "error",
                "message": f"Stream error: {type(exc).__name__}: {exc}",
            })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/council/session/{session_id}")
async def get_session_state(session_id: str):
    """Get the current state of a council session (polling fallback)."""
    session = get_session(session_id)
    if not session:
        return {"error": "Session not found", "session_id": session_id}
    return session


@router.get("/council/personas")
async def get_personas():
    """List all 9 Legal Council personas with their profiles."""
    personas = list_personas_summary()
    return {
        "personas": personas,
        "total": len(personas),
        "council_name": "Legal Council of 9",
        "purpose": "Multi-persona legal deliberation for the Generali/Fannin County defense",
    }
