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
    5. NIM ARM64 Catalog Audit — Daily manifest-level ARM64 probe with mismatch detection

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
import subprocess
import sys
import json
import logging
import argparse
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from config import DB_HOST, DB_NAME, DB_USER, DB_PASS, DB_PORT, NGC_API_KEY  # type: ignore[attr-defined]
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
    """Create the sentinel_state table and nim_arm64_probe_results if they don't exist."""
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
    # Also initialise the Phase 4 probe table
    try:
        init_nim_arm64_probe_table()
    except Exception as exc:
        logger.warning("nim_arm64_probe_results init failed (non-fatal): %s", exc)


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
# VI-B. NIM ARM64 CATALOG AUDIT (Phase 4)
# =============================================================================

# NIM images to watch for ARM64 manifest status each day.
# Combines the three active targets plus the sentinel's existing NGC_IMAGES list.
NIM_ARM64_WATCH = [
    "nvcr.io/nim/nvidia/nemotron-nano-12b-v2-vl:latest",
    "nvcr.io/nim/nvidia/llama-nemotron-embed-1b-v2:latest",
    "nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2:latest",   # broken — watch for fix
    "nvcr.io/nim/nvidia/llama-nemotron-nano-8b-v1:latest",
    "nvcr.io/nim/deepseek-ai/deepseek-r1-distill-llama-70b:latest",
]


def init_nim_arm64_probe_table():
    """Create the nim_arm64_probe_results table if it does not yet exist."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nim_arm64_probe_results (
            id                    SERIAL PRIMARY KEY,
            probe_date            DATE NOT NULL,
            image_path            TEXT NOT NULL,
            tag                   TEXT NOT NULL,
            stage1_arm64          BOOLEAN,
            arm64_digest          TEXT,
            amd64_digest          TEXT,
            arm64_manifest_bytes  INT,
            amd64_manifest_bytes  INT,
            possible_mismatch     BOOLEAN,
            verdict               TEXT,
            probe_notes           TEXT,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (probe_date, image_path, tag)
        );
        CREATE INDEX IF NOT EXISTS idx_nim_arm64_probe_date
            ON nim_arm64_probe_results(probe_date);
        CREATE INDEX IF NOT EXISTS idx_nim_arm64_probe_image
            ON nim_arm64_probe_results(image_path);
    """)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("nim_arm64_probe_results table ready")


def _manifest_inspect_via_docker(image_ref: str) -> Optional[dict]:
    """
    Run `docker manifest inspect <image_ref>` and return parsed JSON, or None on error.
    Uses subprocess — no docker pull, suitable for daily sentinel runs.
    """
    try:
        result = subprocess.run(
            ["docker", "manifest", "inspect", image_ref],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                "docker manifest inspect failed for %s: %s",
                image_ref, result.stderr.strip(),
            )
            return None
        return json.loads(result.stdout)
    except Exception as exc:
        logger.warning("manifest inspect error for %s: %s", image_ref, exc)
        return None


def _parse_manifest_arm64(
    image_ref: str,
) -> tuple[bool, Optional[str], Optional[str], Optional[int], Optional[int]]:
    """
    Stage-1 manifest check via docker manifest inspect.

    Returns:
        (stage1_arm64, arm64_digest, amd64_digest, arm64_manifest_bytes, amd64_manifest_bytes)

    arm64_manifest_bytes / amd64_manifest_bytes are the `size` field reported by the
    registry for each sub-manifest.  If both values are identical, that is the ARM64
    mismatch signal (same-byte packaging defect — the broken 9B VRS image case).
    """
    index = _manifest_inspect_via_docker(image_ref)
    if index is None:
        return False, None, None, None, None

    arm64_digest: Optional[str] = None
    amd64_digest: Optional[str] = None
    arm64_size: Optional[int] = None
    amd64_size: Optional[int] = None

    # Multi-arch image index
    if "manifests" in index:
        for m in index["manifests"]:
            plat = m.get("platform", {})
            arch = plat.get("architecture", "")
            os_name = plat.get("os", "")
            digest = m.get("digest")
            size = m.get("size")
            if arch == "arm64" and os_name == "linux":
                arm64_digest = digest
                arm64_size = size
            elif arch in ("amd64", "x86_64") and os_name == "linux":
                amd64_digest = digest
                amd64_size = size
    elif index.get("architecture") == "arm64":
        # Single-arch manifest already arm64
        arm64_digest = image_ref

    stage1_arm64 = arm64_digest is not None
    return stage1_arm64, arm64_digest, amd64_digest, arm64_size, amd64_size


