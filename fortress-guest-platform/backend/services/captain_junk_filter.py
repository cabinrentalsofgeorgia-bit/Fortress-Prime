"""
Captain — junk / bulk-mail filter.

Three-tier classifier run BEFORE the privilege filter in the Captain
intake pipeline. Keeps newsletters, transactional notifications, and
marketing blasts out of the training capture flywheel.

Tier 1 — header inspection (deterministic, ~0ms)
  RFC-standard bulk-mail headers are a reliable signal: List-Unsubscribe,
  Precedence: bulk|list|junk, Auto-Submitted: auto-generated, and the
  ESP campaign tags (X-Campaign-Id, X-Mailchimp-Campaign-Id,
  X-Mailgun-Tag) between them catch the large majority of inbound bulk.

Tier 2 — sender heuristics (deterministic, ~0ms)
  Structured local-parts (noreply, newsletter, bounce, mailer-daemon)
  and ESP relay domains in the From address (amazonses, mailgun, sendgrid,
  postmark) — personal/legal mail never originates from these.

Tier 3 — LLM triage (Ollama, ~500ms, fails OPEN)
  Only reached for mail that slipped both deterministic tiers. Uses a
  small fast model (qwen2.5:0.5b on the existing TASK_CLASSIFIER_MODEL
  / OLLAMA_BASE_URL) with a 500ms timeout. Any failure — timeout, non-
  200, parse error — returns is_junk=False so legitimate mail is never
  dropped when the LLM tier is unhealthy.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from backend.core.config import settings
from backend.services.captain_multi_mailbox import FetchedEmail

logger = structlog.get_logger(service="captain_junk_filter")


# ──────────────────────────────────────────────────────────────────────────────
# Public types
# ──────────────────────────────────────────────────────────────────────────────

VALID_CATEGORIES: frozenset[str] = frozenset({
    "legal", "business", "marketing", "receipt",
    "newsletter", "notification", "personal", "unknown",
})


@dataclass(frozen=True)
class JunkDecision:
    is_junk: bool
    category: str
    reason: str
    confidence: float


# ──────────────────────────────────────────────────────────────────────────────
# Tier 1 — headers
# ──────────────────────────────────────────────────────────────────────────────

# Headers whose mere presence signals bulk/newsletter routing.
_NEWSLETTER_HEADERS: tuple[str, ...] = (
    "list-unsubscribe",
    "list-unsubscribe-post",
)

# Known campaign/ESP tagging headers. Presence => marketing blast.
_MARKETING_HEADERS: tuple[str, ...] = (
    "x-campaign-id",
    "x-mailchimp-campaign-id",
    "x-mailgun-tag",
)

# Precedence values that indicate bulk delivery per RFC 2076.
_BULK_PRECEDENCE_VALUES: frozenset[str] = frozenset({"bulk", "list", "junk"})


def _check_headers(em: FetchedEmail) -> JunkDecision | None:
    for name in _NEWSLETTER_HEADERS:
        if em.headers_present(name):
            return JunkDecision(
                is_junk=True,
                category="newsletter",
                reason=f"header_{name.replace('-', '_')}",
                confidence=1.0,
            )

    precedence = em.header("precedence").strip().lower()
    if precedence in _BULK_PRECEDENCE_VALUES:
        return JunkDecision(
            is_junk=True,
            category="newsletter",
            reason="header_precedence_bulk",
            confidence=1.0,
        )

    for name in _MARKETING_HEADERS:
        if em.headers_present(name):
            return JunkDecision(
                is_junk=True,
                category="marketing",
                reason=f"header_{name.replace('-', '_')}",
                confidence=1.0,
            )

    auto_submitted = em.header("auto-submitted").strip().lower()
    if auto_submitted and auto_submitted != "no":
        # RFC 3834: values include auto-generated, auto-replied.
        return JunkDecision(
            is_junk=True,
            category="notification",
            reason="header_auto_submitted",
            confidence=1.0,
        )

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Tier 2 — sender heuristics
# ──────────────────────────────────────────────────────────────────────────────

# Match the local-part (left of @). Bounds help avoid catching legitimate
# addresses that happen to contain the pattern as a substring (e.g.
# "newsletters-manager@firm.com").
_NOREPLY_LOCAL_RE = re.compile(
    r"^(?:no[-_.]?reply|donotreply|do[-_.]?not[-_.]?reply)"
    r"(?:[-_.+@]|$)",
    re.IGNORECASE,
)
_NEWSLETTER_LOCAL_RE = re.compile(
    r"^(?:newsletter|news|updates|digest|announce|announcements)"
    r"(?:[-_.+@]|$)",
    re.IGNORECASE,
)
_BOUNCE_LOCAL_RE = re.compile(
    r"^(?:bounce(?:s)?|mailer[-_.]?daemon|postmaster)"
    r"(?:[-_.+@]|$)",
    re.IGNORECASE,
)

# ESP relay domains. If the FROM sender sits on one of these it's a
# marketing/transactional blast — legitimate senders use their own
# domain even when relaying through these services (via Reply-To).
_ESP_RELAY_DOMAINS: frozenset[str] = frozenset({
    "amazonses.com",
    "mailgun.net",
    "sendgrid.net",
    "sendgrid.com",
    "postmarkapp.com",
    "mcsv.net",            # Mailchimp
    "rsgsv.net",           # Mailchimp
    "mailerlite.com",
    "constantcontact.com",
})


def _check_sender(em: FetchedEmail) -> JunkDecision | None:
    sender = em.sender_email or ""
    if "@" not in sender:
        return None
    local, _, domain = sender.partition("@")
    local = local.strip()
    domain = domain.strip().lower()

    if _BOUNCE_LOCAL_RE.match(local):
        return JunkDecision(
            is_junk=True,
            category="notification",
            reason="sender_bounce",
            confidence=1.0,
        )
    if _NOREPLY_LOCAL_RE.match(local):
        return JunkDecision(
            is_junk=True,
            category="notification",
            reason="sender_noreply",
            confidence=0.95,
        )
    if _NEWSLETTER_LOCAL_RE.match(local):
        return JunkDecision(
            is_junk=True,
            category="newsletter",
            reason="sender_newsletter_localpart",
            confidence=0.9,
        )
    if domain in _ESP_RELAY_DOMAINS:
        return JunkDecision(
            is_junk=True,
            category="marketing",
            reason="sender_esp_relay_domain",
            confidence=0.9,
        )
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Tier 3 — LLM triage (fail-open)
# ──────────────────────────────────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """You are a mail triage classifier for Cabin Rentals of Georgia.

