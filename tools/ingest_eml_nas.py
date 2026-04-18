#!/usr/bin/env python3
"""
EML Feeder — Open the NAS floodgates
=====================================
Walks the MailPlus Data Lake GMAIL_ARCHIVE path, parses .eml files,
and inserts into email_archive so the Wolfpack can mine.

Run on Captain:
    python3 tools/ingest_eml_nas.py
    python3 tools/ingest_eml_nas.py /path/to/other/eml/folder

Uses file_path for dedup (ON CONFLICT DO NOTHING). New rows get is_mined=FALSE.
"""

import os
import sys
import re
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

# Project root and env
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
except ImportError:
    pass

import psycopg2

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
NAS_ROOT = os.getenv(
    "EML_ARCHIVE_PATH",
    "/mnt/fortress_nas/Communications/System_MailPlus_Server/ENTERPRISE_DATA_LAKE/01_LANDING_ZONE/GMAIL_ARCHIVE",
)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("ADMIN_DB_USER") or os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("ADMIN_DB_PASS") or os.getenv("DB_PASS", "")
DB_PORT = int(os.getenv("DB_PORT", "5432"))

CATEGORY = "GMAIL_ARCHIVE"


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
    )


def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile("<.*?>")
    return re.sub(cleanr, " ", raw_html).replace("\n", " ").replace("\r", "").strip()


def parse_eml(file_path: str) -> dict | None:
    try:
        with open(file_path, "rb") as f:
            msg = BytesParser(policy=policy.default).parse(f)
    except Exception as e:
        return None

    subject = (msg.get("subject") or "No Subject").strip()
    if isinstance(subject, bytes):
        subject = subject.decode("utf-8", errors="replace")
    sender = msg.get("from") or "Unknown"
    if isinstance(sender, bytes):
        sender = sender.decode("utf-8", errors="replace")
    date_str = msg.get("date")
    try:
        sent_at = parsedate_to_datetime(date_str) if date_str else datetime.utcnow()
    except Exception:
        sent_at = datetime.utcnow()

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in cdispo.lower():
                try:
                    raw = part.get_content()
                    body = raw if isinstance(raw, str) else (raw.decode("utf-8", errors="replace") if raw else "")
                except Exception:
                    pass
                if body:
                    break
            if not body and ctype == "text/html" and "attachment" not in cdispo.lower():
                try:
                    raw = part.get_content()
                    if raw:
                        body = clean_html(raw if isinstance(raw, str) else raw.decode("utf-8", errors="replace"))
                except Exception:
                    pass
    else:
        try:
            raw = msg.get_content()
            body = raw if isinstance(raw, str) else (raw.decode("utf-8", errors="replace") if raw else "")
            if msg.get_content_type() == "text/html":
                body = clean_html(body)
        except Exception:
            body = ""

    return {
        "subject": subject[:2048] if subject else "No Subject",
        "sender": sender[:1024] if sender else "Unknown",
        "sent_at": sent_at,
        "content": (body or "")[:1_000_000],
    }


def ingest_folder(folder_path: str) -> None:
    if not os.path.isdir(folder_path):
        print(f"❌ Not a directory: {folder_path}")
        return

    conn = get_db_connection()
    cur = conn.cursor()

    count = 0
    skipped = 0
    errors = 0

    print(f"📂 Scanning: {folder_path}")
    print("")

    for root, _dirs, files in os.walk(folder_path):
        for file in files:
            if not file.lower().endswith(".eml"):
                continue
            full_path = os.path.join(root, file)
            try:
                data = parse_eml(full_path)
                if not data:
                    errors += 1
                    continue

                cur.execute(
                    """
                    INSERT INTO email_archive (category, file_path, sender, subject, content, sent_at, is_mined)
                    VALUES (%s, %s, %s, %s, %s, %s, FALSE)
                    ON CONFLICT (file_path) DO NOTHING
                    """,
                    (
                        CATEGORY,
                        full_path,
                        data["sender"],
                        data["subject"],
                        data["content"],
                        data["sent_at"],
                    ),
                )
                if cur.rowcount > 0:
                    count += 1
                    if count % 100 == 0:
                        print(f"   -> Ingested {count} emails...", end="\r")
                else:
                    skipped += 1

            except Exception as e:
                errors += 1
                if errors <= 10:
                    print(f"❌ Error {full_path}: {e}")

    conn.commit()
    cur.close()
    conn.close()

    print("")
    print("✅ COMPLETE.")
    print(f"   - Ingested: {count}")
    print(f"   - Skipped (duplicates): {skipped}")
    print(f"   - Errors:   {errors}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else NAS_ROOT
    print("🛡️  Fortress EML Feeder — Open the floodgates")
    print(f"   Target: {target}")
    print("")
    ingest_folder(target)
