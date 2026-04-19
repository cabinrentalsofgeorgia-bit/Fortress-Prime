#!/usr/bin/env python3
"""
drift_alarm.py — Fortress-Prime working-tree drift detector.

Runs every 6 hours via fortress-drift-alarm.timer.
Checks four signals and escalates through WARN → ALERT.

Checks:
  1. Untracked file count (>10 WARN, >50 ALERT)
  2. Whole-repo secret scan (any match → ALERT always)
  3. Modified tracked file count (logged, no threshold)
  4. Any tracked file modified >48h ago without commit (>0 → WARN)

Output:
  Always  → /var/log/fortress-drift.log (append, with timestamp)
  WARN+   → ~/REPO_DRIFT_ALERT.md (overwrite with latest state)
  ALERT   → SMS to STAFF_NOTIFICATION_PHONE via Twilio

Usage:
  python3 drift_alarm.py [--dry-run]

  --dry-run : run all checks, log results, but skip SMS and skip writing
              REPO_DRIFT_ALERT.md

Environment (loaded from .env by systemd service):
  TWILIO_ACCOUNT_SID      required for SMS
  TWILIO_AUTH_TOKEN       required for SMS
  TWILIO_PHONE_NUMBER     from-number
  STAFF_NOTIFICATION_PHONE target phone for alerts
  REPO_ROOT               default: /home/admin/Fortress-Prime
  DRIFT_LOG               default: /var/log/fortress-drift.log
  ALERT_MD                default: ~/REPO_DRIFT_ALERT.md
  UNTRACKED_WARN          default: 10
  UNTRACKED_ALERT         default: 50
  MODIFIED_STALE_HOURS    default: 48
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("drift_alarm")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT         = Path(os.getenv("REPO_ROOT",            "/home/admin/Fortress-Prime"))
DRIFT_LOG         = Path(os.getenv("DRIFT_LOG",            "/var/log/fortress-drift.log"))
ALERT_MD          = Path(os.getenv("ALERT_MD",
                        str(Path.home() / "REPO_DRIFT_ALERT.md")))
UNTRACKED_WARN    = int(os.getenv("UNTRACKED_WARN",        "10"))
UNTRACKED_ALERT   = int(os.getenv("UNTRACKED_ALERT",       "50"))
STALE_HOURS       = int(os.getenv("MODIFIED_STALE_HOURS",  "48"))
PARITY_ALARM_DIR  = Path(os.getenv("PARITY_ALARM_DIR",    "/mnt/fortress_nas/parity-alarm"))

_DRIFT_LOG_FALLBACK         = Path.home() / "fortress-drift.log"
_DRIFT_LOG_WARNED_SENTINEL  = Path.home() / ".fortress_drift_perm_warned"

TWILIO_SID    = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM   = os.getenv("TWILIO_PHONE_NUMBER")
ALERT_PHONE   = os.getenv("STAFF_NOTIFICATION_PHONE")

_MINER_BOT_PASS_PREFIX = "190Antioch"    # split so this file doesn't self-trigger
_MINER_BOT_PASS_SUFFIX = "CemeteryRD"
SECRET_PATTERN = re.compile(
    r"sk-fortress-[a-zA-Z0-9]{20}"
    r"|nvapi-[a-zA-Z0-9]{20}"
    r"|" + re.escape(_MINER_BOT_PASS_PREFIX + _MINER_BOT_PASS_SUFFIX)
    + r"|password\s*=\s*['\"][a-zA-Z0-9]{6,}"
)

EXCLUDE_DIRS = [".git", "node_modules", ".venv", "venv", "__pycache__",
                ".uv-venv", "chroma_data", "fortress_qdrant_data",
                ".cache", "huggingface"]

# Paths that are gitignored-by-design and will always contain credentials.
# Relative to REPO_ROOT. Scanning them produces permanent noise with no fix.
_EXCLUDE_PATHS: frozenset[str] = frozenset({
    ".env",                          # root .env — gitignored, has nvapi key + DB creds
    ".env.security",                 # gitignored gateway secrets
    "litellm_config.yaml",           # gitignored, has live LiteLLM master key
    "fortress-guest-platform/.env",  # gitignored app env — has API keys
    "crog-gateway/.env",             # gitignored gateway env
})

# Lines that contain placeholder text — not real secrets.
_FALSE_POSITIVE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"Fortress-Prime-Test-Password-123"),   # test fixture
    re.compile(r"REPLACE_WITH_ROTATED_SECRET"),        # SQL placeholder
    re.compile(r"REPLACE_ME"),                         # generic placeholder
    re.compile(r"<see MINER_BOT_DB_PASSWORD"),         # doc reference
)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_untracked() -> tuple[int, str]:
    """Return (count, level) — level is '', 'WARN', or 'ALERT'."""
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    count = len([l for l in result.stdout.splitlines() if l.strip()])
    level = ""
    if count > UNTRACKED_ALERT:
        level = "ALERT"
    elif count > UNTRACKED_WARN:
        level = "WARN"
    return count, level


def check_secrets() -> list[str]:
    """Return list of 'file:line: redacted_match' strings. Any hit → ALERT."""
    hits: list[str] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fname in files:
            if not any(fname.endswith(ext) for ext in
                       (".py", ".sh", ".yaml", ".yml", ".env", ".json",
                        ".ts", ".tsx", ".js", ".md", ".txt", ".sql")):
                continue
            fpath = Path(root) / fname
            try:
                rel = fpath.relative_to(REPO_ROOT)
            except ValueError:
                continue
            # Skip gitignored-by-design files (have credentials by necessity)
            if str(rel) in _EXCLUDE_PATHS:
                continue
            try:
                text = fpath.read_text(errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    m = SECRET_PATTERN.search(line)
                    if not m:
                        continue
                    # Skip known false positives (placeholders / test fixtures)
                    if any(fp.search(line) for fp in _FALSE_POSITIVE_PATTERNS):
                        continue
                    redacted = line[:m.start()] + "[REDACTED]" + line[m.end():]
                    hits.append(f"{rel}:{i}: {redacted.strip()[:120]}")
            except (PermissionError, OSError):
                pass
    return hits


def check_parity_alarms() -> list[Path]:
    """Return list of unacknowledged parity alarm files in PARITY_ALARM_DIR."""
    try:
        if not PARITY_ALARM_DIR.exists():
            return []
        return sorted(PARITY_ALARM_DIR.glob("alarm-*.error"))
    except OSError:
        return []


def check_modified() -> tuple[int, list[str]]:
    """Return (count, stale_files) where stale = modified >STALE_HOURS ago."""
    result = subprocess.run(
        ["git", "status", "--short"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    modified = [l[3:].strip() for l in result.stdout.splitlines()
                if re.match(r"^ M|^M ", l)]
    count = len(modified)

    stale: list[str] = []
    threshold = time.time() - STALE_HOURS * 3600
    for rel_path in modified:
        fpath = REPO_ROOT / rel_path
        try:
            mtime = fpath.stat().st_mtime
            if mtime < threshold:
                age_h = (time.time() - mtime) / 3600
                stale.append(f"{rel_path} ({age_h:.0f}h ago)")
        except OSError:
            pass
    return count, stale


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def _append_log(message: str) -> None:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} {message}\n"
    try:
        with open(DRIFT_LOG, "a") as fh:
            fh.write(line)
    except OSError:
        # Warn once across runs via a sentinel file; subsequent runs fall back silently.
        if not _DRIFT_LOG_WARNED_SENTINEL.exists():
            log.warning(
                "Cannot write to %s — falling back to %s. "
                "Fix: sudo touch %s && sudo chown admin:admin %s",
                DRIFT_LOG, _DRIFT_LOG_FALLBACK, DRIFT_LOG, DRIFT_LOG,
            )
            try:
                _DRIFT_LOG_WARNED_SENTINEL.touch()
            except OSError:
                pass
        with open(_DRIFT_LOG_FALLBACK, "a") as fh:
            fh.write(line)


def _write_alert_md(report: str) -> None:
    ALERT_MD.write_text(report)
    log.info("Alert written to %s", ALERT_MD)


def _send_sms(message: str) -> bool:
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, ALERT_PHONE]):
        log.warning("Twilio not configured — cannot send SMS alert")
        return False
    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        msg = client.messages.create(
            body=message[:1600],
            from_=TWILIO_FROM,
            to=ALERT_PHONE,
        )
        log.info("SMS sent: SID=%s status=%s", msg.sid, msg.status)
        return True
    except Exception as exc:
        log.error("SMS send failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(dry_run: bool, why: bool = False) -> int:
    now = datetime.now(tz=timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    log.info("drift_alarm starting ts=%s dry_run=%s repo=%s", ts, dry_run, REPO_ROOT)

    # --- Run checks ---
    untracked_count, untracked_level = check_untracked()
    secret_hits                       = check_secrets()
    modified_count, stale_files       = check_modified()
    parity_alarm_files                = check_parity_alarms()

    if parity_alarm_files:
        log.warning(
            "parity_alarm_detected count=%d files=%s",
            len(parity_alarm_files),
            [f.name for f in parity_alarm_files[:5]],
        )

    # --- Determine overall level ---
    level = ""
    if secret_hits or untracked_level == "ALERT":
        level = "ALERT"
    elif untracked_level == "WARN" or stale_files or parity_alarm_files:
        level = "WARN"

    # --- Log summary ---
    summary = (
        f"[{level or 'OK'}] untracked={untracked_count} "
        f"secrets={len(secret_hits)} modified={modified_count} "
        f"stale={len(stale_files)} parity_alarms={len(parity_alarm_files)}"
    )
    _append_log(summary)
    log.info(summary)

    if level == "":
        log.info("No drift detected.")
        return 0

    # --- Build full report ---
    lines = [
        f"# Fortress-Prime Drift Alarm — {ts}",
        f"",
        f"**Level:** {level}",
        f"**Repo:** {REPO_ROOT}",
        f"",
        f"## Check 1: Untracked files",
        f"Count: {untracked_count}  (WARN>{UNTRACKED_WARN}, ALERT>{UNTRACKED_ALERT})",
        f"Status: {untracked_level or 'OK'}",
        f"",
        f"## Check 2: Secret scan",
        f"Hits: {len(secret_hits)}",
    ]
    for h in secret_hits[:20]:
        lines.append(f"  - {h}")
    if len(secret_hits) > 20:
        lines.append(f"  ... and {len(secret_hits)-20} more")

    lines += [
        f"",
        f"## Check 3: Modified tracked files",
        f"Count: {modified_count}",
        f"",
        f"## Check 4: Stale modified files (>{STALE_HOURS}h without commit)",
        f"Count: {len(stale_files)}",
    ]
    for s in stale_files[:20]:
        lines.append(f"  - {s}")

    lines += [
        f"",
        f"## Check 5: Qdrant dual-write parity alarms",
        f"Count: {len(parity_alarm_files)}",
        f"Dir: {PARITY_ALARM_DIR}",
    ]
    for f in parity_alarm_files[:5]:
        lines.append(f"  - {f.name}")
    if len(parity_alarm_files) > 5:
        lines.append(f"  ... and {len(parity_alarm_files)-5} more")

    report = "\n".join(lines) + "\n"
    log.warning("Drift detected — level=%s", level)
    if why:
        print(f"\n{'='*60}")
        print(f"WHY: drift level={level}")
        if secret_hits:
            print(f"\nSecret hits ({len(secret_hits)}):")
            for h in secret_hits:
                # Show file:line and redacted context for fast triage
                parts = h.split(":", 2)
                fpath, lineno = parts[0], parts[1] if len(parts) > 1 else "?"
                ctx = parts[2].strip() if len(parts) > 2 else ""
                print(f"  {fpath}:{lineno}  {ctx[:100]}")
        if stale_files:
            print(f"\nStale files ({len(stale_files)}):")
            for s in stale_files:
                print(f"  {s}")
        print(f"{'='*60}\n")
    else:
        for h in secret_hits:
            log.warning("SECRET HIT: %s", h)
        for s in stale_files:
            log.warning("STALE: %s", s)

    if not dry_run:
        _write_alert_md(report)

        if level == "ALERT":
            secret_summary = f"{len(secret_hits)} secret hit(s)" if secret_hits else ""
            untracked_summary = f"{untracked_count} untracked files" if untracked_level == "ALERT" else ""
            parts = [p for p in [secret_summary, untracked_summary] if p]
            sms_body = (
                f"FORTRESS DRIFT ALERT [{ts[:10]}]: "
                + ", ".join(parts)
                + f". Check ~/REPO_DRIFT_ALERT.md on spark-node-2."
            )
            _send_sms(sms_body)
    else:
        log.info("[DRY RUN] Would write REPO_DRIFT_ALERT.md and send SMS if ALERT")

    return 1 if level == "ALERT" else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fortress-Prime drift alarm")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run checks but skip SMS and alert file write")
    parser.add_argument("--why", action="store_true",
                        help="Print each hit with file:line context for fast triage")
    args = parser.parse_args()
    return run(args.dry_run, args.why)


if __name__ == "__main__":
    sys.exit(main())
