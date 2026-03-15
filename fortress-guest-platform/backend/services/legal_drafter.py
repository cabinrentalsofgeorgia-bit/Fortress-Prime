"""
Legal Drafter — AI-powered damage claim response generator

Takes a damage report + rental agreement terms and drafts a professional,
legally-grounded response for management review.

Uses HYDRA (deepseek-r1:70b) for deep legal reasoning, falls back to
SWARM (qwen2.5:7b) then OpenAI.
"""
from __future__ import annotations

import re
import difflib
import httpx
import structlog
from typing import Optional


from backend.core.config import settings
from backend.models.damage_claim import DamageClaim
from backend.services.prompt_engineer import PIISanitizer

logger = structlog.get_logger(service="legal_drafter")

SYSTEM_PROMPT = """You are the Legal Response Coordinator for Cabin Rentals of Georgia (CROG),
a luxury cabin rental company in Blue Ridge, Georgia.

Your job is to draft a professional, firm but fair response to a guest regarding
property damage or policy violations discovered during post-checkout inspection.

GUIDELINES:
1. Be PROFESSIONAL and FACTUAL — cite specific damage and policy clauses
2. Reference the rental agreement the guest signed (clauses provided below)
3. State the damage/violations found clearly
4. Explain what charges or actions will be taken per the agreement
5. Provide a path forward (repair costs, security deposit deduction, payment arrangement)
6. Maintain Southern hospitality tone — firm but not hostile
7. Include any applicable Georgia vacation rental law references
8. Keep the response concise (under 500 words for SMS/email readability)

GEORGIA VACATION RENTAL LAW NOTES:
- O.C.G.A. § 44-7-30 through 44-7-37 cover landlord-tenant damage
- Security deposits must be returned within 30 days with itemized deductions
- Damage beyond normal wear and tear is chargeable
- Signed rental agreements are binding contracts in Georgia
- Photo documentation strengthens the claim

FORMAT your response as a letter/message ready to send to the guest.
Address them by name, sign off as "Cabin Rentals of Georgia Management Team"."""


async def draft_legal_response(
    claim: DamageClaim,
    guest_name: str,
    property_name: str,
    check_in: str,
    check_out: str,
    agreement_content: Optional[str] = None,
    staff_notes: Optional[list] = None,
) -> dict:
    """
    Generate a legal response draft for a damage claim.
    Returns {"draft": str, "model": str, "clauses": list[str]}
    """
    clauses_section = ""
    extracted_clauses = []

    if agreement_content:
        relevant_terms = _extract_relevant_clauses(
            agreement_content, claim.damage_description, claim.policy_violations
        )
        if relevant_terms:
            extracted_clauses = relevant_terms
            clauses_section = "\n\nRELEVANT RENTAL AGREEMENT CLAUSES:\n" + "\n".join(
                f"- {c}" for c in relevant_terms
            )
    else:
        logger.warning(
            "legal_draft_no_agreement",
            claim_number=claim.claim_number,
            guest=guest_name,
            property=property_name,
            check_in=check_in,
            check_out=check_out,
            message="No signed rental agreement on file — draft is AI-generated only; may not match this stay",
        )
        clauses_section = """
\nNOTE: No signed rental agreement on file for this reservation.
Use standard CROG damage policy language and reference Georgia property law."""

    staff_notes_section = ""
    if staff_notes:
        formatted = []
        for note in staff_notes:
            if isinstance(note, dict) and note.get("message"):
                author = note.get("processor_name", "Staff")
                ts = note.get("creation_date", "")
                formatted.append(f"[{ts}] {author}: {note['message']}")
        if formatted:
            staff_notes_section = "\n\nSTAFF NOTES FROM PROPERTY MANAGEMENT SYSTEM:\n" + "\n\n".join(formatted)
            staff_notes_section += "\n\nIMPORTANT: These staff notes are firsthand observations from the property management team. Use them as PRIMARY evidence of what actually happened."

    user_prompt = f"""Draft a response to the guest for the following damage claim:

GUEST: {guest_name}
PROPERTY: {property_name}
STAY: {check_in} to {check_out}
CLAIM #: {claim.claim_number}

DAMAGE REPORTED:
{claim.damage_description}

POLICY VIOLATIONS:
{claim.policy_violations or 'None specifically cited'}

AREAS AFFECTED:
{', '.join(claim.damage_areas or ['Not specified'])}

ESTIMATED REPAIR COST:
${claim.estimated_cost or 'TBD — pending assessment'}

INSPECTION NOTES:
{claim.inspection_notes or 'Standard post-checkout inspection'}
{staff_notes_section}
{clauses_section}

Draft the guest communication now. Be specific about the damage, reference applicable
agreement terms, state expected charges, and provide next steps."""

    draft, model = await _call_llm(SYSTEM_PROMPT, user_prompt)

    hallucination_risk = False
    if agreement_content and draft and model != "none":
        if not _validate_citations(draft, agreement_content):
            hallucination_risk = True
            logger.warning(
                "hallucination_risk_detected",
                claim_number=claim.claim_number,
                model=model,
                message="Draft contains quoted text not traceable to the rental agreement",
            )

    return {
        "draft": draft,
        "model": model,
        "clauses": extracted_clauses,
        "hallucination_risk": hallucination_risk,
    }


