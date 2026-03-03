"""
FORTRESS PRIME — Central Configuration (The Constitution's Registry)
=====================================================================
All shared constants, blocklists, and cluster topology in one place.
Import from here — never hardcode in application scripts.

Governing Documents:
    CONSTITUTION.md  — Sovereign Law (ethical & operational boundaries)
    REQUIREMENTS.md  — Non-negotiable technical specifications
    fortress_atlas.yaml — Division Registry (sector map)

Usage:
    from config import SENDER_BLOCKLIST, DB_HOST, DB_NAME, get_inference_client
"""

import os
import httpx
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

# =============================================================================
# CLUSTER TOPOLOGY (Config-Driven — Constitution Rule IV.4)
# =============================================================================
DB_HOST = os.getenv("DB_HOST", "192.168.0.100")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASS", os.getenv("ADMIN_DB_PASS", ""))
DB_PASSWORD = DB_PASS  # Backward-compatible alias for legacy modules

# Spark Nodes — Management LAN (1G Ethernet)
SPARK_01_IP = os.getenv("SPARK_01_IP", "192.168.0.100")  # Captain — API, Postgres, Qdrant
SPARK_02_IP = os.getenv("SPARK_02_IP", "192.168.0.104")  # Muscle  — Mining, Vision
SPARK_03_IP = os.getenv("SPARK_03_IP", "192.168.0.105")  # Ocular  — Vision, Swarm Worker
SPARK_04_IP = os.getenv("SPARK_04_IP", "192.168.0.106")  # Sovereign — Swarm Worker

# Synology NAS — persistent storage, backups
NAS_IP = os.getenv("NAS_IP", "192.168.0.113")

# IPS Penguin POP3 — CROG company email accounts
IPS_POP3_SERVER = os.getenv("IPS_POP3_SERVER", "")
IPS_POP3_PORT = int(os.getenv("IPS_POP3_PORT", "995"))

# Fabric LAN (200G RoCEv2 NDR, MTU 9000) — compute-path only
FABRIC_NODES = {
    "captain":   {"mgmt": SPARK_01_IP, "fabric": os.getenv("FABRIC_CAPTAIN", "10.10.10.2")},
    "muscle":    {"mgmt": SPARK_02_IP, "fabric": os.getenv("FABRIC_MUSCLE", "10.10.10.1")},
    "ocular":    {"mgmt": SPARK_03_IP, "fabric": os.getenv("FABRIC_OCULAR", "10.10.10.3")},
    "sovereign": {"mgmt": SPARK_04_IP, "fabric": os.getenv("FABRIC_SOVEREIGN", "10.10.10.4")},
}

# =============================================================================
# DEFCON MODE — Tri-Mode Architecture (Constitution Amendment IV)
# =============================================================================
# SWARM     = DEFCON 5 (Production) — NIM fast-lane inference via Nginx LB
# HYDRA     = DEFCON 3 (Assault)    — NIM deep-reasoning lane
# TITAN     = DEFCON 1 (Strategic)  — highest-depth sovereign reasoning lane
# ARCHITECT = Planning mode         — Gemini 2.5 Pro via Google AI Studio
FORTRESS_DEFCON = os.getenv("FORTRESS_DEFCON", "SWARM")

# Inference endpoints per mode
SWARM_ENDPOINT = f"http://{SPARK_01_IP}/v1"
HYDRA_ENDPOINT = f"http://{SPARK_01_IP}/hydra/v1"  # Via Nginx LB /hydra/ upstream (600s timeout)
HYDRA_ENDPOINTS = [  # Direct access to all HYDRA worker nodes (bypasses LB)
    f"http://{SPARK_01_IP}:11434/v1",
    f"http://{SPARK_02_IP}:11434/v1",
    f"http://{SPARK_03_IP}:11434/v1",
    f"http://{SPARK_04_IP}:11434/v1",
]
TITAN_ENDPOINT = f"http://{FABRIC_NODES['captain']['fabric']}:8080/v1"
ARCHITECT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/"
GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")

# GODHEAD: OpenAI GPT-4o (cloud reasoning — non-sensitive payloads ONLY)
OPENAI_ENDPOINT = "https://api.openai.com/v1"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
ALLOW_CLOUD_LLM = os.getenv("ALLOW_CLOUD_LLM", "false").lower() == "true"

