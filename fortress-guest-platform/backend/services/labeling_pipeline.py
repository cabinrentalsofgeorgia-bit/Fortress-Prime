"""
labeling_pipeline.py — Phase 4e.1 labeling infrastructure.

Every captured sovereign response is queued for Godhead judgment.
Godhead serves as the teacher-labeler: it evaluates sovereign's response
and decides confident | uncertain | escalate. A sample of labels go
to Gary's QC queue for human review.

Two execution modes:
  Inline: queue_capture_for_labeling() called fire-and-forget after capture write.
          Budget check happens inline; if within real-time budget, call Godhead now.
          If over 80% daily budget, queue for nightly batch.
  Nightly: python -m backend.services.labeling_pipeline --mode=nightly
           Processes previous day's backlog within remaining budget.

Budget config (env vars):
  LABELING_DAILY_BUDGET_USD       default: 20.00
  LABELING_REALTIME_THRESHOLD_PCT default: 80   (above this → defer to nightly)

Godhead routing (from Iron Dome v5 spec):
  legal_*       → Claude (anthropic/claude-sonnet-4-6)
  code_*        → GPT (openai/gpt-4o)
  vision_*      → Gemini (gemini/gemini-2.5-pro)
  real_time     → Grok (xai/grok-4.20-reasoning)
  math_*        → DeepSeek-R1 (deepseek/deepseek-reasoner)
  default       → Claude
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import httpx
import psycopg2
from psycopg2.extras import RealDictCursor

log = logging.getLogger("labeling_pipeline")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_URI = os.getenv("POSTGRES_ADMIN_URI", "").replace("+asyncpg", "")
if not DB_URI:
    raise RuntimeError("POSTGRES_ADMIN_URI env var required")

LITELLM_BASE    = os.getenv("LITELLM_BASE_URL",         "http://127.0.0.1:8002/v1")
LITELLM_KEY     = os.getenv("LITELLM_MASTER_KEY",        "")
DAILY_BUDGET    = Decimal(os.getenv("LABELING_DAILY_BUDGET_USD",       "20.00"))
RT_THRESHOLD    = int(os.getenv("LABELING_REALTIME_THRESHOLD_PCT",     "80"))

# ---------------------------------------------------------------------------
# Godhead teacher routing (Iron Dome v5 spec)
# ---------------------------------------------------------------------------
_GODHEAD_TEACHERS: dict[str, list[str]] = {
    # Legal tasks → Claude primary, GPT fallback, DeepSeek secondary
    "legal_reasoning":    ["anthropic/claude-sonnet-4-6", "openai/gpt-4o", "deepseek/deepseek-reasoner"],
    "brief_drafting":     ["anthropic/claude-sonnet-4-6", "openai/gpt-4o", "deepseek/deepseek-reasoner"],
    "legal_citations":    ["anthropic/claude-sonnet-4-6", "openai/gpt-4o"],
    "contract_analysis":  ["anthropic/claude-sonnet-4-6", "openai/gpt-4o"],
    # Code tasks → GPT primary, Claude fallback
    "code_generation":    ["openai/gpt-4o", "anthropic/claude-sonnet-4-6"],
    "code_refactoring":   ["anthropic/claude-sonnet-4-6", "openai/gpt-4o"],
    "code_debugging":     ["openai/gpt-4o", "anthropic/claude-sonnet-4-6"],
    # Vision tasks → Gemini primary
    "vision_damage":      ["gemini/gemini-2.5-pro", "anthropic/claude-sonnet-4-6"],
    "vision_photo":       ["gemini/gemini-2.5-pro", "anthropic/claude-sonnet-4-6"],
    "ocr":                ["gemini/gemini-2.5-pro", "anthropic/claude-sonnet-4-6"],
    # Real-time → Grok primary
    "real_time":          ["xai/grok-4.20-reasoning", "gemini/gemini-2.5-pro"],
    "current_market":     ["xai/grok-4.20-reasoning", "anthropic/claude-sonnet-4-6"],
    # Math/logic → DeepSeek primary
    "math_reasoning":     ["deepseek/deepseek-reasoner", "anthropic/claude-sonnet-4-6", "openai/gpt-4o"],
    "complex_logic":      ["deepseek/deepseek-reasoner", "anthropic/claude-sonnet-4-6", "openai/gpt-4o"],
    # Summarization → Claude primary
    "summarization_long": ["anthropic/claude-sonnet-4-6", "gemini/gemini-2.5-pro", "openai/gpt-4o"],
    "summarization_news": ["xai/grok-4.20-reasoning",   "anthropic/claude-sonnet-4-6"],
    # VRS tasks → Claude primary
    "vrs_concierge":      ["anthropic/claude-sonnet-4-6", "openai/gpt-4o"],
    "vrs_ota_response":   ["anthropic/claude-sonnet-4-6", "openai/gpt-4o"],
    # Business intelligence
    "competitive_intel":  ["anthropic/claude-sonnet-4-6", "gemini/gemini-2.5-pro"],
    "pricing_math":       ["anthropic/claude-sonnet-4-6", "openai/gpt-4o", "deepseek/deepseek-reasoner"],
    "acquisitions":       ["anthropic/claude-sonnet-4-6", "openai/gpt-4o"],
}
_DEFAULT_TEACHER = ["anthropic/claude-sonnet-4-6", "openai/gpt-4o"]

# Approximate cost per 1K tokens in USD (input/output)
_MODEL_COST_PER_1K: dict[str, tuple[float, float]] = {
    "anthropic/claude-sonnet-4-6":    (0.003, 0.015),
    "openai/gpt-4o":                  (0.005, 0.015),
    "gemini/gemini-2.5-pro":          (0.00125, 0.005),
    "xai/grok-4.20-reasoning":        (0.005, 0.015),
    "deepseek/deepseek-reasoner":     (0.00027, 0.0011),
}

# QC sampling weights — higher = more human review for that task type
_QC_WEIGHTS: dict[str, float] = {
    "legal_reasoning":    1.00,
    "brief_drafting":     1.00,
    "legal_citations":    1.00,
    "contract_analysis":  1.00,
    "pricing_math":       0.50,
    "acquisitions":       0.50,
    "competitive_intel":  0.25,
    "code_generation":    0.15,
    "code_refactoring":   0.15,
    "code_debugging":     0.15,
    "vision_damage":      0.10,
    "vision_photo":       0.10,
    "real_time":          0.10,
    "vrs_concierge":      0.05,
    "vrs_ota_response":   0.05,
}
_DEFAULT_QC_WEIGHT = 0.10


# ---------------------------------------------------------------------------
# Budget tracking
# ---------------------------------------------------------------------------

def check_budget_remaining() -> Decimal:
    """Return remaining budget for today in USD. Reads from DB."""
    try:
        conn = psycopg2.connect(DB_URI)
        cur = conn.cursor()
        cur.execute("""
            SELECT COALESCE(SUM(godhead_cost_usd), 0)
            FROM capture_labels
            WHERE godhead_called_at >= CURRENT_DATE
        """)
        spent = Decimal(str(cur.fetchone()[0]))
        conn.close()
        return max(DAILY_BUDGET - spent, Decimal("0"))
    except Exception as exc:
        log.warning("budget_check_failed error=%s — returning 0", str(exc)[:100])
        return Decimal("0")


def _estimate_call_cost(model: str, prompt_len: int = 500, response_len: int = 200) -> Decimal:
    """Estimate API cost in USD for one labeling call."""
    cost_in, cost_out = _MODEL_COST_PER_1K.get(model, (0.005, 0.015))
    return Decimal(str(cost_in * prompt_len / 1000 + cost_out * response_len / 1000))


def _budget_pct_used() -> float:
    """Return 0-100 representing % of daily budget consumed."""
    remaining = check_budget_remaining()
    if DAILY_BUDGET == 0:
        return 100.0
    return float((DAILY_BUDGET - remaining) / DAILY_BUDGET * 100)


# ---------------------------------------------------------------------------
# Godhead call
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = """You are a strict quality-assurance evaluator for an AI system.
You will be shown a task type, a user prompt, and the AI's response.
Evaluate whether the response is acceptable.

