"""
Jurisprudence Engine — Precedent Radar.

Queries CourtListener for Georgia case law matching specific legal theories,
then routes results through Sovereign to extract only winning precedent
for contract disputes and authority challenges.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.courtlistener_client import courtlistener_get
from backend.services.ai_router import execute_resilient_inference

logger = logging.getLogger(__name__)

GEORGIA_COURTS = [
    "ga",
    "gaapp",
    "gas",
    "ca11",
]


class CasePrecedent(BaseModel):
    case_name: str = Field(..., min_length=1)
    citation: str = Field(default="")
    date_filed: str = Field(default="")
    summary: str = Field(default="")
    url: str = Field(default="")
    relevance: str = Field(default="")

    @field_validator("citation", mode="before")
    @classmethod
    def _coerce_citation(cls, v):
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return str(v or "").strip()

    @field_validator("date_filed", mode="before")
    @classmethod
    def _coerce_date(cls, v):
        return str(v or "").strip()


class PrecedentSearchResult(BaseModel):
    query: str
    total_api_results: int = 0
    precedents: list[CasePrecedent] = Field(default_factory=list)
    inference_source: str = ""
    latency_ms: int = 0


FILTER_SYSTEM_PROMPT = (
    "You are a Georgia litigation research specialist. Analyze the following case law "
    "search results from CourtListener. For each case, determine if it is relevant to "
    "defending a contract dispute, breach of contract, account stated, apparent authority "
    "challenge, or single-member LLC liability case in Georgia. "
    "Extract the legal standard or principle from each relevant case that a defendant "
    "could cite in their defense. Include cases that discuss: authority to bind an LLC, "
    "statute of limitations for account stated, elements of breach of contract, or "
    "procedural defenses under Georgia law. "
    "Return ONLY valid JSON array (at least 3 cases if possible): "
    '[{"case_name":"...","citation":"...","date_filed":"YYYY-MM-DD","summary":"...",'
    '"url":"...","relevance":"The legal standard or defense principle from this case"}]'
)


async def search_georgia_precedent(
    keywords: list[str],
    db: AsyncSession | None = None,
    max_results: int = 10,
) -> PrecedentSearchResult:
    """Search CourtListener for Georgia case law matching the keywords."""
    query_str = " ".join(keywords)

    data = await courtlistener_get(
        "search/",
        params={
            "q": query_str,
            "court": ",".join(GEORGIA_COURTS),
            "type": "o",
            "order_by": "score desc",
            "page_size": min(max_results * 2, 20),
        },
    )

    if not data:
        return PrecedentSearchResult(
            query=query_str,
            total_api_results=0,
            precedents=[],
            inference_source="courtlistener_unavailable",
        )

    results = data.get("results", [])
    total = data.get("count", len(results))

    if not results:
        return PrecedentSearchResult(
            query=query_str,
            total_api_results=total,
            precedents=[],
            inference_source="no_results",
        )

    raw_cases = []
    for r in results[:max_results * 2]:
        raw_cases.append({
            "case_name": r.get("caseName") or r.get("case_name") or "Unknown",
            "citation": r.get("citation") or ",".join(r.get("citation", [])) if isinstance(r.get("citation"), list) else str(r.get("citation", "")),
            "date_filed": r.get("dateFiled") or r.get("date_filed") or "",
            "court": r.get("court") or "",
            "snippet": (r.get("snippet") or "")[:500],
            "url": r.get("absolute_url") or "",
        })

    prompt = json.dumps(raw_cases, indent=2, default=str)

    result = await execute_resilient_inference(
        prompt=prompt,
        task_type="legal",
        system_message=FILTER_SYSTEM_PROMPT,
        max_tokens=2048,
        temperature=0.1,
        db=db,
        source_module="legal_jurisprudence",
    )

    precedents: list[CasePrecedent] = []
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
            for item in parsed[:max_results]:
                try:
                    precedents.append(CasePrecedent.model_validate(item))
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("jurisprudence_parse_failed error=%s", str(exc)[:200])

    logger.info(
        "precedent_search_complete",
        query=query_str,
        api_results=total,
        filtered=len(precedents),
        source=result.source,
    )

    return PrecedentSearchResult(
        query=query_str,
        total_api_results=total,
        precedents=precedents,
        inference_source=result.source,
        latency_ms=result.latency_ms,
    )
