#!/usr/bin/env python3
"""
Historic Email Vault Builder (Theater 3)

Scans a cPanel mail tree, cryptographically deduplicates raw messages by SHA-256,
archives unique .eml payloads, and indexes metadata in a local SQLite database.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path


LOG = logging.getLogger("historic_email_vault")


@dataclass
class MessageMetadata:
    message_id: str | None
    subject: str | None
    sender: str | None
    recipients: str | None
    sent_at_raw: str | None
    parse_ok: bool


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  source_root TEXT NOT NULL,
  archive_root TEXT NOT NULL,
  files_scanned INTEGER NOT NULL DEFAULT 0,
  files_candidate INTEGER NOT NULL DEFAULT 0,
  files_archived INTEGER NOT NULL DEFAULT 0,
  files_deduped INTEGER NOT NULL DEFAULT 0,
  files_failed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
  sha256 TEXT PRIMARY KEY,
  archive_rel_path TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  message_id TEXT,
  subject TEXT,
  sender TEXT,
  recipients TEXT,
  sent_at_raw TEXT,
  parse_ok INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS message_sightings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  source_rel_path TEXT NOT NULL,
  source_size_bytes INTEGER NOT NULL,
  discovered_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE,
  FOREIGN KEY(sha256) REFERENCES messages(sha256) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_messages_subject ON messages(subject);
CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
CREATE INDEX IF NOT EXISTS idx_sightings_sha ON message_sightings(sha256);
CREATE INDEX IF NOT EXISTS idx_sightings_source ON message_sightings(source_rel_path);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_mail_candidate(path: Path) -> bool:
    lower = str(path).lower()
    if lower.endswith(".eml"):
        return True
    # Standard Maildir conventions.
    return "/cur/" in lower or "/new/" in lower


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _parse_metadata(path: Path) -> MessageMetadata:
    try:
        with path.open("rb") as fh:
            msg = BytesParser(policy=policy.default).parse(fh)
        return MessageMetadata(
            message_id=(str(msg.get("Message-Id")).strip() if msg.get("Message-Id") else None),
            subject=(str(msg.get("Subject")).strip() if msg.get("Subject") else None),
            sender=(str(msg.get("From")).strip() if msg.get("From") else None),
            recipients=(str(msg.get("To")).strip() if msg.get("To") else None),
            sent_at_raw=(str(msg.get("Date")).strip() if msg.get("Date") else None),
            parse_ok=True,
        )
    except Exception:
        return MessageMetadata(
            message_id=None,
            subject=None,
            sender=None,
            recipients=None,
            sent_at_raw=None,
            parse_ok=False,
        )


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def _start_run(conn: sqlite3.Connection, source_root: Path, archive_root: Path) -> int:
    cur = conn.execute(
        """
        INSERT INTO runs (started_at, source_root, archive_root)
        VALUES (?, ?, ?)
        """,
        (_utc_now(), str(source_root), str(archive_root)),
    )
    conn.commit()
    return int(cur.lastrowid)


def _complete_run(conn: sqlite3.Connection, run_id: int, counters: dict[str, int]) -> None:
    conn.execute(
        """
        UPDATE runs
        SET completed_at = ?,
            files_scanned = ?,
            files_candidate = ?,
            files_archived = ?,
            files_deduped = ?,
            files_failed = ?
        WHERE id = ?
        """,
        (
            _utc_now(),
            counters["scanned"],
            counters["candidate"],
            counters["archived"],
            counters["deduped"],
            counters["failed"],
            run_id,
        ),
    )
    conn.commit()


def _upsert_message(
    conn: sqlite3.Connection,
    sha256: str,
    archive_rel_path: str,
    size_bytes: int,
    meta: MessageMetadata,
) -> bool:
    now = _utc_now()
    cur = conn.execute("SELECT 1 FROM messages WHERE sha256 = ?", (sha256,))
    exists = cur.fetchone() is not None
    if exists:
        conn.execute(
            "UPDATE messages SET last_seen_at = ? WHERE sha256 = ?",
            (now, sha256),
        )
        return False

    conn.execute(
        """
        INSERT INTO messages
            (sha256, archive_rel_path, size_bytes, first_seen_at, last_seen_at,
             message_id, subject, sender, recipients, sent_at_raw, parse_ok)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sha256,
            archive_rel_path,
            size_bytes,
            now,
            now,
            meta.message_id,
            meta.subject,
            meta.sender,
            meta.recipients,
            meta.sent_at_raw,
            1 if meta.parse_ok else 0,
        ),
    )
    return True


