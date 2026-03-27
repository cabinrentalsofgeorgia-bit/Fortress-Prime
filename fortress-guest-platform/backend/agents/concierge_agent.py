"""Grounded concierge RAG agent for public guest questions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.vector_db import embed_text
from backend.models.knowledge import PropertyKnowledgeChunk
from backend.models.property import Property

GENERATION_TIMEOUT_SECONDS = 120.0
TOP_K_CONTEXT = 3
CONCIERGE_SYSTEM_PROMPT = (
    "You are the Fortress Prime Concierge, a luxury cabin concierge for guests. "
    "Answer ONLY from the supplied property context. "
    "Never invent amenities, rules, policies, locations, or operating details. "
    "If the answer is not clearly supported by the context, say that you do not have enough property context to answer and invite the guest to contact the host directly. "
    "Keep the response warm, concise, and specific to the property."
)


@dataclass(slots=True)
class ConciergeAnswer:
    """Final grounded answer payload for the public chat API."""

    response: str
    context_chunks: list[str]


class ConciergeAgent:
    """Embed, retrieve, and generate a grounded concierge answer."""

    def __init__(self) -> None:
        self.inference_base_url = str(settings.dgx_inference_url or "").strip()
        self.model_name = str(settings.dgx_inference_model or "").strip() or str(settings.ollama_fast_model or "").strip()
        self.inference_api_key = str(settings.dgx_inference_api_key or "").strip()

    async def answer_query(
        self,
        db: AsyncSession,
        *,
        property_id: UUID,
        guest_message: str,
    ) -> ConciergeAnswer:
        property_record = await db.get(Property, property_id)
        if property_record is None:
            raise ValueError("Property not found")

        if not guest_message.strip():
            raise ValueError("Guest message is required")

        context_chunks = await self._retrieve_context_chunks(
            db,
            property_id=property_id,
            guest_message=guest_message,
        )
        if not context_chunks:
            return ConciergeAnswer(
                response=(
                    "I do not have enough property context to answer that confidently yet. "
                    "Please contact the host directly for a verified answer."
                ),
                context_chunks=[],
            )

        response_text = await self._generate_grounded_response(
            property_name=property_record.name,
            guest_message=guest_message,
            context_chunks=context_chunks,
        )
        return ConciergeAnswer(response=response_text, context_chunks=context_chunks)

    async def _retrieve_context_chunks(
        self,
        db: AsyncSession,
        *,
        property_id: UUID,
        guest_message: str,
    ) -> list[str]:
        query_embedding = await embed_text(guest_message)
        distance = PropertyKnowledgeChunk.embedding.cosine_distance(query_embedding)
        result = await db.execute(
            select(PropertyKnowledgeChunk.content)
            .where(PropertyKnowledgeChunk.property_id == property_id)
            .order_by(distance.asc())
            .limit(TOP_K_CONTEXT)
        )
        return list(result.scalars().all())

    async def _generate_grounded_response(
        self,
        *,
        property_name: str,
        guest_message: str,
        context_chunks: list[str],
    ) -> str:
        if not self.inference_base_url:
            raise RuntimeError("DGX_INFERENCE_URL is not configured for concierge responses.")
        if not self.model_name:
            raise RuntimeError("No model is configured for concierge responses.")

        context_block = "\n\n".join(
            f"[Chunk {index}] {chunk}"
            for index, chunk in enumerate(context_chunks, start=1)
        )
        payload = {
            "model": self.model_name,
            "stream": True,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": CONCIERGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "property_name": property_name,
                            "guest_question": guest_message,
                            "context_chunks": context_block,
                        },
                        ensure_ascii=True,
                    ),
                },
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.inference_api_key:
            headers["Authorization"] = f"Bearer {self.inference_api_key}"

        response_parts: list[str] = []
        async with httpx.AsyncClient(timeout=GENERATION_TIMEOUT_SECONDS) as client:
            async with client.stream(
                "POST",
                self._chat_completions_url(self.inference_base_url),
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    chunk = self._extract_stream_chunk(line)
                    if chunk:
                        response_parts.append(chunk)

        final_response = "".join(response_parts).strip()
        if not final_response:
            raise RuntimeError("DGX concierge inference returned no text.")
        return final_response

    @staticmethod
    def _chat_completions_url(base_url: str) -> str:
        value = base_url.strip().rstrip("/")
        if value.endswith("/chat/completions"):
            return value
        if value.endswith("/v1"):
            return f"{value}/chat/completions"
        return f"{value}/v1/chat/completions"

    @staticmethod
    def _extract_stream_chunk(line: str) -> str:
        raw = line.strip()
        if not raw or not raw.startswith("data:"):
            return ""

        payload = raw.removeprefix("data:").strip()
        if payload == "[DONE]":
            return ""

        parsed = json.loads(payload)
        choices = parsed.get("choices") or []
        if not choices:
            return ""
        delta = (choices[0] or {}).get("delta") or {}
        content = delta.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    text_parts.append(item["text"])
            return "".join(text_parts)
        return ""
