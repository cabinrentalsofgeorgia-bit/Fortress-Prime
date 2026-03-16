"""
Agentic Sales Copywriter — Few-Shot LLM-powered quote email drafting.

Uses real historical guest inquiries (extracted from Streamline) as few-shot
examples so the LLM learns CROG's exact hospitality tone. The Tracey Colombo
Thanksgiving inquiry (reservation 42193) serves as the canonical exemplar.

Inference chain: HYDRA (deepseek-r1:70b) -> SWARM (qwen2.5:7b) -> OpenAI (gpt-4o)
Rule 5 compliance: Every failure path logs loudly and falls back to a
safe, professionally-worded default email. No silent failures.
"""
from __future__ import annotations

import re
from typing import List, Dict, Any, Optional

import httpx
import structlog

from backend.core.config import settings

logger = structlog.get_logger(service="agentic_sales")

# ── System Prompt — Elite Luxury Cabin Reservation Specialist ────────────

SYSTEM_PROMPT = """\
You are an elite luxury cabin reservation specialist for Cabin Rentals of \
Georgia (CROG), a premier mountain cabin rental company in Blue Ridge, Georgia.

You craft warm, hyper-personalized sales emails that close bookings. You are \
not writing templates — you are having a one-on-one conversation with a guest \
who is dreaming about their perfect mountain getaway.

RULES:
1. Address the guest BY NAME in the opening line. Show genuine excitement \
about their specific occasion or plans.
2. DIRECTLY ANSWER every question from their original message (hot tub, \
pet policy, views, nearby restaurants, anniversary plans, etc.).
3. Present each property option with its total price and a one-sentence \
highlight that connects to what the guest asked for.
4. Include a clear CALL-TO-ACTION — mention the quote expires in 24 hours.
5. Sign off warmly as the Cabin Rentals of Georgia Reservations Team.
6. Keep the email between 200-400 words. Concise but persuasive.
7. Use line breaks between sections for readability.
8. Write plain-text email body — no markdown, no bullet points with *.
9. Do NOT invent amenities or features not provided in the data.\
"""

# ── Few-Shot Example: Tracey Colombo Thanksgiving (Reservation 42193) ────
# Real guest inquiry extracted from Streamline, sanitized per Rule 6.
# This teaches the LLM the exact warm, empathetic tone CROG expects.

FEW_SHOT_GUEST_INQUIRY = """\
GUEST INQUIRY:
  Name: Tracey Colombo
  Message: Hello! I love your cabin, it's stunning. I'm a former cabin owner \
myself! (the Ozark's) I was planning a trip to spend Thanksgiving with my \
adult daughters and your cabin is the perfect location and size for the three \
of us. I have rented many homes during my marriage and since my divorce, we \
will take care of your home as if it were ours (better) should you decide to \
let us stay for the holiday. Both my daughters are in college and it's my year \
to spend Thanksgiving with them. My older daughter does have a small dog (we \
don't have to bring her) that is completely housebroken and very well behaved. \
I could pay any pet deposit. Please call or write with any questions.

PROPERTY OPTIONS WITH PRICING:
  Option 1: Aska Escape Lodge (3 bedrooms)
    Dates: 2026-11-24 to 2026-11-29 (5 nights)
    Base Rent: $1,695.00
    Cleaning & Fees: $250.00
    Taxes: $252.85
    TOTAL: $2,197.85

Write the personalized sales email now.\
"""

FEW_SHOT_STAFF_RESPONSE = """\
Dear Tracey,

What a wonderful way to spend Thanksgiving — the mountains of Blue Ridge are \
absolutely magical in late November, and I can already picture you and your \
daughters making incredible memories together. As a former cabin owner, you'll \
really appreciate the care we put into Aska Escape Lodge.

Regarding your daughter's dog — absolutely, we welcome well-behaved pets! \
There is a one-time pet fee of $75, and we just ask that furry guests stay \
off the furniture. The cabin has a lovely fenced area perfect for a morning \
stroll with your little one.

Here is your personalized quote:

Aska Escape Lodge (3 bedrooms) — 5 nights over Thanksgiving
  Base Rent:       $1,695.00
  Cleaning & Fees: $250.00
  Taxes:           $252.85
  Total:           $2,197.85

The lodge features a wraparound deck with stunning Aska Adventure Area views, \
a hot tub, full kitchen perfect for Thanksgiving dinner, and a cozy stone \
fireplace — everything you need for a holiday to remember.

This quote is valid for 24 hours. To lock in your Thanksgiving dates, simply \
reply to this email or call us at (706) 258-3900. Holiday weeks fill up fast \
and we'd hate for you to miss out!

We truly look forward to welcoming you and your daughters (and the pup!) to \
Blue Ridge.

Warm regards,
Cabin Rentals of Georgia Reservations Team\
"""


# ── Prompt Builders ──────────────────────────────────────────────────────

