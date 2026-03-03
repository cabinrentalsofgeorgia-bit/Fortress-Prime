#!/usr/bin/env python3
"""
FORTRESS PRIME — Institutional Lesson Extractor (Autonomous Swarm Directive — Pillar 3)
=======================================================================================
Nightly cron that scans resolved post-mortems, extracts structured lessons via SWARM NIM,
embeds them into Qdrant fortress_lessons collection, and marks them as processed.

This creates a cross-domain recursive learning loop: resolved problems become retrievable
institutional memory that all OODA agents consult before making decisions.

Run: python3 src/lesson_extractor.py
Cron: 30 3 * * * (nightly, after classification janitor)
"""

import json
import os
import sys
import logging
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lesson_extractor")

DB_HOST = os.getenv("DB_HOST", "192.168.0.100")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "fortress_db")
DB_USER = os.getenv("DB_USER", "miner_bot")
DB_PASS = os.getenv("DB_PASSWORD", os.getenv("DB_PASS", ""))

NIM_URL = os.getenv("NIM_URL", "http://192.168.0.100:8000/v1/chat/completions")
EMBED_URL = os.getenv("EMBED_URL", "http://192.168.0.100/api/embeddings")
QDRANT_URL = os.getenv("QDRANT_URL", "http://192.168.0.100:6333")
COLLECTION = "fortress_lessons"
BATCH_SIZE = int(os.getenv("LESSON_BATCH_SIZE", "20"))


EXTRACTION_PROMPT = """You are a systems engineering analyst. Analyze this resolved post-mortem
and extract a structured lesson that prevents recurrence across the enterprise.

Post-Mortem:
  Sector: {sector}
  Component: {component}
  Error: {error_summary}
  Root Cause: {root_cause}
  Remediation: {remediation}

Return ONLY valid JSON with these fields:
{{
  "domain": "infrastructure|security|data|operations|legal|financial",
  "pattern": "Brief description of the failure pattern (1 sentence)",
  "root_cause": "Technical root cause (1 sentence)",
  "fix_applied": "What was done to fix it (1 sentence)",
  "prevention_rule": "Rule to prevent recurrence (1 sentence)"
}}"""


def ensure_qdrant_collection() -> bool:
    try:
        r = requests.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=5)
        if r.status_code == 200:
            return True
        requests.put(
            f"{QDRANT_URL}/collections/{COLLECTION}",
            json={
                "vectors": {"size": 768, "distance": "Cosine"},
            },
            timeout=10,
        )
        log.info(f"Created Qdrant collection: {COLLECTION}")
        return True
    except Exception as exc:
        log.error(f"Failed to ensure Qdrant collection: {exc}")
        return False


def ensure_schema(conn) -> None:
    cur = conn.cursor()
    cur.execute("""
        DO $$ BEGIN
            ALTER TABLE system_post_mortems ADD COLUMN lesson_extracted TIMESTAMPTZ;
        EXCEPTION WHEN duplicate_column THEN NULL;
        END $$;
    """)
    conn.commit()


def fetch_unprocessed(conn) -> list[dict]:
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, sector, component, error_summary, root_cause, remediation
        FROM system_post_mortems
        WHERE status = 'resolved'
          AND lesson_extracted IS NULL
          AND error_summary IS NOT NULL
          AND LENGTH(error_summary) > 10
        ORDER BY occurred_at DESC
        LIMIT %s
    """, (BATCH_SIZE,))
    return cur.fetchall()


def extract_lesson(row: dict) -> dict | None:
    prompt = EXTRACTION_PROMPT.format(
        sector=row.get("sector", ""),
        component=row.get("component", ""),
        error_summary=row.get("error_summary", ""),
        root_cause=row.get("root_cause", "N/A"),
        remediation=row.get("remediation", "N/A"),
    )
    try:
        resp = requests.post(
            NIM_URL,
            json={
                "model": os.getenv("NIM_CHAT_MODEL", "qwen2.5:7b"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 300,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            log.warning(f"NIM returned {resp.status_code} for PM #{row['id']}")
            return None
        content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content)
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        log.warning(f"Failed to parse NIM response for PM #{row['id']}: {exc}")
        return None
    except requests.RequestException as exc:
        log.warning(f"NIM request failed for PM #{row['id']}: {exc}")
        return None


def embed_text(text: str) -> list[float] | None:
    try:
        resp = requests.post(
            EMBED_URL,
            json={"model": "nomic-embed-text", "prompt": text},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("embedding")
    except Exception:
        return None


def upsert_lesson(pm_id: int, lesson: dict, vector: list[float]) -> bool:
    try:
        resp = requests.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points",
            json={
                "points": [{
                    "id": pm_id,
                    "vector": vector,
                    "payload": {
                        "post_mortem_id": pm_id,
                        "domain": lesson.get("domain", "operations"),
                        "pattern": lesson.get("pattern", ""),
                        "root_cause": lesson.get("root_cause", ""),
                        "fix_applied": lesson.get("fix_applied", ""),
                        "prevention_rule": lesson.get("prevention_rule", ""),
                        "extracted_at": datetime.now(timezone.utc).isoformat(),
                    },
                }],
            },
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as exc:
        log.error(f"Qdrant upsert failed: {exc}")
        return False


def mark_extracted(conn, pm_id: int) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE system_post_mortems SET lesson_extracted = NOW() WHERE id = %s",
        (pm_id,),
    )
    conn.commit()


def main() -> None:
    log.info("Lesson Extractor starting")

    if not ensure_qdrant_collection():
        log.error("Cannot ensure Qdrant collection — aborting")
        sys.exit(1)

    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, database=DB_NAME,
            user=DB_USER, password=DB_PASS, connect_timeout=10,
        )
        ensure_schema(conn)

        rows = fetch_unprocessed(conn)
        log.info(f"Found {len(rows)} unprocessed resolved post-mortems")

        extracted = 0
        failed = 0

        for row in rows:
            pm_id = row["id"]
            log.info(f"Processing PM #{pm_id}: {row['component']}")

            lesson = extract_lesson(row)
            if not lesson:
                log.warning(f"PM #{pm_id}: extraction failed, skipping")
                failed += 1
                continue

            embed_text_str = (
                f"{lesson.get('domain', '')} {lesson.get('pattern', '')} "
                f"{lesson.get('root_cause', '')} {lesson.get('prevention_rule', '')}"
            )
            vector = embed_text(embed_text_str)
            if not vector:
                log.warning(f"PM #{pm_id}: embedding failed, skipping")
                failed += 1
                continue

            if upsert_lesson(pm_id, lesson, vector):
                mark_extracted(conn, pm_id)
                extracted += 1
                log.info(f"PM #{pm_id}: lesson extracted and embedded")
            else:
                failed += 1

        log.info(f"Complete: {extracted} extracted, {failed} failed, {len(rows)} total")
    except psycopg2.OperationalError as exc:
        log.error(f"Database connection failed: {exc}")
        sys.exit(1)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
