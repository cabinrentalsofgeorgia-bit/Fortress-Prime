"""
Legal Tactical Strike Router — offensive litigation maneuvers
through the Resilient Router with PII sanitization.
"""
import structlog
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.core.database import AsyncSessionLocal
from backend.services.ai_router import execute_resilient_inference
from backend.services.legal_case_graph import get_case_graph_snapshot
from backend.services.legal_search_engine import synthesize_historic_search
from backend.services.legal_sanctions_tripwire import detect_material_contradictions
from backend.services.legal_deposition_prep import generate_kill_sheet
from backend.services.legal_evidence_ingestion import ingest_document_to_graph
from backend.services.legal_ediscovery import process_vault_upload

logger = structlog.get_logger()

router = APIRouter()

STRIKE_TYPES = {"deposition_kill_sheet", "sanctions_tripwire", "proportional_discovery"}

STRIKE_PROMPTS = {
    "deposition_kill_sheet": (
        "You are an aggressive litigation strategist. Generate a Deposition Kill-Sheet: "
        "a structured list of the most devastating questions to ask the opposing party's "
        "deponent, organized by topic. Each question must exploit a specific contradiction "
        "or vulnerability in the evidence graph. Include follow-up trap questions. "
        "Return a strict JSON object: {\"topics\": [{\"topic\": \"...\", \"questions\": [\"...\"]}]}"
    ),
    "sanctions_tripwire": (
        "You are a Rule 11 / O.C.G.A. § 9-15-14 sanctions analyst. Review the evidence graph "
        "for patterns of abusive litigation, frivolous claims, or bad-faith conduct by the "
        "opposing party. Identify every potential sanctions trigger with statutory citations. "
        "Return a strict JSON object: {\"triggers\": [{\"basis\": \"...\", \"statute\": \"...\", "
        "\"evidence_ref\": \"...\", \"severity\": \"high|medium|low\"}]}"
    ),
    "proportional_discovery": (
        "You are a Rule 26 proportionality analyst. Review the evidence graph and identify "
        "the most proportional discovery requests that will yield maximum litigation value "
        "with minimum burden. Return a strict JSON object: "
        "{\"requests\": [{\"type\": \"interrogatory|rfp|admission\", \"content\": \"...\", "
        "\"expected_yield\": \"...\"}]}"
    ),
}


def _graph_to_text(snapshot: dict) -> str:
    nodes = snapshot.get("nodes") or []
    edges = snapshot.get("edges") or []
    if not nodes:
        return "No graph entities available."

    label_by_id = {}
    lines = []
    for n in nodes:
        label = n.label if hasattr(n, "label") else n.get("label", "?")
        etype = n.entity_type if hasattr(n, "entity_type") else n.get("entity_type", "?")
        nid = str(n.id if hasattr(n, "id") else n.get("id", "?"))
        label_by_id[nid] = label
        lines.append(f"- [{etype}] {label}")

    for e in edges:
        src_id = str(e.source_node_id if hasattr(e, "source_node_id") else e.get("source_node_id", "?"))
        tgt_id = str(e.target_node_id if hasattr(e, "target_node_id") else e.get("target_node_id", "?"))
        rel = e.relationship_type if hasattr(e, "relationship_type") else e.get("relationship_type", "?")
        ref = (e.source_ref if hasattr(e, "source_ref") else e.get("source_ref")) or "n/a"
        src_label = label_by_id.get(src_id, src_id)
        tgt_label = label_by_id.get(tgt_id, tgt_id)
        lines.append(f"- {src_label} --({rel})--> {tgt_label} [ref: {ref}]")

    return "\n".join(lines)


class TacticalStrikeRequest(BaseModel):
    strike_type: str = Field(..., pattern="^(deposition_kill_sheet|sanctions_tripwire|proportional_discovery)$")


class OmniSearchRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000)


