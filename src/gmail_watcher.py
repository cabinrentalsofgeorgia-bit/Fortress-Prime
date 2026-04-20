"""
Fortress Prime — Gmail Watcher Service
=========================================
Bridges the air gap between the AI pipeline and the real Gmail inbox.

WHAT IT DOES:
    Watches Gmail for unread guest emails, runs them through the full
    guest_reply_engine pipeline, and saves the AI's response as a DRAFT
    in Gmail — tagged and labeled for human review.

WHAT IT DOES NOT DO:
    It NEVER sends emails. Drafts only. You wake up, check the
    "AI-Drafts" label, review, and hit send yourself.

SAFETY MODEL:
    1. No gmail.send scope — physically cannot send.
    2. Confidence threshold — low-confidence results get flagged, not drafted.
    3. Emergency escalation — emergency-tone emails skip drafting, get
       labeled "AI-Human-Help-Needed" for immediate human attention.
    4. Processed label — prevents double-processing.
    5. Dry-run mode — test the full pipeline without touching Gmail.
    6. Sender allowlist — only processes emails from known platforms/guests.

LABELS MANAGED:
    AI-Drafted        — Thread has an AI-generated draft ready for review
    AI-Processed      — Original email has been processed (skip on next run)
    AI-Human-Help     — Needs human review (emergency, low confidence, unknown topic)

ARCHITECTURE:
    Gmail Inbox (unread, not AI-Processed)
         |
         v
    Sender Filter (booking platforms, known guests, or all)
         |
         v
    guest_reply_engine.process_email()
         |
         ├── Confidence OK + not emergency
         |       -> Create Gmail Draft in thread
         |       -> Label thread: AI-Drafted
         |       -> Label original: AI-Processed
         |
         └── Low confidence OR emergency
                 -> Label thread: AI-Human-Help
                 -> Label original: AI-Processed
                 -> Optional: Push notification

USAGE:
    # One-time auth setup
    python -m src.gmail_auth

    # Single pass (process all pending, then exit)
    python -m src.gmail_watcher --cabin rolling_river

    # Continuous watch (every 5 minutes)
    python -m src.gmail_watcher --cabin rolling_river --watch --interval 300

    # Dry run (no Gmail writes, just show what would happen)
    python -m src.gmail_watcher --cabin rolling_river --dry-run

    # Filter specific senders
    python -m src.gmail_watcher --cabin rolling_river --senders airbnb,vrbo

    # With LLM dry run too (no Gmail writes, no LLM calls)
    python -m src.gmail_watcher --cabin rolling_river --dry-run --no-llm
"""

import sys
import os
import json
import time
import base64
import logging
import argparse
import re
from pathlib import Path
from email.mime.text import MIMEText
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.gmail_auth import get_gmail_service
from src.guest_reply_engine import process_email, ReplyResult
from src.fortress_paths import paths as fortress_paths

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fortress.gmail_watcher")


# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class WatcherConfig:
    """Configuration for the Gmail Watcher."""

    # Cabin to use for context slicing
    cabin_slug: str = "rolling_river"

    # Gmail query filters
    gmail_query: str = "label:INBOX is:unread -label:AI-Processed"

    # Maximum emails to process per run (safety limit)
    max_per_run: int = 20

    # Confidence threshold — below this, flag for human help
    confidence_threshold: float = 0.3

    # Labels
    label_drafted: str = "AI-Drafted"
    label_processed: str = "AI-Processed"
    label_human_help: str = "AI-Human-Help"

    # Sender allowlist (empty = process all)
    # Format: list of email domains or addresses
    sender_allowlist: List[str] = field(default_factory=lambda: [
        # Booking platforms
        "airbnb.com",
        "vrbo.com",
        "booking.com",
        "homeaway.com",
        "expedia.com",
        "houfy.com",
        "hipcamp.com",
        # Add known guest domains or specific addresses here
    ])

    # Whether to filter senders (False = process ALL unread)
    filter_senders: bool = True

    # Watch mode settings
    watch_interval: int = 300  # seconds (5 minutes)

    # LLM settings
    model_override: Optional[str] = None
    skip_llm: bool = False  # If True, runs pipeline without LLM call

    # Safety
    dry_run: bool = False  # If True, don't touch Gmail at all
    verbose: bool = True

    # Draft formatting
    draft_prefix: str = "[AI Draft — Review Before Sending]\n\n"
    draft_suffix: str = (
        "\n\n---\n"
        "Generated by Fortress Prime AI | "
        "Topic: {topic} | Tone: {tone} | "
        "Confidence: {confidence:.0%} | Run: {run_id}"
    )


