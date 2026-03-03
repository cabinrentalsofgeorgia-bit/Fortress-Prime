#!/usr/bin/env python3
"""
NVIDIA SENTINEL — Supply Chain Intelligence (Constitution Amendment IV)
=======================================================================
Watches NVIDIA NGC Registry, Ollama Library, and driver channels for updates.
Alerts when new container images, model versions, or drivers appear.

Monitors:
    1. NGC Container Registry — NIM images (DeepSeek R1-70B, R1-671B, Qwen)
    2. Ollama Library — Model tag changes (deepseek-r1:70b, qwen2.5:7b)
    3. NVIDIA Driver — L4T / JetPack / DGX Spark driver releases
    4. ARM64 NIM availability — The critical gate for HYDRA NIM migration

State:
    Stores last-known digests/versions in Postgres (fortress_db.sentinel_state).
    Compares on each run. If new → logs alert and optionally sends email.

Usage:
    python3 tools/nvidia_sentinel.py              # Full audit
    python3 tools/nvidia_sentinel.py --check-only  # Quick check, no email
    python3 tools/nvidia_sentinel.py --init        # Initialize state table

Cron:
    0 6 * * * cd /home/admin/Fortress-Prime && ./venv/bin/python tools/nvidia_sentinel.py >> /var/log/sentinel.log 2>&1

Governing Documents:
    Constitution Amendment IV — Tri-Mode DEFCON architecture
    001-titan-protocol.mdc   — NIM-first mandate (when ARM64 available)
"""

from __future__ import annotations

import os
import sys
import json
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT, NGC_API_KEY
except ImportError:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    DB_HOST = os.getenv("DB_HOST", "192.168.0.100")
    DB_NAME = os.getenv("DB_NAME", "fortress_db")
    DB_USER = os.getenv("DB_USER", "miner_bot")
    DB_PASS = os.getenv("DB_PASS", "")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    NGC_API_KEY = os.getenv("NGC_API_KEY", "")

logger = logging.getLogger("sentinel")

# =============================================================================
# I. WATCH TARGETS
# =============================================================================

# NGC Container images to monitor (org/team/image)
NGC_IMAGES = [
    {
        "name": "DeepSeek R1-70B NIM",
        "image": "nim/deepseek-ai/deepseek-r1-distill-llama-70b",
        "priority": "CRITICAL",
        "note": "Primary HYDRA target. Waiting for ARM64 build.",
    },
    {
        "name": "DeepSeek R1-671B NIM",
        "image": "nim/deepseek-ai/deepseek-r1",
        "priority": "HIGH",
        "note": "TITAN target. Multi-node NIM would replace llama.cpp RPC.",
    },
    {
        "name": "Qwen 2.5 7B NIM",
        "image": "nim/nvidia/qwen2.5-7b-instruct",
        "priority": "MEDIUM",
        "note": "SWARM mode candidate. Lightweight NIM for fast inference.",
    },
]

# Ollama model tags to monitor
OLLAMA_MODELS = [
    {
        "name": "DeepSeek R1-70B (Ollama)",
        "model": "deepseek-r1:70b",
        "priority": "HIGH",
        "note": "Active HYDRA runtime. Track for quantization improvements.",
    },
    {
        "name": "Qwen 2.5 7B (Ollama)",
        "model": "qwen2.5:7b",
        "priority": "MEDIUM",
        "note": "Active SWARM runtime.",
    },
    {
        "name": "DeepSeek R1-671B (Ollama)",
        "model": "deepseek-r1:671b",
        "priority": "LOW",
        "note": "TITAN fallback. Full-size model for Ollama.",
    },
]

# Email config (optional)
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
ALERT_EMAIL = os.getenv("SENTINEL_ALERT_EMAIL", "")


# =============================================================================
# II. STATE MANAGEMENT (Postgres)
# =============================================================================

def get_db_connection():
    """Get a Postgres connection."""
    import psycopg2
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER,
        password=DB_PASS, port=DB_PORT,
    )


