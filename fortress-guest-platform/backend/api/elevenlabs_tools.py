"""
ELEVENLABS TOOLS — Local Knowledge Webhook for ElevenLabs Conversational AI
============================================================================
Fortress Prime | Voice Matrix (Level 6) — ElevenLabs Route

Lightweight REST endpoint that ElevenLabs Eve calls as a "tool" during
live phone conversations.  When a guest asks a property-specific question,
Eve hits this webhook, which embeds the query via local nomic-embed-text,
searches the Qdrant guest_golden_responses collection, and returns the
exact human-approved policy.

Architecture:
    Phone → Twilio → ElevenLabs (STT + LLM + TTS)
                         ↓ tool call
                     THIS WEBHOOK → nomic-embed-text → Qdrant
                         ↑ policy result
                     ElevenLabs speaks the answer

Endpoint:
    POST /api/elevenlabs/tools/qdrant_search
"""

import os
import sys
import logging

import requests as http_client
from fastapi import APIRouter
from pydantic import BaseModel, Field

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

log = logging.getLogger("crog.voice.elevenlabs")

router = APIRouter(tags=["Voice-ElevenLabs"])

BASE = os.getenv("BASE_IP", "192.168.0.100")


class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)


@router.post("/tools/qdrant_search")
async def qdrant_search_webhook(payload: SearchQuery):
    """
    ElevenLabs tool webhook: embed query → search Qdrant → return policy.

    ElevenLabs sends {"query": "fire pit policy at Aska"} and expects
    a JSON response with the answer text.
    """
    query_text = payload.query
    log.info("elevenlabs_tool_search  query=%s", query_text[:80])

    try:
        embed_resp = http_client.post(
            f"http://{BASE}/v1/embeddings",
            json={"model": "nomic-embed-text:latest", "input": query_text},
            timeout=5,
        )
        embed_resp.raise_for_status()
        query_vector = embed_resp.json()["data"][0]["embedding"]

        from qdrant_client import QdrantClient

        qc = QdrantClient(host="localhost", port=6333, timeout=5,
                          check_compatibility=False)
        results = qc.query_points(
            collection_name="guest_golden_responses",
            query=query_vector,
            limit=3,
            with_payload=True,
        )

        if results.points and results.points[0].score > 0.50:
            parts = []
            for pt in results.points[:3]:
                if pt.score < 0.45:
                    break
                p = pt.payload
                cabin = p.get("cabin", "General")
                answer = p.get("ai_output", "")
                parts.append(f"[{cabin}] {answer}")
                log.info(
                    "elevenlabs_tool_hit  score=%.3f  cabin=%s  preview=%s",
                    pt.score, cabin, answer[:60],
                )

            combined = "\n\n".join(parts)
            return {"result": f"POLICY FOUND: {combined}"}

        log.info("elevenlabs_tool_miss  query=%s", query_text[:60])
        return {"result": "No specific local policy found. Rely on general hospitality knowledge."}

    except Exception as e:
        log.error("elevenlabs_tool_error  query=%s  error=%s", query_text[:60], e)
        return {"result": "Error accessing local memory. Advise the guest you will check and text them back."}
