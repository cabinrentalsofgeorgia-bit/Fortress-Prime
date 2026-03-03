#!/usr/bin/env python3
"""
FORTRESS PRIME — God-Head Router (Autonomous Swarm Directive — Section VI)
==========================================================================
Domain-aware Tier 1 -> Tier 2 escalation module.

When a local OODA agent encounters a task beyond Tier 1 capability (confidence < threshold
or domain-specialized reasoning required), this module:

  1. Sanitizes the context (mandatory, non-bypassable PII/financial/legal stripping)
  2. Selects the appropriate God-Head API based on domain
  3. Calls the external API with timeout and retry logic
  4. Falls back to local HYDRA on failure
  5. Logs every escalation to system_post_mortems

Usage:
    from src.god_head_router import route, sanitize_context

    result = route(
        domain="legal",
        prompt="Analyze this lease clause for regulatory compliance",
        context="The tenant at [property] signed on [date]...",
    )
    print(result["response"])
    print(result["fallback_used"])  # True if HYDRA was used instead
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import psycopg2
import requests
from openai import OpenAI

logger = logging.getLogger("god_head_router")

# ---------------------------------------------------------------------------
# Configuration (all from environment — no hardcoded secrets)
# ---------------------------------------------------------------------------

ALLOW_CLOUD_LLM = os.getenv("ALLOW_CLOUD_LLM", "false").lower() == "true"

GOD_HEAD_REGISTRY: dict[str, dict[str, Any]] = {
    "legal": {
        "provider": "anthropic",
        "base_url": "http://localhost:5100/v1",
        "api_key_env": "ANTHROPIC_API_KEY",
        "model": "claude-opus-4-6",
        "timeout": 120,
    },
    "financial": {
        "provider": "xai",
        "base_url": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "model": "grok-4-0709",
        "timeout": 120,
    },
    "architecture": {
        "provider": "google",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GOOGLE_AI_API_KEY",
        "model": "gemini-2.5-pro",
        "timeout": 60,
    },
    "general": {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "timeout": 60,
    },
}

HYDRA_BASE_URL = os.getenv("HYDRA_FALLBACK_URL", "http://192.168.0.100/hydra/v1")
HYDRA_MODEL = os.getenv("HYDRA_MODEL", "deepseek-r1:70b")
SWARM_BASE_URL = os.getenv("SWARM_FALLBACK_URL", "http://192.168.0.100/v1")
SWARM_MODEL = os.getenv("SWARM_MODEL", "qwen2.5:7b")

HYDRA_TIMEOUT = int(os.getenv("HYDRA_TIMEOUT", "180"))
SWARM_TIMEOUT = int(os.getenv("SWARM_TIMEOUT", "60"))

CONFIDENCE_THRESHOLD = float(os.getenv("GODHEAD_CONFIDENCE_THRESHOLD", "0.6"))

DB_HOST = os.getenv("DB_HOST", "192.168.0.100")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))

# ---------------------------------------------------------------------------
# Sanitization (mandatory, non-bypassable)
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3,4}[-.\s]?\d{4}")
_SHORT_PHONE_RE = re.compile(r"\b\d{3}[-.\s]\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CC_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_LOCAL_IP_RE = re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b")
_CASE_NUMBER_RE = re.compile(r"\b\d{2}-\d{4,6}-[A-Z]{2,5}\b")
_DOLLAR_ACCOUNT_RE = re.compile(
    r"\$[\d,]+\.?\d{0,2}\s*(?:account|acct|invoice|inv|ref|#)\s*[#:]?\s*\S+",
    re.IGNORECASE,
)
_STREET_ADDR_RE = re.compile(
    r"\b\d{1,6}\s+[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3}"
    r"\s+(?:Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Lane|Ln|Way|Court|Ct"
    r"|Boulevard|Blvd|Circle|Cir|Trail|Trl|Place|Pl|Loop)\b\.?",
    re.IGNORECASE,
)

_entity_cache: list[str] = []
_entity_cache_ts: float = 0.0
_ENTITY_CACHE_TTL = float(os.getenv("SANITIZE_CACHE_TTL_SECONDS", "300"))


def _load_entity_blocklist() -> list[str]:
    """
    Pull sensitive entity names from DB tables: guest names from guest_leads,
    property names/addresses from properties (fortress_guest schema).
    Cached for SANITIZE_CACHE_TTL_SECONDS (default 5 min) to avoid per-call DB hits.
    Falls back to SANITIZE_BLOCKLIST env var if DB is unreachable.
    """
    global _entity_cache, _entity_cache_ts

    now = time.time()
    if _entity_cache and (now - _entity_cache_ts) < _ENTITY_CACHE_TTL:
        return _entity_cache

    entities: list[str] = []

    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, database=DB_NAME,
            user=DB_USER, password=DB_PASS, connect_timeout=3,
        )
        cur = conn.cursor()

        cur.execute(
            "SELECT DISTINCT guest_name FROM guest_leads "
            "WHERE guest_name IS NOT NULL AND LENGTH(guest_name) >= 3 LIMIT 500"
        )
        for row in cur.fetchall():
            entities.append(row[0].strip())

        cur.execute(
            "SELECT DISTINCT unnest(cabin_names) AS cabin "
            "FROM guest_leads WHERE cabin_names IS NOT NULL LIMIT 200"
        )
        for row in cur.fetchall():
            cabin = row[0].strip() if row[0] else ""
            if len(cabin) >= 3:
                entities.append(cabin)

        cur.execute(
            "SELECT DISTINCT property_name FROM real_estate_intel "
            "WHERE property_name IS NOT NULL AND LENGTH(property_name) >= 3 LIMIT 200"
        )
        for row in cur.fetchall():
            entities.append(row[0].strip())

        cur.execute(
            "SELECT DISTINCT property_address FROM real_estate_intel "
            "WHERE property_address IS NOT NULL AND LENGTH(property_address) >= 5 LIMIT 200"
        )
        for row in cur.fetchall():
            entities.append(row[0].strip())

        conn.close()
        logger.info(f"Sanitization blocklist loaded: {len(entities)} entities from DB")

    except Exception as exc:
        logger.warning(f"DB entity load failed, using env fallback: {exc}")
        blocklist_raw = os.getenv("SANITIZE_BLOCKLIST", "")
        if blocklist_raw:
            entities = [t.strip() for t in blocklist_raw.split(",") if len(t.strip()) >= 3]

    entities = sorted(set(entities), key=len, reverse=True)
    _entity_cache = entities
    _entity_cache_ts = now
    return entities


def sanitize_context(text: str, dry_run: bool = False) -> str:
    """
    Multi-layer PII/sensitive-data stripping (mandatory, non-bypassable).

    Applied in order:
      1. Regex patterns (emails, phones incl. 7-digit, SSNs, credit cards, local IPs, case numbers)
      2. Dollar amounts near account/invoice identifiers
      3. DB-backed entity blocklist (guest names, property names/addresses) with TTL cache
      4. Static SANITIZE_BLOCKLIST env var fallback

    Args:
        text: Raw context string.
        dry_run: If True, return sanitized text without proceeding to API call.

    Returns:
        Sanitized text with [REDACTED-*] placeholders.
    """
    if not text:
        return text

    result = _EMAIL_RE.sub("[REDACTED-EMAIL]", text)
    result = _SSN_RE.sub("[REDACTED-SSN]", result)
    result = _PHONE_RE.sub("[REDACTED-PHONE]", result)
    result = _SHORT_PHONE_RE.sub("[REDACTED-PHONE]", result)
    result = _CC_RE.sub("[REDACTED-CC]", result)
    result = _LOCAL_IP_RE.sub("[REDACTED-IP]", result)
    result = _CASE_NUMBER_RE.sub("[REDACTED-CASE]", result)
    result = _DOLLAR_ACCOUNT_RE.sub("[REDACTED-AMOUNT-REF]", result)
    result = _STREET_ADDR_RE.sub("[REDACTED-ADDRESS]", result)

    for term in _load_entity_blocklist():
        if term in result or term.lower() in result.lower():
            result = re.sub(re.escape(term), "[REDACTED-ENTITY]", result, flags=re.IGNORECASE)

    return result


# ---------------------------------------------------------------------------
# God-Head selection
# ---------------------------------------------------------------------------

def select_god_head(domain: str) -> dict[str, Any]:
    """
    Return the provider config for a domain. Enforces governance gate.

    Raises:
        RuntimeError: If ALLOW_CLOUD_LLM is not true or domain is unknown.
        RuntimeError: If the required API key env var is empty.
    """
    if not ALLOW_CLOUD_LLM:
        raise RuntimeError(
            "God-Head routing blocked: set ALLOW_CLOUD_LLM=true for approved non-sensitive workloads."
        )

    config = GOD_HEAD_REGISTRY.get(domain)
    if not config:
        raise RuntimeError(
            f"Unknown God-Head domain '{domain}'. Valid: {list(GOD_HEAD_REGISTRY.keys())}"
        )

    api_key = os.getenv(config["api_key_env"], "")
    if config["provider"] != "anthropic" and not api_key:
        raise RuntimeError(
            f"God-Head domain '{domain}' requires {config['api_key_env']} in .env"
        )

    return {**config, "api_key": api_key}


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def _log_escalation(
    domain: str,
    provider: str,
    prompt_hash: str,
    tokens: int,
    fallback_used: bool,
    error: str | None = None,
) -> int:
    """Write escalation audit record to system_post_mortems. Returns row ID or -1."""
    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, database=DB_NAME,
            user=DB_USER, password=DB_PASS, connect_timeout=5,
        )
        cur = conn.cursor()
        severity = "critical" if error else ("warning" if fallback_used else "info")
        summary = (
            f"God-Head escalation: domain={domain}, provider={provider}, "
            f"tokens={tokens}, fallback={fallback_used}"
        )
        if error:
            summary += f", error={error[:200]}"

        cur.execute(
            """INSERT INTO system_post_mortems
               (occurred_at, sector, severity, component, error_summary, status, resolved_by)
               VALUES (NOW(), 'dev', %s, %s, %s, %s, 'god_head_router')
               RETURNING id""",
            (severity, f"god_head/{domain}", summary, "resolved" if not error else "open"),
        )
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else -1
    except Exception as exc:
        logger.error(f"Escalation audit write failed: {exc}")
        return -1
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# Cold-start detection
# ---------------------------------------------------------------------------

def _detect_cold_start(base_url: str, model: str) -> bool:
    """Ping the inference endpoint to check if the model is loaded in VRAM."""
    try:
        r = requests.get(f"{base_url}/models", timeout=3)
        if r.status_code == 200:
            loaded = [m.get("id", "") for m in r.json().get("data", [])]
            return model not in loaded
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# HYDRA fallback (with dynamic timeout)
# ---------------------------------------------------------------------------

def _call_hydra(prompt: str, context: str, temperature: float) -> dict[str, Any]:
    """Fall back to local HYDRA (R1-70B) when God-Head is unreachable."""
    is_cold = _detect_cold_start(HYDRA_BASE_URL, HYDRA_MODEL)
    effective_timeout = HYDRA_TIMEOUT if is_cold else 120
    if is_cold:
        logger.warning(f"HYDRA cold start detected, using {effective_timeout}s timeout")

    try:
        client = OpenAI(
            base_url=HYDRA_BASE_URL,
            api_key="not-needed",
            timeout=httpx.Timeout(effective_timeout, connect=10.0),
        )
        messages = [{"role": "user", "content": f"{prompt}\n\nContext:\n{context}"}]
        resp = client.chat.completions.create(
            model=HYDRA_MODEL,
            messages=messages,
            temperature=temperature,
        )
        content = resp.choices[0].message.content if resp.choices else ""
        tokens = resp.usage.total_tokens if resp.usage else 0
        return {"response": content, "tokens": tokens, "error": None}
    except Exception as exc:
        logger.error(f"HYDRA fallback failed: {exc}")
        return {"response": "", "tokens": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# SWARM fallback (last resort before total failure)
# ---------------------------------------------------------------------------

def _call_swarm(prompt: str, context: str, temperature: float) -> dict[str, Any]:
    """Last-resort fallback to SWARM (qwen2.5:7b) when HYDRA also fails."""
    try:
        client = OpenAI(
            base_url=SWARM_BASE_URL,
            api_key="not-needed",
            timeout=httpx.Timeout(SWARM_TIMEOUT, connect=10.0),
        )
        messages = [{"role": "user", "content": f"{prompt}\n\nContext:\n{context}"}]
        resp = client.chat.completions.create(
            model=SWARM_MODEL,
            messages=messages,
            temperature=temperature,
        )
        content = resp.choices[0].message.content if resp.choices else ""
        tokens = resp.usage.total_tokens if resp.usage else 0
        return {"response": content, "tokens": tokens, "error": None}
    except Exception as exc:
        logger.error(f"SWARM fallback failed: {exc}")
        return {"response": "", "tokens": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# Main routing function
# ---------------------------------------------------------------------------

def route(
    domain: str,
    prompt: str,
    context: str,
    temperature: float = 0.3,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Sanitize context, route to the appropriate God-Head, with retry and fallback.

    Args:
        domain: One of "legal", "financial", "architecture", "general".
        prompt: The task/question (not sanitized — assumed to be agent-generated).
        context: Raw context from Tier 1 (WILL be sanitized before sending).
        temperature: LLM temperature.
        dry_run: If True, return sanitized context without calling any API.

    Returns:
        dict with keys: response, provider, tokens_used, escalation_id, fallback_used,
                        sanitized_context (only if dry_run).
    """
    sanitized = sanitize_context(context)
    prompt_hash = hashlib.sha256(f"{prompt}{sanitized}".encode()).hexdigest()[:16]

    if dry_run:
        return {
            "response": None,
            "provider": None,
            "tokens_used": 0,
            "escalation_id": None,
            "fallback_used": False,
            "sanitized_context": sanitized,
        }

    god_head = select_god_head(domain)
    provider = god_head["provider"]
    timeout = god_head["timeout"]
    max_retries = 2
    fallback_used = False
    response_text = ""
    tokens_used = 0
    error_msg = None

    messages = [{"role": "user", "content": f"{prompt}\n\nContext:\n{sanitized}"}]

    for attempt in range(max_retries):
        try:
            client = OpenAI(
                base_url=god_head["base_url"],
                api_key=god_head["api_key"] or "not-needed",
            )
            resp = client.chat.completions.create(
                model=god_head["model"],
                messages=messages,
                temperature=temperature,
                timeout=timeout,
            )
            response_text = resp.choices[0].message.content if resp.choices else ""
            tokens_used = resp.usage.total_tokens if resp.usage else 0
            error_msg = None
            break

        except Exception as exc:
            exc_str = str(exc)
            logger.warning(
                f"God-Head {provider} attempt {attempt + 1}/{max_retries} failed: {exc_str}"
            )

            if "401" in exc_str or "403" in exc_str:
                error_msg = f"Auth failure ({provider}): {exc_str[:200]}"
                logger.error(error_msg)
                break

            if "429" in exc_str:
                retry_after = 30
                logger.warning(f"Rate limited by {provider}, waiting {retry_after}s")
                time.sleep(retry_after)
                continue

            if attempt < max_retries - 1:
                backoff = 5 * (attempt + 1)
                logger.warning(f"Retrying in {backoff}s...")
                time.sleep(backoff)
            else:
                error_msg = f"God-Head {provider} exhausted retries: {exc_str[:200]}"

    fallback_provider = provider
    if error_msg and "Auth failure" not in (error_msg or ""):
        logger.warning(f"Falling back to local HYDRA for domain={domain}")
        hydra_result = _call_hydra(prompt, sanitized, temperature)
        response_text = hydra_result["response"]
        tokens_used = hydra_result["tokens"]
        fallback_used = True
        fallback_provider = "hydra_fallback"

        if hydra_result["error"]:
            logger.warning(f"HYDRA failed, engaging SWARM last-resort for domain={domain}")
            swarm_result = _call_swarm(prompt, sanitized, temperature)
            response_text = swarm_result["response"]
            tokens_used = swarm_result["tokens"]
            fallback_provider = "swarm_fallback"
            if swarm_result["error"]:
                error_msg = (
                    f"Total cascade failure: God-Head({provider}) -> HYDRA -> SWARM. "
                    f"Last error: {swarm_result['error'][:200]}"
                )
            else:
                error_msg = None

    escalation_id = _log_escalation(
        domain=domain,
        provider=fallback_provider if fallback_used else provider,
        prompt_hash=prompt_hash,
        tokens=tokens_used,
        fallback_used=fallback_used,
        error=error_msg,
    )

    return {
        "response": response_text,
        "provider": fallback_provider if fallback_used else provider,
        "tokens_used": tokens_used,
        "escalation_id": escalation_id,
        "fallback_used": fallback_used,
    }


def should_escalate(domain: str, confidence: float) -> bool:
    """Check if a Tier 1 agent should escalate to a God-Head based on confidence."""
    if domain in GOD_HEAD_REGISTRY and confidence < CONFIDENCE_THRESHOLD:
        return True
    return False
