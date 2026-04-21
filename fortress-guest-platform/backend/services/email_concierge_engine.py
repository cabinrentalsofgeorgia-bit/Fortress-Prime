"""
Email concierge engine — thin wrapper around crog_concierge_engine.

For cold email inquiries (no guest linkage), runs the 9-seat council with
an email-specific case brief.  When the inquirer is already linked to a Guest,
delegates directly to run_guest_triage().

Returns: {draft_text, confidence, meta, intent, sentiment, category}

Phase: draft-quality-fix (PR 3)
  _compose_email_draft() replaces the SMS _compose_draft_reply for the cold-
  inquiry path. It injects up to 3 retrieved exemplars from Taylor's sent-mail
  corpus plus the council's top recommendations, producing specific drafts
  instead of the generic fallback template.
"""
from __future__ import annotations

import json
import logging
import uuid as _uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.email_inquirer import EmailInquirer
from backend.models.email_message import EmailMessage

# Reuse from the existing engine — no code duplication
from backend.services.crog_concierge_engine import (
    ConciergePersona,
    _persist_operational_deliberation_log,
    analyze_with_concierge_persona,
    compute_concierge_consensus,
    _heuristic_escalation,
    _make_error_opinion,
    PERSONA_TIMEOUT_SECONDS,
    run_guest_triage,
    _call_llm,
    HYDRA_MODEL_120B,
    HYDRA_120B_URL,
)

import asyncio

logger = logging.getLogger("email_concierge_engine")


# ---------------------------------------------------------------------------
# Email-specific composer (Phase: draft-quality-fix)
# ---------------------------------------------------------------------------

async def _compose_email_draft(
    *,
    focal_message: str,
    council_recommendations: List[str],
    exemplars: list,  # List[SentMailExemplar] — typed loosely to avoid circular import
) -> str:
    """
    Build an exemplar-augmented composer prompt and call the HYDRA LLM.

    If exemplars are available: injects up to 3 real sent-mail examples so the
    model matches Taylor's actual voice and addresses the specific inquiry.
    If no exemplars: falls back to council-recommendations-only prompt, which
    is still significantly better than the generic SMS fallback template.
    """
    rec_bullets = "\n".join(
        f"- {r}" for r in (council_recommendations or [])[:6] if r
    ) or "- Respond warmly and invite the guest to share dates and party size."

    if exemplars:
        example_blocks = []
        for i, ex in enumerate(exemplars[:3], 1):
            date_str = ex.sent_at[:10] if ex.sent_at else "past"
            example_blocks.append(
                f"=== Example {i} (topic: {ex.detected_topic}, from {date_str}) ===\n"
                f"{ex.body[:1200]}"
            )
        examples_section = "\n\n".join(example_blocks)

        system = (
            "You are writing on behalf of Taylor Knight at Cabin Rentals of Georgia. "
            "Your job is to write a guest reply email. "
            "Match the voice, warmth, specificity, and sign-off style shown in the examples. "
            "Do not mention the council, AI, or that this was generated. "
            "Output plain text only — the exact reply to send, nothing else."
        )
        user = f"""HERE ARE {len(exemplars[:3])} EXAMPLES OF HOW WE REPLY TO SIMILAR INQUIRIES:

{examples_section}

THE COUNCIL REVIEWED THIS INQUIRY AND RECOMMENDS ADDRESSING:
{rec_bullets}

THE GUEST ASKED:
{focal_message[:4000]}

Write a reply that:
- Matches the tone and voice shown in the examples
- Addresses what the guest specifically asked about
- Incorporates the council's recommendations naturally
- Signs off the way the examples sign off
- Does not mention that it was AI-generated, does not mention 'the council'

Reply:"""
    else:
        # Council-only path — no exemplars available
        system = (
            "You are writing on behalf of Taylor Knight at Cabin Rentals of Georgia. "
            "Write a warm, professional email reply to the guest inquiry below. "
            "Be specific about what they asked. Do not mention AI or any internal processes. "
            "Sign off warmly from the CROG team."
        )
        user = f"""THE COUNCIL REVIEWED THIS INQUIRY AND RECOMMENDS ADDRESSING:
{rec_bullets}

THE GUEST ASKED:
{focal_message[:4000]}

Write a warm, professional reply that addresses what the guest asked and
incorporates the council's recommendations naturally.

Reply:"""

    text, _ = await _call_llm(
        system,
        user,
        model=HYDRA_MODEL_120B,
        base_url=HYDRA_120B_URL,
        temperature=0.55,
        max_tokens=600,
    )

    draft = (text or "").strip()
    if not draft:
        draft = (
            "Thank you for reaching out to Cabin Rentals of Georgia! We'd love to help "
            "you plan your perfect mountain getaway. Please share your preferred dates, "
            "party size, and any questions and we'll put together the best options for you.\n\n"
            "Warm regards,\nTaylor\nCabin Rentals of Georgia"
        )
    return draft[:2000]


