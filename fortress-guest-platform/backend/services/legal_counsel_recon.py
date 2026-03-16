"""
Litigator Profiler — attorney reconnaissance via CourtListener.

Profiles opposing counsel or finds defense counsel by querying
the CourtListener people/attorneys database and cross-referencing
their case history for Georgia contract disputes.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.courtlistener_client import courtlistener_get
from backend.services.ai_router import execute_resilient_inference

logger = logging.getLogger(__name__)


class LitigatorProfile(BaseModel):
    name: str = Field(..., min_length=1)
    cases_found: int = Field(default=0)
    frequent_jurisdictions: list[str] = Field(default_factory=list)
    top_cited_precedents: list[str] = Field(default_factory=list)
    practice_areas: list[str] = Field(default_factory=list)
    win_indicators: list[str] = Field(default_factory=list)
    courtlistener_url: str = Field(default="")
    analysis: str = Field(default="")


class ReconResult(BaseModel):
    query: str
    profiles: list[LitigatorProfile] = Field(default_factory=list)
    total_api_results: int = 0
    inference_source: str = ""
    latency_ms: int = 0


PROFILER_SYSTEM_PROMPT = (
    "You are a legal intelligence analyst. Analyze the attorney search results "
    "from CourtListener. For each attorney, build a litigation profile focusing on: "
    "their experience in contract disputes, breach of contract, or account stated cases; "
    "which Georgia courts they frequently appear in; any notable wins or favorable "
    "precedents they have cited; and their practice area specialties. "
    "Return ONLY valid JSON array: "
    '[{"name":"...","cases_found":15,"frequent_jurisdictions":["Fannin County Superior Court"],'
    '"top_cited_precedents":["Smith v. Jones, 300 Ga. App. 123"],'
    '"practice_areas":["contract disputes","commercial litigation"],'
    '"win_indicators":["Successfully defended in 3 breach of contract cases"],'
    '"courtlistener_url":"...","analysis":"Summary of this attorney profile"}]'
)


async def profile_georgia_attorney(
    name_or_specialty: str,
    db: AsyncSession | None = None,
    max_profiles: int = 5,
) -> ReconResult:
    """Search CourtListener for attorney profiles matching the query."""

    people_data = await courtlistener_get(
        "people/",
        params={
            "q": name_or_specialty,
            "type": "a",
            "page_size": min(max_profiles * 2, 10),
        },
    )

    search_data = await courtlistener_get(
        "search/",
        params={
            "q": f'attorney:"{name_or_specialty}" AND court:(ga OR gaapp OR gas OR ca11)',
            "type": "o",
            "order_by": "score desc",
            "page_size": 10,
        },
    )

    raw_results: list[dict] = []
    total = 0

    if people_data and people_data.get("results"):
        total += people_data.get("count", 0)
        for p in people_data["results"][:max_profiles * 2]:
            raw_results.append({
                "type": "person",
                "name": f"{p.get('name_first', '')} {p.get('name_last', '')}".strip() or p.get("name_full", ""),
                "url": p.get("absolute_url") or p.get("resource_uri", ""),
                "positions": [
                    {
                        "court": pos.get("court", {}).get("short_name", "") if isinstance(pos.get("court"), dict) else str(pos.get("court", "")),
                        "position_type": pos.get("position_type", ""),
                    }
                    for pos in (p.get("positions", []) or [])[:5]
                ],
            })

    if search_data and search_data.get("results"):
        total += search_data.get("count", 0)
        for r in search_data["results"][:10]:
            raw_results.append({
                "type": "case_appearance",
                "case_name": r.get("caseName") or r.get("case_name") or "",
                "court": r.get("court") or "",
                "date_filed": r.get("dateFiled") or r.get("date_filed") or "",
                "snippet": (r.get("snippet") or "")[:300],
                "url": r.get("absolute_url") or "",
            })

    if not raw_results:
        return ReconResult(
            query=name_or_specialty,
            total_api_results=0,
            inference_source="no_results",
        )

    prompt = json.dumps(raw_results, indent=2, default=str)

    result = await execute_resilient_inference(
        prompt=prompt,
        task_type="legal",
        system_message=PROFILER_SYSTEM_PROMPT,
        max_tokens=2048,
        temperature=0.1,
        db=db,
        source_module="legal_counsel_recon",
    )

    profiles: list[LitigatorProfile] = []
    try:
        content = result.text.strip()
        if content.startswith("```"):
            nl = content.find("\n")
            content = content[nl + 1:] if nl > 0 else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        start = content.find("[")
        end = content.rfind("]")
        if start >= 0 and end > start:
            content = content[start : end + 1]

        parsed = json.loads(content)
        if isinstance(parsed, list):
            for item in parsed[:max_profiles]:
                try:
                    profiles.append(LitigatorProfile.model_validate(item))
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("counsel_recon_parse_failed error=%s", str(exc)[:200])

    logger.info(
        "counsel_recon_complete",
        query=name_or_specialty,
        api_results=total,
        profiles_built=len(profiles),
        source=result.source,
    )

    return ReconResult(
        query=name_or_specialty,
        profiles=profiles,
        total_api_results=total,
        inference_source=result.source,
        latency_ms=result.latency_ms,
    )