# =============================================================================
# LABEL MANAGEMENT
# =============================================================================

_label_cache: Dict[str, str] = {}  # name -> label_id


def ensure_labels(service, config: WatcherConfig) -> Dict[str, str]:
    """
    Create Gmail labels if they don't exist. Returns {name: label_id}.
    """
    global _label_cache

    if _label_cache:
        return _label_cache

    # Fetch existing labels
    results = service.users().labels().list(userId="me").execute()
    existing = {
        label["name"]: label["id"]
        for label in results.get("labels", [])
    }

    required = [config.label_drafted, config.label_processed, config.label_human_help]

    for label_name in required:
        if label_name in existing:
            _label_cache[label_name] = existing[label_name]
            logger.debug(f"Label exists: {label_name} ({existing[label_name]})")
        else:
            # Create the label
            body = {
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
                "color": _get_label_color(label_name),
            }
            created = service.users().labels().create(
                userId="me", body=body
            ).execute()
            _label_cache[label_name] = created["id"]
            logger.info(f"Created label: {label_name} ({created['id']})")

    return _label_cache


def _get_label_color(label_name: str) -> Dict[str, str]:
    """Assign colors to labels for visual distinction in Gmail."""
    colors = {
        "AI-Drafted": {
            "backgroundColor": "#16a765",  # Green
            "textColor": "#ffffff",
        },
        "AI-Processed": {
            "backgroundColor": "#4986e7",  # Blue
            "textColor": "#ffffff",
        },
        "AI-Human-Help": {
            "backgroundColor": "#cc3a21",  # Red
            "textColor": "#ffffff",
        },
    }
    return colors.get(label_name, {
        "backgroundColor": "#999999",
        "textColor": "#ffffff",
    })


# =============================================================================
# EMAIL FETCHING & PARSING
# =============================================================================

@dataclass
class InboundEmail:
    """Parsed inbound email with metadata."""
    message_id: str
    thread_id: str
    sender: str
    sender_email: str
    subject: str
    body: str
    date: str
    snippet: str
    labels: List[str] = field(default_factory=list)


def fetch_unprocessed(
    service,
    config: WatcherConfig,
) -> List[InboundEmail]:
    """
    Fetch unread, unprocessed emails from Gmail.

    Returns:
        List of InboundEmail objects ready for processing.
    """
    try:
        results = service.users().messages().list(
            userId="me",
            q=config.gmail_query,
            maxResults=config.max_per_run,
        ).execute()
    except Exception as e:
        logger.error(f"Failed to query Gmail: {e}")
        return []

    messages = results.get("messages", [])
    if not messages:
        logger.info("No unprocessed emails found.")
        return []

    logger.info(f"Found {len(messages)} unprocessed email(s).")

    emails = []
    for msg_ref in messages:
        try:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="full",
            ).execute()
            parsed = _parse_message(msg)
            if parsed:
                emails.append(parsed)
        except Exception as e:
            logger.warning(f"Failed to fetch message {msg_ref['id']}: {e}")

    return emails


def _parse_message(msg: Dict) -> Optional[InboundEmail]:
    """Parse a Gmail API message into an InboundEmail."""
    headers = {
        h["name"].lower(): h["value"]
        for h in msg.get("payload", {}).get("headers", [])
    }

    sender_raw = headers.get("from", "")
    sender_email = _extract_email(sender_raw)
    subject = headers.get("subject", "(No Subject)")
    date = headers.get("date", "")

    # Extract body text
    body = _extract_body(msg.get("payload", {}))

    if not body:
        logger.debug(f"Skipping message {msg['id']} — no text body found.")
        return None

    return InboundEmail(
        message_id=msg["id"],
        thread_id=msg.get("threadId", msg["id"]),
        sender=sender_raw,
        sender_email=sender_email,
        subject=subject,
        body=body,
        date=date,
        snippet=msg.get("snippet", ""),
        labels=msg.get("labelIds", []),
    )