def _validate_citations(draft_text: str, source_text: str) -> bool:
    """
    Deterministic hallucination guardrail. Extracts quoted text from the
    LLM draft and fuzzy-matches it against the actual rental agreement.
    Returns False if any substantive quote cannot be traced back to the source.
    """
    quotes = re.findall(r'"([^"]*)"', draft_text)
    if not quotes:
        return True

    source_clean = re.sub(r"\s+", " ", source_text.lower())

    for quote in quotes:
        if len(quote) < 15:
            continue
        quote_clean = re.sub(r"\s+", " ", quote.lower())
        if quote_clean in source_clean:
            continue
        matcher = difflib.SequenceMatcher(None, quote_clean, source_clean)
        match = matcher.find_longest_match(0, len(quote_clean), 0, len(source_clean))
        if match.size < (len(quote_clean) * 0.8):
            return False

    return True


def _extract_relevant_clauses(
    agreement_text: str, damage_desc: str, violations: Optional[str]
) -> list[str]:
    """Pull out clauses from the rental agreement that relate to damage/violations."""
    search_terms = [
        "damage", "repair", "security deposit", "deduction", "liability",
        "pet", "smoking", "noise", "quiet hours", "occupancy", "maximum",
        "hot tub", "fireplace", "grill", "parking", "trash", "bear",
        "indemnification", "hold harmless", "cleaning fee", "excess",
        "termination", "eviction", "violation", "penalty", "charge",
        "responsible", "negligence", "willful",
    ]

    if damage_desc:
        extra = [w.lower() for w in damage_desc.split() if len(w) > 4]
        search_terms.extend(extra[:10])
    if violations:
        extra = [w.lower() for w in violations.split() if len(w) > 4]
        search_terms.extend(extra[:10])

    clauses = []
    lines = agreement_text.split("\n")
    for i, line in enumerate(lines):
        line_lower = line.lower().strip()
        if not line_lower or len(line_lower) < 10:
            continue
        if any(term in line_lower for term in search_terms):
            context = line.strip()
            if i > 0 and lines[i - 1].strip():
                context = lines[i - 1].strip() + " " + context
            clauses.append(context[:300])

    seen = set()
    unique = []
    for c in clauses:
        key = c[:80].lower()
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique[:15]


async def _call_llm(system: str, user: str) -> tuple[str, str]:
    """Try HYDRA -> SWARM -> OpenAI."""
    if settings.use_local_llm:
        for model_name in [settings.ollama_deep_model, settings.ollama_fast_model]:
            try:
                result = await _ollama_chat(model_name, system, user)
                if result:
                    return result, model_name
            except Exception as e:
                logger.warning("ollama_attempt_failed", model=model_name, error=str(e))

    if settings.openai_api_key:
        try:
            result = await _openai_chat(system, user)
            if result:
                return result, settings.openai_model
        except Exception as e:
            logger.warning("openai_failed", error=str(e))

    return (
        "[DRAFT GENERATION FAILED — LLM unavailable. Please draft manually based on the damage report above.]",
        "none",
    )


async def _ollama_chat(model: str, system: str, user: str) -> Optional[str]:
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"temperature": 0.4, "num_predict": 2048},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "").strip()
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()


async def _openai_chat(system: str, user: str) -> Optional[str]:
    sanitizer = PIISanitizer()
    clean_system = sanitizer.sanitize(system)
    clean_user = sanitizer.sanitize(user)

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_model,
                "messages": [
                    {"role": "system", "content": clean_system},
                    {"role": "user", "content": clean_user},
                ],
                "temperature": 0.4,
                "max_tokens": 2048,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        raw_response = data["choices"][0]["message"]["content"].strip()
        return sanitizer.rehydrate(raw_response)