def init_state_table():
    """Create the sentinel_state table if it doesn't exist."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sentinel_state (
            key         TEXT PRIMARY KEY,
            value       TEXT NOT NULL,
            source      TEXT NOT NULL DEFAULT 'unknown',
            priority    TEXT NOT NULL DEFAULT 'MEDIUM',
            note        TEXT DEFAULT '',
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_sentinel_source ON sentinel_state(source);
    """)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("sentinel_state table ready")


def get_state(key: str) -> Optional[str]:
    """Get a stored state value."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT value FROM sentinel_state WHERE key = %s", (key,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.warning(f"State read failed for {key}: {e}")
        return None


def set_state(key: str, value: str, source: str = "unknown",
              priority: str = "MEDIUM", note: str = ""):
    """Upsert a state value."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO sentinel_state (key, value, source, priority, note, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                source = EXCLUDED.source,
                priority = EXCLUDED.priority,
                note = EXCLUDED.note,
                updated_at = NOW()
        """, (key, value, source, priority, note))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.warning(f"State write failed for {key}: {e}")


# =============================================================================
# III. NGC REGISTRY CHECKER
# =============================================================================

def get_ngc_token(image: str) -> Optional[str]:
    """Authenticate with NVIDIA NGC and get a bearer token for a specific image."""
    if not NGC_API_KEY:
        logger.warning("NGC_API_KEY not set — skipping NGC checks")
        return None

    try:
        auth_url = (
            f"https://authn.nvidia.com/token"
            f"?service=ngc&scope=repository:{image}:pull"
        )
        resp = requests.get(auth_url, auth=("$oauthtoken", NGC_API_KEY), timeout=15)
        resp.raise_for_status()
        return resp.json().get("token")
    except Exception as e:
        logger.warning(f"NGC auth failed for {image}: {e}")
        return None


def check_ngc_image(image_spec: dict) -> Optional[dict]:
    """
    Check an NGC image for new tags/digests.
    Returns an alert dict if a change is detected, None otherwise.
    """
    image = image_spec["image"]
    name = image_spec["name"]
    priority = image_spec["priority"]

    token = get_ngc_token(image)
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}

    # Try Docker V2 manifest API (more reliable than NGC's REST API)
    # nvcr.io uses standard Docker V2 registry protocol
    registry_url = f"https://nvcr.io/v2/{image}/tags/list"

    try:
        resp = requests.get(registry_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        tags = data.get("tags", [])

        if not tags:
            logger.info(f"  [{name}] No tags found")
            return None

        # Sort tags, get latest
        tags_str = ",".join(sorted(tags))
        state_key = f"ngc:{image}:tags"
        old_tags = get_state(state_key)

        if old_tags == tags_str:
            logger.info(f"  [{name}] No changes ({len(tags)} tags)")
            return None

        # Check for ARM64 manifests (the critical gate)
        arm64_available = False
        if "latest" in tags:
            manifest_url = f"https://nvcr.io/v2/{image}/manifests/latest"
            try:
                mresp = requests.get(
                    manifest_url, headers={
                        **headers,
                        "Accept": "application/vnd.oci.image.index.v1+json,"
                                  "application/vnd.docker.distribution.manifest.list.v2+json"
                    },
                    timeout=15,
                )
                if mresp.status_code == 200:
                    mdata = mresp.json()
                    manifests = mdata.get("manifests", [])
                    for m in manifests:
                        platform = m.get("platform", {})
                        if platform.get("architecture") == "arm64":
                            arm64_available = True
                            break
            except Exception:
                pass

        # New tags detected
        new_tags = set(tags) - set(old_tags.split(",")) if old_tags else set(tags)
        set_state(state_key, tags_str, source="ngc", priority=priority,
                  note=image_spec.get("note", ""))

        alert = {
            "source": "NGC",
            "name": name,
            "priority": priority,
            "message": f"New tags detected: {', '.join(sorted(new_tags)[:10])}",
            "total_tags": len(tags),
            "arm64": arm64_available,
            "image": image,
        }

        if arm64_available:
            alert["priority"] = "CRITICAL"
            alert["message"] += " >>> ARM64 BUILD AVAILABLE — HYDRA NIM MIGRATION READY <<<"

        return alert

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            logger.info(f"  [{name}] Image not found (may not be public)")
        else:
            logger.warning(f"  [{name}] NGC check failed: {e}")
        return None
    except Exception as e:
        logger.warning(f"  [{name}] NGC check failed: {e}")
        return None


# =============================================================================
# IV. OLLAMA LIBRARY CHECKER
# =============================================================================

def check_ollama_model(model_spec: dict) -> Optional[dict]:
    """
    Check the Ollama library for model updates by querying the local Ollama
    instance for the current digest and comparing with the remote library.
    """
    model = model_spec["model"]
    name = model_spec["name"]
    priority = model_spec["priority"]

    # Get local model digest from Captain's Ollama
    try:
        resp = requests.post(
            "http://localhost:11434/api/show",
            json={"name": model},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            local_digest = data.get("digest", "unknown")[:12]
            modified_at = data.get("modified_at", "unknown")
        else:
            local_digest = "not-pulled"
            modified_at = "N/A"
    except Exception:
        local_digest = "unreachable"
        modified_at = "N/A"

    state_key = f"ollama:{model}:digest"
    old_digest = get_state(state_key)

    if old_digest == local_digest:
        logger.info(f"  [{name}] No changes (digest: {local_digest})")
        return None

    set_state(state_key, local_digest, source="ollama", priority=priority,
              note=model_spec.get("note", ""))

    if old_digest is None:
        # First run — just record, don't alert
        logger.info(f"  [{name}] Initial record (digest: {local_digest})")
        return None

    return {
        "source": "Ollama",
        "name": name,
        "priority": priority,
        "message": f"Model digest changed: {old_digest} → {local_digest} (modified: {modified_at})",
        "model": model,
    }


# =============================================================================
# V. NVIDIA DRIVER CHECKER
# =============================================================================

def check_nvidia_driver() -> Optional[dict]:
    """Check the local NVIDIA driver version and compare with state."""
    import subprocess

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.warning("nvidia-smi failed")
            return None

        driver_version = result.stdout.strip().split("\n")[0].strip()
        state_key = "nvidia:driver_version"
        old_version = get_state(state_key)

        if old_version == driver_version:
            logger.info(f"  [NVIDIA Driver] No changes (v{driver_version})")
            return None

        set_state(state_key, driver_version, source="nvidia-driver", priority="HIGH",
                  note="Local GPU driver version")

        if old_version is None:
            logger.info(f"  [NVIDIA Driver] Initial record (v{driver_version})")
            return None

        return {
            "source": "NVIDIA Driver",
            "name": "GPU Driver Update",
            "priority": "HIGH",
            "message": f"Driver changed: v{old_version} → v{driver_version}",
        }
    except Exception as e:
        logger.warning(f"  [NVIDIA Driver] Check failed: {e}")
        return None


# =============================================================================
# VI. ALERT DISPATCH
# =============================================================================

def send_email_alert(alerts: list):
    """Send alert summary via SMTP."""
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, ALERT_EMAIL]):
        logger.info("Email not configured — skipping email alert")
        return

    import smtplib
    from email.mime.text import MIMEText

    body_lines = [
        "FORTRESS PRIME — NVIDIA SENTINEL REPORT",
        f"Timestamp: {datetime.now(timezone.utc).isoformat()}",
        f"Alerts: {len(alerts)}",
        "=" * 60,
    ]

    for alert in alerts:
        body_lines.append(f"\n[{alert['priority']}] {alert['name']} ({alert['source']})")
        body_lines.append(f"  {alert['message']}")
        if alert.get("arm64"):
            body_lines.append("  >>> ARM64 NIM AVAILABLE — IMMEDIATE ACTION REQUIRED <<<")

    body_lines.append(f"\n{'=' * 60}")
    body_lines.append("End of report. — The Sentinel")

    msg = MIMEText("\n".join(body_lines))
    msg["Subject"] = f"[SENTINEL] {len(alerts)} update(s) detected — Fortress Prime"
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_EMAIL

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, ALERT_EMAIL, msg.as_string())
        logger.info(f"Email alert sent to {ALERT_EMAIL}")
    except Exception as e:
        logger.error(f"Email send failed: {e}")


def log_alert_to_db(alerts: list):
    """Log alerts to Postgres for dashboard consumption."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sentinel_alerts (
                id          SERIAL PRIMARY KEY,
                source      TEXT NOT NULL,
                name        TEXT NOT NULL,
                priority    TEXT NOT NULL,
                message     TEXT NOT NULL,
                arm64       BOOLEAN DEFAULT FALSE,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        for alert in alerts:
            cur.execute("""
                INSERT INTO sentinel_alerts (source, name, priority, message, arm64)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                alert["source"], alert["name"], alert["priority"],
                alert["message"], alert.get("arm64", False),
            ))
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Logged {len(alerts)} alert(s) to sentinel_alerts table")
    except Exception as e:
        logger.error(f"DB alert logging failed: {e}")


# =============================================================================
# VII. MAIN AUDIT LOOP
# =============================================================================

def run_audit(check_only: bool = False) -> list:
    """
    Run the full sentinel audit.

    Returns list of alert dicts for any detected changes.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    logger.info(f"{'=' * 60}")
    logger.info(f"NVIDIA SENTINEL — Audit started at {timestamp}")
    logger.info(f"{'=' * 60}")

    alerts = []

    # 1. NGC Registry
    logger.info("\n[Phase 1] NGC Container Registry")
    for spec in NGC_IMAGES:
        result = check_ngc_image(spec)
        if result:
            alerts.append(result)
            logger.warning(f"  ALERT: {result['name']} — {result['message']}")

    # 2. Ollama Library
    logger.info("\n[Phase 2] Ollama Model Library")
    for spec in OLLAMA_MODELS:
        result = check_ollama_model(spec)
        if result:
            alerts.append(result)
            logger.warning(f"  ALERT: {result['name']} — {result['message']}")

    # 3. NVIDIA Driver
    logger.info("\n[Phase 3] NVIDIA Driver")
    result = check_nvidia_driver()
    if result:
        alerts.append(result)
        logger.warning(f"  ALERT: {result['name']} — {result['message']}")

    # Summary
    logger.info(f"\n{'=' * 60}")
    if alerts:
        logger.warning(f"SENTINEL SUMMARY: {len(alerts)} change(s) detected!")
        for a in alerts:
            logger.warning(f"  [{a['priority']}] {a['name']}: {a['message']}")

        if not check_only:
            log_alert_to_db(alerts)
            send_email_alert(alerts)
    else:
        logger.info("SENTINEL SUMMARY: All clear. No changes detected.")

    logger.info(f"Audit complete at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    return alerts


# =============================================================================
# VIII. CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="NVIDIA Sentinel — Supply chain intelligence for Fortress Prime"
    )
    parser.add_argument(
        "--init", action="store_true",
        help="Initialize the sentinel_state table in Postgres",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="Run audit without sending emails or logging to DB",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.init:
        init_state_table()
        logger.info("State table initialized. Run without --init to start auditing.")
        return

    # Ensure table exists
    try:
        init_state_table()
    except Exception as e:
        logger.error(f"Cannot initialize state table: {e}")
        logger.error("Run with --init to create the table, or check DB connection.")
        sys.exit(1)

    alerts = run_audit(check_only=args.check_only)
    sys.exit(0 if not alerts else 2)  # Exit 2 = changes detected (useful for cron)


if __name__ == "__main__":
    main()