def _extract_email(sender_str: str) -> str:
    """Extract the email address from a 'Name <email@domain.com>' string."""
    match = re.search(r'<([^>]+)>', sender_str)
    if match:
        return match.group(1).lower()
    # Might just be a raw email
    if "@" in sender_str:
        return sender_str.strip().lower()
    return sender_str


def _extract_body(payload: Dict) -> str:
    """
    Recursively extract the plain-text body from a Gmail message payload.
    Prefers text/plain over text/html. Handles multipart messages.
    """
    mime_type = payload.get("mimeType", "")

    # Direct text/plain body
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    # Multipart — recurse into parts
    if mime_type.startswith("multipart/"):
        parts = payload.get("parts", [])
        # First pass: look for text/plain
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        # Second pass: recurse into nested multiparts
        for part in parts:
            result = _extract_body(part)
            if result:
                return result

    # Fallback: try text/html and strip tags (basic)
    if mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return _strip_html(html)

    return ""


def _strip_html(html: str) -> str:
    """Basic HTML tag stripping for fallback body extraction."""
    # Remove script/style blocks
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Decode common entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    return text


# =============================================================================
# SENDER FILTERING
# =============================================================================

def is_allowed_sender(email_addr: str, config: WatcherConfig) -> bool:
    """
    Check if the sender is on the allowlist.
    If filter_senders is False, all senders are allowed.
    """
    if not config.filter_senders:
        return True

    if not config.sender_allowlist:
        return True

    email_lower = email_addr.lower()

    for allowed in config.sender_allowlist:
        allowed_lower = allowed.lower()
        # Match full email address
        if email_lower == allowed_lower:
            return True
        # Match domain
        if email_lower.endswith(f"@{allowed_lower}"):
            return True
        # Match domain suffix (e.g., "airbnb.com" matches "noreply@airbnb.com")
        if allowed_lower.startswith("@"):
            if email_lower.endswith(allowed_lower):
                return True

    return False


# =============================================================================
# GMAIL ACTIONS — Draft Creation & Labeling
# =============================================================================

def create_draft(
    service,
    thread_id: str,
    to_address: str,
    subject: str,
    body: str,
    config: WatcherConfig,
    result: ReplyResult,
) -> Optional[str]:
    """
    Create a Gmail draft reply in the specified thread.

    Returns:
        Draft ID if successful, None if failed.
    """
    # Format the draft body with metadata
    formatted_body = config.draft_prefix + body
    if config.draft_suffix:
        formatted_body += config.draft_suffix.format(
            topic=result.topic,
            tone=result.tone,
            confidence=result.topic_confidence,
            run_id=result.run_id,
        )

    # Build MIME message
    message = MIMEText(formatted_body)
    message["to"] = to_address
    message["subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        draft = service.users().drafts().create(
            userId="me",
            body={
                "message": {
                    "raw": raw,
                    "threadId": thread_id,
                }
            },
        ).execute()

        draft_id = draft.get("id", "unknown")
        logger.info(f"Draft created: {draft_id} (thread: {thread_id})")
        return draft_id

    except Exception as e:
        logger.error(f"Failed to create draft: {e}")
        return None


def apply_labels(
    service,
    message_id: str,
    add_labels: List[str],
    remove_labels: Optional[List[str]] = None,
) -> bool:
    """
    Apply (and optionally remove) labels on a Gmail message.

    Args:
        message_id: The Gmail message ID
        add_labels: List of label IDs to add
        remove_labels: List of label IDs to remove (optional)
    """
    body = {
        "addLabelIds": add_labels,
        "removeLabelIds": remove_labels or [],
    }

    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body=body,
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Failed to apply labels to {message_id}: {e}")
        return False


