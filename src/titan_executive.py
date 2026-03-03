#!/usr/bin/env python3
"""
FORTRESS PRIME — Titan Executive (Master Router)
==================================================
The Sovereign orchestrator that dispatches queries to the correct sector agent.
Reads fortress_atlas.yaml at startup to understand the corporate topology.

Architecture:
    - Loads all sectors from fortress_atlas.yaml
    - Routes queries to the correct sector agent based on context
    - Enforces cross-sector isolation (only Sovereign + Legal may read across)
    - In TITAN mode, injects the correct persona into the DeepSeek-R1 context

Usage:
    from src.titan_executive import TitanExecutive

    executive = TitanExecutive()
    result = executive.route("What is CROG's occupancy rate?")
    # → Dispatches to S01 (crog) sector agent

CLI:
    ./venv/bin/python src/titan_executive.py --query "Summarize legal exposure"
"""

import os
import sys
import json
import yaml
import logging
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import get_inference_client, FORTRESS_DEFCON

log = logging.getLogger("fortress.executive")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [EXEC] %(message)s")

ATLAS_PATH = Path(__file__).resolve().parent.parent / "fortress_atlas.yaml"


class TitanExecutive:
    """Master Router — dispatches queries to sector agents."""

    def __init__(self, atlas_path: Path = ATLAS_PATH):
        self.sectors = {}
        self.atlas = {}
        self._load_atlas(atlas_path)

    def _load_atlas(self, path: Path):
        if not path.exists():
            log.warning(f"Atlas not found at {path}")
            return
        with open(path) as f:
            self.atlas = yaml.safe_load(f)
        for sector in self.atlas.get("fortress_prime", {}).get("sectors", []):
            slug = sector["slug"]
            self.sectors[slug] = sector
            log.info(f"Registered sector: {slug} ({sector['name']}) — {sector.get('persona', 'N/A')}")
        log.info(f"Atlas loaded: {len(self.sectors)} sectors")

    def get_sector(self, slug: str) -> dict:
        if slug not in self.sectors:
            raise ValueError(f"Unknown sector: {slug}. Known: {list(self.sectors.keys())}")
        return self.sectors[slug]

    def classify_query(self, query: str) -> str:
        """Determine which sector should handle a query based on keywords."""
        q = query.lower()
        routing = {
            "crog": ["cabin", "rental", "guest", "booking", "property", "occupancy", "blue ridge",
                     "airbnb", "vrbo", "streamline", "taylor", "cleaning"],
            "comp": ["revenue", "invoice", "tax", "expense", "financial", "vendor", "accounting",
                     "bank", "transaction", "cfo", "audit", "receipt", "payment"],
            "dev": ["construction", "permit", "contractor", "build", "renovation", "engineering",
                    "inspection", "zoning"],
            "legal": ["lawsuit", "legal", "attorney", "court", "case", "stuart", "generali",
                      "motion", "filing", "evidence", "deposition", "subpoena", "eckles"],
            "bloom": ["art", "etsy", "print", "verse", "bloom", "digital", "creative", "shop"],
        }
        scores = {}
        for slug, keywords in routing.items():
            scores[slug] = sum(1 for kw in keywords if kw in q)
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return "comp"  # default to comptroller for unmatched queries
        return best

    def build_system_prompt(self, slug: str) -> str:
        """Build a sector-aware system prompt for the LLM."""
        sector = self.get_sector(slug)
        return (
            f"You are the {sector.get('persona', 'Fortress Agent')}, "
            f"the AI agent responsible for {sector['name']} (sector {sector['code']}).\n"
            f"Description: {sector.get('description', 'N/A')}\n"
            f"DB Schema: {sector.get('db_schema', 'public')}\n"
            f"Stay within your sector's scope. Do not access other divisions' data "
            f"unless you are the Sovereign or Legal agent performing an authorized audit.\n"
            f"Current DEFCON mode: {FORTRESS_DEFCON}"
        )

    def route(self, query: str, sector_override: str = None) -> dict:
        """Route a query to the correct sector and get a response."""
        slug = sector_override or self.classify_query(query)
        sector = self.get_sector(slug)
        system_prompt = self.build_system_prompt(slug)

        log.info(f"Routing to {slug} ({sector['name']}): {query[:80]}...")

        client, model = get_inference_client()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query},
                ],
                temperature=0.3,
                max_tokens=4096,
            )
            answer = response.choices[0].message.content or ""
        except Exception as e:
            log.error(f"LLM call failed: {e}")
            answer = f"Error: {e}"

        return {
            "sector": slug,
            "sector_name": sector["name"],
            "persona": sector.get("persona", ""),
            "model": model,
            "defcon": FORTRESS_DEFCON,
            "answer": answer,
        }

    def state_of_the_union(self) -> str:
        """Generate a cross-sector briefing (Sovereign access only)."""
        lines = [f"FORTRESS PRIME — State of the Union ({FORTRESS_DEFCON} mode)", "=" * 60]
        for slug, sector in self.sectors.items():
            lines.append(f"\n[{sector['code']}] {sector['name']} — {sector.get('persona', '')}")
            lines.append(f"  Schema: {sector.get('db_schema', 'N/A')}")
            lines.append(f"  Description: {sector.get('description', 'N/A')[:100]}...")
        return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Titan Executive — Master Router")
    parser.add_argument("--query", type=str, help="Query to route")
    parser.add_argument("--sector", type=str, help="Override sector slug")
    parser.add_argument("--status", action="store_true", help="Show sector status")
    args = parser.parse_args()

    exec_ = TitanExecutive()

    if args.status:
        print(exec_.state_of_the_union())
    elif args.query:
        result = exec_.route(args.query, sector_override=args.sector)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
