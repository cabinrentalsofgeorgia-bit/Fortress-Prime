#!/usr/bin/env python3
"""
FORTRESS PRIME — Real-Time Operations Dashboard
=================================================
A terminal UI (TUI) showing live status of all autonomous systems.

Displays:
  - OCR Batch progress (GPU)
  - Live Ingester status
  - Cartographer (Vision) status
  - ChromaDB knowledge base stats
  - GPU/System utilization
  - Ollama model status on both nodes

Usage:
    python3 bin/dashboard.py           # Single refresh
    python3 bin/dashboard.py --live    # Auto-refresh every 10s
    python3 bin/dashboard.py --live 5  # Auto-refresh every 5s
"""

import os
import sys
import json
import time
import shutil
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# ANSI Styling
# ---------------------------------------------------------------------------
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
WHITE = "\033[97m"
RESET = "\033[0m"
CLEAR = "\033[2J\033[H"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NAS_LOG_DIR = Path("/mnt/fortress_nas/fortress_data/ai_brain/logs")
OCR_MARATHON_LOG = NAS_LOG_DIR / "ocr_batch" / "gpu_marathon.log"
# ChromaDB — local NVMe (migrated from /mnt/ai_fast NFS 2026-02-10)
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.fortress_paths import CHROMA_PATH as CHROMA_DB_PATH
except ImportError:
    CHROMA_DB_PATH = "/home/admin/fortress_fast/chroma_db"
COLLECTION_NAME = "fortress_knowledge"
INGEST_LOG = NAS_LOG_DIR / "ingest_processed.json"
CARTO_LOG_DIR = NAS_LOG_DIR / "cartographer"
CARTO_PROCESSED = CARTO_LOG_DIR / "cartographer_processed.json"

from config import SPARK_02_IP
MUSCLE_URL = f"http://{SPARK_02_IP}:11434"
CAPTAIN_URL = "http://localhost:11434"


def get_terminal_width():
    return shutil.get_terminal_size((80, 24)).columns


def bar(current, total, width=30, fill_char="█", empty_char="░"):
    """Render a progress bar string."""
    if total <= 0:
        return empty_char * width
    ratio = min(current / total, 1.0)
    filled = int(width * ratio)
    return fill_char * filled + empty_char * (width - filled)


def header():
    w = get_terminal_width()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{BOLD}{CYAN}{'=' * w}{RESET}")
    title = "FORTRESS PRIME — OPERATIONS DASHBOARD"
    print(f"{BOLD}{WHITE}{title:^{w}}{RESET}")
    print(f"{DIM}{now:^{w}}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * w}{RESET}")


def section(title, icon=""):
    w = get_terminal_width()
    print(f"\n{BOLD}{MAGENTA} {icon} {title} {'─' * max(0, w - len(title) - 5)}{RESET}")


# ---------------------------------------------------------------------------
# Data Collection
# ---------------------------------------------------------------------------

def get_ocr_status():
    """Parse OCR batch marathon log for progress."""
    result = {"running": False, "current": 0, "total": 0, "last_file": "", "last_status": "", "last_time": ""}

    if not OCR_MARATHON_LOG.exists():
        return result

    # Read last 20 lines
    try:
        lines = OCR_MARATHON_LOG.read_text(errors="replace").strip().split("\n")
        for line in reversed(lines[-30:]):
            line = line.strip()
            if line.startswith("[") and "/" in line:
                # Parse: [29/912] filename.pdf    OK (170.6s)
                try:
                    bracket = line.split("]")[0].strip("[")
                    current, total = bracket.split("/")
                    result["current"] = int(current)
                    result["total"] = int(total)
                    rest = line.split("]", 1)[1].strip()
                    # Split filename and status
                    parts = rest.rsplit(None, 1)
                    if len(parts) == 2 and "(" in parts[1]:
                        result["last_file"] = parts[0].strip()
                        result["last_status"] = parts[1].strip()
                    elif "OK" in rest or "ERR" in rest or "TIMEOUT" in rest:
                        for status in ["OK", "ERR", "TIMEOUT", "EMPTY"]:
                            if status in rest:
                                idx = rest.index(status)
                                result["last_file"] = rest[:idx].strip()
                                result["last_status"] = rest[idx:].strip()
                                break
                    else:
                        result["last_file"] = rest.strip()
                        result["last_status"] = "PROCESSING..."
                        result["running"] = True
                    break
                except:
                    pass
            elif "Remaining:" in line:
                try:
                    result["total"] = int(line.split(":")[-1].strip())
                except:
                    pass
    except:
        pass

    # Check if the OCR process is alive
    try:
        pid_file = Path("/tmp/ocr_batch_pid.txt")
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            result["running"] = True
    except (ProcessLookupError, ValueError, FileNotFoundError):
        pass

    return result


