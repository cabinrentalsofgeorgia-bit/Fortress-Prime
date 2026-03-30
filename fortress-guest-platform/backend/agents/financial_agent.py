"""
DGX-backed yield analysis agent for sovereign financial intelligence.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.core.config import settings
from backend.services.yield_extraction_service import FinancialExtractionContext

GENERATION_TIMEOUT_SECONDS = 120.0
DEFAULT_YIELD_MODEL = "nemotron-3-super-120b"
YIELD_MANAGER_SYSTEM_PROMPT = (
    "You are the Fortress Prime Yield Swarm, a strict mathematical yield manager. "
    "You receive JSON context extracted from the sovereign booking ledger. "
    "Analyze only the numbers and dates provided. "
    "Return ONLY a JSON object matching this schema exactly: "
    "{"
    '"velocity_score": number from 0 to 100, '
    '"friction_warning": boolean, '
    '"pricing_recommendations": ['
    "{"
    '"start_date": "YYYY-MM-DD", '
    '"end_date": "YYYY-MM-DD", '
    '"adjustment_percent": number between -100 and 100, '
    '"rationale": "short explanation"'
    "}"
    "]"
    "}. "
    "Do not emit markdown, commentary, code fences, or extra keys. "
    "Use an empty pricing_recommendations list when the data does not justify a rate move."
)


class PricingRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date
    adjustment_percent: float = Field(ge=-100.0, le=100.0)
    rationale: str = Field(min_length=1, max_length=320)


class YieldAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    velocity_score: float = Field(ge=0.0, le=100.0)
    friction_warning: bool
    pricing_recommendations: list[PricingRecommendation] = Field(default_factory=list)


class FinancialYieldAgent:
    """
    Read-only yield manager that delegates structured analysis to the local DGX.
    """

    def __init__(self) -> None:
        self.inference_base_url = str(settings.dgx_inference_url or "").strip()
        self.model_name = (
            str(settings.dgx_inference_model or "").strip()
            or str(settings.seo_godhead_model or "").strip()
            or DEFAULT_YIELD_MODEL
        )
        self.inference_api_key = str(settings.dgx_inference_api_key or "").strip()

    async def analyze(self, context: FinancialExtractionContext) -> YieldAnalysis:
        if not self.inference_base_url:
            raise RuntimeError("DGX_INFERENCE_URL is not configured for yield analysis.")
        if not self.model_name:
            raise RuntimeError("No DGX inference model is configured for yield analysis.")

        request_payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": YIELD_MANAGER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        context.model_dump(mode="json"),
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                },
            ],
            "stream": False,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.inference_api_key:
            headers["Authorization"] = f"Bearer {self.inference_api_key}"

        async with httpx.AsyncClient(timeout=GENERATION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                self._chat_completions_url(self.inference_base_url),
                headers=headers,
                json=request_payload,
            )
            response.raise_for_status()
            response_payload = response.json()

        raw_message = _extract_message_content(response_payload)
        parsed = _extract_json_object(raw_message)
        return YieldAnalysis.model_validate(parsed)

    @staticmethod
    def _chat_completions_url(base_url: str) -> str:
        value = base_url.strip().rstrip("/")
        if value.endswith("/chat/completions"):
            return value
        if value.endswith("/v1"):
            return f"{value}/chat/completions"
        return f"{value}/v1/chat/completions"


def _extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise ValueError("DGX yield analysis response did not contain choices.")
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        joined = "\n".join(text_parts).strip()
        if joined:
            return joined
    raise ValueError("DGX yield analysis response did not contain text content.")


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in DGX yield analysis output.")
    parsed = json.loads(raw_text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("DGX yield analysis output must decode to a JSON object.")
    return parsed
