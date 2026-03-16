"""
Contract Auditor — Legal Logic Engine via NVIDIA NIM (FP8)
============================================================
Performs strict clause-by-clause analysis of staff damage reports
against the signed rental agreement BEFORE any communication is drafted.

The auditor acts as a contract lawyer: it identifies which specific
clauses were violated, what charges the agreement authorizes, and
produces a structured Legal Brief (ContractRuling) that the
downstream email drafter is bound to follow.

NIM endpoint: Sparks 1&2 clustered (DGX_REASONER_URL, FP8 model)
Fallback: Anthropic Opus 4.6 -> Council cascade
"""

import json
import time
from typing import Optional

import httpx
import structlog
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.services.ai_engine import query_horseman, query_council

logger = structlog.get_logger()


class ContractRuling(BaseModel):
    """Structured legal brief from the Contract Auditor."""

    contract_breached: bool = Field(
        description="True if one or more rental agreement clauses were violated."
    )
    violated_clauses: list[str] = Field(
        default_factory=list,
        description="Exact clause text quoted from the rental agreement that was violated."
    )
    justification: str = Field(
        default="",
        description="Explanation of how the staff notes evidence a violation of each cited clause."
    )
    permissible_charges: list[str] = Field(
        default_factory=list,
        description="Specific fees or deductions authorized by the contract "
                    "(e.g. 'Security deposit forfeiture per Section 12', "
                    "'Cleaning surcharge per Section 8.3')."
    )
    severity: str = Field(
        default="moderate",
        description="Assessment: minor, moderate, severe, or critical."
    )
    recommended_action: str = Field(
        default="",
        description="Recommended next step (e.g. 'Deduct from security deposit', "
                    "'Invoice guest for repair costs', 'Escalate to legal counsel')."
    )


AUDITOR_SYSTEM_PROMPT = """You are a strict contract lawyer representing Cabin Rentals of Georgia,
a property management firm in Blue Ridge, Georgia.

Read the provided STAFF DAMAGE REPORT and the full RENTAL AGREEMENT.

Your ONLY job is to determine if a specific clause in the agreement was violated.

STRICT RULES:
1. CITE the EXACT clause number and text from the agreement. Do not paraphrase.
2. Do NOT invent clauses that do not exist in the provided agreement.
3. Do NOT invent fees or dollar amounts. If a fee is not explicitly stated in the
   agreement or covered under a general security deposit clause, you CANNOT charge it.
4. If the agreement is not provided or is empty, state that no contract-based charges
   can be levied — only general Georgia property law applies (O.C.G.A. § 44-7-30 et seq.).
5. Be precise. Every statement must be traceable to a specific clause or statute.

Respond STRICTLY in JSON matching this exact schema. No markdown, no explanation — pure JSON only:
{
  "contract_breached": true/false,
  "violated_clauses": ["Exact quoted clause text 1", "Exact quoted clause text 2"],
  "justification": "How the damage notes evidence a violation of each cited clause",
  "permissible_charges": ["Specific fee or deduction authorized by the contract"],
  "severity": "minor|moderate|severe|critical",
  "recommended_action": "Recommended next step"
}"""


async def audit_contract_violations(
    staff_notes: str,
    rental_agreement_text: str,
) -> Optional[ContractRuling]:
    """Analyze staff damage notes against the rental agreement.

    Sends the notes and contract to the local NIM Reasoner (FP8) for
    strict clause-by-clause legal analysis. Falls back to Anthropic
    Opus then the Council cascade if NIM is unavailable.

    Returns a ContractRuling or None if all providers fail.
    """
    user_prompt = f"""STAFF DAMAGE REPORT:
{staff_notes}

RENTAL AGREEMENT:
{rental_agreement_text[:12000] if rental_agreement_text else 'NO RENTAL AGREEMENT ON FILE.'}

Analyze and return your ruling as JSON."""

    t0 = time.perf_counter()
    raw_response = None
    provider = "unknown"

    # Tier 1: Local NIM Reasoner (FP8 on Sparks 1&2)
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{settings.dgx_reasoner_url.rstrip('/')}/chat/completions",
                json={
                    "model": settings.dgx_reasoner_model,
                    "messages": [
                        {"role": "system", "content": AUDITOR_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 1024,
                },
            )
            if resp.status_code == 200:
                raw_response = resp.json()["choices"][0]["message"]["content"].strip()
                provider = f"nim/{settings.dgx_reasoner_model}"
    except Exception as e:
        logger.warning("contract_auditor_nim_failed", error=str(e)[:200])

    # Tier 2: Anthropic Opus
    if not raw_response:
        raw_response = await query_horseman(
            "anthropic",
            prompt=user_prompt,
            system_message=AUDITOR_SYSTEM_PROMPT,
            max_tokens=1024,
            temperature=0.1,
        )
        if raw_response:
            provider = settings.anthropic_model

    # Tier 3: Council cascade
    if not raw_response:
        raw_response, provider = await query_council(
            prompt=user_prompt,
            system_message=AUDITOR_SYSTEM_PROMPT,
            max_tokens=1024,
            temperature=0.1,
        )
        provider = provider or "council"

    latency = (time.perf_counter() - t0) * 1000

    if not raw_response:
        logger.error("contract_auditor_all_providers_failed", latency_ms=round(latency))
        return None

    # Parse the JSON response
    ruling = _parse_ruling(raw_response)

    if ruling:
        logger.info(
            "contract_audit_complete",
            provider=provider,
            breached=ruling.contract_breached,
            clauses=len(ruling.violated_clauses),
            severity=ruling.severity,
            latency_ms=round(latency),
        )
    else:
        logger.warning(
            "contract_audit_parse_failed",
            provider=provider,
            raw_preview=raw_response[:200],
            latency_ms=round(latency),
        )

    return ruling


def _parse_ruling(raw: str) -> Optional[ContractRuling]:
    """Parse AI response into ContractRuling, tolerating markdown fences."""
    if not raw:
        return None

    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start == -1 or brace_end == -1:
        return None

    text = text[brace_start:brace_end + 1]

    try:
        data = json.loads(text)
        return ContractRuling(**data)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def format_ruling_for_drafter(ruling: ContractRuling) -> str:
    """Format a ContractRuling into a text block for the email drafter prompt."""
    parts = [f"CONTRACT AUDIT RULING (severity: {ruling.severity.upper()}):"]

    if ruling.contract_breached:
        parts.append("\nVIOLATED CLAUSES:")
        for i, clause in enumerate(ruling.violated_clauses, 1):
            parts.append(f"  {i}. \"{clause}\"")

        parts.append(f"\nJUSTIFICATION:\n  {ruling.justification}")

        if ruling.permissible_charges:
            parts.append("\nAUTHORIZED CHARGES:")
            for charge in ruling.permissible_charges:
                parts.append(f"  - {charge}")

        parts.append(f"\nRECOMMENDED ACTION: {ruling.recommended_action}")
    else:
        parts.append("\nNO CONTRACT BREACH FOUND.")
        parts.append(f"Justification: {ruling.justification}")
        parts.append(
            "\nNote: Without a specific contract violation, charges must be limited "
            "to security deposit retention for damage beyond normal wear and tear "
            "per Georgia law (O.C.G.A. § 44-7-30 et seq.)."
        )

    return "\n".join(parts)
