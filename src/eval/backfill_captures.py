"""
backfill_captures.py — ingest replayable historical prompt/response data.

Two sources:
  A) NAS ai_brain prompt logs (Feb 2026, deepseek-r1 outputs)
     /mnt/fortress_nas/fortress_data/ai_brain/logs/prompts_*.jsonl
     Format: {run_id, timestamp, template, model, inputs: dict, output: str, ...}
     Conversion: inputs dict serialized as user message, output as assistant.

  B) Quarantine JSONL — 2026-04-11.jsonl (76 ChatML lines, pre-filter)
     /mnt/fortress_nas/training/quarantine-pre-filter-20260418/2026-04-11.jsonl
     Format: {messages: [{role, content}, ...]} — extract user+assistant pair.
     source_module inferred from content (no metadata in this file).

Each record is run through classify_for_capture() from the privilege filter.
  ALLOW      → insert into llm_training_captures (status=pending)
  RESTRICTED → insert into restricted_captures
  BLOCK      → skip, log

Deduplication: SHA256(prompt_text + "|||" + response_text) checked against DB
before any insert to prevent double-ingest on re-runs.

Usage:
  python backfill_captures.py [--dry-run] [--source {prompts,quarantine,all}]

  --dry-run : classify and count without writing to DB
  --source  : restrict to one source (default: all)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import psycopg2
from psycopg2.extras import RealDictCursor

# --- Add repo root to path so we can import privilege_filter ---
_REPO = Path(__file__).resolve().parents[2]
_FGP  = _REPO / "fortress-guest-platform"
sys.path.insert(0, str(_FGP))
sys.path.insert(0, str(_REPO / "src"))

from backend.services.privilege_filter import (
    CaptureRoute,
    classify_for_capture,
)

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"backfill"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("backfill")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_URI = os.getenv("POSTGRES_ADMIN_URI", "").replace("+asyncpg", "")
if not DB_URI:
    raise RuntimeError("POSTGRES_ADMIN_URI env var required")
PROMPTS_DIR     = Path(os.getenv("PROMPTS_DIR",
                    "/mnt/fortress_nas/fortress_data/ai_brain/logs"))
QUARANTINE_FILE = Path(os.getenv("QUARANTINE_FILE",
                    "/mnt/fortress_nas/training/quarantine-pre-filter-20260418/2026-04-11.jsonl"))

# Templates from NAS prompts that map to source_module labels
TEMPLATE_MODULE_MAP = {
    "guest_email_reply":        "concierge_worker",
    "senior_partner_directive": "vrs_agent_dispatcher",
    "ledger_classifier":        "ledger_classifier",
    "thunderdome_judge":        "vrs_agent_dispatcher",
}

# Legal content keywords — if any appear in user+assistant text, route via
# legal_council source_module so classify_for_capture() restricts it.
LEGAL_KEYWORDS = (
    "superior court", "plaintiff", "defendant", "jurisdiction",
    "case suv", "attorney", "counsel", "litigation", "claim",
    "breach of contract", "case brief", "ediscovery", "deposition",
    "privilege", "legal analysis", "claimant",
    "analyze the case", "contradictions", "case evidence", "legal graph",
    "appellate", "statute of limitations", "discovery request",
    "case lf-", "case lfm",  # internal case ID prefixes
)

# Outputs that are test/dry-run artifacts — skip these entirely
_SKIP_OUTPUT_PREFIXES = (
    "[DRY RUN",
    "[dry run",
    "[TEST]",
    "[MOCK]",
)


def _detect_module(user_text: str, asst_text: str) -> str:
    """Infer source_module from text content for records with no metadata."""
    combined = (user_text + " " + asst_text).lower()
    if any(kw in combined for kw in LEGAL_KEYWORDS):
        return "legal_council"
    if any(k in combined for k in ("property:", "check-in", "checkout", "reservation", "guest")):
        return "vrs_agent_dispatcher"
    if any(k in combined for k in ("rate", "pricing", "quote", "market")):
        return "quote_engine"
    return "backfill_misc"


def _prompt_hash(prompt: str, response: str) -> str:
    return hashlib.sha256((prompt + "|||" + response).encode()).hexdigest()


def _already_ingested(cur, prompt: str, response: str) -> bool:
    """Dedup using md5 of full prompt+response text (computed in Python, matched in DB)."""
    import hashlib as _hl
    full_hash = _hl.md5((prompt + "|||" + response).encode("utf-8")).hexdigest()
    cur.execute("""
        SELECT 1 FROM llm_training_captures
        WHERE md5(user_prompt || '|||' || assistant_resp) = %s
        LIMIT 1
    """, (full_hash,))
    if cur.fetchone():
        return True
    cur.execute("""
        SELECT 1 FROM restricted_captures
        WHERE md5(prompt || '|||' || response) = %s
        LIMIT 1
    """, (full_hash,))
    return bool(cur.fetchone())


# ---------------------------------------------------------------------------
# Source A: NAS prompts_*.jsonl
# ---------------------------------------------------------------------------
def _iter_nas_prompts() -> Iterator[dict]:
    """
    Yield normalized records from all prompts_*.jsonl files.
    Each record: {user, assistant, source_module, model_used, created_at, origin}
    """
    for path in sorted(PROMPTS_DIR.glob("prompts_*.jsonl")):
        log.info("Reading NAS prompts: %s", path)
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                output = obj.get("output")
                if not output or str(output).strip() in ("None", ""):
                    continue  # skip null/empty outputs

                template = obj.get("template", "unknown")
                inputs   = obj.get("inputs", {})
                model    = obj.get("model", "unknown")
                ts_str   = obj.get("timestamp")

                # Build user message from inputs dict
                if "guest_email" in inputs and "cabin_context" in inputs:
                    user_text = (
                        f"Context: {inputs['cabin_context']}\n\n"
                        f"Guest message: {inputs['guest_email']}"
                    )
                elif "query" in inputs:
                    user_text = str(inputs["query"])
                elif inputs:
                    user_text = json.dumps(inputs, indent=2)
                else:
                    continue  # no usable input

                asst_text = str(output).strip()
                # Skip test/dry-run outputs — not real model outputs
                if any(asst_text.startswith(p) for p in _SKIP_OUTPUT_PREFIXES):
                    continue
                if not asst_text or len(asst_text) < 5:
                    continue

                source_module = TEMPLATE_MODULE_MAP.get(template, "backfill_nas")

                try:
                    created_at = datetime.fromisoformat(ts_str) if ts_str else datetime.now(tz=timezone.utc)
                except (ValueError, TypeError):
                    created_at = datetime.now(tz=timezone.utc)

                yield {
                    "user":          user_text,
                    "assistant":     asst_text,
                    "source_module": source_module,
                    "model_used":    model,
                    "created_at":    created_at,
                    "origin":        f"nas_prompts/{path.name}",
                }


# ---------------------------------------------------------------------------
# Source B: Quarantine 2026-04-11.jsonl (read-only, copy from quarantine)
# ---------------------------------------------------------------------------
def _iter_quarantine() -> Iterator[dict]:
    """
    Yield records from the quarantine JSONL (ChatML format).
    Does NOT modify or delete the quarantine file.
    """
    if not QUARANTINE_FILE.exists():
        log.warning("Quarantine file not found: %s", QUARANTINE_FILE)
        return

    log.info("Reading quarantine file (read-only): %s", QUARANTINE_FILE)
    with open(QUARANTINE_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            messages = obj.get("messages", [])
            user_msg  = next((m["content"] for m in messages if m["role"] == "user"), "")
            asst_msg  = next((m["content"] for m in messages if m["role"] == "assistant"), "")

            if not user_msg or not asst_msg:
                continue

            # Detect source module from content (file has no source_module field)
            source_module = _detect_module(user_msg, asst_msg)
            model_used    = obj.get("model_used", "unknown/frontier")

            yield {
                "user":          user_msg,
                "assistant":     asst_msg,
                "source_module": source_module,
                "model_used":    model_used,
                "created_at":    datetime.now(tz=timezone.utc),
                "origin":        "quarantine_2026-04-11",
            }


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
def backfill(source: str, dry_run: bool) -> dict:
    conn = psycopg2.connect(DB_URI)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    stats: dict = {
        "processed": 0,
        "skipped_empty": 0,
        "skipped_dedup": 0,
        "allow": 0,
        "restricted": 0,
        "blocked": 0,
        "inserted_training": 0,
        "inserted_restricted": 0,
        "by_source_module": {},
        "by_origin": {},
    }

    sources: list[Iterator] = []
    if source in ("prompts", "all"):
        sources.append(_iter_nas_prompts())
    if source in ("quarantine", "all"):
        sources.append(_iter_quarantine())

    try:
        for iterator in sources:
            for rec in iterator:
                stats["processed"] += 1
                user    = rec["user"]
                asst    = rec["assistant"]
                sm      = rec["source_module"]
                model   = rec["model_used"]
                ts      = rec["created_at"]
                origin  = rec["origin"]

                if not user.strip() or not asst.strip():
                    stats["skipped_empty"] += 1
                    continue

                # Dedup check
                if not dry_run and _already_ingested(cur, user, asst):
                    stats["skipped_dedup"] += 1
                    log.debug("Dedup skip: %s", sm)
                    continue

                decision = classify_for_capture(
                    prompt=user,
                    response=asst,
                    source_module=sm,
                )

                stats["by_source_module"][sm] = stats["by_source_module"].get(sm, 0) + 1
                stats["by_origin"][origin]    = stats["by_origin"].get(origin, 0) + 1

                if decision.route == CaptureRoute.BLOCK:
                    stats["blocked"] += 1
                    log.info("BLOCK: %s reason=%s", sm, decision.reason)
                    continue

                if decision.route == CaptureRoute.RESTRICTED:
                    stats["restricted"] += 1
                    if not dry_run:
                        cur.execute("""
                            INSERT INTO restricted_captures
                              (source_module, source_persona, prompt, response,
                               restriction_reason, matched_patterns, capture_metadata)
                            VALUES (%s, NULL, %s, %s, %s, %s, %s)
                        """, (
                            sm[:128],
                            user[:32000],
                            asst[:32000],
                            decision.reason[:256],
                            list(decision.matched_patterns),
                            json.dumps({"origin": origin, "model_used": model, "backfill": True}),
                        ))
                        stats["inserted_restricted"] += 1

                else:  # ALLOW
                    stats["allow"] += 1
                    if not dry_run:
                        cur.execute("""
                            INSERT INTO llm_training_captures
                              (source_module, model_used, user_prompt, assistant_resp,
                               status, created_at)
                            VALUES (%s, %s, %s, %s, 'pending', %s)
                        """, (
                            sm[:120],
                            model[:120],
                            user[:32000],
                            asst[:32000],
                            ts,
                        ))
                        stats["inserted_training"] += 1

        if dry_run:
            conn.rollback()
            log.info("[DRY RUN] No rows written.")
        else:
            conn.commit()
            log.info("Committed.")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill historical captures into training tables")
    parser.add_argument("--dry-run", action="store_true",
                        help="Classify and count without writing to DB")
    parser.add_argument("--source", choices=["prompts", "quarantine", "all"], default="all",
                        help="Which source to ingest (default: all)")
    args = parser.parse_args()

    log.info("backfill starting source=%s dry_run=%s", args.source, args.dry_run)
    stats = backfill(args.source, args.dry_run)

    log.info("=== RESULTS ===")
    log.info("processed=%d  skipped_empty=%d  skipped_dedup=%d",
             stats["processed"], stats["skipped_empty"], stats["skipped_dedup"])
    log.info("allow=%d  restricted=%d  blocked=%d",
             stats["allow"], stats["restricted"], stats["blocked"])
    if not args.dry_run:
        log.info("inserted_training=%d  inserted_restricted=%d",
                 stats["inserted_training"], stats["inserted_restricted"])
    log.info("by_source_module=%s", stats["by_source_module"])
    log.info("by_origin=%s", stats["by_origin"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
