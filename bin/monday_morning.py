#!/usr/bin/env python3
"""
CROG-FORTRESS EXECUTIVE DASHBOARD
===================================
Run this on Monday morning (or any time) to see the health of the entire system.

Usage:
    python3 bin/monday_morning.py
    status                          (if alias is configured)

Checks:
    1. NAS connectivity and storage
    2. Code backup freshness
    3. Night Shift (Vision Indexer) last run
    4. Early Bird (Market Watcher) last briefing
    5. Sentinel (Gmail Watcher) heartbeat
"""

import os
import sys
import glob
import time
import shutil
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import SPARK_02_IP

# =============================================================================
# CONFIG
# =============================================================================

# ANSI Colors
GREEN  = '\033[92m'
RED    = '\033[91m'
YELLOW = '\033[93m'
RESET  = '\033[0m'
BOLD   = '\033[1m'

NAS_BASE   = "/mnt/fortress_nas/fortress_data/ai_brain"
LOG_DIR    = os.path.join(NAS_BASE, "logs")
BACKUP_DIR = os.path.join(NAS_BASE, "backups/code")


# =============================================================================
# HELPERS
# =============================================================================

def print_header(title):
    print(f"\n{BOLD}{'=' * 60}{RESET}")
    print(f"{BOLD}  {title}{RESET}")
    print(f"{BOLD}{'=' * 60}{RESET}")


def get_status(condition, label, detail=""):
    tag = f"[{GREEN} PASS {RESET}]" if condition else f"[{RED} FAIL {RESET}]"
    print(f"  {tag} {label:<25} {detail}")


def warn_status(label, detail=""):
    print(f"  [{YELLOW} WARN {RESET}] {label:<25} {detail}")


def check_log_freshness(log_path, max_hours=25):
    """Check if a log file was modified within max_hours."""
    if not os.path.exists(log_path):
        return False, "Log file missing"
    mtime = os.path.getmtime(log_path)
    age_hours = (time.time() - mtime) / 3600
    if age_hours > max_hours:
        return False, f"Stale ({age_hours:.0f}h old)"
    return True, f"Fresh ({age_hours:.1f}h ago)"


def scan_log_for_success(log_path, success_keywords, failure_keywords=None):
    """Scan the tail of a log file for success/failure markers."""
    if failure_keywords is None:
        failure_keywords = []
    if not os.path.exists(log_path):
        return False, "File not found"

    try:
        with open(log_path, "r", errors="replace") as f:
            lines = f.readlines()[-50:]
            content = "".join(lines)

            for kw in failure_keywords:
                if kw in content:
                    return False, f"Error found: '{kw}'"

            for kw in success_keywords:
                if kw in content:
                    return True, "Success confirmed"
    except Exception as e:
        return False, f"Read error: {e}"

    return False, "No success marker found"


def count_keyword_in_log(log_path, keyword):
    """Count occurrences of a keyword in a log file."""
    if not os.path.exists(log_path):
        return 0
    try:
        with open(log_path, "r", errors="replace") as f:
            return sum(1 for line in f if keyword in line)
    except Exception:
        return 0


# =============================================================================
# CHECKS
# =============================================================================

def check_system():
    print_header(f"SYSTEM STATUS: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # NAS Connectivity
    nas_ok = os.path.exists(NAS_BASE) and os.path.isdir(NAS_BASE)
    get_status(nas_ok, "NAS Connectivity", NAS_BASE if nas_ok else "MOUNT MISSING!")

    if not nas_ok:
        print(f"\n  {RED}CRITICAL: NAS NOT MOUNTED. Cannot check other systems.{RESET}")
        return False

    # Disk Space
    try:
        total, used, free = shutil.disk_usage(NAS_BASE)
        free_gb = free // (2**30)
        get_status(free_gb > 10, "Brain Storage", f"{free_gb:,} GB free")
    except Exception as e:
        warn_status("Brain Storage", f"Could not check: {e}")

    # Ollama (Captain)
    try:
        import requests
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in resp.json().get("models", [])]
        get_status(True, "Captain (Spark 2)", f"{len(models)} model(s) loaded")
    except Exception:
        get_status(False, "Captain (Spark 2)", "Ollama not responding")

    # Ollama (Muscle)
    try:
        import requests
        resp = requests.get(f"http://{SPARK_02_IP}:11434/api/tags", timeout=3)
        models = [m["name"] for m in resp.json().get("models", [])]
        get_status(True, "Muscle (Spark 1)", f"{len(models)} model(s) loaded")
    except Exception:
        warn_status("Muscle (Spark 1)", "Unreachable (vision indexing offline)")

    return True


