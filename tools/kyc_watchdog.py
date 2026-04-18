#!/usr/bin/env python3
"""
FORTRESS PRIME — Legal CRM Watchdog
======================================
Cron job that runs every 2 hours and performs:

  1. EMAIL SCAN — Searches email archive against all active case watchdog terms
  2. DEADLINE MONITOR — Checks legal.deadlines for upcoming/overdue deadlines
  3. CORRESPONDENCE WATCH — Detects replies to outbound correspondence

If alerts are detected, it:
  1. Logs P0/P1/P2 alerts by severity
  2. Writes alert rows to sentinel_alerts (if table exists)
  3. Updates legal.case_actions with deadline warnings
  4. Auto-links inbound replies to legal.correspondence

Usage:
    python tools/kyc_watchdog.py [--notify]

Cron:
    0 */2 * * * cd /home/admin/Fortress-Prime && ./venv/bin/python tools/kyc_watchdog.py >> /mnt/fortress_nas/fortress_data/ai_brain/logs/kyc_watchdog/cron.log 2>&1
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone, date, timedelta

import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LEGAL-WATCHDOG] %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("legal_watchdog")

DB_CONFIG = {"dbname": "fortress_db", "user": "admin"}

# ─── Search Terms ─────────────────────────────────────────────────────────────
# These are the EXACT terms that would appear in a legitimate KYC distribution
# email from the Plan Administrator for Case 23-11161-JKS.

CRITICAL_SENDERS = [
    "primetrustwinddown",
    "stretto-services",
    "cases-cr.stretto",
    "terraforminfo@ra.kroll",
    "detweiler",
    "wbd-us.com",
    "plan.administrator",
    "province",
    "womble",
]

CRITICAL_SUBJECTS = [
    "Estate Property Determination",
    "KYC verification",
    "claim distribution",
    "unique code",
    "claimant ID",
    "Bar Date",
]

CRITICAL_BODY = [
    "complete KYC within",
    "unique code and instructions",
    "Claimant ID",
    "Integrator Customer",
    "23-11161-JKS",
    "primetrustwinddown.com",
]


def load_watchdog_terms_from_db():
    """Load watchdog terms from legal.case_watchdog for all active cases."""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT w.search_type, w.search_term, w.priority, c.case_slug, c.case_number
            FROM legal.case_watchdog w
            JOIN legal.cases c ON c.id = w.case_id
            WHERE w.is_active = true AND c.status = 'active'
        """)
        terms = [dict(r) for r in cur.fetchall()]
        cur.close()
        conn.close()
        return terms
    except Exception as e:
        log.debug(f"Could not load DB watchdog terms (falling back to hardcoded): {e}")
        return []


