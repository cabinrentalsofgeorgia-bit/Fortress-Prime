#!/usr/bin/env python3
"""
HISTORICAL DAMAGE EXTRACTION AGENT
====================================
Scans all reservations with Streamline staff notes, uses AI to detect
property damage incidents, and backfills the damage_claims table with
structured records.

LLM cascade:
  1. DGX Memory (Spark 4, Llama 3.3 70B) — local, sovereign
  2. DGX Ollama base (Nginx LB) — local fallback
  3. OpenAI GPT-4o — cloud fallback (non-PII prompt only)

Run:
  cd ~/Fortress-Prime/fortress-guest-platform
  ./venv/bin/python -m backend.scripts.extract_historical_damages
"""

import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select, cast, String, and_

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.reservation import Reservation
from backend.models.damage_claim import DamageClaim

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Output formatting
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"

BATCH_SIZE = 10


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic schema for AI extraction
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DamageExtraction(BaseModel):
    """Structured output from AI damage analysis of staff notes."""
    has_damage: bool = Field(
        description="True if the guest caused property damage, broke items, "
                    "or had a security deposit deduction for damage."
    )
    incident_description: str = Field(
        default="",
        description="Summary of what was damaged or broken. Empty if no damage."
    )
    damage_areas: list[str] = Field(
        default_factory=list,
        description="List of affected areas (e.g. 'hot tub', 'bed frame', 'kitchen')."
    )
    reported_by: str = Field(
        default="",
        description="Staff member name who reported or documented the damage, if available."
    )
    action_taken: str = Field(
        default="",
        description="What action was taken (e.g. 'kept security deposit', 'threw away mirror', "
                    "'charged guest for cleaning')."
    )
    policy_violations: str = Field(
        default="",
        description="Any policy violations noted (e.g. 'smoking', 'unauthorized pets', 'excess occupancy')."
    )