def check_backups():
    print_header("BLACK BOX BACKUPS")

    backups = sorted(
        glob.glob(os.path.join(BACKUP_DIR, "fortress_code_*.tar.gz")),
        key=os.path.getmtime,
        reverse=True,
    )

    if not backups:
        get_status(False, "Code Archive", "No backups found!")
        return

    newest = backups[0]
    fresh, detail = check_log_freshness(newest, max_hours=26)
    size_mb = os.path.getsize(newest) / (1024 * 1024)
    get_status(fresh, "Latest Backup", f"{os.path.basename(newest)} ({size_mb:.0f} MB)")

    # Retention count
    print(f"          > Archives on NAS: {len(backups)}")


def check_night_shift():
    print_header("NIGHT SHIFT (Vision Indexer)")

    # Check system log for start/stop events
    sys_log = os.path.join(LOG_DIR, "vision_indexer", "night_shift_system.log")
    fresh_sys, age_sys = check_log_freshness(sys_log, max_hours=25)

    if not fresh_sys:
        get_status(False, "Execution", f"Did not run last night. {age_sys}")
        return

    ok_sys, msg_sys = scan_log_for_success(
        sys_log,
        success_keywords=["[END]", "[DONE]", "Night Shift complete"],
        failure_keywords=["[ABORT]"],
    )
    get_status(ok_sys, "Completion", msg_sys)

    # Check run log for processed images
    today = datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.now() - __import__("datetime").timedelta(days=1)).strftime("%Y%m%d")

    run_log = None
    for date_str in [today, yesterday]:
        candidate = os.path.join(LOG_DIR, "vision_indexer", f"night_shift_{date_str}.log")
        if os.path.exists(candidate):
            run_log = candidate
            break

    if run_log:
        processed = count_keyword_in_log(run_log, "[CAPTION]")
        skipped = count_keyword_in_log(run_log, "[SKIP]")
        failed = count_keyword_in_log(run_log, "[FAIL]")
        print(f"          > Captioned: {processed}  |  Skipped: {skipped}  |  Failed: {failed}")
    else:
        warn_status("Run Log", "No run log found for today/yesterday")

    # SQLite index total (if accessible)
    for db_candidate in [
        "/mnt/fortress_nas/Real_Estate_Assets/Properties/570_Morgan_Street/vision_index.db",
    ]:
        if os.path.exists(db_candidate):
            try:
                import sqlite3
                conn = sqlite3.connect(db_candidate)
                total = conn.execute("SELECT COUNT(*) FROM vision_index").fetchone()[0]
                conn.close()
                print(f"          > Total in Vision Index: {total:,}")
            except Exception:
                pass
            break


def check_market():
    print_header("EARLY BIRD (Market Watcher)")

    log = os.path.join(LOG_DIR, "market_watcher", "daily_run.log")

    fresh, age = check_log_freshness(log, max_hours=25)
    if not fresh:
        # Also check audit JSONL
        audit = os.path.join(LOG_DIR, "market_watcher_audit.jsonl")
        fresh_a, age_a = check_log_freshness(audit, max_hours=25)
        if fresh_a:
            get_status(True, "Briefing", f"Audit log fresh ({age_a})")
        else:
            get_status(False, "Execution", f"Did not run today. {age}")
        return

    ok, msg = scan_log_for_success(
        log,
        success_keywords=["DAILY MARKET BRIEF", "Draft created", "Synthesizing"],
        failure_keywords=["Traceback", "CRITICAL"],
    )
    get_status(ok, "Briefing", msg)


def check_sentinel():
    print_header("SENTINEL (Guest Emails)")

    log = os.path.join(LOG_DIR, "gmail_watcher", "cron_run.log")

    # Heartbeat: should be very fresh (runs every 10 min during business hours)
    now_hour = datetime.now().hour
    if 8 <= now_hour <= 22:
        max_hours = 0.5  # Should have run within 30 min during business hours
    else:
        max_hours = 12   # Off-hours: last run was end of business

    fresh, age = check_log_freshness(log, max_hours=max_hours)

    if 8 <= now_hour <= 22:
        get_status(fresh, "Heartbeat", f"Last pulse: {age}")
    else:
        # Off-hours: don't alarm, just inform
        if os.path.exists(log):
            _, age_info = check_log_freshness(log, max_hours=999)
            print(f"  [{YELLOW} IDLE {RESET}] {'Heartbeat':<25} Off-hours. Last run: {age_info}")
        else:
            warn_status("Heartbeat", "No log file yet")

    if os.path.exists(log):
        drafts = count_keyword_in_log(log, "Draft created")
        processed = count_keyword_in_log(log, "AI-Processed")
        print(f"          > Drafts Created: {drafts}  |  Emails Processed: {processed}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print(f"\n{BOLD}  CROG-FORTRESS EXECUTIVE DASHBOARD{RESET}")

    ok = check_system()
    if not ok:
        sys.exit(1)

    check_backups()
    check_night_shift()
    check_market()
    check_sentinel()

    print(f"\n{'=' * 60}")
    print(f"  Dashboard generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