def _build_user_prompt_from_strings(
    lead_name: str,
    guest_message: str,
    option_summaries: List[Dict[str, Any]],
) -> str:
    """Construct the user-side prompt from plain strings and pricing data."""
    lines = [
        "GUEST INQUIRY:",
        f"  Name: {lead_name}",
        f"  Message: {guest_message or '(no message provided)'}",
        "",
        "PROPERTY OPTIONS WITH PRICING:",
    ]

    for i, opt in enumerate(option_summaries, 1):
        lines.append(f"  Option {i}: {opt['property_name']} ({opt['bedrooms']} bedrooms)")
        lines.append(f"    Dates: {opt['check_in_date']} to {opt['check_out_date']} ({opt['nights']} nights)")
        lines.append(f"    Base Rent: ${opt['base_rent']}")
        lines.append(f"    Cleaning & Fees: ${opt['fees']}")
        lines.append(f"    Taxes: ${opt['taxes']}")
        lines.append(f"    TOTAL: ${opt['total_price']}")
        if opt.get("booking_link"):
            lines.append(f"    Booking Link: {opt['booking_link']}")
        lines.append("")

    lines.append("Write the personalized sales email now.")
    return "\n".join(lines)


def _build_few_shot_messages(user_prompt: str) -> List[Dict[str, str]]:
    """Build the full 4-message few-shot conversation for the LLM."""
    return [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": FEW_SHOT_GUEST_INQUIRY},
        {"role": "assistant", "content": FEW_SHOT_STAFF_RESPONSE},
        {"role": "user",      "content": user_prompt},
    ]


def _build_fallback_email(
    lead_name: str,
    option_summaries: List[Dict[str, Any]],
) -> str:
    """Safe default email when all LLMs fail (Rule 5: no silent failures)."""
    guest = lead_name or "Valued Guest"
    lines = [
        f"Dear {guest},",
        "",
        "Thank you for your interest in Cabin Rentals of Georgia! We've put together",
        "a personalized quote for your upcoming mountain getaway.",
        "",
    ]

    for i, opt in enumerate(option_summaries, 1):
        lines.append(
            f"Option {i}: {opt['property_name']} ({opt['bedrooms']}BR) — "
            f"{opt['nights']} nights, ${opt['total_price']} total"
        )

    lines.extend([
        "",
        "This quote is valid for 24 hours. To secure your dates, please reply to",
        "this email or call us at (706) 258-3900.",
        "",
        "We look forward to hosting you in the beautiful Blue Ridge mountains!",
        "",
        "Warm regards,",
        "Cabin Rentals of Georgia Reservations Team",
    ])
    return "\n".join(lines)


# ── Public API ───────────────────────────────────────────────────────────

async def draft_quote_email(
    lead_name: str,
    guest_message: str,
    quote_options_data: List[Dict[str, Any]],
) -> tuple[str, str]:
    """
    Draft a hyper-personalized sales email using few-shot prompting.

    Args:
        lead_name:         Guest's name (e.g., "David Mitchell")
        guest_message:     The guest's original inquiry text
        quote_options_data: List of dicts with property_name, bedrooms,
                            check_in_date, check_out_date, nights,
                            base_rent, fees, taxes, total_price, booking_link

    Returns:
        (email_body, model_used) tuple.
        Falls back to a template email if all LLM providers fail.
    """
    user_prompt = _build_user_prompt_from_strings(
        lead_name, guest_message, quote_options_data,
    )
    messages = _build_few_shot_messages(user_prompt)

    # HYDRA -> SWARM -> OpenAI fallback chain (DEFCON 3: 70B primary)
    if settings.use_local_llm:
        for model_name in [settings.ollama_deep_model, settings.ollama_fast_model]:
            try:
                result = await _ollama_chat(model_name, messages)
                if result and len(result) > 50:
                    logger.info("sales_email_generated", model=model_name, length=len(result))
                    return result, model_name
            except Exception as e:
                logger.warning("ollama_sales_attempt_failed", model=model_name, error=str(e))

    if settings.openai_api_key:
        try:
            result = await _openai_chat(messages)
            if result and len(result) > 50:
                logger.info("sales_email_generated", model=settings.openai_model, length=len(result))
                return result, settings.openai_model
        except Exception as e:
            logger.warning("openai_sales_failed", error=str(e))

    logger.error(
        "all_llm_providers_failed_for_sales_email",
        lead_name=lead_name,
        fallback="template",
    )
    return _build_fallback_email(lead_name, quote_options_data), "fallback_template"


async def generate_quote_email(
    lead,
    option_summaries: List[Dict[str, Any]],
) -> tuple[str, str]:
    """
    Backward-compatible wrapper that accepts a Lead ORM object.
    Delegates to draft_quote_email() with the few-shot pipeline.
    """
    return await draft_quote_email(
        lead_name=lead.guest_name or "Valued Guest",
        guest_message=lead.guest_message or "",
        quote_options_data=option_summaries,
    )


# ── DeepSeek R1 Think-Tag Stripping ──────────────────────────────────────

def _strip_think_tags(text: str) -> str:
    """Remove DeepSeek R1's internal reasoning wrapped in <think>...</think>."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# ── LLM Clients (few-shot aware — accept full message lists) ────────────

async def _ollama_chat(model: str, messages: List[Dict[str, str]]) -> Optional[str]:
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 2048},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("message", {}).get("content", "").strip()
        return _strip_think_tags(raw)


async def _openai_chat(messages: List[Dict[str, str]]) -> Optional[str]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 2048,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
