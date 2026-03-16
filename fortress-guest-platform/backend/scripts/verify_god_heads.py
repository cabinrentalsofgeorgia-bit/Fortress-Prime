#!/usr/bin/env python3
"""
GOD HEADS VERIFICATION SCRIPT — Fortress Prime Council of Intelligence
======================================================================
Pings every AI inference endpoint in the stack, sends a 1-token probe,
and reports connection status + latency in a formatted terminal report.

Endpoints tested:
  1. SWARM   — qwen2.5:7b via Nginx LB (Captain :80)
  2. HYDRA   — deepseek-r1:70b via Nginx LB (Captain :80)
  3. EMBEDDINGS — nomic-embed-text via Nginx LB (Captain :80)
  4. OPENAI  — gpt-4o via api.openai.com (cloud fallback)

Run:
  cd ~/Fortress-Prime/fortress-guest-platform
  ./venv/bin/python -m backend.scripts.verify_god_heads
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from backend.core.config import settings

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Terminal formatting
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"

PASS = f"{GREEN}■ ONLINE{RESET}"
FAIL = f"{RED}■ OFFLINE{RESET}"
WARN = f"{YELLOW}■ DEGRADED{RESET}"
SKIP = f"{DIM}■ SKIPPED{RESET}"


def banner():
    print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════╗
║          FORTRESS PRIME — GOD HEADS VERIFICATION                ║
║          Council of Intelligence Connection Audit               ║
╚══════════════════════════════════════════════════════════════════╝{RESET}
""")


def section(name: str):
    print(f"\n{BOLD}{'─' * 64}")
    print(f"  {name}")
    print(f"{'─' * 64}{RESET}")


def result_line(label: str, status: str, latency_ms: float = 0, detail: str = ""):
    lat = f"{latency_ms:>7.0f}ms" if latency_ms > 0 else "       -"
    det = f"  {DIM}{detail}{RESET}" if detail else ""
    print(f"  {status}  {lat}  {label}{det}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Model registry — what we're testing
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OLLAMA_BASE = settings.ollama_base_url.rstrip("/")

GOD_HEADS = [
    {
        "name": "SWARM (Fast Inference)",
        "model": settings.ollama_fast_model,
        "base_url": OLLAMA_BASE,
        "type": "ollama",
    },
    {
        "name": "HYDRA (Deep Reasoning)",
        "model": settings.ollama_deep_model,
        "base_url": OLLAMA_BASE,
        "type": "ollama",
    },
    {
        "name": "EMBEDDINGS (nomic-embed-text)",
        "model": "nomic-embed-text",
        "base_url": "http://192.168.0.100",
        "type": "embedding",
    },
    {
        "name": "ANTHROPIC (Claude Opus 4.6)",
        "model": settings.anthropic_model,
        "base_url": "https://api.anthropic.com",
        "type": "anthropic",
    },
    {
        "name": "GEMINI (Google 3.1 Pro)",
        "model": settings.gemini_model,
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "type": "openai_compat",
        "api_key_attr": "gemini_api_key",
    },
    {
        "name": "XAI (Grok 4.1)",
        "model": settings.xai_model,
        "base_url": "https://api.x.ai/v1",
        "type": "openai_compat",
        "api_key_attr": "xai_api_key",
    },
    {
        "name": "OPENAI (GPT-4o)",
        "model": settings.openai_model,
        "base_url": "https://api.openai.com/v1",
        "type": "openai",
    },
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Probe functions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def probe_models_endpoint(client: httpx.AsyncClient, base_url: str) -> list[str]:
    """Hit /api/tags (Ollama) or /v1/models to list loaded models."""
    loaded = []
    for path in ["/api/tags", "/v1/models"]:
        try:
            resp = await client.get(f"{base_url}{path}", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if "models" in data:
                    loaded = [m.get("name") or m.get("id", "") for m in data["models"]]
                elif "data" in data:
                    loaded = [m.get("id", "") for m in data["data"]]
                break
        except Exception:
            continue
    return loaded


async def probe_ollama_chat(
    client: httpx.AsyncClient, base_url: str, model: str
) -> tuple[bool, float, str]:
    """Send a 1-token probe to an Ollama-compatible chat endpoint."""
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Respond with the single word ONLINE"}],
                "stream": False,
                "options": {"num_predict": 10, "temperature": 0.0},
            },
            timeout=120,
        )
        latency = (time.perf_counter() - t0) * 1000
        if resp.status_code == 200:
            content = resp.json().get("message", {}).get("content", "").strip()
            return True, latency, content[:80]
        return False, latency, f"HTTP {resp.status_code}"
    except httpx.ConnectError:
        return False, (time.perf_counter() - t0) * 1000, "Connection refused"
    except httpx.ReadTimeout:
        return False, (time.perf_counter() - t0) * 1000, "Timeout (>120s)"
    except Exception as e:
        return False, (time.perf_counter() - t0) * 1000, str(e)[:80]


async def probe_embedding(
    client: httpx.AsyncClient, base_url: str, model: str
) -> tuple[bool, float, str]:
    """Send a probe to the embedding endpoint."""
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{base_url}/api/embeddings",
            json={"model": model, "prompt": "test"},
            timeout=30,
        )
        latency = (time.perf_counter() - t0) * 1000
        if resp.status_code == 200:
            vec = resp.json().get("embedding", [])
            return True, latency, f"{len(vec)}-dim vector returned"
        return False, latency, f"HTTP {resp.status_code}"
    except httpx.ConnectError:
        return False, (time.perf_counter() - t0) * 1000, "Connection refused"
    except Exception as e:
        return False, (time.perf_counter() - t0) * 1000, str(e)[:80]


