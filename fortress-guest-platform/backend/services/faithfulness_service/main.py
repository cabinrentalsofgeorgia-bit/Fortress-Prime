"""Wave 5.6 — Faithfulness wrapper service.

Thin FastAPI wrapper around `backend.services.guardrails.faithfulness_judge.score`
so callers can hit a stable HTTP endpoint instead of importing the module
directly. Bound to 127.0.0.1 only — callers are on spark-2.

Per Wave 5.6 brief §4.2 Option B: keeps the prompt template versioned in
code rather than YAML middleware, simpler debug + rollback than introducing
LiteLLM hook chains.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from backend.services.guardrails.faithfulness_judge import score

app = FastAPI(title="Fortress Faithfulness Judge", version="0.1.0")


class FaithfulnessRequest(BaseModel):
    section_id: str = Field(..., description="Echo'd back into the judge output.")
    generated_section: str = Field(..., description="Section text to be audited.")
    retrieval_packet: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Chunks fed to the section's generation. Each item is "
        "{source_id|source|file_name, text|content}.",
    )


@app.post("/v1/faithfulness/score")
async def faithfulness_score(req: FaithfulnessRequest) -> dict[str, Any]:
    result = score(req.section_id, req.generated_section, req.retrieval_packet)
    if result.get("error") in ("empty_section", "empty_packet"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
