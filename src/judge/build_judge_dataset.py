#!/usr/bin/env python3
"""
build_judge_dataset.py — Extract labeled captures as judge training JSONL.

Gary's QC decisions take precedence over Godhead decisions.
Output format matches judge chat template expected by train_judge.py.

Usage:
  python -m src.judge.build_judge_dataset \\
      --judge-name vrs_concierge_judge \\
      --task-types vrs_concierge \\
      --since "7 days ago" \\
      --output /mnt/fortress_nas/judge-training/vrs_concierge_judge-2026-04-18.jsonl \\
      [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s","svc":"build_judge_dataset"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("build_judge_dataset")

DB_URI = os.getenv(
    "POSTGRES_ADMIN_URI",
    "postgresql://fortress_admin:fortress@127.0.0.1:5432/fortress_shadow"
).replace("+asyncpg", "")

_SYSTEM = (
    'You are a quality judge for {task_type} responses. '
    'Output JSON only: {{"decision": "confident|uncertain|escalate", "reasoning": "<one sentence>"}}'
)
_USER = "Prompt: {prompt}\n\nResponse: {sovereign_response}\n\nEvaluate quality."
_ASST = '{{"decision": "{decision}", "reasoning": "{reasoning}"}}'


def build_dataset(task_types: list[str], since: str, output_path: Path, dry_run: bool) -> dict:
    stats = {"total_considered": 0, "labeled": 0, "gary_qcd": 0,
             "skipped_no_label": 0, "output_count": 0}

    ph = ",".join(["%s"] * len(task_types))
    conn = psycopg2.connect(DB_URI)
    cur  = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(f"""
        SELECT
            cl.task_type,
            cl.final_decision,
            cl.godhead_reasoning,
            cl.qc_decision,
            cl.qc_note,
            cl.qc_reviewed_at,
            cl.label_source,
            COALESCE(tc.user_prompt, rc.prompt)       AS user_prompt,
            COALESCE(tc.assistant_resp, rc.response)  AS sovereign_response
        FROM capture_labels cl
        LEFT JOIN llm_training_captures tc
            ON tc.id = cl.capture_id AND cl.capture_table = 'llm_training_captures'
        LEFT JOIN restricted_captures rc
            ON rc.id = cl.capture_id AND cl.capture_table = 'restricted_captures'
        WHERE cl.task_type IN ({ph})
          AND cl.final_decision IS NOT NULL
          AND cl.created_at >= NOW() - INTERVAL %s
        ORDER BY cl.created_at DESC
    """, (*task_types, since))
    rows = cur.fetchall()
    conn.close()

    records: list[dict] = []
    for row in rows:
        stats["total_considered"] += 1
        if not row["final_decision"]:
            stats["skipped_no_label"] += 1
            continue
        stats["labeled"] += 1
        if row["qc_reviewed_at"]:
            stats["gary_qcd"] += 1
            decision  = (row["qc_decision"] or row["final_decision"]).replace("override_", "")
            reasoning = row["qc_note"] or row["godhead_reasoning"] or "QC override"
        else:
            decision  = row["final_decision"]
            reasoning = row["godhead_reasoning"] or "Godhead judgment"

        prompt   = (row["user_prompt"]        or "")[:2000]
        response = (row["sovereign_response"] or "")[:2000]
        if not prompt or not response:
            stats["skipped_no_label"] += 1
            continue

        task = row["task_type"]
        records.append({"messages": [
            {"role": "system",    "content": _SYSTEM.format(task_type=task)},
            {"role": "user",      "content": _USER.format(prompt=prompt, sovereign_response=response)},
            {"role": "assistant", "content": _ASST.format(decision=decision, reasoning=reasoning)},
        ], "metadata": {"task_type": task, "decision": decision, "source": row["label_source"]}})

    stats["output_count"] = len(records)
    if dry_run:
        log.info("[DRY RUN] Would write %d records to %s | stats=%s", len(records), output_path, stats)
        return stats

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    log.info("Written %d records to %s", len(records), output_path)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge-name",  required=True)
    parser.add_argument("--task-types",  required=True)
    parser.add_argument("--since",       default="7 days ago")
    parser.add_argument("--output",      required=True, type=Path)
    parser.add_argument("--dry-run",     action="store_true")
    args = parser.parse_args()
    task_types = [t.strip() for t in args.task_types.split(",")]
    log.info("build_judge_dataset judge=%s tasks=%s since=%r dry_run=%s",
             args.judge_name, task_types, args.since, args.dry_run)
    stats = build_dataset(task_types, args.since, args.output, args.dry_run)
    log.info("Complete: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