def get_chromadb_stats():
    """Get collection stats from ChromaDB."""
    result = {"total": 0, "vision": 0, "text": 0, "online": False}
    try:
        import chromadb
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        col = client.get_collection(COLLECTION_NAME)
        result["total"] = col.count()
        result["online"] = True

        # Count vision entries
        try:
            vision = col.get(where={"origin": "vision_cartographer"}, include=[])
            result["vision"] = len(vision["ids"])
        except:
            pass

        result["text"] = result["total"] - result["vision"]
    except:
        pass
    return result


def get_ingester_status():
    """Check live ingester status."""
    result = {"running": False, "processed": 0}
    try:
        if INGEST_LOG.exists():
            data = json.loads(INGEST_LOG.read_text())
            result["processed"] = len(data)
    except:
        pass

    # Check screen session
    try:
        out = subprocess.run(["screen", "-ls"], capture_output=True, text=True, timeout=5)
        if "ingest_watcher" in out.stdout:
            result["running"] = True
    except:
        pass
    return result


def get_cartographer_status():
    """Check cartographer status."""
    result = {"running": False, "processed": 0, "activity": ""}
    try:
        if CARTO_PROCESSED.exists():
            data = json.loads(CARTO_PROCESSED.read_text())
            result["processed"] = len(data)
    except:
        pass

    # Check screen session
    try:
        out = subprocess.run(["screen", "-ls"], capture_output=True, text=True, timeout=5)
        if "cartographer" in out.stdout:
            result["running"] = True
    except:
        pass

    # Get latest activity from log
    try:
        today = datetime.now().strftime("%Y%m%d")
        log_file = CARTO_LOG_DIR / f"cartographer_{today}.jsonl"
        if log_file.exists():
            lines = log_file.read_text().strip().split("\n")
            if lines:
                last = json.loads(lines[-1])
                result["activity"] = (
                    f"{last.get('status', '?')} | "
                    f"garbled={last.get('garbled_sections', 0)} "
                    f"vision={last.get('pages_sent_to_vision', 0)} "
                    f"indexed={last.get('descriptions_indexed', 0)}"
                )
    except:
        pass
    return result


def get_gpu_status():
    """Query nvidia-smi for GPU stats."""
    result = {"available": False, "util": "?", "mem_used": "?", "temp": "?", "processes": []}
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            parts = out.stdout.strip().split(",")
            if len(parts) >= 3:
                result["available"] = True
                result["util"] = parts[0].strip() + "%"
                result["mem_used"] = parts[1].strip() + " MiB"
                result["temp"] = parts[2].strip() + "C"

        # Get process list
        out2 = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if out2.returncode == 0:
            for line in out2.stdout.strip().split("\n"):
                if line.strip():
                    result["processes"].append(line.strip())
    except:
        pass
    return result


def get_node_status(url, name):
    """Check if an Ollama node is responding."""
    result = {"online": False, "models": []}
    try:
        import requests
        resp = requests.get(f"{url}/api/tags", timeout=5)
        if resp.status_code == 200:
            result["online"] = True
            for m in resp.json().get("models", []):
                size_gb = m.get("size", 0) / 1e9
                result["models"].append(f"{m['name']} ({size_gb:.0f}GB)")
    except:
        pass
    return result