Return ONLY valid JSON:
{"decision": "confident|uncertain|escalate", "reasoning": "one sentence", "confidence_score": 0.0-1.0}

confident   = response is correct and suitable to return to user
uncertain   = response has issues but is marginally acceptable; flag for human review
escalate    = response is wrong, incomplete, or risky; discard and use a better model
"""


def call_godhead_sync(
    task_type: str,
    user_prompt: str,
    sovereign_response: str,
) -> tuple[str, str, str, Decimal]:
    """
    Call the appropriate Godhead teacher synchronously (for nightly batch).
    Returns: (model_used, decision, reasoning, cost_usd)
    Falls through teacher fallback chain on failure.
    """
    import json
    teachers = _GODHEAD_TEACHERS.get(task_type, _DEFAULT_TEACHER)

    user_content = (
        f"Task type: {task_type}\n\n"
        f"User prompt (first 2000 chars):\n{user_prompt[:2000]}\n\n"
        f"Sovereign response (first 2000 chars):\n{sovereign_response[:2000]}\n\n"
        "Evaluate the response. Return only JSON."
    )
    cost = _estimate_call_cost(teachers[0])

    for model in teachers:
        try:
            resp = httpx.post(
                f"{LITELLM_BASE.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _JUDGE_SYSTEM},
                        {"role": "user",   "content": user_content},
                    ],
                    "max_tokens": 200,
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"},
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            data = json.loads(text)
            decision  = data.get("decision", "uncertain")
            reasoning = data.get("reasoning", "")
            cost = _estimate_call_cost(model)
            log.info("godhead_label model=%s task=%s decision=%s", model, task_type, decision)
            return model, decision, reasoning, cost
        except Exception as exc:
            log.warning("godhead_call_failed model=%s error=%s — trying fallback",
                        model, str(exc)[:100])

    return "none", "skip", "all teachers failed", Decimal("0")


# ---------------------------------------------------------------------------
# Label write
# ---------------------------------------------------------------------------

def write_label_sync(
    capture_id: str,
    capture_table: str,
    task_type: str,
    godhead_model: str,
    godhead_decision: str,
    godhead_reasoning: str,
    cost_usd: Decimal,
) -> Optional[str]:
    """Write a label row and set qc_sampled based on task weight. Returns label id."""
    qc_sample = random.random() < _QC_WEIGHTS.get(task_type, _DEFAULT_QC_WEIGHT)
    label_id  = str(uuid.uuid4())
    try:
        conn = psycopg2.connect(DB_URI)
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO capture_labels
                (id, capture_id, capture_table, task_type,
                 godhead_model, godhead_decision, godhead_reasoning,
                 godhead_called_at, godhead_cost_usd,
                 qc_sampled, final_decision, label_source)
            VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'godhead')
            ON CONFLICT (capture_id, capture_table) DO NOTHING
        """, (
            label_id, capture_id, capture_table, task_type,
            godhead_model, godhead_decision, godhead_reasoning,
            datetime.now(tz=timezone.utc), float(cost_usd),
            qc_sample, godhead_decision,
        ))
        conn.commit()
        conn.close()
        return label_id
    except Exception as exc:
        log.error("write_label_failed capture_id=%s error=%s", capture_id, str(exc)[:200])
        return None


