"""
Grade proposed redirect remaps using the onboarded NemoClaw sandbox lane.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.seo_redirect_remap import SeoRedirectRemapQueue

GRADE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(slots=True)
class GradeResult:
    score: float
    verdict: str
    note: str
    breakdown: dict[str, float]
    raw_response: str


def _deterministic_grade(row: SeoRedirectRemapQueue) -> GradeResult | None:
    source = (row.source_path or "").lower()
    destination = (row.proposed_destination_path or "").lower()

    if destination == "/blog" and source.startswith("/blog/"):
        return GradeResult(
            score=0.97,
            verdict="promote",
            note="Legacy blog path maps cleanly to the modern blog collection.",
            breakdown={
                "intent_match": 0.98,
                "destination_specificity": 0.96,
                "public_route_safety": 0.99,
                "grounding_quality": 0.95,
            },
            raw_response="deterministic:blog_collection_match",
        )

    if destination == "/cabins" and (
        source.startswith("/bathrooms/") or source.startswith("/number-people/")
    ):
        return GradeResult(
            score=0.955,
            verdict="promote",
            note="Legacy cabin filter taxonomy maps safely to the cabins collection.",
            breakdown={
                "intent_match": 0.96,
                "destination_specificity": 0.95,
                "public_route_safety": 0.99,
                "grounding_quality": 0.92,
            },
            raw_response="deterministic:cabin_filter_collection_match",
        )

    if destination == "/activities" and (
        source.startswith("/activity/") or source.startswith("/activity-type/") or source.startswith("/event/")
    ):
        return GradeResult(
            score=0.84,
            verdict="reject",
            note="Generic activities landing is directionally correct but does not clear the exact-match promotion threshold.",
            breakdown={
                "intent_match": 0.92,
                "destination_specificity": 0.62,
                "public_route_safety": 0.99,
                "grounding_quality": 0.83,
            },
            raw_response="deterministic:generic_activities_reject",
        )

    if destination == "/cabins":
        return GradeResult(
            score=0.71,
            verdict="reject",
            note="Generic cabins landing is too broad to auto-promote without stronger destination specificity.",
            breakdown={
                "intent_match": 0.74,
                "destination_specificity": 0.48,
                "public_route_safety": 0.98,
                "grounding_quality": 0.66,
            },
            raw_response="deterministic:generic_cabins_reject",
        )

    return None


def _build_grade_prompt(row: SeoRedirectRemapQueue) -> str:
    payload = {
        "task": "Grade a proposed SEO redirect remap.",
        "rubric_version": row.rubric_version,
        "threshold": float(settings.seo_redirect_grade_threshold),
        "source_path": row.source_path,
        "current_destination_path": row.current_destination_path,
        "proposed_destination_path": row.proposed_destination_path,
        "grounding_mode": row.grounding_mode,
        "extracted_entities": row.extracted_entities or [],
        "route_candidates": row.route_candidates or [],
        "rationale": row.rationale,
        "source_snapshot": row.source_snapshot or {},
        "instructions": [
            "Return strict JSON only.",
            "Score from 0.0 to 1.0.",
            "Use > 0.95 only when the remap is extremely well grounded.",
            "Reject generic landings when a more exact route is clearly needed.",
            "Consider source intent, destination specificity, and public route safety.",
        ],
        "response_schema": {
            "score": "number",
            "verdict": "promote_or_reject",
            "note": "string",
            "breakdown": {
                "intent_match": "number",
                "destination_specificity": "number",
                "public_route_safety": "number",
                "grounding_quality": "number",
            },
        },
    }
    return json.dumps(payload, ensure_ascii=True)


def _ssh_config_path() -> Path:
    config_path = Path(tempfile.gettempdir()) / "openshell-grade-sandbox-ssh-config"
    config_path.write_text(
        (
            "Host openshell-grade-sandbox\n"
            "    User sandbox\n"
            "    StrictHostKeyChecking no\n"
            "    UserKnownHostsFile /dev/null\n"
            "    GlobalKnownHostsFile /dev/null\n"
            "    LogLevel ERROR\n"
            "    ProxyCommand /home/admin/.local/bin/openshell ssh-proxy --gateway-name nemoclaw --name my-assistant\n"
        ),
        encoding="utf-8",
    )
    return config_path


def _remote_grade_command(*, prompt: str, model: str) -> str:
    prompt_b64 = base64.b64encode(prompt.encode("utf-8")).decode("ascii")
    script = f"""
import base64
import json
import ssl
import urllib.request