# =============================================================================
# ESCALATION / NOTIFICATION
# =============================================================================

def should_escalate(result: ReplyResult, config: WatcherConfig) -> bool:
    """
    Determine if an email needs human intervention instead of auto-drafting.

    Escalation triggers:
        - Emergency tone (guest safety issue)
        - Topic is "general" with low confidence (system doesn't understand)
        - Topic confidence below threshold
        - LLM call failed
    """
    # Always escalate emergencies — human must handle safety issues
    if result.escalation_required or result.tone == "emergency":
        return True

    # Low confidence — system isn't sure what the guest is asking
    if result.topic_confidence < config.confidence_threshold:
        return True

    # Unknown topic with no examples — risky to auto-draft
    if result.topic == "general" and result.examples_loaded == 0:
        return True

    # LLM failure
    if not result.success:
        return True

    return False


def send_notification(
    email: InboundEmail,
    result: ReplyResult,
    reason: str,
    config: WatcherConfig,
):
    """
    Send a push notification for escalated emails.

    Currently logs the notification. Extend with:
        - Pushover API (recommended for mobile push)
        - Twilio SMS
        - Slack webhook
        - Telegram bot
    """
    logger.warning(
        f"ESCALATION: {reason} | "
        f"From: {email.sender_email} | "
        f"Subject: {email.subject} | "
        f"Topic: {result.topic} | "
        f"Tone: {result.tone}"
    )

    # ── Pushover Integration (uncomment and configure) ──
    #
    # import requests
    # PUSHOVER_TOKEN = os.getenv("PUSHOVER_APP_TOKEN")
    # PUSHOVER_USER = os.getenv("PUSHOVER_USER_KEY")
    #
    # if PUSHOVER_TOKEN and PUSHOVER_USER:
    #     try:
    #         requests.post("https://api.pushover.net/1/messages.json", data={
    #             "token": PUSHOVER_TOKEN,
    #             "user": PUSHOVER_USER,
    #             "title": f"Fortress: {reason}",
    #             "message": (
    #                 f"From: {email.sender_email}\n"
    #                 f"Subject: {email.subject}\n"
    #                 f"Topic: {result.topic} | Tone: {result.tone}\n"
    #                 f"Preview: {email.snippet[:100]}"
    #             ),
    #             "priority": 1 if result.tone == "emergency" else 0,
    #             "sound": "siren" if result.tone == "emergency" else "pushover",
    #         }, timeout=10)
    #     except Exception as e:
    #         logger.error(f"Pushover notification failed: {e}")


# =============================================================================
# PROCESSING LOG — Persistent record of all Gmail processing
# =============================================================================

WATCH_LOG_DIR = fortress_paths.gmail_watch_dir


def log_watch_event(
    email: InboundEmail,
    result: ReplyResult,
    action: str,
    draft_id: Optional[str] = None,
    config: Optional[WatcherConfig] = None,
):
    """Write a processing event to the watcher log."""
    WATCH_LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = WATCH_LOG_DIR / f"watch_{time.strftime('%Y%m%d')}.jsonl"

    entry = {
        "timestamp": datetime.now().isoformat(),
        "message_id": email.message_id,
        "thread_id": email.thread_id,
        "sender": email.sender_email,
        "subject": email.subject,
        "action": action,  # "drafted", "escalated", "skipped", "error"
        "draft_id": draft_id,
        "run_id": result.run_id if result else None,
        "topic": result.topic if result else None,
        "tone": result.tone if result else None,
        "confidence": result.topic_confidence if result else None,
        "escalation": result.escalation_required if result else None,
        "tokens_used": result.context_tokens if result else None,
        "tokens_saved": result.tokens_saved if result else None,
        "duration_ms": result.duration_ms if result else None,
        "success": result.success if result else None,
        "cabin": config.cabin_slug if config else None,
    }

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        logger.warning(f"Failed to write watch log: {e}")


# =============================================================================
# MAIN PROCESSING LOOP
# =============================================================================

