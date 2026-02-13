"""
GUEST COMMS AGENT — Strangler Fig Replacement for Streamline Guest Messaging
=============================================================================
Fortress Prime | Sector S01 (CROG) — Cabin Rentals of Georgia

This agent wraps the existing guest_reply_engine pipeline in the mandated
OODA Reflection Loop and exposes it via the Fortress API Gateway.

The existing pipeline (guest_reply_engine + gmail_watcher) is already 100%
local. This agent adds:
    1. OODA audit trail (Constitution Article III)
    2. Guest lead enrichment (cross-reference guest_leads for context)
    3. API surface (POST /v1/crog/guests/reply)
    4. Feature flag gating (FF_GUEST_COMMS)
    5. R1 quality review for high-value responses (TITAN mode)

Data Sources (all local — Constitution Article I compliant):
    guest_reply_engine   — Topic classification, tone detection, context slicing
    cabins/*.yaml        — Property-specific knowledge base
    guest_leads          — Guest history and contact enrichment
    email_archive        — Prior correspondence for thread context
    prompts/*            — Dynamic few-shot examples and prompt templates

OODA Pattern:
    OBSERVE  — Receive guest email, identify cabin, fetch guest history
    ORIENT   — Classify topic + tone, slice context, load examples
    DECIDE   — Generate AI draft (SWARM) or R1-reviewed draft (TITAN)
    ACT      — Return draft for human review (NEVER auto-send)
    POST-MORTEM — Log to system_post_mortems with full pipeline trace

Safety Model (inherited from gmail_watcher.py):
    - NEVER sends emails. Drafts only. Human reviews and sends.
    - Emergency tone always escalates to human.
    - Low-confidence results flagged, not drafted.

Usage:
    # Programmatic
    from src.agents.guest_comms import generate_guest_reply
    result = generate_guest_reply(
        cabin_slug="rolling_river",
        guest_email="Can I charge my Tesla at the cabin?",
        guest_email_address="guest@example.com",
    )

    # API
    POST /v1/crog/guests/reply
    {"cabin_slug": "rolling_river", "guest_email": "...", "guest_email_address": "..."}

Governing Documents:
    CONSTITUTION.md      — Article I (zero cloud), Article III (OODA mandate)
    REQUIREMENTS.md      — Section 3.2 (Strangler Fig), Section 3.5 (LangGraph)
    docs/STRANGLER_FIG_GUEST_COMMS.md — Migration audit
"""

from __future__ import annotations

import os
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("agents.guest_comms")

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# I. PYDANTIC MODELS (REQUIREMENTS.md Section 3.4)
# =============================================================================

class GuestContext(BaseModel):
    """Enrichment context from guest_leads and email_archive."""
    guest_name: Optional[str] = None
    prior_stays: int = Field(default=0, ge=0)
    prior_topics: List[str] = Field(default_factory=list)
    vip_flag: bool = False
    last_stay_property: Optional[str] = None


class ClassificationResult(BaseModel):
    """Topic + tone classification from the guest_reply_engine."""
    topic: str = Field(..., min_length=1)
    secondary_topics: List[str] = Field(default_factory=list)
    topic_confidence: float = Field(..., ge=0, le=1)
    tone: str = Field(..., min_length=1)
    tone_modifier: str = Field(default="")
    tone_confidence: float = Field(default=0.0, ge=0, le=1)
    escalation_required: bool = False


class GuestReplyRequest(BaseModel):
    """Inbound request for guest reply generation."""
    cabin_slug: str = Field(..., min_length=1, max_length=50)
    guest_email: str = Field(..., min_length=1)
    guest_email_address: Optional[str] = Field(
        default=None,
        description="Guest email address for history lookup (PII — SOVEREIGN, never cloud)"
    )
    model_override: Optional[str] = None
    dry_run: bool = False

    @field_validator("cabin_slug")
    @classmethod
    def slug_lowercase(cls, v: str) -> str:
        return v.lower().strip()


class GuestReplyResponse(BaseModel):
    """Complete response from the Guest Comms agent."""
    # Draft
    draft: str = Field(default="")
    success: bool = False
    error: Optional[str] = None

    # Classification
    classification: ClassificationResult

    # Context
    cabin_slug: str
    cabin_name: str = Field(default="")
    guest_context: GuestContext = Field(default_factory=GuestContext)

    # Pipeline metrics
    context_tokens: int = Field(default=0, ge=0)
    tokens_saved: int = Field(default=0, ge=0)
    examples_loaded: int = Field(default=0, ge=0)
    duration_ms: float = Field(default=0.0, ge=0)
    model_used: str = Field(default="")
    run_id: str = Field(default="")

    # OODA audit
    ooda_sector: str = Field(default="crog")
    ooda_confidence: float = Field(default=0.0, ge=0, le=1)
    ooda_decision: str = Field(default="")
    audit_trail: List[str] = Field(default_factory=list)

    # Metadata
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field(default="fortress_local")
    classification_level: str = Field(default="RESTRICTED")  # Contains guest email text