def _upsert_nim_arm64_probe_result(
    probe_date: date,
    image_path: str,
    tag: str,
    stage1_arm64: Optional[bool],
    arm64_digest: Optional[str],
    amd64_digest: Optional[str],
    arm64_manifest_bytes: Optional[int],
    amd64_manifest_bytes: Optional[int],
    possible_mismatch: Optional[bool],
    verdict: str,
    probe_notes: str,
) -> None:
    """Upsert a probe result row into nim_arm64_probe_results."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO nim_arm64_probe_results
                (probe_date, image_path, tag, stage1_arm64, arm64_digest,
                 amd64_digest, arm64_manifest_bytes, amd64_manifest_bytes,
                 possible_mismatch, verdict, probe_notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (probe_date, image_path, tag) DO UPDATE SET
                stage1_arm64         = EXCLUDED.stage1_arm64,
                arm64_digest         = EXCLUDED.arm64_digest,
                amd64_digest         = EXCLUDED.amd64_digest,
                arm64_manifest_bytes = EXCLUDED.arm64_manifest_bytes,
                amd64_manifest_bytes = EXCLUDED.amd64_manifest_bytes,
                possible_mismatch    = EXCLUDED.possible_mismatch,
                verdict              = EXCLUDED.verdict,
                probe_notes          = EXCLUDED.probe_notes,
                created_at           = NOW()
        """, (
            probe_date, image_path, tag, stage1_arm64, arm64_digest,
            amd64_digest, arm64_manifest_bytes, amd64_manifest_bytes,
            possible_mismatch, verdict, probe_notes,
        ))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as exc:
        logger.warning("nim_arm64_probe_results write failed for %s: %s", image_path, exc)


def _get_yesterday_probe(image_path: str, tag: str) -> Optional[dict]:
    """Return the probe row from yesterday for the given image, or None."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT stage1_arm64, arm64_digest, arm64_manifest_bytes, amd64_manifest_bytes,
                   possible_mismatch, verdict
            FROM nim_arm64_probe_results
            WHERE image_path = %s AND tag = %s
              AND probe_date = (CURRENT_DATE - INTERVAL '1 day')::DATE
            LIMIT 1
        """, (image_path, tag))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None:
            return None
        return {
            "stage1_arm64": row[0],
            "arm64_digest": row[1],
            "arm64_manifest_bytes": row[2],
            "amd64_manifest_bytes": row[3],
            "possible_mismatch": row[4],
            "verdict": row[5],
        }
    except Exception as exc:
        logger.warning("Yesterday probe read failed for %s: %s", image_path, exc)
        return None


