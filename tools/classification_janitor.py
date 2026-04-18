#!/usr/bin/env python3
"""
FORTRESS PRIME — Classification Janitor (Self-Healing Watchdog)
================================================================
A nightly cron job that hunts for errors in vendor classifications and
auto-corrects them using the Hydra cluster (deepseek-r1:70b) for
deep reasoning.

Architecture:
    1. SCAN:   Find UNKNOWN vendors + low-confidence classifications
    2. ENRICH: Retrieve RAG precedents from classification_rules (pgvector)
    3. REASON: Send to Hydra (R1-70B) with Chain-of-Thought prompting
    4. DECIDE: Auto-correct if ≥95% confidence, else flag for morning review
    5. LEARN:  High-confidence corrections become new golden rules

Usage:
    # Dry run (report only, no DB changes)
    ./venv/bin/python tools/classification_janitor.py --dry-run

    # Full run
    ./venv/bin/python tools/classification_janitor.py

    # Limit to N vendors
    ./venv/bin/python tools/classification_janitor.py --limit 50

    # Use SWARM (fast, less accurate) instead of HYDRA (slow, accurate)
    ./venv/bin/python tools/classification_janitor.py --mode swarm

Schedule:
    Crontab: 0 2 * * * /home/admin/Fortress-Prime/venv/bin/python /home/admin/Fortress-Prime/tools/classification_janitor.py >> /tmp/janitor.log 2>&1
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import NGINX_LB_URL, get_inference_url, get_embeddings_url

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

DB_CONFIG = {"dbname": "fortress_db", "user": "admin"}

# Hydra = R1-70B deep reasoning (3 GPU nodes via Nginx)
HYDRA_URL = f"{NGINX_LB_URL}/hydra/v1/chat/completions"
HYDRA_MODEL = "deepseek-r1:70b"
HYDRA_TIMEOUT = 300  # 5 min — R1-70B thinks deeply

# Swarm = qwen2.5:7b fast inference (all 4 nodes)
SWARM_URL = get_inference_url()
SWARM_MODEL = "qwen2.5:7b"
SWARM_TIMEOUT = 60

EMBED_URL = get_embeddings_url()
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768

# Confidence thresholds
AUTO_CORRECT_THRESHOLD = 0.95   # Auto-correct if janitor confidence ≥ 95%
FLAG_THRESHOLD = 0.70           # Flag in DB if confidence < 70%
SCAN_CONFIDENCE_BELOW = 0.65   # Scan vendors classified with confidence below this

VALID_CLASSIFICATIONS = [
    "OWNER_PRINCIPAL", "REAL_BUSINESS", "CONTRACTOR", "CROG_INTERNAL",
    "FAMILY_INTERNAL", "FINANCIAL_SERVICE", "PROFESSIONAL_SERVICE",
    "LEGAL_SERVICE", "INSURANCE", "OPERATIONAL_EXPENSE", "SUBSCRIPTION",
    "MARKETING", "TENANT_GUEST", "PERSONAL_EXPENSE", "GOVERNMENT",
    "LITIGATION_RECOVERY", "NOISE", "UNKNOWN",
]

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [JANITOR] %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("janitor")

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def get_embedding(text: str) -> list:
    """Get embedding from nomic-embed-text."""
    try:
        resp = requests.post(EMBED_URL, json={"model": EMBED_MODEL, "prompt": text}, timeout=30)
        return resp.json().get("embedding", [])
    except Exception as e:
        log.warning(f"Embedding failed: {e}")
        return []


def retrieve_precedents(embedding: list, top_k: int = 5) -> list:
    """Retrieve similar golden rules from pgvector."""
    if not embedding or len(embedding) != EMBED_DIM:
        return []
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        SELECT vendor_pattern, assigned_category, reasoning,
               1 - (embedding <=> %s::vector) as similarity
        FROM finance.classification_rules
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (str(embedding), str(embedding), top_k))
    results = []
    for row in cur.fetchall():
        if row[3] >= 0.5:  # minimum similarity
            results.append({
                "vendor": row[0], "category": row[1],
                "reasoning": row[2], "similarity": round(row[3], 3),
            })
    cur.close()
    conn.close()
    return results


def compute_flags(classification: str) -> tuple:
    """Compute is_revenue and is_expense flags."""
    REVENUE = ("REAL_BUSINESS", "CROG_INTERNAL", "TENANT_GUEST")
    EXPENSE = ("CONTRACTOR", "OPERATIONAL_EXPENSE", "PROFESSIONAL_SERVICE",
               "LEGAL_SERVICE", "INSURANCE", "SUBSCRIPTION", "MARKETING",
               "GOVERNMENT", "CROG_INTERNAL", "FINANCIAL_SERVICE")
    NEUTRAL = ("NOISE", "FAMILY_INTERNAL", "UNKNOWN", "PERSONAL_EXPENSE")
    is_revenue = classification in REVENUE
    is_expense = classification in EXPENSE
    if classification in NEUTRAL:
        is_revenue = is_expense = False
    return is_revenue, is_expense


def store_golden_rule(vendor_pattern: str, category: str, reasoning: str,
                      source_id: int = None):
    """Store a janitor-learned rule."""
    embedding = get_embedding(vendor_pattern)
    if not embedding or len(embedding) != EMBED_DIM:
        return None
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO finance.classification_rules
            (vendor_pattern, assigned_category, reasoning, source_vendor_id, embedding, created_by)
        VALUES (%s, %s, %s, %s, %s::vector, 'JANITOR-AUTO')
        RETURNING id
    """, (vendor_pattern, category, reasoning, source_id, str(embedding)))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN CLASSIFICATION LOGIC
