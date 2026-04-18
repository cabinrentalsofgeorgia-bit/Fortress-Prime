"""
Sovereign Wealth Swarm — LangGraph Multi-Agent Cognitive Engine

Three-agent linear pipeline for autonomous receipt processing:
  1. Data Extractor (SWARM)         — deterministic JSON from raw OCR text
  2. CFP Tax Strategist (HYDRA)     — CapEx vs OpEx classification via R1-70B
  3. Compliance Inspector (SWARM)   — RAG retrieval from cfp_wealth_vault + zoning eval

The compiled graph is invoked synchronously. All nodes use the sync OpenAI
client from config.get_inference_client() and sync Qdrant/httpx clients to
avoid nested event-loop crashes when called from FastAPI via to_thread().

Usage (standalone):
    from src.wealth_swarm_graph import wealth_swarm
    result = wealth_swarm.invoke({
        "project_id": "uuid-here",
        "receipt_text": "HOME DEPOT  ...",
        "extracted_data": {},
        "tax_strategy": "",
        "compliance_flags": [],
        "ready_for_ledger": False,
        "audit_trail": [],
    })
"""

import json
import os
import re
import logging
from typing import TypedDict, List

import httpx
from langgraph.graph import StateGraph, END
from qdrant_client import QdrantClient

from config import get_inference_client

log = logging.getLogger("wealth_swarm")

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = "cfp_wealth_vault"
EMBED_MODEL = "nomic-embed-text"


class WealthState(TypedDict):
    project_id: str
    receipt_text: str
    extracted_data: dict
    tax_strategy: str
    compliance_flags: List[str]
    ready_for_ledger: bool
    audit_trail: List[str]


# ---------------------------------------------------------------------------
# Agent 1: Data Extractor (SWARM — fast JSON extraction)
# ---------------------------------------------------------------------------

def extraction_node(state: WealthState) -> dict:
    """Parse raw receipt/invoice OCR text into structured JSON."""
    log.info("[SWARM] Extractor Agent parsing receipt data...")
    client, model = get_inference_client("SWARM")

    prompt = (
        "You are an expert accounting data extractor. Parse the following "
        "receipt or invoice text. Extract the vendor name, the total amount "
        "as a float, and a list of purchased categories (e.g., lumber, "
        "plumbing, electrical, appliances).\n\n"
        f"RECEIPT TEXT:\n{state['receipt_text']}\n\n"
        'Respond ONLY with valid JSON: '
        '{"vendor": "name", "total": 0.00, "categories": ["item1"]}'
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": prompt}],
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    raw_content = resp.choices[0].message.content
    try:
        extracted = json.loads(raw_content)
    except (json.JSONDecodeError, TypeError):
        log.error("Extractor returned non-JSON: %s", raw_content[:200])
        extracted = {"vendor": "PARSE_ERROR", "total": 0.0, "categories": []}

    trail = list(state.get("audit_trail", []))
    trail.append(f"extractor: vendor={extracted.get('vendor')}, total={extracted.get('total')}")
    return {"extracted_data": extracted, "audit_trail": trail}


# ---------------------------------------------------------------------------
# Agent 2: CFP Tax Strategist (HYDRA — R1-70B deep reasoning)
# ---------------------------------------------------------------------------

def tax_strategist_node(state: WealthState) -> dict:
    """Classify purchase as Capital Improvement (CapEx) or Maintenance (OpEx)."""
    log.info("[HYDRA] CFP Tax Strategist categorizing for tax ledgers...")
    client, model = get_inference_client("HYDRA")

    prompt = (
        "You are a Certified Financial Planner (CFP) and Real Estate Tax "
        "Strategist specializing in IRS Publication 527 and Georgia rental "
        "property regulations.\n\n"
        f"Analyze this purchase for a property development portfolio:\n"
        f"{json.dumps(state['extracted_data'])}\n\n"
        "Determine if these items constitute standard Maintenance (OpEx — "
        "immediately deductible under Schedule E) or Capital Improvements "
        "(CapEx — must be depreciated over 27.5 years per MACRS).\n\n"
        "Provide a brief, authoritative classification with the applicable "
        "IRS rule reference."
    )

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": prompt}],
        temperature=0.2,
    )

    raw = resp.choices[0].message.content
    clean_strategy = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    trail = list(state.get("audit_trail", []))
    trail.append(f"tax_strategist: classification_length={len(clean_strategy)}")
    return {"tax_strategy": clean_strategy, "audit_trail": trail}


