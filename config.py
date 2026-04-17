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

# Spark Nodes — Management LAN (1G Ethernet)
SPARK_01_IP = os.getenv("SPARK_01_IP", "192.168.0.100")  # Captain — API, Postgres, Qdrant
SPARK_02_IP = os.getenv("SPARK_02_IP", "192.168.0.104")  # Muscle  — Mining, Vision
SPARK_03_IP = os.getenv("SPARK_03_IP", "192.168.0.107")  # Ocular  — Vision, Swarm Worker
SPARK_04_IP = os.getenv("SPARK_04_IP", "192.168.0.108")  # Sovereign — Swarm Worker

# Fabric LAN (200G RoCEv2 NDR, MTU 9000) — compute-path only
FABRIC_NODES = {
    "captain":   {"mgmt": SPARK_01_IP, "fabric": os.getenv("FABRIC_CAPTAIN", "10.101.1.2")},
    "muscle":    {"mgmt": SPARK_02_IP, "fabric": os.getenv("FABRIC_MUSCLE", "10.101.1.1")},
    "ocular":    {"mgmt": SPARK_03_IP, "fabric": os.getenv("FABRIC_OCULAR", "10.10.10.3")},
    "sovereign": {"mgmt": SPARK_04_IP, "fabric": os.getenv("FABRIC_SOVEREIGN", "10.10.10.4")},
}

# =============================================================================
# DEFCON MODE — Dual-Mode Architecture (Constitution Amendment I & II)
# =============================================================================
# SWARM     = DEFCON 5 (Production) — Ollama via Nginx LB
# TITAN     = DEFCON 1 (Strategic)  — DeepSeek-R1-671B via llama.cpp RPC
# ARCHITECT = Planning mode         — Gemini 3 Pro via Google AI Studio
FORTRESS_DEFCON = os.getenv("FORTRESS_DEFCON", "SWARM")

# Inference endpoints per mode
SWARM_ENDPOINT = f"http://{SPARK_01_IP}/v1"
TITAN_ENDPOINT = f"http://{FABRIC_NODES['captain']['fabric']}:8080/v1"
ARCHITECT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/"
GOOGLE_AI_API_KEY = os.getenv("GOOGLE_AI_API_KEY", "")

# Model assignments per mode
SWARM_MODEL = os.getenv("SWARM_MODEL", "qwen2.5:7b")
TITAN_MODEL = os.getenv("TITAN_MODEL", "deepseek-r1")
ARCHITECT_MODEL = os.getenv("ARCHITECT_MODEL", "gemini-2.5-pro")

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

def get_inference_client(mode: str = None) -> tuple:
    """
    Return (OpenAI_client, model_name) for the given DEFCON mode.

    Uses FORTRESS_DEFCON env var if mode is not specified.
    Respects the Dual-Brain routing rules from REQUIREMENTS.md Section 2.2.

    WARNING: The ARCHITECT path (Gemini) MUST NOT receive PII, financial,
    or legal payloads (Constitution Article I, Section 1.1).

    Args:
        mode: One of "SWARM", "TITAN", "ARCHITECT". Defaults to FORTRESS_DEFCON.

    Returns:
        Tuple of (OpenAI client, model name string).
    """
    from openai import OpenAI

    mode = (mode or FORTRESS_DEFCON).upper()

    if mode == "TITAN":
        return OpenAI(base_url=TITAN_ENDPOINT, api_key="not-needed"), TITAN_MODEL
    elif mode == "ARCHITECT":
        if not GOOGLE_AI_API_KEY:
            raise RuntimeError(
                "ARCHITECT mode requires GOOGLE_AI_API_KEY in .env"
            )
        return OpenAI(
            base_url=ARCHITECT_ENDPOINT,
            api_key=GOOGLE_AI_API_KEY,
        ), ARCHITECT_MODEL
    else:
        # Default: SWARM (production)
        return OpenAI(base_url=SWARM_ENDPOINT, api_key="not-needed"), SWARM_MODEL


# =============================================================================
# OLLAMA ENDPOINTS — Sentinel & RAG Embedding Nodes
# =============================================================================

def get_ollama_endpoints() -> list:
    """
    Return list of Ollama endpoints for all active Spark nodes.
    Used by fortress_sentinel.py for distributed embedding.
    """
    return [
        f"http://{SPARK_01_IP}:11434",  # Captain
        f"http://{SPARK_02_IP}:11434",  # Muscle
        f"http://{SPARK_03_IP}:11434",  # Ocular
        f"http://{SPARK_04_IP}:11434",  # Sovereign
    ]