def process_inbox(
    service,
    config: WatcherConfig,
) -> Dict[str, int]:
    """
    Process all pending emails in one pass.

    Returns:
        Dict with counts: {"processed", "drafted", "escalated", "skipped", "errors"}
    """
    stats = {"processed": 0, "drafted": 0, "escalated": 0, "skipped": 0, "errors": 0}

    # Ensure labels exist
    if not config.dry_run:
        labels = ensure_labels(service, config)
    else:
        labels = {
            config.label_drafted: "DRY_RUN",
            config.label_processed: "DRY_RUN",
            config.label_human_help: "DRY_RUN",
        }

    # Fetch unprocessed emails
    emails = fetch_unprocessed(service, config)
    if not emails:
        return stats

    for email in emails:
        stats["processed"] += 1

        # ── SENDER FILTER ──
        if config.filter_senders and not is_allowed_sender(email.sender_email, config):
            logger.info(
                f"Skipped (sender not in allowlist): {email.sender_email} — "
                f"\"{email.subject}\""
            )
            stats["skipped"] += 1
            continue

        logger.info(
            f"Processing: {email.sender_email} — \"{email.subject}\" "
            f"({len(email.body)} chars)"
        )

        # ── RUN AI PIPELINE ──
        try:
            result = process_email(
                cabin_slug=config.cabin_slug,
                guest_email=email.body,
                model=config.model_override,
                dry_run=config.skip_llm,
                verbose=config.verbose,
            )
        except Exception as e:
            logger.error(f"Pipeline error for {email.message_id}: {e}")
            stats["errors"] += 1
            log_watch_event(email, None, "error", config=config)
            continue

        # ── ESCALATION CHECK ──
        if should_escalate(result, config):
            reason = _get_escalation_reason(result, config)
            logger.warning(f"Escalating: {reason}")

            if not config.dry_run:
                # Apply AI-Human-Help + AI-Processed labels
                apply_labels(
                    service,
                    email.message_id,
                    add_labels=[
                        labels[config.label_human_help],
                        labels[config.label_processed],
                    ],
                )

            send_notification(email, result, reason, config)
            log_watch_event(email, result, "escalated", config=config)
            stats["escalated"] += 1

            if config.verbose:
                print(f"  => ESCALATED: {reason}")
            continue

        # ── CREATE DRAFT ──
        draft_id = None
        if not config.dry_run and result.success:
            draft_id = create_draft(
                service=service,
                thread_id=email.thread_id,
                to_address=email.sender_email,
                subject=email.subject,
                body=result.draft,
                config=config,
                result=result,
            )

            if draft_id:
                # Apply AI-Drafted + AI-Processed labels
                apply_labels(
                    service,
                    email.message_id,
                    add_labels=[
                        labels[config.label_drafted],
                        labels[config.label_processed],
                    ],
                )
                stats["drafted"] += 1
            else:
                stats["errors"] += 1
        elif config.dry_run:
            stats["drafted"] += 1
            if config.verbose:
                print(f"  => DRY RUN: Would create draft for {email.sender_email}")
                if result.draft and not result.draft.startswith("[DRY RUN"):
                    print(f"     Draft preview: {result.draft[:150]}...")

        log_watch_event(email, result, "drafted" if draft_id or config.dry_run else "error",
                        draft_id=draft_id, config=config)

        if config.verbose:
            print(f"  => {result.summary()}")

    return stats


def _get_escalation_reason(result: ReplyResult, config: WatcherConfig) -> str:
    """Build a human-readable escalation reason."""
    reasons = []
    if result.tone == "emergency":
        reasons.append("EMERGENCY tone detected")
    if result.escalation_required:
        reasons.append("escalation flag set")
    if result.topic_confidence < config.confidence_threshold:
        reasons.append(f"low confidence ({result.topic_confidence:.2f})")
    if result.topic == "general" and result.examples_loaded == 0:
        reasons.append("unknown topic, no examples")
    if not result.success:
        reasons.append(f"LLM error: {result.error}")
    return " + ".join(reasons) if reasons else "unknown"