# =============================================================================
# II. GUEST LEAD ENRICHMENT (Local Postgres)
# =============================================================================

def enrich_guest_context(guest_email_address: Optional[str]) -> GuestContext:
    """
    Look up guest history from guest_leads table.
    Returns enrichment context for better response personalization.

    This is RESTRICTED PII data — NEVER sent to cloud (Article I).
    """
    if not guest_email_address:
        return GuestContext()

    try:
        import psycopg2
        import psycopg2.extras

        try:
            from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
        except ImportError:
            DB_HOST = os.getenv("DB_HOST", "192.168.0.100")
            DB_NAME = os.getenv("DB_NAME", "fortress_db")
            DB_USER = os.getenv("DB_USER", "miner_bot")
            DB_PASS = os.getenv("DB_PASS", "")

        conn = psycopg2.connect(
            host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        cur = conn.cursor()

        # Count prior interactions
        cur.execute("""
            SELECT guest_name, COUNT(*) as interaction_count,
                   array_agg(DISTINCT event_type) FILTER (WHERE event_type IS NOT NULL) as topics,
                   MAX(check_out) as last_checkout
            FROM guest_leads
            WHERE guest_email = %s
            GROUP BY guest_name
            LIMIT 1
        """, (guest_email_address.lower(),))

        row = cur.fetchone()
        conn.close()

        if not row:
            return GuestContext()

        return GuestContext(
            guest_name=row.get("guest_name"),
            prior_stays=int(row.get("interaction_count", 0)),
            prior_topics=row.get("topics") or [],
            vip_flag=int(row.get("interaction_count", 0)) >= 3,
        )

    except Exception as e:
        logger.warning(f"Guest enrichment failed (non-fatal): {e}")
        return GuestContext()


# =============================================================================
# III. OODA NODE IMPLEMENTATIONS
# =============================================================================

def observe(state: dict) -> dict:
    """
    OBSERVE: Receive the guest email, identify the cabin, fetch guest history.
    """
    request: GuestReplyRequest = state.get("_request")
    now = datetime.now(timezone.utc).isoformat()

    # Enrich with guest history (local DB only)
    guest_ctx = enrich_guest_context(request.guest_email_address)
    state["_guest_context"] = guest_ctx

    state["observation"] = (
        f"Guest email received for cabin '{request.cabin_slug}'. "
        f"Length: {len(request.guest_email)} chars. "
        f"Guest history: {guest_ctx.prior_stays} prior stays, "
        f"VIP: {guest_ctx.vip_flag}."
    )

    state["audit_trail"].append(
        f"[{now}] OBSERVE: Email received, {len(request.guest_email)} chars, "
        f"guest_history={'enriched' if guest_ctx.prior_stays > 0 else 'new_guest'}"
    )
    return state


def orient(state: dict) -> dict:
    """
    ORIENT: Run topic classification, tone detection, and context slicing.
    Delegates to the existing guest_reply_engine pipeline steps 1-4.
    """
    request: GuestReplyRequest = state.get("_request")
    now = datetime.now(timezone.utc).isoformat()

    try:
        from prompts.topic_classifier import classify_topic
        from prompts.tone_detector import detect_tone
        from prompts.context_slicer import slice_context
        from prompts.starred_db import load_dynamic_examples

        # Step 1: Classify topic
        topic_result = classify_topic(request.guest_email)

        # Step 2: Detect tone
        tone_result = detect_tone(request.guest_email)

        # Step 3: Slice context
        slice_result = slice_context(
            request.cabin_slug,
            topic_result.primary,
            topic_result.secondary or None,
        )

        # Step 4: Load examples
        examples_text = load_dynamic_examples(topic_result.primary)
        if not examples_text:
            for sec in topic_result.secondary:
                examples_text = load_dynamic_examples(sec)
                if examples_text:
                    break
        if not examples_text:
            examples_text = "(No proven examples for this topic yet.)"

        # Store classification
        classification = ClassificationResult(
            topic=topic_result.primary,
            secondary_topics=topic_result.secondary,
            topic_confidence=topic_result.confidence,
            tone=tone_result.tone,
            tone_modifier=tone_result.modifier,
            tone_confidence=tone_result.confidence,
            escalation_required=tone_result.escalation_required,
        )

        state["_classification"] = classification
        state["_slice_result"] = slice_result
        state["_examples_text"] = examples_text
        state["_cabin_name"] = getattr(slice_result, "cabin_name", request.cabin_slug)

        # Determine confidence from classification
        base_confidence = topic_result.confidence
        if tone_result.escalation_required:
            base_confidence *= 0.5  # Reduce confidence for escalations
        if state.get("_guest_context", GuestContext()).vip_flag:
            base_confidence = min(base_confidence * 1.1, 1.0)  # Boost for VIPs

        state["confidence"] = base_confidence

        state["orientation"] = (
            f"Topic: {topic_result.primary} (conf: {topic_result.confidence:.2f}), "
            f"Tone: {tone_result.tone} (conf: {tone_result.confidence:.2f}), "
            f"Escalation: {tone_result.escalation_required}, "
            f"Context: {slice_result.token_estimate} tokens "
            f"(saved {slice_result.full_context_tokens - slice_result.token_estimate})"
        )

    except Exception as e:
        state["_classification"] = ClassificationResult(
            topic="unknown", topic_confidence=0.0,
            tone="unknown", escalation_required=True,
        )
        state["confidence"] = 0.0
        state["orientation"] = f"Classification FAILED: {e}"
        logger.error(f"Orient phase failed: {e}")

    state["audit_trail"].append(f"[{now}] ORIENT: {state['orientation'][:200]}")
    return state


def decide(state: dict) -> dict:
    """
    DECIDE: Determine whether to generate a draft or escalate.
    In TITAN mode with escalation, submit to R1 for quality review.
    """
    classification: ClassificationResult = state.get("_classification")
    guest_ctx: GuestContext = state.get("_guest_context", GuestContext())
    confidence = state.get("confidence", 0.0)
    now = datetime.now(timezone.utc).isoformat()

    # Escalation logic (mirrors gmail_watcher.should_escalate)
    escalate = False
    reasons = []

    if classification.escalation_required or classification.tone == "emergency":
        escalate = True
        reasons.append("emergency_tone")

    if classification.topic_confidence < 0.3:
        escalate = True
        reasons.append(f"low_confidence({classification.topic_confidence:.2f})")

    if classification.topic == "general" and state.get("_examples_text", "").startswith("(No"):
        escalate = True
        reasons.append("unknown_topic_no_examples")

    if escalate:
        state["decision"] = (
            f"ESCALATE to human. Reasons: {', '.join(reasons)}. "
            f"Do NOT auto-draft. Label as AI-Human-Help."
        )
        state["_escalate"] = True
    else:
        # Check if TITAN mode should review VIP or high-value responses
        defcon = os.getenv("FORTRESS_DEFCON", "SWARM").upper()
        if defcon == "TITAN" and guest_ctx.vip_flag:
            state["decision"] = (
                f"GENERATE draft with R1 quality review. "
                f"VIP guest ({guest_ctx.prior_stays} stays). "
                f"Confidence: {confidence:.2f}."
            )
            state["_r1_review"] = True
        else:
            state["decision"] = (
                f"GENERATE draft via SWARM inference. "
                f"Confidence: {confidence:.2f}. "
                f"Topic: {classification.topic}."
            )
            state["_r1_review"] = False
        state["_escalate"] = False

    state["audit_trail"].append(
        f"[{now}] DECIDE: {'ESCALATE' if escalate else 'GENERATE'}, "
        f"confidence={confidence:.2f}"
    )
    return state


def act(state: dict) -> dict:
    """
    ACT: Generate the AI draft using guest_reply_engine, or return escalation.
    NEVER auto-sends. Drafts only.
    """
    request: GuestReplyRequest = state.get("_request")
    classification: ClassificationResult = state.get("_classification")
    now = datetime.now(timezone.utc).isoformat()

    if state.get("_escalate"):
        state["action_result"] = (
            f"ESCALATED: {state['decision']}. "
            f"Email requires human review before response."
        )
        state["_reply_result"] = None
        state["audit_trail"].append(f"[{now}] ACT: Escalated — no draft generated")
        return state

    # Generate draft using the existing engine
    try:
        from src.guest_reply_engine import process_email, ReplyResult

        result: ReplyResult = process_email(
            cabin_slug=request.cabin_slug,
            guest_email=request.guest_email,
            model=request.model_override,
            dry_run=request.dry_run,
            verbose=False,
        )

        state["_reply_result"] = result

        if result.success:
            state["action_result"] = (
                f"SUCCESS: Draft generated. "
                f"Model: {result.model}, "
                f"Duration: {result.duration_ms:.0f}ms, "
                f"Tokens: {result.context_tokens}."
            )
        else:
            state["action_result"] = f"FAILED: LLM error — {result.error}"
            state["confidence"] = 0.1

        # Optional R1 quality review (TITAN mode, VIP guests)
        if state.get("_r1_review") and result.success:
            state = _r1_quality_review(state, result)

    except Exception as e:
        state["action_result"] = f"FAILED: Pipeline error — {e}"
        state["_reply_result"] = None
        state["confidence"] = 0.0
        logger.error(f"Guest comms act phase failed: {e}")

    state["audit_trail"].append(f"[{now}] ACT: {state['action_result'][:150]}")
    return state


def _r1_quality_review(state: dict, result) -> dict:
    """
    Submit the generated draft to R1 for quality review (TITAN mode only).
    R1 checks for:
    - Factual accuracy (does the draft match cabin context?)
    - Tone appropriateness
    - Policy compliance
    """
    try:
        from config import get_inference_client

        client, model = get_inference_client("TITAN")
        prompt = (
            "You are the Sovereign Quality Auditor for Cabin Rentals of Georgia.\n"
            "Review this AI-generated guest reply for:\n"
            "1. Factual accuracy — does it match the cabin's actual amenities?\n"
            "2. Tone appropriateness — warm, professional, helpful?\n"
            "3. Policy compliance — no promises we can't keep?\n\n"
            f"Guest asked about: {state.get('_classification').topic}\n"
            f"Guest tone: {state.get('_classification').tone}\n\n"
            f"AI Draft:\n{result.draft}\n\n"
            "Respond with: APPROVED or REVISE (with specific notes)."
        )

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.1,
        )
        r1_verdict = response.choices[0].message.content
        state["audit_trail"].append(
            f"[{datetime.now(timezone.utc).isoformat()}] R1_REVIEW: {r1_verdict[:200]}"
        )

        if "REVISE" in r1_verdict.upper():
            state["confidence"] = max(state.get("confidence", 0) - 0.2, 0.1)

    except Exception as e:
        logger.warning(f"R1 quality review failed (non-fatal): {e}")
        state["audit_trail"].append(
            f"[{datetime.now(timezone.utc).isoformat()}] R1_REVIEW: "
            f"Failed (non-fatal): {e}"
        )

    return state