# ---------------------------------------------------------------------------
# Agent 3: Compliance Inspector (SWARM + RAG from cfp_wealth_vault)
# ---------------------------------------------------------------------------

def _embed_sync(text: str) -> list[float]:
    """Generate embedding via nomic-embed-text (sync, single node)."""
    try:
        from config import get_embeddings_url
        embed_url = get_embeddings_url()
    except ImportError:
        embed_url = "http://localhost:11434/api/embeddings"

    with httpx.Client(timeout=30.0) as http:
        resp = http.post(embed_url, json={"model": EMBED_MODEL, "prompt": text[:8000]})
        resp.raise_for_status()
        return resp.json().get("embedding", [])


def compliance_inspector_node(state: WealthState) -> dict:
    """Check extracted categories against Fannin County zoning/septic regulations via RAG."""
    log.info("[SWARM] Compliance Inspector querying Fannin County regulations...")
    categories = " ".join(state["extracted_data"].get("categories", []))
    flags: List[str] = []

    if not categories.strip():
        trail = list(state.get("audit_trail", []))
        trail.append("compliance_inspector: no categories to check, CLEAR")
        return {"compliance_flags": [], "ready_for_ledger": True, "audit_trail": trail}

    try:
        vector = _embed_sync(categories)
        if not vector:
            raise ValueError("Empty embedding returned")

        q_client = QdrantClient(url=QDRANT_URL, timeout=15)
        results = q_client.search(
            collection_name=COLLECTION,
            query_vector=vector,
            limit=3,
            score_threshold=0.60,
        )
        q_client.close()

        context_chunks = [hit.payload.get("text", "") for hit in results if hit.payload]

        if context_chunks:
            client, model = get_inference_client("SWARM")
            context_str = "\n---\n".join(context_chunks)
            prompt = (
                f"You are a Fannin County, Georgia compliance inspector.\n\n"
                f"A property development project purchased items in these "
                f"categories: {categories}\n\n"
                f"Relevant local regulations:\n{context_str}\n\n"
                f"Does this purchase require permits, inspections, or trigger "
                f"zoning/septic review under Fannin County Environmental Health "
                f"rules? Respond with 'FLAG: [reason]' if yes, or 'CLEAR' if no "
                f"compliance action is needed."
            )
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            answer = resp.choices[0].message.content.strip()
            if "FLAG" in answer.upper():
                flags.append(answer)
                log.warning("Compliance flag raised: %s", answer[:120])
        else:
            log.info("No relevant regulations found in cfp_wealth_vault (score < 0.60).")

    except Exception as e:
        log.error("Compliance check error (non-fatal, proceeding): %s", e)
        flags.append(f"COMPLIANCE_CHECK_UNAVAILABLE: {e}")

    trail = list(state.get("audit_trail", []))
    trail.append(f"compliance_inspector: flags={len(flags)}, ready=True")
    return {"compliance_flags": flags, "ready_for_ledger": True, "audit_trail": trail}


# ---------------------------------------------------------------------------
# Graph Assembly
# ---------------------------------------------------------------------------

workflow = StateGraph(WealthState)
workflow.add_node("extractor", extraction_node)
workflow.add_node("tax_strategist", tax_strategist_node)
workflow.add_node("compliance_inspector", compliance_inspector_node)

workflow.set_entry_point("extractor")
workflow.add_edge("extractor", "tax_strategist")
workflow.add_edge("tax_strategist", "compliance_inspector")
workflow.add_edge("compliance_inspector", END)

wealth_swarm = workflow.compile()