# ═══════════════════════════════════════════════════════════════════════════════


def classify_with_reasoning(vendor: dict, precedents: list, llm_url: str,
                            model: str, timeout: int) -> dict:
    """Send a vendor to the LLM with Chain-of-Thought + RAG precedents."""
    label = vendor.get("vendor_label", "")
    pattern = vendor.get("vendor_pattern", "")
    current = vendor.get("classification", "UNKNOWN")
    notes = vendor.get("titan_notes", "")

    # Build RAG-augmented prompt
    precedent_text = ""
    if precedents:
        precedent_text = "\n\n**LEARNED PRECEDENTS (from human CFO corrections):**\n"
        for i, p in enumerate(precedents, 1):
            precedent_text += (
                f"  {i}. '{p['vendor']}' → {p['category']} "
                f"(similarity: {p['similarity']:.0%}). Reason: {p['reasoning']}\n"
            )

    system = f"""You are a forensic financial auditor performing a deep review of a vendor classification.
The business is "Cabin Rentals of Georgia" (CROG), a vacation cabin rental in Blue Ridge, GA.
The Knight family owns CROG. Skyfall is the owner's holding company (Monarch Deli = Skyfall entity).

Current classification: {current}
Previous AI notes: {notes}

Available categories: {', '.join(VALID_CLASSIFICATIONS)}
{precedent_text}

Think step by step:
1. What is this vendor? Is it a person, company, or automated email?
2. What industry/sector does it belong to?
3. Does it match any precedent from the learned rules?
4. What is the most precise category?

Respond with ONLY a JSON object:
{{"classification": "CATEGORY", "confidence": 0.95, "reasoning": "Detailed explanation of your decision"}}"""

    user = f"Deep-review this vendor:\n- Name: {label}\n- Pattern: {pattern}\n- Currently: {current}"

    try:
        resp = requests.post(
            llm_url,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
                "max_tokens": 500,
            },
            timeout=timeout,
        )
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()

        # Handle <think>...</think> blocks from R1
        if "<think>" in content:
            # Extract the part after </think>
            if "</think>" in content:
                content = content.split("</think>")[-1].strip()

        # Parse JSON (handle markdown code blocks)
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        classification = result.get("classification", "UNKNOWN").upper()
        if classification not in VALID_CLASSIFICATIONS:
            classification = "UNKNOWN"

        return {
            "classification": classification,
            "confidence": float(result.get("confidence", 0.5)),
            "reasoning": result.get("reasoning", ""),
            "error": None,
        }

    except json.JSONDecodeError:
        # Try to extract category from free text
        ct = content.upper() if "content" in dir() else ""
        for cat in VALID_CLASSIFICATIONS:
            if cat in ct:
                return {"classification": cat, "confidence": 0.5,
                        "reasoning": "Extracted from text", "error": None}
        return {"classification": "UNKNOWN", "confidence": 0.0,
                "reasoning": "JSON parse error", "error": "parse"}
    except requests.Timeout:
        return {"classification": "UNKNOWN", "confidence": 0.0,
                "reasoning": "LLM timeout", "error": "timeout"}
    except Exception as e:
        return {"classification": "UNKNOWN", "confidence": 0.0,
                "reasoning": str(e)[:200], "error": "exception"}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="Fortress Classification Janitor")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no DB changes")
    parser.add_argument("--limit", type=int, default=0, help="Max vendors to process (0=all)")
    parser.add_argument("--mode", choices=["hydra", "swarm"], default="hydra",
                        help="LLM mode: hydra (R1-70B, slow+accurate) or swarm (7B, fast)")
    args = parser.parse_args()

    if args.mode == "hydra":
        llm_url, model, timeout = HYDRA_URL, HYDRA_MODEL, HYDRA_TIMEOUT
    else:
        llm_url, model, timeout = SWARM_URL, SWARM_MODEL, SWARM_TIMEOUT

    log.info("=" * 60)
    log.info("  FORTRESS PRIME — Classification Janitor")
    log.info(f"  Mode: {args.mode.upper()} ({model})")
    log.info(f"  Dry run: {args.dry_run}")
    log.info("=" * 60)

    # ── Phase 1: Find candidates ──
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find: UNKNOWN vendors + low-confidence classifications
    cur.execute("""
        SELECT id, vendor_label, vendor_pattern, classification, titan_notes, classified_by
        FROM finance.vendor_classifications
        WHERE classification = 'UNKNOWN'
           OR (titan_notes LIKE 'confidence=%%'
               AND CAST(
                   SPLIT_PART(SPLIT_PART(titan_notes, 'confidence=', 2), ' ', 1) AS NUMERIC
               ) < %s)
        ORDER BY
            CASE WHEN classification = 'UNKNOWN' THEN 0 ELSE 1 END,
            id
    """, (SCAN_CONFIDENCE_BELOW,))
    candidates = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()

    if args.limit > 0:
        candidates = candidates[:args.limit]

    if not candidates:
        log.info("No candidates found. The floor is clean.")
        return

    log.info(f"Found {len(candidates)} candidates for review")

    # ── Phase 2: Process each candidate ──
    stats = {"reviewed": 0, "corrected": 0, "flagged": 0, "unchanged": 0,
             "errors": 0, "rules_created": 0}
    t0 = time.time()

    for i, vendor in enumerate(candidates, 1):
        vid = vendor["id"]
        label = vendor["vendor_label"]
        old_class = vendor["classification"]

        log.info(f"[{i}/{len(candidates)}] Reviewing: {label} (currently: {old_class})")

        # Get RAG precedents
        embedding = get_embedding(label)
        precedents = retrieve_precedents(embedding) if embedding else []
        if precedents:
            log.info(f"  RAG: {len(precedents)} precedents found "
                     f"(top: '{precedents[0]['vendor']}' → {precedents[0]['category']} "
                     f"@ {precedents[0]['similarity']:.0%})")

        # Classify with deep reasoning
        result = classify_with_reasoning(vendor, precedents, llm_url, model, timeout)
        new_class = result["classification"]
        confidence = result["confidence"]
        reasoning = result["reasoning"]

        stats["reviewed"] += 1

        if result.get("error"):
            stats["errors"] += 1
            log.warning(f"  ERROR: {result['error']} — {reasoning}")
            continue

        # Decision logic
        if new_class == old_class:
            stats["unchanged"] += 1
            log.info(f"  CONFIRMED: {old_class} (confidence: {confidence:.0%})")
            continue

        if new_class == "UNKNOWN":
            stats["unchanged"] += 1
            log.info(f"  STILL UNKNOWN (confidence too low)")
            continue

        if confidence >= AUTO_CORRECT_THRESHOLD:
            # Auto-correct
            if args.dry_run:
                log.info(f"  [DRY RUN] WOULD CORRECT: {old_class} → {new_class} "
                         f"(confidence: {confidence:.0%})")
                stats["corrected"] += 1
            else:
                is_revenue, is_expense = compute_flags(new_class)
                conn = psycopg2.connect(**DB_CONFIG)
                conn.autocommit = True
                cur = conn.cursor()
                cur.execute("""
                    UPDATE finance.vendor_classifications
                    SET classification = %s, is_revenue = %s, is_expense = %s,
                        classified_by = 'JANITOR-AUTO',
                        titan_notes = %s
                    WHERE id = %s
                """, (new_class, is_revenue, is_expense,
                      f"confidence={confidence:.2f} | {reasoning} | was:{old_class}",
                      vid))
                cur.close()
                conn.close()
                stats["corrected"] += 1
                log.info(f"  AUTO-CORRECTED: {old_class} → {new_class} "
                         f"(confidence: {confidence:.0%})")

                # Create golden rule from high-confidence correction
                try:
                    rule_id = store_golden_rule(label, new_class, reasoning, vid)
                    if rule_id:
                        stats["rules_created"] += 1
                        log.info(f"  LEARNED: Golden Rule #{rule_id}")
                except Exception as e:
                    log.warning(f"  Rule creation failed: {e}")
        else:
            # Flag for human review
            stats["flagged"] += 1
            if args.dry_run:
                log.info(f"  [DRY RUN] WOULD FLAG: {old_class} → {new_class}? "
                         f"(confidence: {confidence:.0%}, below {AUTO_CORRECT_THRESHOLD:.0%})")
            else:
                conn = psycopg2.connect(**DB_CONFIG)
                conn.autocommit = True
                cur = conn.cursor()
                cur.execute("""
                    UPDATE finance.vendor_classifications
                    SET titan_notes = %s
                    WHERE id = %s
                """, (f"confidence={confidence:.2f} | JANITOR-FLAGGED: suggests {new_class} | {reasoning}",
                      vid))
                cur.close()
                conn.close()
                log.info(f"  FLAGGED: suggests {new_class} (confidence: {confidence:.0%})")

        # Rate limiting — be kind to the cluster
        if args.mode == "hydra":
            time.sleep(2)
        else:
            time.sleep(0.5)

    # ── Summary ──
    elapsed = time.time() - t0
    log.info("")
    log.info("=" * 60)
    log.info("  JANITOR REPORT")
    log.info("=" * 60)
    log.info(f"  Reviewed:      {stats['reviewed']}")
    log.info(f"  Auto-corrected:{stats['corrected']}")
    log.info(f"  Flagged:       {stats['flagged']}")
    log.info(f"  Unchanged:     {stats['unchanged']}")
    log.info(f"  Errors:        {stats['errors']}")
    log.info(f"  Rules created: {stats['rules_created']}")
    log.info(f"  Elapsed:       {elapsed:.1f}s")
    log.info(f"  Mode:          {args.mode.upper()} ({'dry run' if args.dry_run else 'live'})")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
