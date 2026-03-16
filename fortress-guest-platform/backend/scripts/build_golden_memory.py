#!/usr/bin/env python3
"""
GOLDEN FEW-SHOT MEMORY BUILDER
================================
Vectorizes resolved damage claims into a dedicated Qdrant collection
(fgp_golden_claims) so the Legal Drafter can inject real historical
examples as few-shot context before drafting new claims.

Creates the collection if it doesn't exist, embeds each claim's
damage description + resolution, and upserts with full metadata.

Run:
  cd ~/Fortress-Prime/fortress-guest-platform
  ./venv/bin/python -m backend.scripts.build_golden_memory
"""

import asyncio
import hashlib
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal
from backend.models.damage_claim import DamageClaim

BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"

COLLECTION = "fgp_golden_claims"
VECTOR_DIM = 768
EMBED_URL = "http://192.168.0.100/api/embeddings"
EMBED_MODEL = "nomic-embed-text"


def _deterministic_uuid(claim_id: str) -> str:
    seed = f"golden:{claim_id}"
    return str(uuid.UUID(hashlib.md5(seed.encode()).hexdigest()))


async def _embed(client: httpx.AsyncClient, text: str) -> Optional[list[float]]:
    try:
        resp = await client.post(
            EMBED_URL,
            json={"model": EMBED_MODEL, "prompt": text[:8000]},
            timeout=30,
        )
        resp.raise_for_status()
        vec = resp.json().get("embedding", [])
        return vec if len(vec) == VECTOR_DIM else None
    except Exception as e:
        print(f"    {RED}Embedding failed: {e}{RESET}")
        return None


async def ensure_collection(client: httpx.AsyncClient) -> bool:
    qdrant_url = settings.qdrant_url.rstrip("/")
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}

    resp = await client.get(f"{qdrant_url}/collections/{COLLECTION}", headers=headers)
    if resp.status_code == 200:
        info = resp.json().get("result", {})
        print(f"  {GREEN}Collection '{COLLECTION}' exists — {info.get('points_count', 0)} points{RESET}")
        return True

    resp = await client.put(
        f"{qdrant_url}/collections/{COLLECTION}",
        json={"vectors": {"size": VECTOR_DIM, "distance": "Cosine"}},
        headers=headers,
    )
    if resp.status_code == 200:
        print(f"  {GREEN}Created collection '{COLLECTION}' (768-dim, Cosine){RESET}")

        for field in ["claim_id", "property_name", "status"]:
            await client.put(
                f"{qdrant_url}/collections/{COLLECTION}/index",
                json={"field_name": field, "field_schema": "keyword"},
                headers=headers,
            )
        return True

    print(f"  {RED}Failed to create collection: HTTP {resp.status_code}{RESET}")
    return False


def build_claim_text(claim: DamageClaim) -> str:
    """Build the text representation for embedding."""
    parts = []
    if claim.damage_description:
        parts.append(f"Damage: {claim.damage_description}")
    if claim.inspection_notes:
        parts.append(f"Inspection: {claim.inspection_notes}")
    if claim.resolution:
        parts.append(f"Resolution: {claim.resolution}")
    if claim.legal_draft:
        parts.append(f"Response sent: {claim.legal_draft[:500]}")
    if claim.policy_violations:
        parts.append(f"Violations: {claim.policy_violations}")
    if claim.damage_areas:
        parts.append(f"Areas: {', '.join(claim.damage_areas)}")
    return ". ".join(parts) if parts else ""


async def main():
    print(f"""
{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════╗
║        GOLDEN FEW-SHOT MEMORY BUILDER                           ║
║        Vectorizing historical damage claims for RAG              ║
╚══════════════════════════════════════════════════════════════════╝{RESET}
""")

    stats = {"scanned": 0, "embedded": 0, "skipped": 0, "errors": 0}

    async with httpx.AsyncClient(timeout=30) as http:
        ready = await ensure_collection(http)
        if not ready:
            print(f"  {RED}Aborting — Qdrant collection unavailable{RESET}")
            return

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DamageClaim)
                .where(DamageClaim.damage_description.isnot(None))
                .order_by(DamageClaim.created_at.desc())
            )
            claims = result.scalars().all()

            print(f"\n  {BOLD}Found {len(claims)} damage claims to vectorize{RESET}\n")

            qdrant_url = settings.qdrant_url.rstrip("/")
            headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
            batch: list[dict] = []

            for claim in claims:
                stats["scanned"] += 1
                text = build_claim_text(claim)
                if not text or len(text) < 20:
                    stats["skipped"] += 1
                    continue

                vec = await _embed(http, text)
                if not vec:
                    stats["errors"] += 1
                    continue

                point_id = _deterministic_uuid(str(claim.id))

                prop_name = ""
                if claim.property:
                    prop_name = claim.property.name or ""

                guest_name = ""
                if claim.guest:
                    guest_name = f"{claim.guest.first_name or ''} {claim.guest.last_name or ''}".strip()

                batch.append({
                    "id": point_id,
                    "vector": vec,
                    "payload": {
                        "claim_id": str(claim.id),
                        "claim_number": claim.claim_number,
                        "text": text[:2000],
                        "damage_description": (claim.damage_description or "")[:500],
                        "resolution": (claim.resolution or "")[:500],
                        "legal_draft": (claim.legal_draft or "")[:1000],
                        "status": claim.status or "",
                        "property_name": prop_name,
                        "guest_name": guest_name,
                        "damage_areas": claim.damage_areas or [],
                        "estimated_cost": float(claim.estimated_cost) if claim.estimated_cost else None,
                        "vectorized_at": datetime.utcnow().isoformat(),
                    },
                })
                stats["embedded"] += 1

                print(f"    {GREEN}EMBEDDED{RESET} {claim.claim_number}  "
                      f"{(claim.damage_description or '')[:60]}...")

                if len(batch) >= 50:
                    resp = await http.put(
                        f"{qdrant_url}/collections/{COLLECTION}/points",
                        json={"points": batch},
                        headers=headers,
                    )
                    resp.raise_for_status()
                    batch = []

            if batch:
                resp = await http.put(
                    f"{qdrant_url}/collections/{COLLECTION}/points",
                    json={"points": batch},
                    headers=headers,
                )
                resp.raise_for_status()

    print(f"""
{BOLD}{'─' * 64}
  GOLDEN MEMORY BUILD COMPLETE
{'─' * 64}{RESET}

    Claims scanned:    {stats['scanned']}
    Embedded:          {GREEN}{stats['embedded']}{RESET}
    Skipped (empty):   {stats['skipped']}
    Errors:            {stats['errors']}

  Collection: {COLLECTION} @ {settings.qdrant_url}
""")


if __name__ == "__main__":
    asyncio.run(main())