# Nginx load balancer (Captain) — single entry point for SWARM/HYDRA traffic
NGINX_LB_URL = f"http://{SPARK_01_IP}"

# Model assignments per mode
SWARM_MODEL = os.getenv("SWARM_MODEL", "qwen2.5:7b")
HYDRA_MODEL = os.getenv("HYDRA_MODEL", "deepseek-r1:70b")
TITAN_MODEL = os.getenv("TITAN_MODEL", "deepseek-r1")
ARCHITECT_MODEL = os.getenv("ARCHITECT_MODEL", "gemini-2.5-pro")

# HYDRA runtime notes:
# This stack is governed as NIM-first. Any non-NIM fallback must be explicitly approved
# and documented in governance policy before use in production.
NGC_API_KEY = os.getenv("NGC_API_KEY", "")

# =============================================================================
# DIVISION 1 — IoT / Digital Twin Bridge (Z-Wave Mesh)
# =============================================================================
IOT_BRIDGE_MODE = os.getenv("IOT_BRIDGE_MODE", "simulate")      # "live" or "simulate"
MQTT_BROKER_URL = os.getenv("MQTT_BROKER_URL", "192.168.0.50")   # Z-Wave hub MQTT broker
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
IOT_SIMULATE_INTERVAL = int(os.getenv("IOT_SIMULATE_INTERVAL", "30"))  # seconds between mock events

# =============================================================================
# STRANGLER FIG — Feature Flags (REQUIREMENTS.md Section 3.2)
# =============================================================================
# When True, traffic routes to the new Fortress agent instead of legacy Streamline.
# Set to True ONLY after the new agent passes 2-week parallel validation.
FEATURE_FLAGS = {
    "pricing":       os.getenv("FF_PRICING", "false").lower() == "true",
    "availability":  os.getenv("FF_AVAILABILITY", "false").lower() == "true",
    "guest_comms":   os.getenv("FF_GUEST_COMMS", "false").lower() == "true",
    "owner_reports": os.getenv("FF_OWNER_REPORTS", "false").lower() == "true",
}

# =============================================================================
# SENDER BLOCKLIST — The Gate (27 Identified Spam Sources)
# =============================================================================
# These senders have been verified as pure noise through forensic audit of
# 156,946 emails. They produce zero actionable intelligence and contaminate
# downstream tables (sales_intel, guest_leads, market_intel).
#
# Total blocked: ~43,938 emails across 27 sender patterns.
# Matching is case-insensitive and uses substring matching on the sender field.

SENDER_BLOCKLIST = [
    # --- High-volume automated receipts / notifications ---
    "noreply@mail.authorize.net",          # 12,048 — duplicate merchant receipts
    "mailer-daemon@ips201.securednshost.com",  # 7,421 — bounce-backs
    "newsletter@theepochtimes.com",        # 6,048 — news spam
    "notify@ringcentral.com",              # 5,896 — phone notifications
    "adwords-noreply@google.com",          # 2,258 — AdWords automated rules

    # --- Social media noise ---
    "info@twitter.com",                    # 1,577 — X/Twitter notifications
    "notify@twitter.com",                  # (included in 1,577 above)

    # --- USPS digests (both capitalizations) ---
    "uspsinformeddelivery",                # 1,185 — USPS mail digests (substring match)

    # --- Retail / promotions ---
    "costco@digital.costco.com",           # 889 — promotions
    "us.travelzoo.com",                    # 842 — travel deals (substring match)
    "nobody@e.feedspot.com",               # 819 — blog digest
    "alert@pollen.com",                    # 646 — allergy alerts
    "help@walmart.com",                    # 552 — order confirmations
    "walmartcustomerexperience",           # 169 — surveys (substring match)
    "order.homedepot.com",                 # 391 — Home Depot receipts (substring match)

    # --- Smart home / IoT ---
    "mytotalconnectcomfort@alarmnet.com",  # 464 — thermostat alerts
    "noreply@august.com",                  # 384 — smart lock alerts
    "sns@synology.com",                    # 82  — NAS notifications

    # --- Real estate spam (not actionable intel) ---
    "tlgkw@buyinfla.com",                 # 444 — Florida RE spam
    "recommendations@mail.zillow.com",     # 425 — Zillow recs (not property data)

    # --- Bill pay / telecom ---
    "tdscustomerserviceepay@tdstelecom.com",  # 301 — telecom bills
    "billpay@paymentus.com",               # 207 — bill pay notifications
    "discover@services.discover.com",      # 254 — credit card notifications

    # --- Newsletters / political ---
    "newsletter@zerohedge.com",            # 283 — news
    "noreply@sharylattkisson.com",         # 82  — political newsletter

    # --- Account security / medical ---
    "no-reply@accounts.google.com",        # 277 — security alerts
    "noreply@nextgen.com",                 # 76  — medical portal
]