async def run_email_triage(
    db: AsyncSession,
    *,
    email_message_id: UUID,
) -> Dict[str, Any]:
    """
    Email-channel analog of run_guest_triage.

    1. Load EmailMessage + EmailInquirer.
    2. If inquirer.guest_id is set → delegate to run_guest_triage with
       email body as inbound_message.
    3. Otherwise → run the 9-seat council with an email-shaped case brief,
       skipping property context (no reservation available).
    4. Persist audit row to core.deliberation_logs.
    5. Return {draft_text, confidence, meta, intent, sentiment, category}.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(EmailMessage)
        .options(selectinload(EmailMessage.inquirer))
        .where(EmailMessage.id == email_message_id)
    )
    msg: Optional[EmailMessage] = result.scalar_one_or_none()
    if msg is None:
        raise ValueError(f"EmailMessage not found: {email_message_id}")

    inquirer: Optional[EmailInquirer] = msg.inquirer
    focal_message = (msg.body_text or "").strip()

    # ── Path A: inquirer already linked to a guest → reuse full SMS triage ──
    if inquirer and inquirer.guest_id:
        try:
            triage = await run_guest_triage(
                db,
                guest_id=inquirer.guest_id,
                inbound_message=focal_message,
                trigger_type="EMAIL_CONCIERGE_TRIAGE",
            )
            draft_text = triage.get("draft_reply", {}).get("text", "")
            consensus = triage.get("council", {})
            return {
                "draft_text": _adapt_draft_for_email(draft_text),
                "confidence": consensus.get("consensus_conviction"),
                "meta": {
                    "path": "guest_triage_delegate",
                    "session_id": triage.get("session_id"),
                    "consensus_signal": consensus.get("consensus_signal"),
                    "triage": triage.get("triage"),
                },
                "intent": triage.get("triage", {}).get("primary_issue"),
                "sentiment": None,
                "category": None,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "email_triage_guest_delegate_failed guest_id=%s err=%s",
                str(inquirer.guest_id), str(exc)[:200],
            )
            # Fall through to cold-inquiry path

    # ── Path B: cold inquiry — no guest linkage ──────────────────────────────
    session_id = f"email-concierge-{_uuid.uuid4()}"
    personas = ConciergePersona.load_all()
    if not personas:
        logger.warning("email_concierge_no_personas — using fast fallback")
        return _fast_fallback(focal_message)

    case_brief = _build_email_case_brief(
        focal_message=focal_message,
        inquirer=inquirer,
        subject=msg.subject or "",
        received_at=msg.received_at,
    )

    opinions = []

    async def _one(persona: ConciergePersona) -> None:
        try:
            op = await asyncio.wait_for(
                analyze_with_concierge_persona(persona, case_brief),
                timeout=float(PERSONA_TIMEOUT_SECONDS),
            )
        except asyncio.TimeoutError:
            op = _make_error_opinion(
                persona, f"timeout after {PERSONA_TIMEOUT_SECONDS}s",
                float(PERSONA_TIMEOUT_SECONDS),
            )
        except Exception as exc:  # noqa: BLE001
            op = _make_error_opinion(persona, f"{type(exc).__name__}: {str(exc)[:200]}", 0.0)
        opinions.append(op)

    await asyncio.gather(*[_one(p) for p in personas])
    opinions.sort(key=lambda o: o.seat)

    consensus = compute_concierge_consensus(opinions)
    if consensus.get("error"):
        return _fast_fallback(focal_message)

    # Retrieve exemplars for few-shot composer injection (fail-fast, non-blocking)
    exemplars = []
    try:
        from backend.services.sent_mail_retriever import SentMailRetriever
        retriever = SentMailRetriever()
        exemplars = await retriever.find_similar_replies(focal_message, k=3)
    except Exception as exc:  # noqa: BLE001
        logger.warning("email_triage_retriever_failed err=%s", str(exc)[:200])

    council_recs = consensus.get("top_recommended_actions", [])
    draft_text = await _compose_email_draft(
        focal_message=focal_message,
        council_recommendations=council_recs,
        exemplars=exemplars,
    )

    escalation_level, escalation_rationale = _heuristic_escalation(
        focal_message,
        str(consensus.get("consensus_signal", "NEUTRAL")),
        False,
    )

    # Infer simple intent/sentiment from consensus
    intent = (consensus.get("top_operational_arguments") or [None])[0]
    if intent:
        intent = intent[:50]

    # Composition mode for audit / debugging
    n_exemplars = len(exemplars)
    composition_mode = (
        f"council_plus_{n_exemplars}_exemplars" if exemplars else "council_only"
    )

    meta = {
        "path": "cold_inquiry_9seat",
        "session_id": session_id,
        "consensus_signal": consensus.get("consensus_signal"),
        "consensus_conviction": consensus.get("consensus_conviction"),
        "escalation_level": escalation_level,
        "escalation_rationale": escalation_rationale,
        "signal_breakdown": consensus.get("signal_breakdown"),
        "top_recommended_actions": consensus.get("top_recommended_actions", [])[:5],
        "composition_mode": composition_mode,
        "exemplar_scores": [round(e.score, 4) for e in exemplars],
        "exemplar_topics": [e.detected_topic for e in exemplars],
    }

    # Persist deliberation audit log (best-effort, never blocks the result)
    try:
        await _persist_operational_deliberation_log(
            db,
            verdict_type="email_concierge_triage",
            session_id=session_id,
            guest_id=None,
            reservation_id=None,
            property_id=None,
            message_id=email_message_id,
            payload={
                "session_id": session_id,
                "consensus": consensus,
                "opinions": [o.to_dict() for o in opinions],
                "draft_text": draft_text,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("email_triage_deliberation_persist_failed err=%s", str(exc)[:200])

    return {
        "draft_text": draft_text,
        "confidence": consensus.get("consensus_conviction"),
        "meta": meta,
        "intent": intent,
        "sentiment": None,
        "category": "email_inquiry",
    }


def _build_email_case_brief(
    *,
    focal_message: str,
    inquirer: Optional[EmailInquirer],
    subject: str,
    received_at: Optional[datetime],
) -> str:
    lines = [
        "=== EMAIL TRIAGE — COLD INQUIRY CASE BRIEF ===",
        "",
        f"EMAIL_SUBJECT: {subject[:255]}",
        f"RECEIVED_AT: {received_at.isoformat() if received_at else 'unknown'}",
        "",
        f"FOCAL_MESSAGE:\n{focal_message[:8000]}",
        "",
    ]
    if inquirer:
        lines += [
            "INQUIRER:",
            json.dumps(
                {
                    "email": inquirer.email,
                    "display_name": inquirer.display_name,
                    "first_name": inquirer.first_name,
                    "last_name": inquirer.last_name,
                    "inquiry_count": inquirer.inquiry_count,
                    "first_seen_at": inquirer.first_seen_at.isoformat() if inquirer.first_seen_at else None,
                    "inferred_party_size": inquirer.inferred_party_size,
                    "inferred_dates_text": inquirer.inferred_dates_text,
                },
                default=str,
                indent=2,
            ),
        ]
    else:
        lines.append("INQUIRER: unknown cold contact")
    lines += [
        "",
        "CONTEXT: This is a cold email inquiry — no reservation or guest record linked yet.",
        "Draft a warm, professional response. Do NOT promise specific availability, pricing,",
        "or access codes — those require staff verification. Invite the guest to share",
        "their dates and party size so a quote can be prepared.",
    ]
    return "\n".join(lines)


def _adapt_draft_for_email(sms_draft: str) -> str:
    """Expand terse SMS drafts to a warmer email-appropriate tone."""
    if not sms_draft:
        return (
            "Thank you for reaching out to Cabin Rentals of Georgia! We'd love to help "
            "you plan your stay. Please share your preferred dates and party size and we'll "
            "get back to you with availability and pricing.\n\n"
            "Warm regards,\nThe CROG Concierge Team"
        )
    # If the draft already looks like a multi-sentence email, return as-is
    if len(sms_draft) > 200 or "\n" in sms_draft:
        return sms_draft
    # Otherwise wrap the SMS message in a basic email greeting/closing
    return (
        f"Thank you for contacting Cabin Rentals of Georgia!\n\n"
        f"{sms_draft}\n\n"
        f"Warm regards,\nThe CROG Concierge Team"
    )


def _fast_fallback(focal_message: str) -> Dict[str, Any]:  # noqa: ARG001
    """Used when personas are unavailable or upstream fails."""
    return {
        "draft_text": (
            "Thank you for reaching out to Cabin Rentals of Georgia! We'd love to help "
            "you plan your perfect mountain getaway. Please share your preferred dates, "
            "party size, and any questions so we can put together the perfect options for you.\n\n"
            "Warm regards,\nThe CROG Concierge Team"
        ),
        "confidence": 0.5,
        "meta": {"path": "fast_fallback"},
        "intent": "general_inquiry",
        "sentiment": None,
        "category": "email_inquiry",
    }
