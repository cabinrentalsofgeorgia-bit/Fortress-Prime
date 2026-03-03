"""
FORTRESS PRIME — Self-Healing Classification Janitor
=====================================================
Nightly cron (2 AM) — scans UNKNOWN and low-confidence vendors,
re-classifies via HYDRA (DeepSeek-R1-70B), auto-corrects at >= 95%
confidence, and creates golden rules for future classification runs.

Bounded strictly:
  - Max 100 vendors per run
  - Max 3 LLM retries per vendor
  - 30-minute global timeout

Schedule:
  0 2 * * * python3 /fortress/tools/classification_janitor.py >> /tmp/janitor.log 2>&1
"""

import os
import sys
import json
import re
import time
import signal
import logging
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_inference_client, DB_HOST, DB_NAME, DB_PORT, DB_USER, DB_PASS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("classification_janitor")

MAX_VENDORS_PER_RUN = 100
MAX_RETRIES_PER_VENDOR = 3
GLOBAL_TIMEOUT_SECONDS = 1800  # 30 minutes
AUTO_CORRECT_THRESHOLD = 0.95
FLAG_THRESHOLD = 0.65

VALID_CATEGORIES = [
    "UTILITIES", "INSURANCE", "MAINTENANCE", "SUPPLIES", "CLEANING",
    "LANDSCAPING", "PEST_CONTROL", "MARKETING", "PROFESSIONAL_SERVICES",
    "TECHNOLOGY", "TRAVEL", "FOOD_BEVERAGE", "TAXES_FEES", "MORTGAGE",
    "CAPITAL_IMPROVEMENTS", "VEHICLE", "PAYROLL", "LITIGATION_RECOVERY",
]

_timed_out = False


def _timeout_handler(signum, frame):
    global _timed_out
    _timed_out = True
    log.critical("Global timeout reached (%ds). Committing progress and exiting.", GLOBAL_TIMEOUT_SECONDS)


def _get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
    )


def _fetch_rag_precedents(cur, vendor_name: str, description: str, limit: int = 5) -> str:
    """Retrieve semantically similar golden rules from classification_rules (pgvector)."""
    try:
        cur.execute(
            """
            SELECT vendor_pattern, assigned_category, reasoning
            FROM finance.classification_rules
            ORDER BY vendor_pattern <-> %s
            LIMIT %s
            """,
            (vendor_name + " " + (description or ""), limit),
        )
        rows = cur.fetchall()
        if not rows:
            return ""
        lines = []
        for pattern, category, reasoning in rows:
            entry = f"- {pattern} → {category}"
            if reasoning:
                entry += f" ({reasoning})"
            lines.append(entry)
        return "\nLEARNED PRECEDENTS (from golden rules):\n" + "\n".join(lines)
    except Exception as e:
        log.warning("RAG precedent lookup failed (non-fatal): %s", e)
        return ""


def _classify_one(client, model: str, vendor_name: str, description: str, precedents: str) -> dict:
    """Call HYDRA to classify a single vendor. Returns {category, confidence, reasoning}."""
    prompt = f"""You are a financial classification engine for a luxury cabin rental property management company (Cabin Rentals of Georgia).

Classify this vendor into exactly ONE of these categories:
{json.dumps(VALID_CATEGORIES)}

VENDOR: {vendor_name}
DESCRIPTION: {description or 'No description available'}
{precedents}

Return ONLY valid JSON (no markdown, no explanation outside the JSON):
{{"category": "<CATEGORY>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}}"""

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=256,
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    parsed = json.loads(raw)
    category = parsed.get("category", "UNKNOWN").upper().strip()
    confidence = float(parsed.get("confidence", 0.0))
    reasoning = parsed.get("reasoning", "")

    if category not in VALID_CATEGORIES:
        log.warning("LLM returned invalid category '%s' for %s — treating as UNKNOWN", category, vendor_name)
        category = "UNKNOWN"
        confidence = 0.0

    return {"category": category, "confidence": confidence, "reasoning": reasoning}


