"""
Legal Auditor — Dual-Layer Legal Logic Engine via NVIDIA NIM (FP8)
===================================================================
Performs two layers of analysis on every damage report:

  Layer 1 (Contract):  Clause-by-clause breach analysis against the
                       signed rental agreement.
  Layer 2 (Statutory): Cross-reference against vectorized Georgia
                       Civil & Criminal Code (O.C.G.A.) for exposure
                       assessment. This layer is STRICTLY INTERNAL —
                       never exposed to the guest.

NIM endpoint: Sparks 1&2 clustered (DGX_REASONER_URL, FP8 model)
Statutory vectors: Qdrant legal_library_v2 (2048-dim sovereign legal-embed; cut over 2026-04-30 in Phase A PR #2)
Fallback: Anthropic Opus 4.6 -> Council cascade
"""

import json
import time
from typing import Optional, List

import httpx
import structlog
from pydantic import BaseModel, Field

from backend.core.config import settings
from backend.services.ai_engine import query_horseman, query_council

logger = structlog.get_logger()

# Phase A PR #2 (2026-04-30): legal_library cut over to legal_library_v2 on the
# 2048-dim sovereign legal-embed encoder. Statutory queries now go through the
# LiteLLM gateway (see _embed_statutory_query below) with the mandatory caller
# contract from PR #300 §9.5 (input_type=query + encoding_format=float).
STATUTORY_COLLECTION = "legal_library_v2"
STATUTORY_EMBED_DIM = 2048


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Structured Output — Comprehensive Legal Ruling
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ComprehensiveLegalRuling(BaseModel):
    """Full legal dossier: contract analysis + statutory exposure."""

    # Layer 1: Contract Analysis (guest-safe)
    contract_breached: bool = Field(
        description="True if one or more rental agreement clauses were violated."
    )
    violated_clauses: List[str] = Field(
        default_factory=list,
        description="Exact clause text quoted from the rental agreement."
    )
    justification: str = Field(
        default="",
        description="How the staff notes evidence a violation of each cited clause."
    )
    permissible_charges: List[str] = Field(
        default_factory=list,
        description="Specific fees/deductions authorized by the contract."
    )
    severity: str = Field(
        default="moderate",
        description="Contract severity: minor, moderate, severe, or critical."
    )
    recommended_action: str = Field(
        default="",
        description="Recommended next step for the guest-facing claim."
    )

    # Layer 2: Statutory Analysis (INTERNAL ONLY — never shown to guest)
    statutory_violations_detected: bool = Field(
        default=False,
        description="True if the guest's actions may violate Georgia civil or criminal statutes."
    )
    relevant_statutes: List[str] = Field(
        default_factory=list,
        description="Specific Georgia Code sections (e.g. 'O.C.G.A. § 16-7-23')."
    )
    internal_legal_brief: str = Field(
        default="",
        description="PRIVATE advice to the property owner about civil/criminal exposure, "
                    "police report recommendations, or litigation options. "
                    "NEVER include this in guest-facing communications."
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Statutory Law RAG — Query vectorized Georgia Code
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def query_statutory_law(query: str, top_k: int = 5) -> str:
    """Search the vectorized Georgia Civil & Criminal Code (legal_library).

    Returns formatted statute excerpts or empty string if unavailable.
    """
    qdrant_url = settings.qdrant_url.rstrip("/")
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            check = await client.get(
                f"{qdrant_url}/collections/{STATUTORY_COLLECTION}", headers=headers,
            )
            if check.status_code != 200:
                logger.debug("statutory_collection_not_found", collection=STATUTORY_COLLECTION)
                return ""

            from backend.core.vector_db import embed_legal_query
            try:
                vec = await embed_legal_query(query[:4000])
            except Exception as e:
                logger.warning("statutory_embed_failed", error=str(e)[:200])
                return ""
            if len(vec) != STATUTORY_EMBED_DIM:
                logger.warning("statutory_embed_dim_unexpected", got=len(vec))
                return ""

            search_resp = await client.post(
                f"{qdrant_url}/collections/{STATUTORY_COLLECTION}/points/search",
                json={
                    "vector": vec,
                    "limit": top_k,
                    "with_payload": True,
                    "with_vector": False,
                },
                headers=headers,
            )
            search_resp.raise_for_status()
            results = search_resp.json().get("result", [])

            if not results:
                return ""

            parts = []
            for pt in results:
                p = pt.get("payload", {})
                text = p.get("text", "")
                source = p.get("source_file", "")
                score = pt.get("score", 0)
                if text:
                    parts.append(f"[score={score:.2f}] {source}\n{text[:500]}")

            logger.info(
                "statutory_law_retrieved",
                results=len(parts),
                top_score=results[0].get("score", 0) if results else 0,
            )
            return "\n\n".join(parts)

    except Exception as e:
        logger.warning("statutory_law_query_failed", error=str(e)[:200])
        return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  System Prompt — Dual-Layer Legal Analysis
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AUDITOR_SYSTEM_PROMPT = """You are a senior legal analyst representing Cabin Rentals of Georgia,
a property management firm in Blue Ridge, Georgia.

Perform a THREE-STEP legal analysis:

STEP 1 — CONTRACT BREACH ANALYSIS (Guest-Facing):
  Read the STAFF DAMAGE REPORT and the RENTAL AGREEMENT.
  Determine if specific clauses were violated.
  CITE the EXACT clause number and text. Do NOT invent clauses.
  Do NOT invent fees or dollar amounts not in the agreement.
  If no agreement is provided, state that only Georgia property law applies.

STEP 2 — STATUTORY LAW ANALYSIS (Internal Only):
  Read the GEORGIA CODE EXCERPTS provided.
  Determine if the guest's actions may violate Georgia civil or criminal statutes.
  Cite specific O.C.G.A. sections.
  Common relevant statutes:
    - O.C.G.A. § 16-7-23: Criminal damage to property (2nd degree)
    - O.C.G.A. § 16-7-22: Criminal damage to property (1st degree)
    - O.C.G.A. § 51-10-6: Liability for damage to rented property
    - O.C.G.A. § 44-7-30 through 44-7-37: Landlord-tenant damage
    - O.C.G.A. § 16-7-21: Criminal trespass
    - O.C.G.A. § 16-13-32: Drug paraphernalia

STEP 3 — INTERNAL LEGAL BRIEF (Private — NEVER shown to guest):
  Advise the property owner on:
  - Whether a police report is warranted
  - Whether civil litigation is advisable
  - Risk assessment for pursuing charges
  - DO NOT threaten criminal action in the guest-facing fields

Respond STRICTLY in JSON. No markdown, no explanation — pure JSON only:
{
  "contract_breached": true/false,
  "violated_clauses": ["Exact quoted clause 1", "Exact quoted clause 2"],
  "justification": "How the notes evidence each violation",
  "permissible_charges": ["Specific authorized fee 1"],
  "severity": "minor|moderate|severe|critical",
  "recommended_action": "Guest-facing recommended next step",
  "statutory_violations_detected": true/false,
  "relevant_statutes": ["O.C.G.A. § XX-X-XX"],
  "internal_legal_brief": "PRIVATE owner advice about criminal/civil exposure"
}"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Main Audit Function
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def audit_contract_violations(
    staff_notes: str,
    rental_agreement_text: str,
) -> Optional[ComprehensiveLegalRuling]:
    """Perform dual-layer legal analysis: contract + statutory.

    Sends the staff notes, rental agreement, and retrieved Georgia Code
    to the NIM Reasoner for comprehensive analysis.

    Returns a ComprehensiveLegalRuling or None if all providers fail.
    """
    # Retrieve relevant Georgia statutes from Qdrant legal_library
    statutory_query = f"Georgia property damage liability criminal {staff_notes[:200]}"
    statutory_context = await query_statutory_law(statutory_query, top_k=5)

    statutory_section = ""
    if statutory_context:
        statutory_section = f"\n\nGEORGIA CODE EXCERPTS (from vectorized legal library):\n{statutory_context}"
    else:
        statutory_section = (
            "\n\nGEORGIA CODE: No vectorized excerpts available. Use your knowledge of "
            "O.C.G.A. Title 16 (Criminal) and Title 51 (Torts) for statutory analysis."
        )

    user_prompt = f"""STAFF DAMAGE REPORT:
{staff_notes}

RENTAL AGREEMENT:
{rental_agreement_text[:12000] if rental_agreement_text else 'NO RENTAL AGREEMENT ON FILE.'}
{statutory_section}

Perform the three-step legal analysis and return your comprehensive ruling as JSON."""

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
                    "max_tokens": 2048,
                },
            )
            if resp.status_code == 200:
                raw_response = resp.json()["choices"][0]["message"]["content"].strip()
                provider = f"nim/{settings.dgx_reasoner_model}"
    except Exception as e:
        logger.warning("legal_auditor_nim_failed", error=str(e)[:200])

    # Tier 2: Anthropic Opus
    if not raw_response:
        raw_response = await query_horseman(
            "anthropic",
            prompt=user_prompt,
            system_message=AUDITOR_SYSTEM_PROMPT,
            max_tokens=2048,
            temperature=0.1,
        )
        if raw_response:
            provider = settings.anthropic_model

    # Tier 3: Council cascade
    if not raw_response:
        raw_response, provider = await query_council(
            prompt=user_prompt,
            system_message=AUDITOR_SYSTEM_PROMPT,
            max_tokens=2048,
            temperature=0.1,
        )
        provider = provider or "council"

    latency = (time.perf_counter() - t0) * 1000

    if not raw_response:
        logger.error("legal_auditor_all_providers_failed", latency_ms=round(latency))
        return None

    ruling = _parse_ruling(raw_response)

    if ruling:
        logger.info(
            "legal_audit_complete",
            provider=provider,
            contract_breached=ruling.contract_breached,
            clauses=len(ruling.violated_clauses),
            statutory_detected=ruling.statutory_violations_detected,
            statutes=len(ruling.relevant_statutes),
            severity=ruling.severity,
            latency_ms=round(latency),
        )
    else:
        logger.warning(
            "legal_audit_parse_failed",
            provider=provider,
            raw_preview=raw_response[:200],
            latency_ms=round(latency),
        )

    return ruling


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_ruling(raw: str) -> Optional[ComprehensiveLegalRuling]:
    """Parse AI response into ComprehensiveLegalRuling, tolerating markdown fences."""
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
        return ComprehensiveLegalRuling(**data)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def format_ruling_for_drafter(ruling: ComprehensiveLegalRuling) -> str:
    """Format ONLY the contract layer for the guest-facing email drafter.

    Statutory analysis is NEVER included in drafter context.
    """
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