Read the email and classify it. Respond ONLY with valid JSON — no markdown, no explanation:
{
  "category": "legal|business|marketing|receipt|newsletter|notification|personal|unknown",
  "is_junk": true|false,
  "confidence": 0.0-1.0,
  "reason": "short phrase, e.g. marketing_body_copy, personal_thread_reply"
}

is_junk=true ONLY for: newsletter, marketing, notification, receipt (low-value bulk).
is_junk=false for: legal correspondence, business inquiries, personal messages, anything that needs a human.
When unsure, prefer is_junk=false — a false negative (junk gets through) is cheaper than a false positive (important mail dropped).
"""

_LLM_TIMEOUT_S = 0.5


def _ollama_endpoint() -> str:
    """Resolve the Ollama base URL. TASK_CLASSIFIER_OLLAMA_URL wins."""
    override = os.environ.get("TASK_CLASSIFIER_OLLAMA_URL", "").strip()
    if override:
        return override.rstrip("/")
    return (settings.ollama_base_url or "").rstrip("/")


def _ollama_model() -> str:
    override = os.environ.get("TASK_CLASSIFIER_MODEL", "").strip()
    if override:
        return override
    # Smallest fast model available on the task-classifier stack.
    return "qwen2.5:0.5b"


async def _check_llm(em: FetchedEmail) -> JunkDecision:
    base_url = _ollama_endpoint()
    if not base_url:
        return JunkDecision(
            is_junk=False, category="unknown",
            reason="llm_unavailable", confidence=0.0,
        )

    prompt = (
        f"From: {em.sender_email}\n"
        f"Subject: {em.subject}\n\n"
        f"{em.body[:2000]}"
    )
    payload = {
        "model": _ollama_model(),
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 128},
    }

    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT_S) as client:
            resp = await client.post(f"{base_url}/api/chat", json=payload)
        if resp.status_code != 200:
            return JunkDecision(
                is_junk=False, category="unknown",
                reason=f"llm_http_{resp.status_code}", confidence=0.0,
            )
        content = (resp.json().get("message") or {}).get("content", "").strip()
    except (httpx.TimeoutException, asyncio.TimeoutError):
        return JunkDecision(
            is_junk=False, category="unknown",
            reason="llm_timeout", confidence=0.0,
        )
    except Exception as exc:
        logger.debug("captain_junk_llm_error", error=str(exc)[:120])
        return JunkDecision(
            is_junk=False, category="unknown",
            reason="llm_error", confidence=0.0,
        )

    parsed = _parse_llm_json(content)
    if parsed is None:
        return JunkDecision(
            is_junk=False, category="unknown",
            reason="llm_parse_failed", confidence=0.0,
        )
    category = str(parsed.get("category") or "unknown").strip().lower()
    if category not in VALID_CATEGORIES:
        category = "unknown"
    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    is_junk = bool(parsed.get("is_junk"))
    reason_text = str(parsed.get("reason") or "")[:64] or "llm_classified"
    return JunkDecision(
        is_junk=is_junk,
        category=category,
        reason=f"llm_{reason_text}",
        confidence=confidence,
    )


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if text.startswith("```"):
        lines = [ln for ln in text.split("\n") if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        loaded = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

async def classify_junk(em: FetchedEmail) -> JunkDecision:
    """
    Classify an inbound email. Short-circuits at the first tier that
    returns a verdict so the ordering (headers → sender → LLM) is
    observable by tests and operator dashboards.
    """
    tier1 = _check_headers(em)
    if tier1 is not None:
        return tier1
    tier2 = _check_sender(em)
    if tier2 is not None:
        return tier2
    return await _check_llm(em)