def scan_archive():
    """Scan the email archive for any KYC-related emails (hardcoded + DB-driven)."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Merge DB watchdog terms into hardcoded lists
    db_terms = load_watchdog_terms_from_db()
    for t in db_terms:
        if t["search_type"] == "sender" and t["search_term"] not in CRITICAL_SENDERS:
            CRITICAL_SENDERS.append(t["search_term"])
        elif t["search_type"] == "subject" and t["search_term"] not in CRITICAL_SUBJECTS:
            CRITICAL_SUBJECTS.append(t["search_term"])
        elif t["search_type"] == "body" and t["search_term"] not in CRITICAL_BODY:
            CRITICAL_BODY.append(t["search_term"])

    alerts = []
    ts_now = datetime.now(timezone.utc)

    # 1. Sender matches (highest priority — direct from Plan Administrator)
    for term in CRITICAL_SENDERS:
        cur.execute("""
            SELECT id, sender, subject, sent_at, content
            FROM email_archive
            WHERE sender ILIKE %s
            ORDER BY sent_at DESC
        """, (f"%{term}%",))
        for row in cur.fetchall():
            alerts.append({
                "priority": "P1-CRITICAL",
                "match_type": "SENDER",
                "match_term": term,
                "email_id": row["id"],
                "sender": row["sender"],
                "subject": row["subject"],
                "sent_at": str(row["sent_at"]),
            })

    # 2. Subject matches
    for term in CRITICAL_SUBJECTS:
        cur.execute("""
            SELECT id, sender, subject, sent_at
            FROM email_archive
            WHERE subject ILIKE %s
              AND sender NOT ILIKE %s
            ORDER BY sent_at DESC
        """, (f"%{term}%", "%coinbits%"))
        for row in cur.fetchall():
            alerts.append({
                "priority": "P1-URGENT",
                "match_type": "SUBJECT",
                "match_term": term,
                "email_id": row["id"],
                "sender": row["sender"],
                "subject": row["subject"],
                "sent_at": str(row["sent_at"]),
            })

    # 3. Body content (deep scan for KYC-specific phrases, excluding known email #46437)
    for phrase in CRITICAL_BODY:
        cur.execute("""
            SELECT id, sender, subject, sent_at
            FROM email_archive
            WHERE content ILIKE %s
              AND id != 46437
              AND sender NOT ILIKE %s
            ORDER BY sent_at DESC
        """, (f"%{phrase}%", "%coinbits%"))
        for row in cur.fetchall():
            alerts.append({
                "priority": "P2-INVESTIGATE",
                "match_type": "BODY_CONTENT",
                "match_term": phrase,
                "email_id": row["id"],
                "sender": row["sender"],
                "subject": row["subject"],
                "sent_at": str(row["sent_at"]),
            })

    # Deduplicate by email_id
    seen = set()
    unique_alerts = []
    for a in alerts:
        if a["email_id"] not in seen:
            seen.add(a["email_id"])
            unique_alerts.append(a)

    # Log results
    if unique_alerts:
        log.warning("=" * 60)
        log.warning("  *** KYC EMAIL ALERT DETECTED ***")
        log.warning("=" * 60)
        for a in unique_alerts:
            log.warning(
                f"  [{a['priority']}] {a['match_type']}: '{a['match_term']}' "
                f"— Email #{a['email_id']} from {a['sender']} ({a['sent_at']})"
            )

        # Write alert to sentinel_alerts if the table exists
        try:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'sentinel_alerts'
                )
            """)
            if cur.fetchone()["exists"]:
                for a in unique_alerts:
                    if a["priority"] == "P1-CRITICAL":
                        cur.execute("""
                            INSERT INTO sentinel_alerts (alert_type, severity, message, metadata, created_at)
                            VALUES ('KYC_EMAIL_DETECTED', 'CRITICAL',
                                    %s, %s, NOW())
                            ON CONFLICT DO NOTHING
                        """, (
                            f"KYC email detected from {a['sender']} (Email #{a['email_id']})",
                            psycopg2.extras.Json(a),
                        ))
                conn.commit()
        except Exception as e:
            log.debug(f"Could not write to sentinel_alerts: {e}")
    else:
        log.info(
            f"Scan complete — No KYC distribution email found. "
            f"Archive size: {_get_archive_size(cur):,} emails. "
            f"Continuing to watch."
        )

    cur.close()
    conn.close()
    return unique_alerts


def _get_archive_size(cur):
    cur.execute("SELECT COUNT(*) as cnt FROM email_archive")
    return cur.fetchone()["cnt"]


# ═══════════════════════════════════════════════════════════════════════════════
# DEADLINE MONITOR — Check all legal.deadlines for upcoming/overdue items
# ═══════════════════════════════════════════════════════════════════════════════

