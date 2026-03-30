"""
LLM-backed Streamline webhook mapper for trust-ledger proposals.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from backend.agents.financial.schemas import ProposedTransaction
from backend.core.config import settings
from backend.services.swarm_service import submit_chat_completion

logger = logging.getLogger("trust_swarm")
logger.setLevel(logging.INFO)

DEFAULT_ORACLE_MODEL = "qwen2.5:14b"
ORACLE_TIMEOUT_SECONDS = 90.0
ORACLE_SYSTEM_PROMPT = (
    "You are a Trust Accounting Ingestion Agent for Cabin Rentals of Georgia. "
    "Your job is to read raw PMS webhooks and translate them into strict double-entry "
    "ledger proposals. "
    "Rules: "
    "1. All amounts must be in integer cents. "
    "2. If the raw event amount is expressed in dollars, convert it to integer cents. "
    "3. A guest payment DEBITS 'Trust Cash' and CREDITS 'Guest Advance Deposits'. "
    "4. A refund CREDITS 'Trust Cash' and DEBITS 'Guest Advance Deposits'. "
    "5. Total debits must exactly equal total credits. "
    "6. Return only a ProposedTransaction payload with no markdown or commentary outside the schema."
)


class StreamlineOracleAgent:
    """Routes Streamline webhook normalization through the local DGX model lane."""

    def __init__(self) -> None:
        self.model_name = (
            str(settings.dgx_inference_model or "").strip()
            or str(settings.swarm_model or "").strip()
            or DEFAULT_ORACLE_MODEL
        )

    async def process_event(
        self,
        raw_event: dict[str, Any],
        *,
        run_id: UUID | None = None,
    ) -> ProposedTransaction:
        prompt = json.dumps(
            {
                "task": "Map the raw Streamline PMS webhook into a strict double-entry trust-ledger proposal.",
                "raw_event": raw_event,
                "output_contract": {
                    "entries": [
                        {
                            "account_name": "Trust Cash | Guest Advance Deposits | Owner Funds Payable",
                            "entry_type": "debit | credit",
                            "amount_cents": "integer cents only",
                        }
                    ],
                    "reasoning": "short explanation",
                },
            },
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        )
        request_payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": ORACLE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 900,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "proposed_transaction",
                    "strict": True,
                    "schema": ProposedTransaction.model_json_schema(),
                },
            },
        }
        _log_inference_event(
            "streamline_oracle_request",
            run_id=run_id,
            model_name=self.model_name,
            payload=request_payload,
        )

        response = await submit_chat_completion(
            prompt=prompt,
            model=self.model_name,
            system_message=ORACLE_SYSTEM_PROMPT,
            timeout_s=ORACLE_TIMEOUT_SECONDS,
            extra_payload={
                "temperature": 0.0,
                "max_tokens": 900,
                "response_format": request_payload["response_format"],
            },
        )
        raw_message = _extract_message_content(response)
        usage = response.get("usage") or {}
        _log_inference_event(
            "streamline_oracle_response",
            run_id=run_id,
            model_name=self.model_name,
            payload={
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "raw_response": raw_message,
            },
        )
        parsed = _extract_json_object(raw_message)
        return ProposedTransaction.model_validate(parsed)


def _extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise ValueError("Streamline Oracle response did not contain choices.")

    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        stripped = content.strip()
        if stripped:
            return stripped

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        joined = "\n".join(text_parts).strip()
        if joined:
            return joined

    raise ValueError("Streamline Oracle response did not contain text content.")


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in Streamline Oracle output.")

    parsed = json.loads(raw_text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Structured output must decode to a JSON object.")
    return parsed


def _log_inference_event(
    event_name: str,
    *,
    run_id: UUID | None,
    model_name: str,
    payload: dict[str, Any],
) -> None:
    logger.warning(
        "%s %s",
        event_name,
        json.dumps(
            {
                "run_id": str(run_id) if run_id else None,
                "model_name": model_name,
                "payload": payload,
            },
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        ),
    )