def run_janitor(max_vendors: int = MAX_VENDORS_PER_RUN):
    global _timed_out

    log.info("=" * 60)
    log.info("FORTRESS PROTOCOL: Self-Healing Vendor Classification Sweep")
    log.info("=" * 60)
    log.info("Max vendors: %d | Auto-correct threshold: %.0f%% | Timeout: %ds",
             max_vendors, AUTO_CORRECT_THRESHOLD * 100, GLOBAL_TIMEOUT_SECONDS)

    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(GLOBAL_TIMEOUT_SECONDS)

    conn = _get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, vendor_name, original_description
        FROM finance.vendor_classifications
        WHERE category = 'UNKNOWN' OR confidence < %s
        ORDER BY confidence ASC NULLS FIRST
        LIMIT %s
    """, (FLAG_THRESHOLD, max_vendors))
    targets = cur.fetchall()

    if not targets:
        log.info("Zero unclassified vendors found. System healthy.")
        cur.close()
        conn.close()
        return

    log.info("Found %d vendors requiring classification.", len(targets))

    try:
        client, model = get_inference_client("HYDRA")
    except Exception as e:
        log.error("HYDRA unavailable: %s — aborting sweep.", e)
        cur.close()
        conn.close()
        return

    auto_corrected = 0
    flagged = 0
    failed = 0
    ts = time.strftime("%Y%m%d")

    for v_id, name, desc in targets:
        if _timed_out:
            break

        precedents = _fetch_rag_precedents(cur, name, desc)
        result = None

        for attempt in range(1, MAX_RETRIES_PER_VENDOR + 1):
            try:
                result = _classify_one(client, model, name, desc, precedents)
                break
            except json.JSONDecodeError as e:
                log.warning("Attempt %d/%d for '%s' — JSON parse error: %s",
                            attempt, MAX_RETRIES_PER_VENDOR, name, e)
            except Exception as e:
                log.warning("Attempt %d/%d for '%s' — LLM error: %s",
                            attempt, MAX_RETRIES_PER_VENDOR, name, e)

        if result is None:
            failed += 1
            log.error("All %d attempts failed for vendor '%s'.", MAX_RETRIES_PER_VENDOR, name)
            continue

        category = result["category"]
        confidence = result["confidence"]
        reasoning = result["reasoning"]

        if category == "UNKNOWN":
            flagged += 1
            continue

        if confidence >= AUTO_CORRECT_THRESHOLD:
            classified_by = f"JANITOR-AUTO-{ts}"
            cur.execute("""
                UPDATE finance.vendor_classifications
                SET category = %s, confidence = %s, classified_by = %s
                WHERE id = %s
            """, (category, confidence, classified_by, v_id))

            cur.execute("""
                INSERT INTO finance.classification_rules
                    (vendor_pattern, assigned_category, reasoning, created_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (name, category, reasoning, classified_by))

            auto_corrected += 1
            log.info("AUTO-CORRECT: '%s' → %s (%.1f%%)", name, category, confidence * 100)
        else:
            flagged += 1
            log.info("FLAGGED for review: '%s' → %s (%.1f%% < 95%%)", name, category, confidence * 100)

    conn.commit()
    cur.close()
    conn.close()

    if hasattr(signal, "SIGALRM"):
        signal.alarm(0)

    log.info("=" * 60)
    log.info("JANITOR SWEEP COMPLETE")
    log.info("  Processed:      %d / %d", auto_corrected + flagged + failed, len(targets))
    log.info("  Auto-corrected: %d (>= 95%% confidence)", auto_corrected)
    log.info("  Flagged:        %d (< 95%% — awaiting CFO review)", flagged)
    log.info("  Failed:         %d (LLM errors)", failed)
    if _timed_out:
        log.info("  NOTE: Run was terminated by global timeout.")
    log.info("=" * 60)


if __name__ == "__main__":
    run_janitor()