def get_disk_usage():
    """Get disk usage for key mount points."""
    results = {}
    for mount, label in [("/mnt/ai_fast", "NVMe (Fast)"), ("/mnt/ai_bulk", "HDD (Bulk)")]:
        try:
            usage = shutil.disk_usage(mount)
            results[label] = {
                "total_gb": usage.total / (1024**3),
                "used_gb": usage.used / (1024**3),
                "free_gb": usage.free / (1024**3),
                "pct": usage.used / usage.total * 100,
            }
        except:
            pass
    return results


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render():
    """Collect all data and render the dashboard."""
    ocr = get_ocr_status()
    chroma = get_chromadb_stats()
    ingester = get_ingester_status()
    carto = get_cartographer_status()
    gpu = get_gpu_status()
    captain = get_node_status(CAPTAIN_URL, "Captain")
    muscle = get_node_status(MUSCLE_URL, "Muscle")
    disks = get_disk_usage()

    header()

    # --- OCR Batch ---
    section("OCR BATCH (GPU)", "")
    status_color = GREEN if ocr["running"] else RED
    status_text = "RUNNING" if ocr["running"] else "STOPPED"
    print(f"  Status:   {status_color}{BOLD}{status_text}{RESET}")
    if ocr["total"] > 0:
        pct = ocr["current"] / ocr["total"] * 100
        progress = bar(ocr["current"], ocr["total"], width=40)
        print(f"  Progress: {CYAN}{progress}{RESET} {ocr['current']}/{ocr['total']} ({pct:.0f}%)")
    if ocr["last_file"]:
        print(f"  Current:  {ocr['last_file'][:60]}")
    if ocr["last_status"]:
        color = GREEN if "OK" in ocr["last_status"] else (RED if "ERR" in ocr["last_status"] or "TIMEOUT" in ocr["last_status"] else YELLOW)
        print(f"  Last:     {color}{ocr['last_status']}{RESET}")

    # --- Knowledge Base ---
    section("KNOWLEDGE BASE (ChromaDB)", "")
    if chroma["online"]:
        print(f"  Status:   {GREEN}{BOLD}ONLINE{RESET}  ({COLLECTION_NAME})")
        print(f"  Total:    {BOLD}{chroma['total']:,}{RESET} chunks")
        print(f"  Text:     {chroma['text']:,}  |  Vision: {chroma['vision']:,}")
    else:
        print(f"  Status:   {RED}{BOLD}OFFLINE{RESET}")

    # --- Ingester ---
    section("LIVE INGESTER", "")
    status_color = GREEN if ingester["running"] else RED
    status_text = "WATCHING" if ingester["running"] else "STOPPED"
    print(f"  Status:   {status_color}{BOLD}{status_text}{RESET}")
    print(f"  Files:    {ingester['processed']} processed")

    # --- Cartographer ---
    section("CARTOGRAPHER (Vision)", "")
    status_color = GREEN if carto["running"] else RED
    status_text = "WATCHING" if carto["running"] else "STOPPED"
    print(f"  Status:   {status_color}{BOLD}{status_text}{RESET}")
    print(f"  Scanned:  {carto['processed']} files")
    if carto["activity"]:
        print(f"  Last:     {carto['activity']}")

    # --- GPU ---
    section("GPU (NVIDIA GB10)", "")
    if gpu["available"]:
        # Color-code utilization
        util_num = int(gpu["util"].replace("%", "").strip()) if gpu["util"] != "?" else 0
        util_color = GREEN if util_num > 50 else (YELLOW if util_num > 10 else DIM)
        print(f"  Util:     {util_color}{BOLD}{gpu['util']}{RESET}  |  Mem: {gpu['mem_used']}  |  Temp: {gpu['temp']}")
        if gpu["processes"]:
            print(f"  Active:   {len(gpu['processes'])} process(es)")
    else:
        print(f"  Status:   {RED}UNAVAILABLE{RESET}")

    # --- Cluster ---
    section("CLUSTER NODES", "")
    cap_color = GREEN if captain["online"] else RED
    mus_color = GREEN if muscle["online"] else RED
    cap_status = "ONLINE" if captain["online"] else "OFFLINE"
    mus_status = "ONLINE" if muscle["online"] else "OFFLINE"
    print(f"  Captain (Spark 2): {cap_color}{BOLD}{cap_status}{RESET}", end="")
    if captain["models"]:
        print(f"  [{', '.join(captain['models'][:2])}]")
    else:
        print()
    print(f"  Muscle  (Spark 1): {mus_color}{BOLD}{mus_status}{RESET}", end="")
    if muscle["models"]:
        print(f"  [{', '.join(muscle['models'][:2])}]")
    else:
        print()

    # --- Storage ---
    section("STORAGE", "")
    for label, info in disks.items():
        pct = info["pct"]
        color = GREEN if pct < 60 else (YELLOW if pct < 80 else RED)
        disk_bar = bar(info["used_gb"], info["total_gb"], width=20)
        print(f"  {label:<15} {color}{disk_bar}{RESET} "
              f"{info['used_gb']:.0f}/{info['total_gb']:.0f} GB ({pct:.0f}%)")

    w = get_terminal_width()
    print(f"\n{BOLD}{CYAN}{'=' * w}{RESET}")
    print(f"{DIM}{'Press Ctrl+C to exit live mode':^{w}}{RESET}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fortress Prime Operations Dashboard")
    parser.add_argument("--live", nargs="?", const=10, type=int, metavar="SECONDS",
                        help="Auto-refresh mode (default: every 10s)")
    args = parser.parse_args()

    if args.live:
        try:
            while True:
                print(CLEAR, end="")
                render()
                time.sleep(args.live)
        except KeyboardInterrupt:
            print(f"\n{DIM}Dashboard stopped.{RESET}")
    else:
        render()


if __name__ == "__main__":
    main()