# Pre-compute a lowercase set for O(1) substring matching
_BLOCKLIST_LOWER = [s.lower() for s in SENDER_BLOCKLIST]


def is_sender_blocked(sender: str) -> bool:
    """
    Check if a sender matches the blocklist (case-insensitive substring match).

    Args:
        sender: The email sender string (may include display name + address).

    Returns:
        True if the sender should be blocked.
    """
    if not sender:
        return False
    sender_lower = sender.lower()
    return any(blocked in sender_lower for blocked in _BLOCKLIST_LOWER)


# =============================================================================
# INFERENCE CLIENT FACTORY (Constitution Article II / REQUIREMENTS Section 2.2)
# =============================================================================

MODE_TIMEOUTS = {
    "SWARM": 60,
    "HYDRA": 180,
    "TITAN": 600,
    "ARCHITECT": 120,
    "GODHEAD": 300,
}


def get_inference_client(mode: str = None, timeout: int = None) -> tuple:
    """
    Return (OpenAI_client, model_name) for the given DEFCON mode.

    Uses FORTRESS_DEFCON env var if mode is not specified.
    Respects the Tri-Mode routing rules from Constitution Amendment IV.

    WARNING: The ARCHITECT and GODHEAD paths (Gemini / OpenAI) MUST NOT
    receive PII, financial, or legal payloads (Constitution Article I, Section 1.1).

    Args:
        mode: One of "SWARM", "HYDRA", "TITAN", "ARCHITECT", "GODHEAD".
              Defaults to FORTRESS_DEFCON.
        timeout: Override timeout in seconds. If None, uses MODE_TIMEOUTS default
                 for the selected mode. Handles cold-start scenarios for HYDRA/TITAN.

    Returns:
        Tuple of (OpenAI client, model name string).
    """
    from openai import OpenAI

    mode = (mode or FORTRESS_DEFCON).upper()
    effective_timeout = httpx.Timeout(
        timeout or MODE_TIMEOUTS.get(mode, 60),
        connect=10.0,
    )

    if mode == "TITAN":
        return OpenAI(base_url=TITAN_ENDPOINT, api_key="not-needed", timeout=effective_timeout), TITAN_MODEL
    elif mode == "HYDRA":
        return OpenAI(base_url=HYDRA_ENDPOINT, api_key="not-needed", timeout=effective_timeout), HYDRA_MODEL
    elif mode == "ARCHITECT":
        if not ALLOW_CLOUD_LLM:
            raise RuntimeError("ARCHITECT mode blocked: set ALLOW_CLOUD_LLM=true for approved non-sensitive workloads.")
        if not GOOGLE_AI_API_KEY:
            raise RuntimeError(
                "ARCHITECT mode requires GOOGLE_AI_API_KEY in .env"
            )
        return OpenAI(
            base_url=ARCHITECT_ENDPOINT,
            api_key=GOOGLE_AI_API_KEY,
            timeout=effective_timeout,
        ), ARCHITECT_MODEL
    elif mode == "GODHEAD":
        if not ALLOW_CLOUD_LLM:
            raise RuntimeError("GODHEAD mode blocked: set ALLOW_CLOUD_LLM=true for approved non-sensitive workloads.")
        if not OPENAI_API_KEY:
            raise RuntimeError(
                "GODHEAD mode requires OPENAI_API_KEY in .env"
            )
        return OpenAI(
            base_url=OPENAI_ENDPOINT,
            api_key=OPENAI_API_KEY,
            timeout=effective_timeout,
        ), OPENAI_MODEL
    else:
        # Default: SWARM (production)
        return OpenAI(base_url=SWARM_ENDPOINT, api_key="not-needed", timeout=effective_timeout), SWARM_MODEL


# =============================================================================
# INFERENCE URL HELPERS (Fortress Prime Architecture)
# =============================================================================