def _insert_sighting(
    conn: sqlite3.Connection,
    run_id: int,
    sha256: str,
    source_rel_path: str,
    source_size_bytes: int,
) -> None:
    conn.execute(
        """
        INSERT INTO message_sightings
            (run_id, sha256, source_rel_path, source_size_bytes, discovered_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, sha256, source_rel_path, source_size_bytes, _utc_now()),
    )


def build_vault(
    source_root: Path,
    archive_root: Path,
    index_db: Path,
    dry_run: bool,
    max_files: int,
) -> int:
    if not source_root.exists():
        LOG.error("source_root_missing path=%s", source_root)
        return 1

    archive_root.mkdir(parents=True, exist_ok=True)
    index_db.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(index_db)
    conn.row_factory = sqlite3.Row
    _init_db(conn)

    run_id = _start_run(conn, source_root, archive_root)
    LOG.info("run_started run_id=%s source_root=%s", run_id, source_root)

    counters = {"scanned": 0, "candidate": 0, "archived": 0, "deduped": 0, "failed": 0}

    try:
        for root, _dirs, files in os.walk(source_root):
            for name in files:
                counters["scanned"] += 1
                path = Path(root) / name
                if not _is_mail_candidate(path):
                    continue
                counters["candidate"] += 1

                if max_files > 0 and counters["candidate"] > max_files:
                    LOG.info("max_files_reached max_files=%s", max_files)
                    _complete_run(conn, run_id, counters)
                    return 0

                try:
                    sha256 = _sha256_file(path)
                    size_bytes = path.stat().st_size
                    source_rel_path = str(path.relative_to(source_root))

                    shard = sha256[:2]
                    archive_rel_path = f"{shard}/{sha256}.eml"
                    archive_abs = archive_root / archive_rel_path
                    archive_abs.parent.mkdir(parents=True, exist_ok=True)

                    meta = _parse_metadata(path)
                    inserted = _upsert_message(conn, sha256, archive_rel_path, size_bytes, meta)
                    _insert_sighting(conn, run_id, sha256, source_rel_path, size_bytes)

                    if inserted:
                        if not dry_run:
                            shutil.copy2(path, archive_abs)
                        counters["archived"] += 1
                    else:
                        counters["deduped"] += 1

                    if (counters["candidate"] % 500) == 0:
                        conn.commit()
                        LOG.info(
                            "progress scanned=%s candidate=%s archived=%s deduped=%s failed=%s",
                            counters["scanned"],
                            counters["candidate"],
                            counters["archived"],
                            counters["deduped"],
                            counters["failed"],
                        )
                except Exception as exc:
                    counters["failed"] += 1
                    LOG.warning("file_failed path=%s error=%s", path, str(exc)[:240])

        conn.commit()
        _complete_run(conn, run_id, counters)
        LOG.info(
            "run_complete run_id=%s scanned=%s candidate=%s archived=%s deduped=%s failed=%s",
            run_id,
            counters["scanned"],
            counters["candidate"],
            counters["archived"],
            counters["deduped"],
            counters["failed"],
        )
        return 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build cryptographically deduplicated historic email vault.")
    parser.add_argument(
        "--source-root",
        default="/mnt/vol1_source/Backups/CPanel_Extracted/backup/homedir/mail",
        help="Root path containing extracted maildir data.",
    )
    parser.add_argument(
        "--archive-root",
        default="/mnt/vol1_source/Backups/Email_Vault/archive",
        help="Target root for unique archived .eml files.",
    )
    parser.add_argument(
        "--index-db",
        default="/mnt/vol1_source/Backups/Email_Vault/email_index.sqlite3",
        help="SQLite index database path.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Index only, do not copy files into archive_root.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Optional cap on candidate mail files (0 = no cap).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - [HISTORIC EMAIL VAULT] - %(message)s",
    )

    return build_vault(
        source_root=Path(args.source_root),
        archive_root=Path(args.archive_root),
        index_db=Path(args.index_db),
        dry_run=args.dry_run,
        max_files=args.max_files,
    )


if __name__ == "__main__":
    raise SystemExit(main())