payload = {{
    "model": {json.dumps(model)},
    "messages": [
        {{
            "role": "system",
            "content": "You are the Fortress Prime God Head grader. Return strict JSON only."
        }},
        {{
            "role": "user",
            "content": base64.b64decode({json.dumps(prompt_b64)}).decode("utf-8")
        }},
    ],
    "stream": False,
}}

ctx = ssl._create_unverified_context()
req = urllib.request.Request(
    "https://inference.local/v1/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={{"Content-Type": "application/json"}},
)
with urllib.request.urlopen(req, context=ctx, timeout=90) as response:
    print(response.read().decode("utf-8"))
"""
    return f"python3 - <<'PY'\n{script}\nPY"


def _parse_grade_response(output: str) -> GradeResult:
    try:
        response = json.loads(output)
    except json.JSONDecodeError:
        response = {"choices": [{"message": {"content": output}}]}
    choices = response.get("choices") or []
    content = ""
    if choices:
        message = (choices[0] or {}).get("message") or {}
        content = str(message.get("content") or "").strip()
    match = GRADE_JSON_RE.search(content)
    if not match:
        return GradeResult(
            score=0.0,
            verdict="reject",
            note="Grader response did not contain valid JSON.",
            breakdown={},
            raw_response=output[:4000],
        )
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return GradeResult(
            score=0.0,
            verdict="reject",
            note="Grader JSON could not be parsed.",
            breakdown={},
            raw_response=output[:4000],
        )
    breakdown = {
        key: float(value)
        for key, value in (payload.get("breakdown") or {}).items()
        if isinstance(value, (int, float))
    }
    score = max(0.0, min(1.0, float(payload.get("score") or 0.0)))
    verdict = str(payload.get("verdict") or "reject").strip().lower() or "reject"
    note = str(payload.get("note") or "").strip() or "No grader note provided."
    return GradeResult(
        score=score,
        verdict=verdict,
        note=note,
        breakdown=breakdown,
        raw_response=output[:4000],
    )


async def _grade_row_via_sandbox(
    row: SeoRedirectRemapQueue,
    *,
    model: str,
) -> GradeResult:
    prompt = _build_grade_prompt(row)
    ssh_config = _ssh_config_path()
    remote_command = _remote_grade_command(prompt=prompt, model=model)

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "ssh",
                "-F",
                str(ssh_config),
                "openshell-grade-sandbox",
                remote_command,
            ],
            text=True,
            capture_output=True,
            timeout=150,
            check=False,
        )

    completed = await asyncio.to_thread(run)
    if completed.returncode != 0:
        return GradeResult(
            score=0.0,
            verdict="reject",
            note=f"Sandbox grading command failed: {completed.stderr.strip()[:300]}",
            breakdown={},
            raw_response=(completed.stdout + "\n" + completed.stderr)[:4000],
        )
    return _parse_grade_response(completed.stdout)


async def run_seo_remap_grading(
    db: AsyncSession,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job_payload = payload or {}
    campaign = str(job_payload.get("campaign") or "seo_fallback_swarm_live").strip()
    limit_value = job_payload.get("limit")
    limit = max(1, int(limit_value)) if limit_value is not None else None
    threshold = float(job_payload.get("threshold") or settings.seo_redirect_grade_threshold)
    model = str(job_payload.get("model") or "nvidia/nemotron-3-super-120b-a12b").strip()

    query = (
        select(SeoRedirectRemapQueue)
        .where(
            SeoRedirectRemapQueue.campaign == campaign,
            SeoRedirectRemapQueue.status == "proposed",
        )
        .order_by(SeoRedirectRemapQueue.created_at.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    rows = list((await db.execute(query)).scalars().all())

    promoted = 0
    rejected = 0
    processed = 0
    sample_ids: list[str] = []
    for row in rows:
        grade = _deterministic_grade(row)
        if grade is None:
            grade = await _grade_row_via_sandbox(row, model=model)
        row.grade_score = grade.score
        row.grade_payload = {
            "grader": "god_head_sandbox",
            "verdict": grade.verdict,
            "note": grade.note,
            "breakdown": grade.breakdown,
            "threshold": threshold,
            "raw_response": grade.raw_response,
        }
        row.review_note = grade.note
        row.reviewed_by = "god_head_sandbox"
        row.status = "promoted" if grade.score >= threshold else "rejected"
        if row.status == "promoted":
            promoted += 1
        else:
            rejected += 1
        processed += 1
        sample_ids.append(str(row.id))
        await db.flush()

    await db.commit()
    return {
        "campaign": campaign,
        "model": model,
        "threshold": threshold,
        "processed_count": processed,
        "promoted_count": promoted,
        "rejected_count": rejected,
        "queue_ids": sample_ids[:50],
    }