# =============================================================================
# WATCH MODE — Continuous polling loop
# =============================================================================

def watch_loop(service, config: WatcherConfig):
    """
    Run the watcher in continuous mode, polling Gmail at regular intervals.
    """
    logger.info("=" * 60)
    logger.info("  FORTRESS PRIME — GMAIL WATCHER (LIVE)")
    logger.info("=" * 60)
    logger.info(f"  Cabin:    {config.cabin_slug}")
    logger.info(f"  Interval: {config.watch_interval}s")
    logger.info(f"  Filter:   {'sender allowlist' if config.filter_senders else 'all emails'}")
    logger.info(f"  Mode:     {'DRY RUN' if config.dry_run else 'LIVE'}")
    logger.info(f"  LLM:      {'disabled' if config.skip_llm else config.model_override or 'default'}")
    logger.info("=" * 60)
    logger.info("Press Ctrl+C to stop.\n")

    cycle = 0
    total_stats = {"processed": 0, "drafted": 0, "escalated": 0, "skipped": 0, "errors": 0}

    try:
        while True:
            cycle += 1
            logger.info(f"─── Cycle {cycle} ({datetime.now().strftime('%H:%M:%S')}) ───")

            stats = process_inbox(service, config)

            for key in total_stats:
                total_stats[key] += stats[key]

            if stats["processed"] > 0:
                logger.info(
                    f"Cycle {cycle} complete: "
                    f"{stats['drafted']} drafted, "
                    f"{stats['escalated']} escalated, "
                    f"{stats['skipped']} skipped, "
                    f"{stats['errors']} errors"
                )
            else:
                logger.info(f"Cycle {cycle}: inbox clear.")

            logger.info(f"Next check in {config.watch_interval}s...\n")
            time.sleep(config.watch_interval)

    except KeyboardInterrupt:
        logger.info("\n")
        logger.info("=" * 60)
        logger.info("  GMAIL WATCHER STOPPED")
        logger.info("=" * 60)
        logger.info(f"  Total cycles:    {cycle}")
        logger.info(f"  Total processed: {total_stats['processed']}")
        logger.info(f"  Total drafted:   {total_stats['drafted']}")
        logger.info(f"  Total escalated: {total_stats['escalated']}")
        logger.info(f"  Total skipped:   {total_stats['skipped']}")
        logger.info(f"  Total errors:    {total_stats['errors']}")
        logger.info("=" * 60)


# =============================================================================
# CLI INTERFACE
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fortress Prime — Gmail Watcher Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  # One-time auth setup
  python -m src.gmail_auth

  # Single pass — process pending emails, then exit
  python -m src.gmail_watcher --cabin rolling_river

  # Continuous watch (every 5 minutes)
  python -m src.gmail_watcher --cabin rolling_river --watch

  # Dry run (no Gmail modifications)
  python -m src.gmail_watcher --cabin rolling_river --dry-run

  # Full dry run (no Gmail, no LLM)
  python -m src.gmail_watcher --cabin rolling_river --dry-run --no-llm

  # Custom interval (every 2 minutes)
  python -m src.gmail_watcher --cabin rolling_river --watch --interval 120

  # Process ALL senders (no allowlist)
  python -m src.gmail_watcher --cabin rolling_river --all-senders

  # Only process specific senders
  python -m src.gmail_watcher --cabin rolling_river --senders airbnb.com,vrbo.com

  # Override LLM model for faster testing
  python -m src.gmail_watcher --cabin rolling_river --model deepseek-r1:8b