EXTRACTION_PROMPT = """Analyze the following staff notes for a cabin rental reservation. 
Did the guest cause any property damage, break any items, leave excessive mess, 
or require a deduction from their security deposit?

STAFF NOTES:
{notes_text}

Respond STRICTLY in JSON matching this exact schema. No markdown, no explanation — pure JSON only:
{{
  "has_damage": true/false,
  "incident_description": "summary of damage if any",
  "damage_areas": ["area1", "area2"],
  "reported_by": "staff member name if mentioned",
  "action_taken": "what was done about it",
  "policy_violations": "any policy violations noted"
}}

If there is NO damage, respond: {{"has_damage": false, "incident_description": "", "damage_areas": [], "reported_by": "", "action_taken": "", "policy_violations": ""}}"""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LLM call with cascade fallback
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def call_llm(prompt: str, client: httpx.AsyncClient) -> Optional[str]:
    """Try DGX Memory -> Ollama base -> OpenAI. Returns raw text or None."""

    # Tier 1: DGX Memory (Spark 4)
    try:
        resp = await client.post(
            settings.dgx_memory_url,
            json={
                "model": settings.dgx_memory_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512},
            },
            timeout=90,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
    except Exception:
        pass

    # Tier 2: Ollama base (Nginx LB -> SWARM)
    try:
        resp = await client.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": settings.ollama_fast_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 512},
            },
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
    except Exception:
        pass

    # Tier 3: OpenAI (cloud fallback)
    if settings.openai_api_key:
        try:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": [
                        {"role": "system", "content": "You are a property damage analyst. Respond with JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 512,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

    return None


def parse_extraction(raw: str) -> Optional[DamageExtraction]:
    """Parse the AI response into a DamageExtraction, tolerating markdown fences."""
    if not raw:
        return None

    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start == -1 or brace_end == -1:
        return None

    text = text[brace_start:brace_end + 1]

    try:
        data = json.loads(text)
        return DamageExtraction(**data)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def format_notes(notes_json) -> Optional[str]:
    """Convert streamline_notes JSONB to a readable text block."""
    if not notes_json:
        return None
    if isinstance(notes_json, str):
        try:
            notes_json = json.loads(notes_json)
        except json.JSONDecodeError:
            return notes_json if len(notes_json) > 10 else None

    if not isinstance(notes_json, list) or len(notes_json) == 0:
        return None

    parts = []
    for n in notes_json:
        if isinstance(n, dict):
            msg = n.get("message", "").strip()
            if msg and len(msg) > 5:
                author = n.get("processor_name", "Staff")
                parts.append(f"[{author}] {msg}")
        elif isinstance(n, str) and len(n.strip()) > 5:
            parts.append(n.strip())

    return " | ".join(parts) if parts else None


def generate_claim_number() -> str:
    """Generate a unique damage claim number."""
    ts = int(time.time())
    short = str(uuid4())[:6].upper()
    return f"DC-{ts}-{short}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Main extraction loop
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def main():
    print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════╗
║        HISTORICAL DAMAGE EXTRACTION AGENT                       ║
║        Scanning Streamline staff notes for damage incidents      ║
╚══════════════════════════════════════════════════════════════════╝{RESET}
""")

    stats = {
        "scanned": 0,
        "with_notes": 0,
        "damage_found": 0,
        "claims_created": 0,
        "already_claimed": 0,
        "parse_errors": 0,
        "llm_errors": 0,
    }

    async with AsyncSessionLocal() as db:
        # Find reservations with non-empty staff notes
        result = await db.execute(
            select(Reservation)
            .where(
                and_(
                    Reservation.streamline_notes.isnot(None),
                    cast(Reservation.streamline_notes, String) != "null",
                    cast(Reservation.streamline_notes, String) != "[]",
                )
            )
            .order_by(Reservation.check_in_date.desc())
        )
        all_reservations = result.scalars().all()

        print(f"  {BOLD}Found {len(all_reservations)} reservations with staff notes{RESET}\n")

        # Get existing claims to avoid duplicates
        existing_claims = await db.execute(
            select(DamageClaim.reservation_id)
        )
        claimed_res_ids = {row[0] for row in existing_claims.fetchall()}

        async with httpx.AsyncClient() as http:
            for batch_start in range(0, len(all_reservations), BATCH_SIZE):
                batch = all_reservations[batch_start:batch_start + BATCH_SIZE]
                batch_num = (batch_start // BATCH_SIZE) + 1
                total_batches = (len(all_reservations) + BATCH_SIZE - 1) // BATCH_SIZE

                print(f"  {DIM}── Batch {batch_num}/{total_batches} "
                      f"(reservations {batch_start + 1}-{batch_start + len(batch)}) ──{RESET}")

                for res in batch:
                    stats["scanned"] += 1

                    notes_text = format_notes(res.streamline_notes)
                    if not notes_text:
                        continue

                    stats["with_notes"] += 1

                    if res.id in claimed_res_ids:
                        stats["already_claimed"] += 1
                        continue

                    prompt = EXTRACTION_PROMPT.format(notes_text=notes_text[:4000])
                    raw_response = await call_llm(prompt, http)

                    if not raw_response:
                        stats["llm_errors"] += 1
                        print(f"    {RED}LLM failed for res {res.confirmation_code}{RESET}")
                        continue

                    extraction = parse_extraction(raw_response)
                    if not extraction:
                        stats["parse_errors"] += 1
                        print(f"    {YELLOW}Parse error for res {res.confirmation_code}: "
                              f"{raw_response[:80]}...{RESET}")
                        continue

                    if not extraction.has_damage:
                        continue

                    stats["damage_found"] += 1

                    claim = DamageClaim(
                        claim_number=generate_claim_number(),
                        reservation_id=res.id,
                        property_id=res.property_id,
                        guest_id=res.guest_id,
                        damage_description=extraction.incident_description[:2000],
                        policy_violations=extraction.policy_violations or None,
                        damage_areas=extraction.damage_areas or None,
                        reported_by=extraction.reported_by or "AI-extracted from staff notes",
                        inspection_date=res.check_out_date or date.today(),
                        inspection_notes=f"Action taken: {extraction.action_taken}" if extraction.action_taken else None,
                        status="reported",
                        agreement_clauses={
                            "extraction_source": "streamline_notes",
                            "ai_model": "damage_extraction_agent",
                            "confirmation_code": res.confirmation_code,
                        },
                    )
                    db.add(claim)
                    claimed_res_ids.add(res.id)
                    stats["claims_created"] += 1

                    print(f"    {GREEN}DAMAGE{RESET} res={res.confirmation_code}  "
                          f"{extraction.incident_description[:70]}...")

                # Commit after each batch
                await db.commit()
                print(f"    {DIM}Batch committed. "
                      f"Running total: {stats['damage_found']} damage, "
                      f"{stats['claims_created']} claims created{RESET}\n")

    # Summary
    print(f"""
{BOLD}{'─' * 64}
  EXTRACTION COMPLETE
{'─' * 64}{RESET}

  {BOLD}Scan Results:{RESET}
    Reservations scanned          {stats['scanned']}
    With readable notes           {stats['with_notes']}
    Already had claims            {stats['already_claimed']}
    Damage incidents detected     {GREEN}{stats['damage_found']}{RESET}
    New claims created            {GREEN}{BOLD}{stats['claims_created']}{RESET}

  {BOLD}Errors:{RESET}
    LLM call failures             {stats['llm_errors']}
    JSON parse failures           {stats['parse_errors']}
""")


if __name__ == "__main__":
    asyncio.run(main())