@router.post("/cases/{slug}/tactical-strike", summary="Execute aggressive tactical maneuver")
async def execute_tactical_strike(slug: str, body: TacticalStrikeRequest):
    if body.strike_type not in STRIKE_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid strike_type: {body.strike_type}")

    async with AsyncSessionLocal() as db:
        snapshot = await get_case_graph_snapshot(db, case_slug=slug)
        graph_text = _graph_to_text(snapshot)

        system_prompt = STRIKE_PROMPTS[body.strike_type]

        result = await execute_resilient_inference(
            prompt=graph_text,
            task_type="legal",
            system_message=system_prompt,
            max_tokens=1500,
            temperature=0.15,
            db=db,
            source_module=f"legal_tactical/{body.strike_type}",
        )

        await db.commit()

    return {
        "strike_type": body.strike_type,
        "case_slug": slug,
        "output": result.text,
        "inference_source": result.source,
        "breaker_state": result.breaker_state,
        "latency_ms": result.latency_ms,
    }


@router.post("/cases/{slug}/omni-search", summary="Historic Omni-Search")
async def omni_search(slug: str, body: OmniSearchRequest):
    async with AsyncSessionLocal() as db:
        result = await synthesize_historic_search(
            db=db,
            query=body.query,
            case_slug=slug,
        )
        await db.commit()
    return result


@router.post("/cases/{slug}/tactical/tripwire/run", summary="Run Sanctions Tripwire")
async def run_sanctions_tripwire(slug: str):
    async with AsyncSessionLocal() as db:
        result = await detect_material_contradictions(db=db, case_slug=slug)
    return result


@router.post("/cases/{slug}/tactical/kill-sheet/generate", summary="Generate Deposition Kill-Sheet")
async def generate_deposition_kill_sheet(slug: str):
    async with AsyncSessionLocal() as db:
        result = await generate_kill_sheet(db=db, case_slug=slug)
    return result


@router.get("/cases/{slug}/deposition/kill-sheet", summary="Generate Deposition Kill-Sheet (GET alias)")
async def get_deposition_kill_sheet(slug: str):
    """Clean GET alias for the kill-sheet — generates on demand."""
    async with AsyncSessionLocal() as db:
        result = await generate_kill_sheet(db=db, case_slug=slug)
    return result


class EvidenceIngestRequest(BaseModel):
    document_text: str = Field(..., min_length=20, max_length=500000)
    source_ref: str = Field(..., min_length=3, max_length=500)


@router.post("/cases/{slug}/evidence/ingest-text", summary="Ingest document text into case graph")
async def ingest_evidence_text(slug: str, body: EvidenceIngestRequest):
    async with AsyncSessionLocal() as db:
        try:
            result = await ingest_document_to_graph(
                db=db,
                case_slug=slug,
                document_text=body.document_text,
                source_ref=body.source_ref,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


async def _bg_process_upload(case_slug: str, file_bytes: bytes, file_name: str, mime_type: str):
    async with AsyncSessionLocal() as db:
        await process_vault_upload(db, case_slug, file_bytes, file_name, mime_type)


@router.post("/cases/{slug}/vault/upload", summary="Upload file to E-Discovery Vault")
async def upload_vault_file(
    slug: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=422, detail="Empty file")
    if len(file_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds 50MB limit")

    mime = file.content_type or "application/octet-stream"
    fname = file.filename or "unknown"

    background_tasks.add_task(_bg_process_upload, slug, file_bytes, fname, mime)

    return {"status": "queued", "file_name": fname, "size_bytes": len(file_bytes)}


@router.get("/cases/{slug}/vault/documents", summary="List vault documents for case")
async def list_vault_documents(slug: str):
    async with AsyncSessionLocal() as db:
        r = await db.execute(
            text("""
                SELECT id, file_name, mime_type, file_size_bytes, chunk_count,
                       processing_status, error_detail, created_at
                FROM legal.vault_documents
                WHERE case_slug = :slug
                ORDER BY created_at DESC
            """),
            {"slug": slug},
        )
        docs = []
        for row in r.fetchall():
            d = dict(row._mapping)
            d["id"] = str(d["id"])
            if d.get("created_at"):
                d["created_at"] = str(d["created_at"])
            docs.append(d)
    return {"case_slug": slug, "documents": docs, "total": len(docs)}