LABELS:
  AI-Drafted     — Draft created, ready for human review
  AI-Processed   — Email has been processed (won't be re-processed)
  AI-Human-Help  — Needs human attention (emergency, low confidence)

SAFETY:
  - NEVER sends emails. Creates drafts only.
  - gmail.send scope is NOT requested.
  - Emergencies are never auto-drafted — always escalated.
  - Low-confidence results are flagged for human review.
        """,
    )

    parser.add_argument(
        "--cabin", "-c",
        type=str,
        default="rolling_river",
        help="Cabin slug for context slicing (default: rolling_river)",
    )
    parser.add_argument(
        "--watch", "-w",
        action="store_true",
        help="Continuous watch mode (poll every --interval seconds)",
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=300,
        help="Polling interval in seconds (default: 300 = 5 min)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't modify Gmail (no labels, no drafts)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM call (pipeline dry-run mode)",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        help="Override LLM model (e.g., deepseek-r1:8b)",
    )
    parser.add_argument(
        "--all-senders",
        action="store_true",
        help="Process emails from ALL senders (no allowlist)",
    )
    parser.add_argument(
        "--senders",
        type=str,
        help="Comma-separated sender domains/addresses to allow",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=20,
        help="Max emails per run (default: 20)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.3,
        help="Confidence threshold for auto-drafting (default: 0.3)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress verbose output",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current label stats and exit",
    )

    return parser


def show_status(service, config: WatcherConfig):
    """Show current Gmail label counts and watcher state."""
    labels = ensure_labels(service, config)

    print("=" * 60)
    print("  FORTRESS PRIME — GMAIL WATCHER STATUS")
    print("=" * 60)

    # Count emails per label
    for label_name, label_id in labels.items():
        try:
            result = service.users().messages().list(
                userId="me",
                q=f"label:{label_name.replace(' ', '-')}",
                maxResults=1,
            ).execute()
            count = result.get("resultSizeEstimate", 0)
            print(f"  {label_name:<20} {count:>5} emails")
        except Exception:
            print(f"  {label_name:<20}     ? (query failed)")

    # Unprocessed count
    try:
        result = service.users().messages().list(
            userId="me",
            q=config.gmail_query,
            maxResults=1,
        ).execute()
        pending = result.get("resultSizeEstimate", 0)
        print(f"\n  Pending (unprocessed): {pending}")
    except Exception:
        pass

    # Watch log stats
    today_log = WATCH_LOG_DIR / f"watch_{time.strftime('%Y%m%d')}.jsonl"
    if today_log.exists():
        with open(today_log) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        actions = {}
        for e in entries:
            action = e.get("action", "unknown")
            actions[action] = actions.get(action, 0) + 1
        print(f"\n  Today's log ({len(entries)} entries):")
        for action, count in sorted(actions.items()):
            print(f"    {action:<15} {count:>5}")
    else:
        print(f"\n  No watch log for today yet.")

    print(f"\n{'=' * 60}")


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Build config
    config = WatcherConfig(
        cabin_slug=args.cabin,
        dry_run=args.dry_run,
        skip_llm=args.no_llm,
        model_override=args.model,
        watch_interval=args.interval,
        max_per_run=args.max,
        confidence_threshold=args.threshold,
        verbose=not args.quiet,
    )

    if args.all_senders:
        config.filter_senders = False

    if args.senders:
        config.sender_allowlist = [s.strip() for s in args.senders.split(",")]
        config.filter_senders = True

    # Connect to Gmail
    try:
        service = get_gmail_service()
    except FileNotFoundError:
        sys.exit(1)
    except Exception as e:
        logger.error(f"Gmail auth failed: {e}")
        sys.exit(1)

    # ── Status mode ──
    if args.status:
        show_status(service, config)
        return

    # ── Single pass or watch mode ──
    if args.watch:
        watch_loop(service, config)
    else:
        print("=" * 60)
        print("  FORTRESS PRIME — GMAIL WATCHER (SINGLE PASS)")
        print("=" * 60)
        print(f"  Cabin:  {config.cabin_slug}")
        print(f"  Mode:   {'DRY RUN' if config.dry_run else 'LIVE'}")
        print(f"  Filter: {'sender allowlist' if config.filter_senders else 'all senders'}")

        stats = process_inbox(service, config)

        print(f"\n{'=' * 60}")
        print(f"  Processed:  {stats['processed']}")
        print(f"  Drafted:    {stats['drafted']}")
        print(f"  Escalated:  {stats['escalated']}")
        print(f"  Skipped:    {stats['skipped']}")
        print(f"  Errors:     {stats['errors']}")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