# ---------------------------------------------------------------------------
# Public API — inline fire-and-forget
# ---------------------------------------------------------------------------

def queue_capture_for_labeling(
    capture_id: str,
    capture_table: str,
    task_type: str,
    user_prompt: str,
    sovereign_response: str,
) -> None:
    """
    Queue a capture for Godhead labeling. Fire-and-forget — never raises.
    Called from _capture_interaction after DB write.

    If real-time budget headroom exists (< RT_THRESHOLD % used), calls
    Godhead immediately in a background thread. Otherwise marks for nightly
    batch by writing a placeholder label row.
    """
    import threading

    def _label_sync() -> None:
        try:
            if _budget_pct_used() >= RT_THRESHOLD:
                log.info("labeling_deferred_to_nightly capture_id=%s", capture_id)
                return
            model, decision, reasoning, cost = call_godhead_sync(
                task_type, user_prompt, sovereign_response)
            write_label_sync(
                capture_id, capture_table, task_type,
                model, decision, reasoning, cost)
        except Exception as exc:
            log.error("labeling_thread_error capture_id=%s error=%s", capture_id, str(exc)[:200])

    t = threading.Thread(target=_label_sync, daemon=True, name=f"label-{capture_id[:8]}")
    t.start()


# ---------------------------------------------------------------------------
# Nightly batch
# ---------------------------------------------------------------------------

