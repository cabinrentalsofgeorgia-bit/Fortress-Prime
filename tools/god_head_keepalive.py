#!/usr/bin/env python3
"""
GOD HEAD VRAM KEEPALIVE — Fortress Prime
==========================================
Lightweight daemon that pings HYDRA (R1-70B) every 5 minutes during active
hours (6 AM - 11 PM ET) to keep model weights loaded in VRAM.

Logs TTFT on every heartbeat for trend analysis. If 3 consecutive pings
fail, writes a P1 alert to system_post_mortems.

Cron:
    */5 6-23 * * * cd /home/admin/Fortress-Prime && ./venv/bin/python tools/god_head_keepalive.py \
        >> /mnt/fortress_nas/fortress_data/ai_brain/logs/god_head_keepalive.log 2>&1

Run once (test mode):
    python3 tools/god_head_keepalive.py
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg2
import requests

env_file = Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [KEEPALIVE] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("keepalive")

HYDRA_URL = os.getenv("HYDRA_FALLBACK_URL", "http://192.168.0.100/hydra/v1")
HYDRA_MODEL = os.getenv("HYDRA_MODEL", "deepseek-r1:70b")

DB_HOST = os.getenv("DB_HOST", "192.168.0.100")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))

STATE_FILE = Path("/tmp/god_head_keepalive_state.json")
MAX_CONSECUTIVE_FAILURES = 3


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"consecutive_failures": 0, "last_ttft": None, "last_status": None}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state))


def _write_alert(severity: str, summary: str):
    """Write a P1 alert to system_post_mortems."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, database=DB_NAME,
            user=DB_USER, password=DB_PASS, connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO system_post_mortems
               (occurred_at, sector, severity, component, error_summary, status, resolved_by)
               VALUES (NOW(), 'infra', %s, 'god_head_keepalive', %s, 'open', 'keepalive_daemon')""",
            (severity, summary),
        )
        conn.commit()
        conn.close()
        log.info("Alert written to system_post_mortems: %s", severity)
    except Exception as e:
        log.error("Failed to write alert: %s", e)


def ping_hydra() -> tuple[bool, float]:
    """
    Send a minimal 1-token streaming ping to HYDRA.
    Returns (success, ttft_seconds).
    """
    payload = {
        "model": HYDRA_MODEL,
        "messages": [{"role": "user", "content": "ping"}],
        "stream": True,
        "temperature": 0.0,
        "max_tokens": 5,
    }

    start = time.perf_counter()
    try:
        with requests.post(
            f"{HYDRA_URL}/chat/completions",
            json=payload,
            stream=True,
            timeout=180,
        ) as r:
            if r.status_code != 200:
                return False, time.perf_counter() - start

            for line in r.iter_lines():
                if line:
                    ttft = time.perf_counter() - start
                    return True, ttft

        return False, time.perf_counter() - start

    except requests.exceptions.ReadTimeout:
        return False, time.perf_counter() - start
    except Exception:
        return False, time.perf_counter() - start


def main():
    state = _load_state()
    now = datetime.now()
    log.info("Keepalive ping at %s — targeting %s via %s", now.strftime("%H:%M:%S"), HYDRA_MODEL, HYDRA_URL)

    ok, ttft = ping_hydra()

    if ok:
        state["consecutive_failures"] = 0
        state["last_ttft"] = round(ttft, 2)
        state["last_status"] = "warm"

        if ttft > 30.0:
            log.warning("HYDRA responded but TTFT=%.1fs — cold start detected", ttft)
            state["last_status"] = "cold_start"
        else:
            log.info("HYDRA warm — TTFT=%.2fs", ttft)
    else:
        state["consecutive_failures"] += 1
        state["last_ttft"] = None
        state["last_status"] = "failed"
        log.error(
            "HYDRA ping FAILED (attempt %d/%d)",
            state["consecutive_failures"], MAX_CONSECUTIVE_FAILURES,
        )

        if state["consecutive_failures"] >= MAX_CONSECUTIVE_FAILURES:
            _write_alert(
                "critical",
                f"HYDRA keepalive failed {MAX_CONSECUTIVE_FAILURES} consecutive times. "
                f"Model may be unloaded from VRAM or inference endpoint is down.",
            )
            state["consecutive_failures"] = 0

    state["last_check"] = now.isoformat()
    _save_state(state)


if __name__ == "__main__":
    main()