def check_deadlines():
    """Check all active deadlines and generate alerts for upcoming/overdue items."""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT d.*, c.case_slug, c.case_number, c.case_name
        FROM legal.deadlines d
        JOIN legal.cases c ON c.id = d.case_id
        WHERE c.status = 'active' AND d.status IN ('pending', 'extended')
        ORDER BY COALESCE(d.extended_to, d.due_date) ASC
    """)

    alerts = []
    today = date.today()

    for row in cur.fetchall():
        effective_date = row.get("extended_to") or row["due_date"]
        if isinstance(effective_date, str):
            effective_date = date.fromisoformat(effective_date)
        days_remaining = (effective_date - today).days
        alert_threshold = row.get("alert_days_before", 7)

        if days_remaining < 0:
            # OVERDUE
            severity = "P0-OVERDUE"
            msg = (
                f"DEADLINE OVERDUE by {abs(days_remaining)} days: "
                f"{row['description']} (Case {row['case_number']})"
            )
            log.error(f"  [{severity}] {msg}")
            alerts.append({
                "severity": severity,
                "case_slug": row["case_slug"],
                "case_number": row["case_number"],
                "deadline_type": row["deadline_type"],
                "description": row["description"],
                "effective_date": str(effective_date),
                "days_remaining": days_remaining,
                "message": msg,
            })

            # Update deadline status to missed if no extension filed
            if row["status"] == "pending":
                cur.execute(
                    "UPDATE legal.deadlines SET status = 'missed' WHERE id = %s AND status = 'pending'",
                    (row["id"],)
                )

        elif days_remaining <= alert_threshold:
            # APPROACHING
            if days_remaining == 0:
                severity = "P0-TODAY"
            elif days_remaining <= 3:
                severity = "P1-CRITICAL"
            else:
                severity = "P1-URGENT"

            msg = (
                f"DEADLINE in {days_remaining} days ({effective_date}): "
                f"{row['description']} (Case {row['case_number']})"
            )
            log.warning(f"  [{severity}] {msg}")
            alerts.append({
                "severity": severity,
                "case_slug": row["case_slug"],
                "case_number": row["case_number"],
                "deadline_type": row["deadline_type"],
                "description": row["description"],
                "effective_date": str(effective_date),
                "days_remaining": days_remaining,
                "message": msg,
            })

    # Write deadline alerts to sentinel_alerts
    if alerts:
        try:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'sentinel_alerts'
                )
            """)
            if cur.fetchone()["exists"]:
                for a in alerts:
                    if a["severity"].startswith("P0"):
                        cur.execute("""
                            INSERT INTO sentinel_alerts (alert_type, severity, message, metadata, created_at)
                            VALUES ('DEADLINE_ALERT', %s, %s, %s, NOW())
                            ON CONFLICT DO NOTHING
                        """, (
                            a["severity"],
                            a["message"],
                            psycopg2.extras.Json(a),
                        ))
        except Exception as e:
            log.debug(f"Could not write deadline alerts to sentinel_alerts: {e}")

    conn.commit()
    cur.close()
    conn.close()
    return alerts


# ═══════════════════════════════════════════════════════════════════════════════
# CORRESPONDENCE WATCH — Detect replies to outbound legal communications
# ═══════════════════════════════════════════════════════════════════════════════