def get_inference_url() -> str:
    """
    Return the correct LLM inference URL based on DEFCON mode.

    - SWARM: Through Nginx LB on management network (Captain)
    - TITAN: Direct fabric inference endpoint
    """
    if FORTRESS_DEFCON == "TITAN":
        return f"http://{FABRIC_NODES['captain']['fabric']}:8080/v1/chat/completions"
    return f"http://{SPARK_01_IP}/v1/chat/completions"


def get_embeddings_url() -> str:
    """Return the embeddings URL (through Nginx LB)."""
    return f"http://{SPARK_01_IP}/api/embeddings"


def get_inference_client_simple():
    """
    Return a configured OpenAI client for the current DEFCON mode.
    Use get_inference_client(mode) for mode override or (client, model) tuple.
    """
    from openai import OpenAI

    if FORTRESS_DEFCON == "TITAN":
        return OpenAI(base_url=f"http://{FABRIC_NODES['captain']['fabric']}:8080/v1", api_key="not-needed")
    return OpenAI(base_url=f"http://{SPARK_01_IP}/v1", api_key="not-needed")


def get_default_model() -> str:
    """Return the default model name for the current DEFCON mode."""
    if FORTRESS_DEFCON == "TITAN":
        return "deepseek-r1"
    return "qwen2.5:7b"


def get_swarm_node_endpoints() -> list[str]:
    """Return list of all node endpoints for round-robin/health checks."""
    return [f"http://{n['mgmt']}:11434" for n in FABRIC_NODES.values()]


def get_ollama_endpoints() -> list[str]:
    """Backward-compatible alias for legacy callers."""
    return get_swarm_node_endpoints()


# =============================================================================
# CAPTAIN (Sovereign R1) — DeepSeek R1:70b on Spark-02
# =============================================================================

CAPTAIN_URL = HYDRA_ENDPOINT
CAPTAIN_MODEL = HYDRA_MODEL
CAPTAIN_GENERATE_URL = f"http://{SPARK_01_IP}:11434/api/generate"

# Legacy aliases used by app.py and older scripts
MUSCLE_NODE = "muscle"
MUSCLE_IP = SPARK_02_IP
WORKER_IP = SPARK_02_IP
MUSCLE_VISION_MODEL = os.getenv("MUSCLE_VISION_MODEL", "llama3.2-vision")
MUSCLE_GENERATE_URL = f"http://{MUSCLE_IP}:11434/api/generate"
MUSCLE_EMBED_MODEL = os.getenv("MUSCLE_EMBED_MODEL", "nomic-embed-text")
MUSCLE_EMBED_URL = f"http://{MUSCLE_IP}:11434/api/embeddings"


def captain_think(prompt: str, system_role: str = "", temperature: float = 0.3) -> str:
    """
    Send a reasoning request to the Captain (DeepSeek R1:70b).

    Used by the Sovereign Orchestrator, Prompt Governor, and Escalation
    Processor for meta-cognition tasks (analyzing failures, rewriting
    prompts, issuing directives).

    Args:
        prompt:       The reasoning prompt
        system_role:  System message defining the LLM's role
        temperature:  Sampling temperature (lower = more deterministic)

    Returns:
        The LLM's response text.
    """
    try:
        from openai import OpenAI

        client = OpenAI(base_url=CAPTAIN_URL, api_key="not-needed")

        messages = []
        if system_role:
            messages.append({"role": "system", "content": system_role})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=CAPTAIN_MODEL,
            messages=messages,
            temperature=temperature,
            max_tokens=4096,
        )

        return response.choices[0].message.content or ""

    except Exception as e:
        import logging
        logging.getLogger("config").error(f"Captain think failed: {e}")
        return f'{{"error": "{str(e)}"}}'


def muscle_embed(text: str) -> list[float] | None:
    """Backward-compatible helper for legacy embedding calls."""
    try:
        import requests

        resp = requests.post(
            MUSCLE_EMBED_URL,
            json={"model": MUSCLE_EMBED_MODEL, "prompt": text},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("embedding")
    except Exception:
        return None


def muscle_see(prompt: str) -> str:
    """Backward-compatible helper for legacy vision/generation calls."""
    try:
        import requests

        resp = requests.post(
            MUSCLE_GENERATE_URL,
            json={"model": MUSCLE_VISION_MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as exc:
        return f'{{"error":"{exc}"}}'
