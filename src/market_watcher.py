"""
Fortress Prime — Market Watcher (Financial Intelligence Module)
================================================================
Reads market data from NAS, synthesizes a Daily Brief via DeepSeek-R1,
and optionally drafts it to Gmail.

Usage:
    python -m src.market_watcher              # Analyze and print brief
    python -m src.market_watcher --email      # Also draft to Gmail
"""

import os
import json
import argparse
from datetime import datetime
from src.fortress_paths import LOGS_DIR, NAS_AI_BRAIN
import requests

# CONFIG
MARKET_DATA_DIR = os.path.join(NAS_AI_BRAIN, "market_data")
WATCH_LOG = os.path.join(str(LOGS_DIR), "market_watcher_audit.jsonl")


def ask_captain(prompt, model="deepseek-r1:70b"):
    """Direct API call to the Captain's DeepSeek-R1 for reasoning."""
    url = "http://localhost:11434/api/generate"
    data = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    try:
        response = requests.post(url, json=data, timeout=600)
        response.raise_for_status()
        return response.json()["response"]
    except Exception as e:
        return f"Error contacting Captain Node: {e}"


def get_briefing_prompt(context):
    return f"""
    ROLE: Chief Investment Officer.
    TASK: Analyze these market notes.
    OUTPUT: A structured Daily Briefing.

    CONTEXT:
    {context}

    FORMAT:
    1. MARKET STATUS: [GREEN/YELLOW/RED]
    2. KEY SIGNALS:
    3. ACTION PLAN:
    """


def get_email_market_context():
    """Pull recent Market Club intelligence from email_archive (CF-02 pipeline)."""
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME", "fortress_db"),
            user=os.getenv("DB_USER", "miner_bot"),
            password=os.getenv("DB_PASSWORD", os.getenv("DB_PASS", "")),
        )
        cur = conn.cursor()

        # Get key market emails from last 24 hours
        cur.execute("""
            SELECT sender, subject, LEFT(content, 500) as preview, sent_at
            FROM email_archive
            WHERE category = 'Market Intelligence'
              AND sent_at >= NOW() - INTERVAL '24 hours'
              AND (
                  sender ILIKE '%%marketclub%%' OR sender ILIKE '%%ino.com%%'
                  OR sender ILIKE '%%goldfix%%' OR sender ILIKE '%%seekingalpha%%'
                  OR sender ILIKE '%%carnivoretrading%%' OR sender ILIKE '%%analystratings%%'
                  OR sender ILIKE '%%investors.com%%' OR sender ILIKE '%%coinbits%%'
                  OR (sender ILIKE '%%patreon%%' AND sender ILIKE '%%market%%')
              )
            ORDER BY sent_at DESC
            LIMIT 15
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return ""

        context = "\n--- MARKET EMAIL INTELLIGENCE (Last 24h) ---\n"
        for sender, subject, preview, sent_at in rows:
            context += f"\n[{sent_at.strftime('%H:%M')}] {sender}: {subject}\n"
            if preview:
                context += f"  {preview[:300].strip()}\n"
        return context

    except Exception as e:
        print(f"  [WARN] Could not read email archive: {e}")
        return ""


def run_watcher(email_mode=False):
    print("Scanning Market Data...")

    # 1. Read Files from NAS
    context = ""
    if os.path.exists(MARKET_DATA_DIR):
        for f in os.listdir(MARKET_DATA_DIR):
            if f.endswith(".txt") or f.endswith(".md"):
                path = os.path.join(MARKET_DATA_DIR, f)
                with open(path, "r") as file:
                    context += f"\n--- {f} ---\n" + file.read()

    # 2. Pull live Market Club email intelligence
    email_context = get_email_market_context()
    if email_context:
        context += email_context
        print(f"  Added email intelligence ({len(email_context)} chars)")

    if not context:
        print("No market data found in", MARKET_DATA_DIR, "or email_archive")
        return

    # 2. Analyze
    print(f"Synthesizing {len(context)} chars with DeepSeek-R1...")
    analysis = ask_captain(get_briefing_prompt(context))

    print("\n" + "=" * 60)
    print("  FORTRESS DAILY MARKET BRIEF")
    print("=" * 60)
    print(analysis)
    print("=" * 60)

    # 3. Audit log
    os.makedirs(os.path.dirname(WATCH_LOG), exist_ok=True)
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "files_read": [f for f in os.listdir(MARKET_DATA_DIR)
                       if f.endswith((".txt", ".md"))],
        "context_chars": len(context),
        "brief_chars": len(analysis),
        "email_drafted": email_mode,
    }
    with open(WATCH_LOG, "a") as lf:
        lf.write(json.dumps(log_entry) + "\n")

    # 4. Draft to Gmail (optional)
    if email_mode:
        try:
            from src.gmail_auth import get_gmail_service
            from email.mime.text import MIMEText
            import base64

            service = get_gmail_service()
            subject = f"Fortress Daily Market Brief: {datetime.now().strftime('%Y-%m-%d')}"

            message = MIMEText(analysis)
            message["to"] = "me"
            message["subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

            draft = service.users().drafts().create(
                userId="me",
                body={"message": {"raw": raw}},
            ).execute()

            print(f"\nDraft created: {subject}")
            print(f"Draft ID: {draft['id']}")
        except Exception as e:
            print(f"\nGmail draft failed (non-critical): {e}")
            print("Brief was still printed above and logged to audit trail.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fortress Prime - Market Watcher (Financial Intelligence)",
    )
    parser.add_argument("--email", action="store_true",
                        help="Draft the brief to Gmail")
    args = parser.parse_args()
    run_watcher(email_mode=args.email)