def watch_correspondence():
    """
    Check for replies to outbound correspondence by scanning email archive
    for messages from recipients of sent correspondence.
    """
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get all sent outbound correspondence with recipient emails
    cur.execute("""
        SELECT cr.id, cr.case_id, cr.recipient, cr.recipient_email,
               cr.subject, cr.sent_at, c.case_slug, c.case_number
        FROM legal.correspondence cr
        JOIN legal.cases c ON c.id = cr.case_id
        WHERE cr.direction = 'outbound'
          AND cr.status IN ('sent', 'delivered')
          AND cr.recipient_email IS NOT NULL
          AND c.status = 'active'
    """)
    sent_items = cur.fetchall()

    new_replies = []
    for item in sent_items:
        # Search for emails from the recipient after we sent our correspondence
        sent_date = item.get("sent_at")
        if not sent_date:
            continue

        cur.execute("""
            SELECT id, sender, subject, sent_at
            FROM email_archive
            WHERE sender ILIKE %s
              AND sent_at > %s
            ORDER BY sent_at DESC
            LIMIT 5
        """, (f"%{item['recipient_email']}%", sent_date))

        for email_row in cur.fetchall():
            # Check if this reply is already tracked
            cur.execute("""
                SELECT 1 FROM legal.correspondence
                WHERE case_id = %s AND direction = 'inbound'
                  AND subject ILIKE %s
                  AND created_at > %s
                LIMIT 1
            """, (item["case_id"], f"%{email_row['subject'][:30]}%", sent_date))

            if not cur.fetchone():
                # New inbound reply detected
                cur.execute("""
                    INSERT INTO legal.correspondence (
                        case_id, direction, comm_type, recipient, recipient_email,
                        subject, status
                    ) VALUES (%s, 'inbound', 'email', %s, %s, %s, 'filed')
                    RETURNING id
                """, (
                    item["case_id"],
                    email_row["sender"],
                    item["recipient_email"],
                    f"Reply: {email_row['subject'][:100]}",
                ))
                new_id = cur.fetchone()["id"]

                # Log action
                cur.execute("""
                    INSERT INTO legal.case_actions (case_id, action_type, description, status)
                    VALUES (%s, 'reply_detected', %s, 'completed')
                """, (
                    item["case_id"],
                    f"Reply detected from {email_row['sender']}: {email_row['subject'][:80]}",
                ))

                new_replies.append({
                    "case_slug": item["case_slug"],
                    "case_number": item["case_number"],
                    "from": email_row["sender"],
                    "subject": email_row["subject"],
                    "email_id": email_row["id"],
                    "correspondence_id": new_id,
                })
                log.warning(
                    f"  [REPLY DETECTED] Case {item['case_number']}: "
                    f"Email from {email_row['sender']} — {email_row['subject'][:60]}"
                )

    conn.commit()
    cur.close()
    conn.close()
    return new_replies


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN — Orchestrates all three watchdog functions
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Legal CRM Watchdog")
    parser.add_argument("--notify", action="store_true", help="Send email notification if alerts found")
    parser.add_argument("--deadlines-only", action="store_true", help="Only check deadlines")
    parser.add_argument("--correspondence-only", action="store_true", help="Only check correspondence")
    parser.add_argument("--email-only", action="store_true", help="Only scan email archive")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("  LEGAL CRM WATCHDOG — Starting scan")
    log.info("=" * 60)

    total_alerts = 0

    # 1. Email archive scan (original KYC watchdog behavior)
    if not args.deadlines_only and not args.correspondence_only:
        log.info("[1/3] Scanning email archive against watchdog terms...")
        email_alerts = scan_archive()
        if email_alerts:
            p1 = [a for a in email_alerts if a["priority"].startswith("P1")]
            log.warning(f"  Email alerts: {len(email_alerts)} ({len(p1)} critical)")
            total_alerts += len(email_alerts)
        else:
            log.info("  Email scan: all clear")

    # 2. Deadline monitoring
    if not args.email_only and not args.correspondence_only:
        log.info("[2/3] Checking legal deadlines...")
        deadline_alerts = check_deadlines()
        if deadline_alerts:
            overdue = [a for a in deadline_alerts if "OVERDUE" in a["severity"]]
            log.warning(f"  Deadline alerts: {len(deadline_alerts)} ({len(overdue)} overdue)")
            total_alerts += len(deadline_alerts)
        else:
            log.info("  Deadlines: all clear")

    # 3. Correspondence reply detection
    if not args.email_only and not args.deadlines_only:
        log.info("[3/3] Checking for correspondence replies...")
        replies = watch_correspondence()
        if replies:
            log.warning(f"  New replies detected: {len(replies)}")
            total_alerts += len(replies)
        else:
            log.info("  Correspondence: no new replies")

    log.info("=" * 60)
    log.info(f"  SCAN COMPLETE — {total_alerts} total alerts")
    log.info("=" * 60)

    return total_alerts


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 0)  # Always exit 0 for cron
