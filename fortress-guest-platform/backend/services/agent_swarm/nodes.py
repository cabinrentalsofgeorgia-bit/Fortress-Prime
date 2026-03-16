"""
Agent Nodes — The four specialists in the multi-agent swarm.

Each node is a pure function: (QuoteState) -> dict of state updates.
Rule 5: Every node wraps external calls in try/except with graceful fallback.
"""
from __future__ import annotations

import re
import time
from typing import Dict, Any, List

import httpx
import structlog

from backend.core.config import settings
from backend.core.vector_db import get_qdrant_client, embed_text_sync, HISTORICAL_QUOTES_COLLECTION
from backend.services.agent_swarm.state import QuoteState

logger = structlog.get_logger(service="agent_swarm")

# ── Shared LLM helpers ───────────────────────────────────────────────────


def _strip_think_tags(text: str) -> str:
    """Remove DeepSeek R1 internal reasoning from <think>...</think> blocks."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _llm_chat_sync(
    messages: List[Dict[str, str]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    timeout: float = 180.0,
    min_length: int = 20,
) -> tuple[str, str]:
    """
    Synchronous LLM call via Ollama's OpenAI-compatible API.

    Returns (response_text, model_used). Falls through HYDRA -> SWARM.
    Rule 5: raises on total failure so the caller can handle it.
    """
    models_to_try = (
        [model] if model
        else [settings.ollama_deep_model, settings.ollama_fast_model]
    )

    last_error = None
    for m in models_to_try:
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{settings.ollama_base_url}/api/chat",
                    json={
                        "model": m,
                        "messages": messages,
                        "stream": False,
                        "options": {"temperature": temperature, "num_predict": max_tokens},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                raw = data.get("message", {}).get("content", "").strip()
                cleaned = _strip_think_tags(raw)
                if cleaned and len(cleaned) >= min_length:
                    return cleaned, m
        except Exception as e:
            last_error = e
            logger.warning("llm_node_attempt_failed", model=m, error=str(e))

    raise RuntimeError(f"All LLM models failed. Last error: {last_error}")


# ═════════════════════════════════════════════════════════════════════════
# NODE 1: RAG Researcher
# ═════════════════════════════════════════════════════════════════════════


def rag_researcher(state: QuoteState) -> dict:
    """
    Query Qdrant for historical quotes semantically similar to the guest's
    inquiry. Returns up to 3 relevant past interactions as context.
    """
    t0 = time.time()
    guest_msg = state.get("guest_message", "")
    node_log = list(state.get("node_log", []))

    if not guest_msg:
        node_log.append("[rag_researcher] No guest message — skipping RAG")
        return {"rag_context": "", "node_log": node_log}

    try:
        query_vector = embed_text_sync(guest_msg)
        client = get_qdrant_client()
        response = client.query_points(
            collection_name=HISTORICAL_QUOTES_COLLECTION,
            query=query_vector,
            limit=3,
        )

        context_parts = []
        for hit in response.points:
            p = hit.payload
            guest = p.get("guest_name", "Unknown")
            msg = p.get("guest_message", "")
            resp = p.get("staff_response", "")
            score = hit.score
            entry = f"[Score: {score:.3f}] Guest '{guest}': {msg}"
            if resp:
                entry += f"\n  Staff response: {resp[:300]}"
            context_parts.append(entry)

        rag_context = "\n---\n".join(context_parts) if context_parts else ""
        elapsed = time.time() - t0
        node_log.append(f"[rag_researcher] Found {len(context_parts)} similar quotes in {elapsed:.1f}s")
        logger.info("rag_researcher_complete", hits=len(context_parts), elapsed=f"{elapsed:.1f}s")
        return {"rag_context": rag_context, "node_log": node_log}

    except Exception as e:
        elapsed = time.time() - t0
        node_log.append(f"[rag_researcher] RAG failed ({e}) — continuing without context")
        logger.warning("rag_researcher_failed", error=str(e))
        return {"rag_context": "", "node_log": node_log}


# ═════════════════════════════════════════════════════════════════════════
# NODE 2: Pricing Calculator
# ═════════════════════════════════════════════════════════════════════════


def pricing_calculator(state: QuoteState) -> dict:
    """
    Call the Phase 3 pricing engine for each property. Runs synchronously
    using a direct DB session (not the async FastAPI session).
    """
    import os
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from datetime import date as dt_date
    from decimal import Decimal, ROUND_HALF_UP
    from backend.models.property import Property
    from backend.services.quote_builder import (
        BEDROOM_BASE_RATES, _DEFAULT_RATE, _cleaning_fee_for_bedrooms,
        _weekend_seasonal_rate, DEFAULT_TAX_RATE, TWO_PLACES,
        _nightly_from_rate_card, _fees_from_rate_card, _tax_rate_from_rate_card,
    )

    t0 = time.time()
    node_log = list(state.get("node_log", []))
    property_ids = state.get("property_ids", [])
    check_in_str = state.get("check_in_date", "")
    check_out_str = state.get("check_out_date", "")

    if not property_ids or not check_in_str or not check_out_str:
        node_log.append("[pricing_calculator] Missing property_ids or dates")
        return {"pricing_math": [], "node_log": node_log}

    check_in = dt_date.fromisoformat(check_in_str)
    check_out = dt_date.fromisoformat(check_out_str)
    nights = (check_out - check_in).days

    db_url = os.getenv("DATABASE_URL", settings.database_url)
    engine = create_engine(db_url)
    results = []

    try:
        with Session(engine) as db:
            for pid in property_ids:
                prop = db.query(Property).filter_by(id=pid).first()
                if not prop:
                    node_log.append(f"[pricing_calculator] Property {pid[:8]}... not found")
                    continue

                rate_card = prop.rate_card
                use_rc = (
                    rate_card is not None
                    and isinstance(rate_card, dict)
                    and len(rate_card.get("rates", [])) > 0
                )

                base_rent = Decimal("0")
                bedroom_base = BEDROOM_BASE_RATES.get(prop.bedrooms, _DEFAULT_RATE)
                from datetime import timedelta

                current = check_in
                while current < check_out:
                    if use_rc:
                        rate = _nightly_from_rate_card(rate_card, current)
                        if rate is None:
                            rate = _weekend_seasonal_rate(bedroom_base, current)
                    else:
                        rate = _weekend_seasonal_rate(bedroom_base, current)
                    base_rent += rate
                    current += timedelta(days=1)

                if use_rc:
                    fees = _fees_from_rate_card(rate_card)
                    tax_rate = _tax_rate_from_rate_card(rate_card)
                    source = "streamline_rate_card"
                else:
                    fees = _cleaning_fee_for_bedrooms(prop.bedrooms)
                    tax_rate = DEFAULT_TAX_RATE
                    source = "bedroom_rate_fallback"

                taxable = base_rent + fees
                taxes = (taxable * tax_rate).quantize(TWO_PLACES, ROUND_HALF_UP)
                total = base_rent + fees + taxes

                results.append({
                    "property_name": prop.name,
                    "bedrooms": prop.bedrooms,
                    "nights": nights,
                    "check_in_date": check_in_str,
                    "check_out_date": check_out_str,
                    "base_rent": str(base_rent),
                    "fees": str(fees),
                    "taxes": str(taxes),
                    "total_price": str(total),
                    "pricing_source": source,
                })

        elapsed = time.time() - t0
        node_log.append(f"[pricing_calculator] Priced {len(results)} properties in {elapsed:.1f}s")
        logger.info("pricing_calculator_complete", properties=len(results), elapsed=f"{elapsed:.1f}s")
        return {"pricing_math": results, "node_log": node_log}

    except Exception as e:
        elapsed = time.time() - t0
        node_log.append(f"[pricing_calculator] FAILED: {e}")
        logger.error("pricing_calculator_failed", error=str(e))
        return {"pricing_math": [], "node_log": node_log}


# ═════════════════════════════════════════════════════════════════════════
# NODE 3: Lead Copywriter
# ═════════════════════════════════════════════════════════════════════════


def lead_copywriter(state: QuoteState) -> dict:
    """
    Draft the personalized sales email using HYDRA 70B with RAG context
    and pricing math injected into the prompt.
    """
    t0 = time.time()
    node_log = list(state.get("node_log", []))
    rewrite_count = state.get("rewrite_count", 0)

    lead_name = state.get("lead_name", "Valued Guest")
    guest_message = state.get("guest_message", "")
    rag_context = state.get("rag_context", "")
    pricing_math = state.get("pricing_math", [])
    audit_notes = state.get("audit_notes", "")

    pricing_text = _format_pricing_for_prompt(pricing_math)

    system_prompt = (
        "You are an elite luxury cabin reservation specialist for Cabin Rentals of "
        "Georgia (CROG), a premier mountain cabin rental company in Blue Ridge, Georgia.\n\n"
        "RULES:\n"
        "1. Address the guest BY NAME. Show genuine excitement about their plans.\n"
        "2. DIRECTLY ANSWER every question from their message.\n"
        "3. Present each property with its EXACT total price from the pricing data.\n"
        "4. The dollar amounts in your email MUST EXACTLY MATCH the pricing data provided. "
        "Do NOT round, estimate, or change any prices.\n"
        "5. Include a call-to-action mentioning the quote expires in 24 hours.\n"
        "6. Sign off as the Cabin Rentals of Georgia Reservations Team.\n"
        "7. Keep 200-400 words. Plain text — no markdown bullets.\n"
        "8. Do NOT invent amenities not in the data."
    )

    user_parts = [f"GUEST INQUIRY:\n  Name: {lead_name}\n  Message: {guest_message}"]

    if rag_context:
        user_parts.append(f"\nHISTORICAL CONTEXT (similar past inquiries):\n{rag_context}")

    user_parts.append(f"\nPROPERTY OPTIONS WITH EXACT PRICING:\n{pricing_text}")

    if audit_notes and rewrite_count > 0:
        user_parts.append(
            f"\nCOMPLIANCE CORRECTION (your previous draft had errors — fix them):\n{audit_notes}"
        )

    user_parts.append("\nWrite the personalized sales email now.")
    user_prompt = "\n".join(user_parts)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        email_body, model_used = _llm_chat_sync(messages, timeout=180.0)
        elapsed = time.time() - t0
        attempt_label = f" (rewrite #{rewrite_count})" if rewrite_count > 0 else ""
        node_log.append(
            f"[lead_copywriter] Drafted {len(email_body)} chars via {model_used} in {elapsed:.1f}s{attempt_label}"
        )
        return {
            "draft_email": email_body,
            "draft_model": model_used,
            "rewrite_count": rewrite_count + 1,
            "node_log": node_log,
        }

    except Exception as e:
        elapsed = time.time() - t0
        node_log.append(f"[lead_copywriter] LLM failed ({e}) — using fallback template")
        logger.error("lead_copywriter_failed", error=str(e))
        fallback = _build_fallback(lead_name, pricing_math)
        return {
            "draft_email": fallback,
            "draft_model": "fallback_template",
            "rewrite_count": rewrite_count + 1,
            "node_log": node_log,
        }


# ═════════════════════════════════════════════════════════════════════════
# NODE 4: Compliance Auditor
# ═════════════════════════════════════════════════════════════════════════


def compliance_auditor(state: QuoteState) -> dict:
    """
    Fact-check the draft email against the pricing math. Uses a separate
    LLM call to verify dollar amounts match exactly. Sets audit_passed
    to True/False accordingly.
    """
    t0 = time.time()
    node_log = list(state.get("node_log", []))
    draft_email = state.get("draft_email", "")
    pricing_math = state.get("pricing_math", [])
    rewrite_count = state.get("rewrite_count", 0)

    if not draft_email or not pricing_math:
        node_log.append("[compliance_auditor] No draft or pricing — auto-pass")
        return {"audit_passed": True, "audit_notes": "", "node_log": node_log}

    if rewrite_count > 2:
        node_log.append("[compliance_auditor] Max rewrites (2) reached — auto-pass to prevent loop")
        return {"audit_passed": True, "audit_notes": "", "node_log": node_log}

    pricing_text = _format_pricing_for_prompt(pricing_math)

    audit_prompt = (
        "You are a compliance auditor for a vacation rental company. Your ONLY job is to "
        "verify that dollar amounts in a sales email EXACTLY match the official pricing data.\n\n"
        f"OFFICIAL PRICING DATA:\n{pricing_text}\n\n"
        f"DRAFT EMAIL TO AUDIT:\n{draft_email}\n\n"
        "TASK: Compare every dollar amount mentioned in the email against the official pricing. "
        "Check total prices, base rents, fees, and taxes.\n\n"
        "If ALL amounts match exactly, respond with ONLY: AUDIT_PASS\n"
        "If ANY amount is wrong, respond with: AUDIT_FAIL followed by a list of corrections needed."
    )

    messages = [{"role": "user", "content": audit_prompt}]

    try:
        result, model = _llm_chat_sync(
            messages,
            model=settings.ollama_fast_model,
            temperature=0.1,
            max_tokens=512,
            timeout=60.0,
            min_length=5,
        )

        passed = "AUDIT_PASS" in result.upper()
        elapsed = time.time() - t0
        status = "PASS" if passed else "FAIL"
        node_log.append(f"[compliance_auditor] {status} via {model} in {elapsed:.1f}s")

        if not passed:
            logger.warning("compliance_audit_failed", result=result[:200])

        return {
            "audit_passed": passed,
            "audit_notes": "" if passed else result,
            "node_log": node_log,
        }

    except Exception as e:
        elapsed = time.time() - t0
        node_log.append(f"[compliance_auditor] Audit LLM failed ({e}) — auto-pass")
        logger.warning("compliance_auditor_llm_failed", error=str(e))
        return {"audit_passed": True, "audit_notes": "", "node_log": node_log}


# ── Helpers ──────────────────────────────────────────────────────────────


def _format_pricing_for_prompt(pricing_math: List[Dict[str, Any]]) -> str:
    """Format pricing data as human-readable text for LLM prompts."""
    lines = []
    for i, opt in enumerate(pricing_math, 1):
        lines.append(f"Option {i}: {opt['property_name']} ({opt['bedrooms']} bedrooms)")
        lines.append(f"  Dates: {opt['check_in_date']} to {opt['check_out_date']} ({opt['nights']} nights)")
        lines.append(f"  Base Rent: ${opt['base_rent']}")
        lines.append(f"  Cleaning & Fees: ${opt['fees']}")
        lines.append(f"  Taxes: ${opt['taxes']}")
        lines.append(f"  TOTAL: ${opt['total_price']}")
        lines.append("")
    return "\n".join(lines)


def _build_fallback(lead_name: str, pricing_math: List[Dict[str, Any]]) -> str:
    """Rule 5 fallback template when all LLMs fail."""
    guest = lead_name or "Valued Guest"
    lines = [
        f"Dear {guest},",
        "",
        "Thank you for your interest in Cabin Rentals of Georgia!",
        "",
    ]
    for i, opt in enumerate(pricing_math, 1):
        lines.append(
            f"Option {i}: {opt['property_name']} ({opt['bedrooms']}BR) — "
            f"{opt['nights']} nights, ${opt['total_price']} total"
        )
    lines.extend([
        "",
        "This quote is valid for 24 hours. Reply or call (706) 258-3900.",
        "",
        "Warm regards,",
        "Cabin Rentals of Georgia Reservations Team",
    ])
    return "\n".join(lines)