# =============================================================================
# IV. AGENT ASSEMBLY
# =============================================================================

def build_guest_comms_agent():
    """Build the Guest Comms OODA agent. Returns a compiled LangGraph agent."""
    from src.sovereign_ooda import build_ooda_graph
    graph = build_ooda_graph(
        observe_fn=observe,
        orient_fn=orient,
        decide_fn=decide,
        act_fn=act,
    )
    return graph.compile()


def generate_guest_reply(
    cabin_slug: str,
    guest_email: str,
    guest_email_address: str = None,
    model_override: str = None,
    dry_run: bool = False,
) -> GuestReplyResponse:
    """
    High-level API: Generate a guest reply with full OODA audit trail.

    This is the function called by the FastAPI endpoint and programmatic callers.
    It wraps the existing guest_reply_engine in the OODA pattern and adds
    guest lead enrichment, audit logging, and optional R1 quality review.

    Args:
        cabin_slug: Cabin identifier (e.g., "rolling_river").
        guest_email: The raw guest email text.
        guest_email_address: Guest email for history lookup (optional PII).
        model_override: Override LLM model.
        dry_run: If True, skip LLM call.

    Returns:
        GuestReplyResponse with draft, classification, and OODA audit trail.
    """
    from src.sovereign_ooda import make_initial_state

    # Build request model
    request = GuestReplyRequest(
        cabin_slug=cabin_slug,
        guest_email=guest_email,
        guest_email_address=guest_email_address,
        model_override=model_override,
        dry_run=dry_run,
    )

    # Initialize OODA state
    initial = make_initial_state(sector="crog", query=f"guest_reply:{cabin_slug}")
    initial["_request"] = request

    # Run the OODA agent
    agent = build_guest_comms_agent()
    result_state = agent.invoke(initial)

    # Extract pipeline result
    reply_result = result_state.get("_reply_result")
    classification = result_state.get("_classification", ClassificationResult(
        topic="unknown", topic_confidence=0.0, tone="unknown",
    ))
    guest_ctx = result_state.get("_guest_context", GuestContext())

    # Build response
    response = GuestReplyResponse(
        draft=reply_result.draft if reply_result else "",
        success=reply_result.success if reply_result else False,
        error=reply_result.error if reply_result else result_state.get("action_result"),
        classification=classification,
        cabin_slug=cabin_slug,
        cabin_name=result_state.get("_cabin_name", cabin_slug),
        guest_context=guest_ctx,
        context_tokens=reply_result.context_tokens if reply_result else 0,
        tokens_saved=reply_result.tokens_saved if reply_result else 0,
        examples_loaded=reply_result.examples_loaded if reply_result else 0,
        duration_ms=reply_result.duration_ms if reply_result else 0,
        model_used=reply_result.model if reply_result else "",
        run_id=reply_result.run_id if reply_result else "",
        ooda_sector="crog",
        ooda_confidence=result_state.get("confidence", 0.0),
        ooda_decision=result_state.get("decision", ""),
        audit_trail=result_state.get("audit_trail", []),
    )

    return response