async def probe_openai_compat(
    client: httpx.AsyncClient, base_url: str, model: str, api_key: str,
) -> tuple[bool, float, str]:
    """Send a 1-token probe to any OpenAI-compatible endpoint (OpenAI, xAI, Gemini)."""
    if not api_key:
        return False, 0, "No API key configured"

    url = f"{base_url.rstrip('/')}/chat/completions"
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Respond with the single word ONLINE"}],
                "max_tokens": 5,
                "temperature": 0.0,
            },
            timeout=30,
        )
        latency = (time.perf_counter() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            try:
                content = data["choices"][0]["message"]["content"].strip()
            except (KeyError, IndexError, TypeError):
                content = str(data)[:80]
            return True, latency, content[:80]
        elif resp.status_code == 401:
            return False, latency, "Invalid API key"
        elif resp.status_code == 429:
            return False, latency, "Rate limited"
        return False, latency, f"HTTP {resp.status_code}"
    except httpx.ConnectError:
        return False, (time.perf_counter() - t0) * 1000, "Connection refused"
    except Exception as e:
        return False, (time.perf_counter() - t0) * 1000, str(e)[:80]


async def probe_anthropic(
    client: httpx.AsyncClient, model: str,
) -> tuple[bool, float, str]:
    """Send a 1-token probe to the Anthropic Messages API."""
    api_key = settings.anthropic_api_key
    if not api_key:
        return False, 0, "No ANTHROPIC_API_KEY configured"

    t0 = time.perf_counter()
    try:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "Respond with the single word ONLINE"}],
            },
            timeout=30,
        )
        latency = (time.perf_counter() - t0) * 1000
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("content", [{}])[0].get("text", "").strip()
            return True, latency, content[:80]
        elif resp.status_code == 401:
            return False, latency, "Invalid API key"
        elif resp.status_code == 429:
            return False, latency, "Rate limited"
        return False, latency, f"HTTP {resp.status_code}: {resp.text[:100]}"
    except httpx.ConnectError:
        return False, (time.perf_counter() - t0) * 1000, "Connection refused"
    except Exception as e:
        return False, (time.perf_counter() - t0) * 1000, str(e)[:80]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Qdrant probe
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def probe_qdrant(client: httpx.AsyncClient) -> tuple[bool, float, str]:
    qdrant_url = settings.qdrant_url.rstrip("/")
    t0 = time.perf_counter()
    try:
        resp = await client.get(f"{qdrant_url}/collections/fgp_knowledge", timeout=5)
        latency = (time.perf_counter() - t0) * 1000
        if resp.status_code == 200:
            info = resp.json().get("result", {})
            pts = info.get("points_count", 0)
            return True, latency, f"{pts} vectors in fgp_knowledge"
        return False, latency, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, (time.perf_counter() - t0) * 1000, str(e)[:80]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Main
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def main():
    banner()

    online_count = 0
    total_count = 0

    async with httpx.AsyncClient() as client:

        # ── Phase 1: Model Discovery ──
        section("PHASE 1: Model Discovery (Ollama /api/tags)")
        loaded_models = await probe_models_endpoint(client, OLLAMA_BASE)
        if loaded_models:
            print(f"  {GREEN}Found {len(loaded_models)} model(s) loaded:{RESET}")
            for m in loaded_models:
                print(f"    • {m}")
        else:
            print(f"  {RED}No models detected at {OLLAMA_BASE}{RESET}")

        # ── Phase 2: God Head Probes ──
        section("PHASE 2: God Head Inference Probes")

        print(f"\n  {'STATUS':<12} {'LATENCY':>9}  {'ENDPOINT'}")
        print(f"  {'─' * 56}")

        for gh in GOD_HEADS:
            total_count += 1
            name = gh["name"]
            model = gh["model"]
            ghtype = gh["type"]

            if ghtype == "ollama":
                ok, lat, detail = await probe_ollama_chat(client, gh["base_url"], model)
            elif ghtype == "embedding":
                ok, lat, detail = await probe_embedding(client, gh["base_url"], model)
            elif ghtype == "anthropic":
                if not settings.anthropic_api_key:
                    result_line(f"{name}  [{model}]", SKIP, detail="No API key")
                    continue
                ok, lat, detail = await probe_anthropic(client, model)
            elif ghtype == "openai_compat":
                key_attr = gh.get("api_key_attr", "")
                api_key = getattr(settings, key_attr, "") if key_attr else ""
                if not api_key:
                    result_line(f"{name}  [{model}]", SKIP, detail=f"No {key_attr}")
                    continue
                ok, lat, detail = await probe_openai_compat(client, gh["base_url"], model, api_key)
            elif ghtype == "openai":
                if not settings.openai_api_key:
                    result_line(f"{name}  [{model}]", SKIP, detail="No API key")
                    continue
                ok, lat, detail = await probe_openai_compat(
                    client, gh["base_url"], model, settings.openai_api_key,
                )
            else:
                continue

            status = PASS if ok else FAIL
            if ok:
                online_count += 1
            result_line(f"{name}  [{model}]", status, lat, detail)

        # ── Phase 3: Vector Store ──
        section("PHASE 3: Vector Store (Qdrant)")
        total_count += 1
        ok, lat, detail = await probe_qdrant(client)
        status = PASS if ok else FAIL
        if ok:
            online_count += 1
        result_line(f"Qdrant fgp_knowledge  [{settings.qdrant_url}]", status, lat, detail)

    # ── Summary ──
    section("SUMMARY")
    color = GREEN if online_count == total_count else (YELLOW if online_count > 0 else RED)
    print(f"  {color}{BOLD}{online_count}/{total_count} endpoints operational{RESET}")

    def _mask(key: str) -> str:
        return f"***{key[-4:]}" if key else "NOT SET"

    print(f"\n  {DIM}Configuration source:{RESET}")
    print(f"    {'─' * 48}")
    print(f"    {BOLD}Local DGX Cluster{RESET}")
    print(f"      Ollama base:   {OLLAMA_BASE}")
    print(f"      Fast model:    {settings.ollama_fast_model}")
    print(f"      Deep model:    {settings.ollama_deep_model}")
    print(f"      Local LLM:     {settings.use_local_llm}")
    print(f"    {BOLD}The 4 Horsemen (Cloud Council){RESET}")
    print(f"      Anthropic:     {settings.anthropic_model:<30} key={_mask(settings.anthropic_api_key)}")
    print(f"      Gemini:        {settings.gemini_model:<30} key={_mask(settings.gemini_api_key)}")
    print(f"      xAI:           {settings.xai_model:<30} key={_mask(settings.xai_api_key)}")
    print(f"      OpenAI:        {settings.openai_model:<30} key={_mask(settings.openai_api_key)}")
    print(f"    {BOLD}Vector Store{RESET}")
    print(f"      Qdrant:        {settings.qdrant_url}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