def nightly_batch_label() -> dict:
    """Process previous day's unlabeled captures within remaining budget."""
    remaining = check_budget_remaining()
    log.info("nightly_batch_start budget_remaining=$%.4f", remaining)

    stats = {"processed": 0, "labeled": 0, "skipped_budget": 0, "errors": 0}

    try:
        conn = psycopg2.connect(DB_URI)
        cur  = conn.cursor(cursor_factory=RealDictCursor)

        # Find captures from yesterday that have no label yet
        cur.execute("""
            SELECT tc.id::text, 'llm_training_captures' AS tbl,
                   tc.task_type, tc.user_prompt, tc.assistant_resp
            FROM llm_training_captures tc
            LEFT JOIN capture_labels cl
                ON cl.capture_id = tc.id AND cl.capture_table = 'llm_training_captures'
            WHERE tc.created_at >= CURRENT_DATE - INTERVAL '1 day'
              AND tc.created_at < CURRENT_DATE
              AND tc.task_type IS NOT NULL
              AND cl.id IS NULL
            LIMIT 500
        """)
        rows = cur.fetchall()
        conn.close()

        spent_today = Decimal("0")
        for row in rows:
            stats["processed"] += 1
            est = _estimate_call_cost(_GODHEAD_TEACHERS.get(row["task_type"] or "", _DEFAULT_TEACHER)[0])
            if spent_today + est > remaining:
                stats["skipped_budget"] += 1
                continue
            model, decision, reasoning, cost = call_godhead_sync(
                row["task_type"] or "unknown",
                row["user_prompt"] or "",
                row["assistant_resp"] or "",
            )
            write_label_sync(row["id"], row["tbl"], row["task_type"] or "unknown",
                             model, decision, reasoning, cost)
            spent_today += cost
            stats["labeled"] += 1

    except Exception as exc:
        log.error("nightly_batch_error error=%s", str(exc)[:300])
        stats["errors"] += 1

    log.info("nightly_batch_complete stats=%s", stats)
    return stats


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, json, logging as _l
    _l.basicConfig(level=_l.INFO,
                   format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"labeling"}',
                   datefmt="%Y-%m-%dT%H:%M:%S")
    p = argparse.ArgumentParser(description="Fortress Prime labeling pipeline")
    p.add_argument("--mode", choices=["nightly", "status"], default="nightly")
    args = p.parse_args()

    if args.mode == "nightly":
        result = nightly_batch_label()
        print(json.dumps(result, indent=2))
    elif args.mode == "status":
        remaining = check_budget_remaining()
        pct = _budget_pct_used()
        print(json.dumps({"remaining_usd": float(remaining), "budget_pct_used": pct}))
