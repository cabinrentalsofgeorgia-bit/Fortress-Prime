#!/usr/bin/env python3
"""
GOD HEAD DIAGNOSTIC DAEMON — Fortress Prime Phase 1
=====================================================
Exposes the exact vector mismatch between PostgreSQL and Qdrant,
measures cold-start TTFT for SWARM and HYDRA inference models.

Run:
    python3 tools/god_head_audit.py
    python3 tools/god_head_audit.py --quick   # skip inference TTFT test
"""

import os
import sys
import time
import json
import argparse
import psycopg2
import requests
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
for env_name in [".env", "fortress-guest-platform/.env"]:
    env_file = project_root / env_name
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

# --- CONFIGURATION (all from environment — no hardcoded secrets) ---
DB_HOST = os.getenv("DB_HOST", "192.168.0.100")
DB_USER = os.getenv("DB_USER", os.getenv("FORTRESS_DB_USER", "miner_bot"))
DB_PASS = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))
DB_NAME = os.getenv("DB_NAME", os.getenv("FORTRESS_DB_NAME", "fortress_db"))

QDRANT_URL = os.getenv("QDRANT_URL", "http://192.168.0.100:6333")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://192.168.0.100/v1")

def get_db_connection():
    return psycopg2.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, dbname=DB_NAME)

# --- A. VECTOR SYNC DELTA ---
def check_vector_sync():
    print("\n[*] Initiating Vector Sync Audit...")
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM public.email_archive;")
    total_pg = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM public.email_archive WHERE is_vectorized = true;")
    vectorized_pg = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM public.email_archive WHERE is_vectorized = false OR is_vectorized IS NULL;")
    pending_pg = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    qdrant_count = 0
    try:
        resp = requests.get(f"{QDRANT_URL}/collections/email_embeddings", timeout=5)
        if resp.status_code == 200:
            qdrant_count = resp.json().get('result', {}).get('points_count', 0)
        else:
            print(f"  [!] Qdrant Error: HTTP {resp.status_code}")
    except Exception as e:
        print(f"  [!] Qdrant Connection Failed: {e}")

    delta = vectorized_pg - qdrant_count

    print("--------------------------------------------------")
    print(f"  PostgreSQL Total Emails : {total_pg}")
    print(f"  PostgreSQL Vectorized   : {vectorized_pg}")
    print(f"  PostgreSQL Pending      : {pending_pg}")
    print(f"  Qdrant Points Count     : {qdrant_count}")
    print("--------------------------------------------------")

    if delta == 0:
        print("  [+] STATUS: PERFECT SYNC. Ledgers match exactly.")
    else:
        print(f"  [-] STATUS: DESYNC DETECTED. Vector gap: {abs(delta)} records.")
        if pending_pg > 0:
            print(f"  [!] ACTION REQUIRED: {pending_pg} emails waiting in ingestion queue.")

# --- B. COLD-START TTFT MEASUREMENT ---
def measure_ttft(model_name: str):
    print(f"\n[*] Pinging {model_name} for TTFT (Time-To-First-Token)...")

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "Acknowledge ping."}],
        "stream": True,
        "temperature": 0.0,
        "max_tokens": 10
    }

    start_time = time.perf_counter()
    first_token_time = None
    ttft = None

    try:
        with requests.post(f"{LLM_BASE_URL}/chat/completions", json=payload, stream=True, timeout=180) as r:
            if r.status_code != 200:
                print(f"  [!] API Error: HTTP {r.status_code}")
                try:
                    print(f"  [!] Response: {r.text[:200]}")
                except Exception:
                    pass
                return

            for line in r.iter_lines():
                if line and not first_token_time:
                    first_token_time = time.perf_counter()
                    ttft = first_token_time - start_time
                    print(f"  [+] First token received in {ttft:.2f} seconds.")
                    break

        total_time = time.perf_counter() - start_time
        print(f"  [+] Total execution time: {total_time:.2f} seconds.")

        if ttft and ttft > 30.0:
            print("  [!] WARNING: SEVERE COLD START DETECTED. Model weights were not in VRAM.")
        elif ttft:
            print("  [+] Model is warm. VRAM allocation active.")

    except requests.exceptions.ReadTimeout:
        elapsed = time.perf_counter() - start_time
        print(f"  [!] FATAL: Request timed out after {elapsed:.0f} seconds. {model_name} failed to load.")
    except requests.exceptions.ConnectionError as e:
        print(f"  [!] Connection Failed: {e}")
    except Exception as e:
        print(f"  [!] Request Failed: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="God Head Diagnostic Daemon")
    parser.add_argument("--quick", action="store_true", help="Skip inference TTFT test")
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"  GOD HEAD DIAGNOSTIC — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    check_vector_sync()

    if not args.quick:
        measure_ttft("qwen2.5:7b")
        measure_ttft("deepseek-r1:70b")

    print(f"\n[*] Audit Complete.")