def audit_nim_arm64_catalog(check_only: bool = False) -> list:
    """
    Phase 4 — NIM ARM64 Catalog Audit.

    For each image in NIM_ARM64_WATCH:
      1. Run stage-1 manifest check only (no pull, no ELF — too slow for daily cron).
      2. Compare against yesterday's result in nim_arm64_probe_results.
      3. Detect three alert categories:
         - ARM64_NEW: arm64 manifest newly appeared
         - ARM64_REGRESSION: arm64 manifest previously present, now gone
         - ARM64_MANIFEST_MISMATCH: arm64 and amd64 sub-manifests have identical
           byte counts (packaging defect signal — same as the broken 9B VRS image)

    Returns list of alert dicts (same shape as other audit phases).
    """
    alerts: list = []
    today = date.today()

    for image_ref in NIM_ARM64_WATCH:
        # Split "nvcr.io/<image_path>:<tag>"
        ref_no_registry = image_ref.replace("nvcr.io/", "", 1)
        if ":" in ref_no_registry:
            image_path, tag = ref_no_registry.rsplit(":", 1)
        else:
            image_path = ref_no_registry
            tag = "latest"

        logger.info("  [NIM ARM64] Checking %s:%s ...", image_path, tag)

        stage1, arm64_digest, amd64_digest, arm64_bytes, amd64_bytes = (
            _parse_manifest_arm64(image_ref)
        )

        # Determine possible mismatch: both manifests exist and share identical byte count
        possible_mismatch = (
            arm64_bytes is not None
            and amd64_bytes is not None
            and arm64_bytes == amd64_bytes
        )

        if not stage1:
            verdict = "NO_ARM64"
        elif possible_mismatch:
            verdict = "ARM64_MANIFEST_MISMATCH"
        else:
            verdict = "ARM64_OK"

        notes_parts: list[str] = []
        if arm64_bytes:
            notes_parts.append(f"arm64_bytes={arm64_bytes}")
        if amd64_bytes:
            notes_parts.append(f"amd64_bytes={amd64_bytes}")
        probe_notes = "; ".join(notes_parts)

        # Persist today's result
        if not check_only:
            _upsert_nim_arm64_probe_result(
                probe_date=today,
                image_path=image_path,
                tag=tag,
                stage1_arm64=stage1,
                arm64_digest=arm64_digest,
                amd64_digest=amd64_digest,
                arm64_manifest_bytes=arm64_bytes,
                amd64_manifest_bytes=amd64_bytes,
                possible_mismatch=possible_mismatch,
                verdict=verdict,
                probe_notes=probe_notes,
            )

        # Compare with yesterday
        yesterday = _get_yesterday_probe(image_path, tag)

        alert: Optional[dict] = None

        if yesterday is None:
            # First-run for this image — no delta to report
            logger.info("    [%s] First probe — %s", image_path, verdict)
        elif not yesterday.get("stage1_arm64") and stage1:
            # ARM64_NEW: previously absent, now present
            alert = {
                "source": "NIM_ARM64_CATALOG",
                "name": f"ARM64_NEW: {image_path}:{tag}",
                "priority": "CRITICAL",
                "message": (
                    f"ARM64 manifest newly available for {image_ref}. "
                    f"arm64_digest={arm64_digest} — new candidate ready for pull."
                ),
                "arm64": True,
                "image": image_path,
                "alert_class": "ARM64_NEW",
            }
        elif yesterday.get("stage1_arm64") and not stage1:
            # ARM64_REGRESSION: previously present, now gone
            alert = {
                "source": "NIM_ARM64_CATALOG",
                "name": f"ARM64_REGRESSION: {image_path}:{tag}",
                "priority": "HIGH",
                "message": (
                    f"ARM64 manifest REMOVED for {image_ref}. "
                    f"Yesterday had arm64_digest={yesterday.get('arm64_digest')}. "
                    f"NVIDIA may have re-packaged — check for regression."
                ),
                "arm64": False,
                "image": image_path,
                "alert_class": "ARM64_REGRESSION",
            }
        elif possible_mismatch and not yesterday.get("possible_mismatch"):
            # ARM64_MANIFEST_MISMATCH: mismatch newly detected (or not flagged yesterday)
            alert = {
                "source": "NIM_ARM64_CATALOG",
                "name": f"ARM64_MANIFEST_MISMATCH: {image_path}:{tag}",
                "priority": "HIGH",
                "message": (
                    f"ARM64/AMD64 manifest byte counts are IDENTICAL for {image_ref} "
                    f"({arm64_bytes} bytes each). Likely packaging defect — "
                    f"manifest claims arm64 but layers may be x86. Do NOT pull."
                ),
                "arm64": False,
                "image": image_path,
                "alert_class": "ARM64_MANIFEST_MISMATCH",
            }
        else:
            logger.info("    [%s] No change — verdict=%s", image_path, verdict)

        if alert:
            alerts.append(alert)
            logger.warning(
                "  NIM ARM64 ALERT [%s] %s: %s",
                alert["alert_class"], image_path, alert["message"],
            )

    return alerts


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

    # 4. NIM ARM64 Catalog Audit
    logger.info("\n[Phase 4] NIM ARM64 Catalog Audit")
    nim_alerts = audit_nim_arm64_catalog(check_only=check_only)
    for alert in nim_alerts:
        alerts.append(alert)
        logger.warning(f"  ALERT: {alert['name']} — {alert['message']}")

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
