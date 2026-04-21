#!/usr/bin/env python3
"""
probe_council_health.py — Reusable health-check for the 9-seat concierge council.

For each seat, fires a 1-token test against the primary provider + fallback chain.
Reports which seats are LIVE (primary responds), FALLBACK (degraded but functional),
or BLANK (all fail).

Usage:
  cd ~/Fortress-Prime && fortress-guest-platform/.uv-venv/bin/python3 tools/probe_council_health.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "fortress-guest-platform"))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / "fortress-guest-platform" / ".env", override=False)
    load_dotenv(Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass

from backend.services.crog_concierge_engine import (
    _call_llm,
    SEAT_ROUTING, SEAT_RETRY_FALLBACKS,
    ANTHROPIC_PROXY, ANTHROPIC_MODEL, FRONTIER_GATEWAY_API_KEY,
    GEMINI_BASE_URL, GEMINI_MODEL,
    XAI_BASE_URL, XAI_MODEL, XAI_MODEL_FLAGSHIP,
    HYDRA_32B_URL, HYDRA_MODEL_32B,
    HYDRA_120B_URL, HYDRA_MODEL_120B,
    VLLM_120B_URL, VLLM_MODEL_120B,
    SWARM_URL, SWARM_MODEL,
    ALLOW_CLOUD_LLM,
)

_PROVIDER_ENDPOINTS = {
    "ANTHROPIC":    (ANTHROPIC_PROXY,  ANTHROPIC_MODEL,     FRONTIER_GATEWAY_API_KEY),
    "GEMINI":       (GEMINI_BASE_URL,   GEMINI_MODEL,        FRONTIER_GATEWAY_API_KEY),
    "XAI":          (XAI_BASE_URL,      XAI_MODEL,           FRONTIER_GATEWAY_API_KEY),
    "XAI_FLAGSHIP": (XAI_BASE_URL,      XAI_MODEL_FLAGSHIP,  FRONTIER_GATEWAY_API_KEY),
    "HYDRA_32B":    (HYDRA_32B_URL,     HYDRA_MODEL_32B,     ""),
    "HYDRA_120B":   (HYDRA_120B_URL,    HYDRA_MODEL_120B,    ""),
    "VLLM_120B":    (VLLM_120B_URL,     VLLM_MODEL_120B,     ""),
    "SWARM":        (SWARM_URL,         SWARM_MODEL,         ""),
}

PROBE_TIMEOUT = 45   # Gemini 2.5 Pro (thinking model) needs ~20-30s at this token budget
PROBE_MAX_TOKENS = 256  # must exceed Gemini's thinking token consumption (~130 reasoning + text


async def _probe_provider(provider: str) -> tuple[str, str]:
    if provider not in _PROVIDER_ENDPOINTS:
        return "unknown_provider", ""
    url, model, key = _PROVIDER_ENDPOINTS[provider]
    if not ALLOW_CLOUD_LLM and provider in ("ANTHROPIC", "GEMINI", "XAI", "XAI_FLAGSHIP"):
        return "cloud_disabled", ""
    try:
        text, used = await asyncio.wait_for(
            _call_llm("Reply WORKING.", "Say WORKING.", model=model, base_url=url,
                      api_key=key, temperature=0.35, max_tokens=PROBE_MAX_TOKENS),
            timeout=PROBE_TIMEOUT,
        )
        return ("live" if text.strip() else "empty"), used
    except asyncio.TimeoutError:
        return "timeout", ""
    except Exception as e:
        return f"error:{str(e)[:40]}", ""


async def probe_all() -> None:
    print(f"ALLOW_CLOUD_LLM: {ALLOW_CLOUD_LLM}\n")
    print(f"{'Seat':<6} {'Role':<30} {'Primary':<14} {'Status':<10} {'Model used'}")
    print("-" * 85)

    live = fallback = blank = 0
    for seat_num in sorted(SEAT_ROUTING.keys()):
        routing = SEAT_ROUTING[seat_num]
        primary = routing["provider"]
        role = routing["role"]
        status, used = await _probe_provider(primary)

        if status == "live":
            badge = "LIVE ✓"
            live += 1
        else:
            fallbacks = SEAT_RETRY_FALLBACKS.get(seat_num, [primary, "HYDRA_32B", "SWARM"])
            fb_status, fb_used = "blank", ""
            for fb in fallbacks[1:]:
                fb_st, fb_used = await _probe_provider(fb)
                if fb_st == "live":
                    fb_status = "fallback"
                    used = fb_used
                    break
            if fb_status == "fallback":
                badge = "FALLBACK"
                fallback += 1
            else:
                badge = "BLANK ✗"
                blank += 1

        print(f"  {seat_num:<4} {role:<30} {primary:<14} {badge:<10} {used[:35]}")

    print(f"\nSummary: {live} live, {fallback} fallback, {blank} blank  |  {live + fallback}/9 effective")


if __name__ == "__main__":
    asyncio.run(probe_all())
