"""
LEGAL SENTINEL AGENT — Fortress JD (Sector S05, The Counselor)
===============================================================
Fortress Prime | The on-premise General Counsel for CROG.

Wraps the CF-03 CounselorCRM RAG pipeline in the mandated OODA Reflection
Loop and adds:
    1. Cross-sector privilege (Article IV — may read ALL schemas for audit)
    2. Dual-brain routing (SWARM for quick lookups, TITAN for contract review)
    3. Document category routing (Georgia statutes, deeds, permits, leases)
    4. Anomaly detection (conflicting clauses, expired permits, zoning risks)
    5. OODA audit trail (every legal query logged to system_post_mortems)

Data Sources (all local — Article I compliant):
    Qdrant legal_library    — 2,455+ vectors of deeds, statutes, permits, contracts
    Qdrant email_embeddings — Filtered by division='LEGAL_ADMIN'
    division_legal/knowledge_base/ — O.C.G.A. Titles 9, 13, 16, 44, 48, 51
    public.legal_matters    — Case tracking
    public.legal_docket     — Document registry

OODA Pattern:
    OBSERVE  — Receive legal question, classify domain and urgency
    ORIENT   — Retrieve from Qdrant legal_library + email_embeddings, build context
    DECIDE   — Route: SWARM (quick lookup) or TITAN (deep contract/compliance analysis)
    ACT      — Generate cited legal analysis, flag conflicts and risks
    POST-MORTEM — Log to system_post_mortems with sources and confidence

Firewall (fortress_atlas.yaml):
    READ access to ALL schemas (privileged for audit/compliance)
    WRITE only to public.legal_* tables

Usage:
    from src.agents.legal_sentinel import analyze_legal_question
    result = analyze_legal_question(
        question="Can I add a deck to the Whispering Pines cabin?",
        category="permit_license",
    )

Governing Documents:
    CONSTITUTION.md  — Article I (zero cloud), Article IV (sector privileges)
    REQUIREMENTS.md  — Section 3.5 (LangGraph)
    fortress_atlas.yaml — S05 firewall rules
"""

from __future__ import annotations

import os
import sys
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("agents.legal_sentinel")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# I. PYDANTIC MODELS
# =============================================================================

LEGAL_CATEGORIES = [
    "lease_agreement", "property_deed", "easement", "contract",
    "insurance", "tax_document", "permit_license", "court_filing",
    "discovery_material", "deposition_transcript", "billing_fees",
    "georgia_statute", "local_regulation", "correspondence", "general_legal",
]


class LegalSource(BaseModel):
    """A document source cited in the analysis."""
    file_name: str
    category: str
    relevance_score: float = Field(ge=0, le=1)
    source_file: str = ""


class LegalAnalysisRequest(BaseModel):
    """Inbound request for legal analysis."""
    question: str = Field(..., min_length=5)
    category: Optional[str] = Field(
        default=None,
        description="Filter retrieval to a specific document category"
    )
    top_k: int = Field(default=8, ge=1, le=20)
    brain: str = Field(default="auto")
    matter_id: Optional[str] = Field(
        default=None,
        description="Link analysis to an existing legal matter"
    )

    @field_validator("category")
    @classmethod
    def valid_category(cls, v):
        if v and v not in LEGAL_CATEGORIES:
            raise ValueError(f"category must be one of {LEGAL_CATEGORIES}")
        return v

    @field_validator("brain")
    @classmethod
    def valid_brain(cls, v):
        if v not in ("auto", "captain", "muscle", "fast", "titan"):
            raise ValueError("brain must be: auto, captain, muscle, fast, or titan")
        return v


class LegalAnalysisResponse(BaseModel):
    """Complete response from the Legal Sentinel."""
    answer: str = Field(default="")
    sources: List[LegalSource] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)
    success: bool = False
    error: Optional[str] = None

    # Classification
    question: str
    category_filter: Optional[str] = None
    inferred_domains: List[str] = Field(default_factory=list)

    # Performance
    retrieval_time_s: float = 0.0
    reasoning_time_s: float = 0.0
    total_time_s: float = 0.0
    brain_used: str = ""
    chunks_retrieved: int = 0
    context_chars: int = 0

    # OODA
    ooda_confidence: float = Field(default=0.0, ge=0, le=1)
    ooda_decision: str = ""
    audit_trail: List[str] = Field(default_factory=list)

    # Metadata
    matter_id: Optional[str] = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field(default="fortress_local")
    classification_level: str = Field(default="SOVEREIGN")
    disclaimer: str = Field(
        default="This analysis is for informational purposes only. "
                "It does not constitute legal advice. Consult an attorney "
                "for decisions based on this analysis."
    )


# =============================================================================
# II. DOMAIN CLASSIFICATION
# =============================================================================

DOMAIN_KEYWORDS = {
    "zoning": ["zoning", "zone", "variance", "land use", "residential", "commercial",
               "setback", "buffer", "overlay"],
    "permits": ["permit", "building permit", "septic", "grading", "construction",
                "certificate of occupancy", "inspection"],
    "property": ["deed", "title", "easement", "boundary", "survey", "plat",
                 "right-of-way", "encumbrance", "lien"],
    "contracts": ["lease", "rental agreement", "contract", "amendment", "termination",
                  "clause", "liability", "indemnification"],
    "tax": ["property tax", "assessment", "millage", "exemption", "1099", "depreciation"],
    "ada_compliance": ["ada", "service animal", "disability", "accommodation",
                       "fair housing", "hud", "emotional support"],
    "hospitality": ["guest", "booking", "cancellation", "pet fee", "damage deposit",
                    "occupancy", "noise ordinance"],
    "corporate": ["llc", "operating agreement", "dissolution", "registered agent",
                  "articles of organization", "annual report"],
}


def classify_legal_domains(question: str) -> List[str]:
    """Identify which legal domains a question touches."""
    q_lower = question.lower()
    domains = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(kw in q_lower for kw in keywords):
            domains.append(domain)
    return domains or ["general"]


def determine_brain(question: str, domains: List[str], explicit: str) -> str:
    """
    Route to the appropriate brain based on question complexity.

    TITAN (R1): Contract disputes, ADA compliance, multi-clause analysis
    Captain (R1:70b): Standard legal lookups, single-document queries
    Fast (R1:8b): Simple fact lookups, yes/no questions
    """
    if explicit != "auto":
        return explicit

    # TITAN-worthy: multi-domain, compliance, disputes
    complex_domains = {"ada_compliance", "contracts", "corporate"}
    if len(domains) >= 2 or any(d in complex_domains for d in domains):
        defcon = os.getenv("FORTRESS_DEFCON", "SWARM").upper()
        if defcon == "TITAN":
            return "titan"
        return "captain"

    # Quick lookups
    q_lower = question.lower()
    if any(q_lower.startswith(w) for w in ["what is", "who is", "when was", "where is"]):
        return "fast"

    return "captain"


# =============================================================================
# III. OODA NODE IMPLEMENTATIONS
# =============================================================================

def observe(state: dict) -> dict:
    """OBSERVE: Receive question, classify domains, determine routing."""
    request: LegalAnalysisRequest = state["_request"]
    now = datetime.now(timezone.utc).isoformat()

    domains = classify_legal_domains(request.question)
    brain = determine_brain(request.question, domains, request.brain)

    state["_domains"] = domains
    state["_brain"] = brain
    state["observation"] = (
        f"Legal question received. Domains: {', '.join(domains)}. "
        f"Category filter: {request.category or 'none'}. "
        f"Brain routing: {brain}."
    )
    state["audit_trail"].append(
        f"[{now}] OBSERVE: Domains={domains}, brain={brain}, "
        f"category={request.category or 'all'}"
    )
    return state


def orient(state: dict) -> dict:
    """ORIENT: Retrieve from Qdrant legal_library, build context."""
    request: LegalAnalysisRequest = state["_request"]
    now = datetime.now(timezone.utc).isoformat()

    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from Modules import CF_03_helper
    except ImportError:
        pass

    try:
        # Use CF-03's retrieval engine directly
        from Modules.CF_03_CounselorCRM_helper import retrieve, build_context
    except ImportError:
        # Fall back to direct Qdrant calls via the query engine
        try:
            # Load the module dynamically to avoid hyphenated import issues
            import importlib.util
            qe_path = PROJECT_ROOT / "Modules" / "CF-03_CounselorCRM" / "query_engine.py"
            spec = importlib.util.spec_from_file_location("cf03_query", str(qe_path))
            qe_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(qe_mod)
            retrieve = qe_mod.retrieve
            build_context = qe_mod.build_context
        except Exception as e:
            state["orientation"] = f"FAILED: Cannot load CF-03 query engine: {e}"
            state["confidence"] = 0.0
            state["audit_trail"].append(f"[{now}] ORIENT: FAILED — {e}")
            return state

    t0 = time.time()
    chunks = retrieve(
        request.question,
        top_k=request.top_k,
        category=request.category,
    )
    retrieval_time = time.time() - t0

    if not chunks:
        state["orientation"] = (
            "No relevant documents found in legal_library. "
            "The corpus may need re-indexing or the query is outside scope."
        )
        state["confidence"] = 0.1
        state["_chunks"] = []
        state["_context"] = ""
        state["_retrieval_time"] = retrieval_time
    else:
        context = build_context(chunks)
        state["_chunks"] = chunks
        state["_context"] = context
        state["_retrieval_time"] = retrieval_time

        # Build source list
        sources = []
        seen = set()
        for c in chunks:
            fn = c.get("file_name", "unknown")
            if fn not in seen:
                sources.append(LegalSource(
                    file_name=fn,
                    category=c.get("category", "general_legal"),
                    relevance_score=c.get("score", 0.0),
                    source_file=c.get("source_file", ""),
                ))
                seen.add(fn)
        state["_sources"] = sources

        avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks)
        state["confidence"] = min(avg_score * 1.2, 0.95)

        state["orientation"] = (
            f"Retrieved {len(chunks)} chunks from {len(sources)} documents. "
            f"Avg relevance: {avg_score:.3f}. "
            f"Context: {len(context)} chars. "
            f"Categories: {', '.join(set(c.get('category', '') for c in chunks))}."
        )

    state["audit_trail"].append(
        f"[{now}] ORIENT: {len(chunks) if chunks else 0} chunks retrieved "
        f"in {retrieval_time:.2f}s, confidence={state['confidence']:.2f}"
    )
    return state


def decide(state: dict) -> dict:
    """DECIDE: Route to the chosen brain for reasoning."""
    request: LegalAnalysisRequest = state["_request"]
    brain = state.get("_brain", "captain")
    context = state.get("_context", "")
    now = datetime.now(timezone.utc).isoformat()

    if not context:
        state["decision"] = (
            "ABORT: No context available. Cannot generate legal analysis "
            "without supporting documents."
        )
        state["audit_trail"].append(f"[{now}] DECIDE: ABORT — no context")
        return state

    # For TITAN routing, use the DEFCON-aware client
    if brain == "titan":
        defcon = os.getenv("FORTRESS_DEFCON", "SWARM").upper()
        if defcon != "TITAN":
            brain = "captain"
            state["_brain"] = brain
            logger.info("TITAN requested but DEFCON is SWARM — falling back to captain")

    state["decision"] = (
        f"ANALYZE using {brain} brain. "
        f"Context: {len(context)} chars from {len(state.get('_chunks', []))} chunks. "
        f"Domains: {', '.join(state.get('_domains', []))}."
    )
    state["audit_trail"].append(
        f"[{now}] DECIDE: brain={brain}, context_chars={len(context)}"
    )
    return state


def act(state: dict) -> dict:
    """ACT: Send context + question to the chosen LLM for legal analysis."""
    request: LegalAnalysisRequest = state["_request"]
    brain = state.get("_brain", "captain")
    context = state.get("_context", "")
    now = datetime.now(timezone.utc).isoformat()

    if not context:
        state["action_result"] = "FAILED: No context — cannot generate analysis."
        state["_answer"] = ""
        state["_reasoning_time"] = 0
        return state

    t0 = time.time()

    if brain == "titan":
        # Use config.get_inference_client for TITAN mode
        try:
            from config import get_inference_client
            client, model = get_inference_client("TITAN")

            system_prompt = _build_system_prompt(state.get("_domains", []))
            user_prompt = _build_user_prompt(request.question, context)

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=4096,
                temperature=0.1,
            )
            answer = response.choices[0].message.content
            # Strip R1 think tags
            import re
            answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()

        except Exception as e:
            answer = f"[TITAN ERROR] {e}"
            logger.error(f"TITAN inference failed: {e}")
    else:
        # Use CF-03's ask_llm for SWARM mode
        try:
            import importlib.util
            qe_path = PROJECT_ROOT / "Modules" / "CF-03_CounselorCRM" / "query_engine.py"
            spec = importlib.util.spec_from_file_location("cf03_query", str(qe_path))
            qe_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(qe_mod)
            answer = qe_mod.ask_llm(request.question, context, brain=brain)
        except Exception as e:
            answer = f"[LLM ERROR] {e}"
            logger.error(f"LLM inference failed: {e}")

    reasoning_time = time.time() - t0
    state["_answer"] = answer
    state["_reasoning_time"] = reasoning_time

    # Detect risk flags in the answer
    risk_flags = _detect_risk_flags(answer, state.get("_domains", []))
    state["_risk_flags"] = risk_flags

    if "[ERROR]" in answer:
        state["action_result"] = f"FAILED: LLM error — {answer[:200]}"
        state["confidence"] = 0.1
    else:
        state["action_result"] = (
            f"SUCCESS: Analysis generated. {len(answer)} chars. "
            f"Brain: {brain}. Time: {reasoning_time:.1f}s. "
            f"Risk flags: {len(risk_flags)}."
        )

    state["audit_trail"].append(
        f"[{now}] ACT: brain={brain}, time={reasoning_time:.1f}s, "
        f"risks={len(risk_flags)}, len={len(answer)}"
    )
    return state


# =============================================================================
# IV. HELPER FUNCTIONS
# =============================================================================

def _build_system_prompt(domains: List[str]) -> str:
    """Build domain-aware system prompt for the Counselor."""
    base = (
        "You are the Fortress Prime Counselor — Senior Legal Analyst for "
        "Cabin Rentals of Georgia, a vacation rental property management company "
        "in Fannin County, Georgia.\n\n"
        "RULES:\n"
        "1. Base your answer EXCLUSIVELY on the provided document context.\n"
        "2. ALWAYS cite sources: [Source: filename.pdf] after each claim.\n"
        "3. Quote relevant passages directly with quotation marks.\n"
        "4. Flag ANY conflicts between documents.\n"
        "5. Include specific dates, amounts, section numbers, clause references.\n"
        "6. NEVER provide legal advice. Recommend consulting an attorney.\n"
        "7. If context is insufficient, state what documents are needed.\n"
    )

    if "ada_compliance" in domains:
        base += (
            "\nSPECIAL: This query involves ADA/Fair Housing. You MUST:\n"
            "- Cite specific HUD guidelines and O.C.G.A. provisions.\n"
            "- Distinguish between service animals (ADA) and emotional support animals (FHA).\n"
            "- Note that pet fees CANNOT be charged for legitimate service animals.\n"
            "- Flag any conflict between property rules and federal/state law.\n"
        )

    if "zoning" in domains or "permits" in domains:
        base += (
            "\nSPECIAL: This query involves zoning/permits. You MUST:\n"
            "- Reference Fannin County ordinances and GA state building codes.\n"
            "- Check setback requirements and buffer zones.\n"
            "- Note permit expiration dates and renewal requirements.\n"
        )

    return base


def _build_user_prompt(question: str, context: str) -> str:
    """Build the user prompt with question and document context."""
    return (
        f"LEGAL QUESTION: {question}\n\n"
        f"DOCUMENT CONTEXT:\n{context}\n\n"
        "Provide a detailed, well-cited answer based ONLY on the above context. "
        "Include specific document references, section numbers, and direct quotes. "
        "Flag any conflicts, risks, or missing documents."
    )


def _detect_risk_flags(answer: str, domains: List[str]) -> List[str]:
    """Scan the analysis for risk indicators."""
    flags = []
    answer_lower = answer.lower()

    risk_patterns = [
        ("conflict", "Conflicting clauses or documents detected"),
        ("violation", "Potential legal violation identified"),
        ("expired", "Expired permit, license, or deadline"),
        ("non-compliant", "Non-compliance risk flagged"),
        ("insufficient", "Insufficient documentation for definitive answer"),
        ("federal law", "Federal law preemption — supersedes local rules"),
        ("ada", "ADA/Fair Housing implications — high liability exposure"),
        ("zoning violation", "Zoning non-compliance risk"),
        ("setback", "Setback or buffer zone concern"),
        ("lien", "Lien or encumbrance on property"),
    ]

    for pattern, description in risk_patterns:
        if pattern in answer_lower:
            flags.append(description)

    return flags


# =============================================================================
# V. AGENT ASSEMBLY
# =============================================================================

def analyze_legal_question(
    question: str,
    category: str = None,
    top_k: int = 8,
    brain: str = "auto",
    matter_id: str = None,
) -> LegalAnalysisResponse:
    """
    High-level API: Analyze a legal question with full OODA audit trail.

    This is the function called by the API endpoint and programmatic callers.
    All data stays local. All reasoning is sovereign.

    Uses run_ooda_sequence (sequential runner) instead of LangGraph StateGraph
    to preserve internal state keys (_request, _chunks, _context, _sources)
    that LangGraph's TypedDict channels would drop between nodes.

    Args:
        question: The legal question to analyze.
        category: Filter to specific document category (optional).
        top_k: Number of chunks to retrieve (default: 8).
        brain: Routing override (auto, captain, muscle, fast, titan).
        matter_id: Link to an existing legal matter (optional).

    Returns:
        LegalAnalysisResponse with cited analysis, risk flags, and OODA audit.
    """
    from src.sovereign_ooda import make_initial_state, run_ooda_sequence

    request = LegalAnalysisRequest(
        question=question,
        category=category,
        top_k=top_k,
        brain=brain,
        matter_id=matter_id,
    )

    initial = make_initial_state(sector="legal", query=question[:200])
    initial["_request"] = request

    start = time.time()
    result_state = run_ooda_sequence(
        state=initial,
        observe_fn=observe,
        orient_fn=orient,
        decide_fn=decide,
        act_fn=act,
    )
    total_time = time.time() - start

    # Build response
    return LegalAnalysisResponse(
        answer=result_state.get("_answer", ""),
        sources=result_state.get("_sources", []),
        risk_flags=result_state.get("_risk_flags", []),
        success="SUCCESS" in result_state.get("action_result", ""),
        error=result_state.get("action_result") if "FAILED" in result_state.get("action_result", "") else None,
        question=question,
        category_filter=category,
        inferred_domains=result_state.get("_domains", []),
        retrieval_time_s=round(result_state.get("_retrieval_time", 0), 3),
        reasoning_time_s=round(result_state.get("_reasoning_time", 0), 3),
        total_time_s=round(total_time, 3),
        brain_used=result_state.get("_brain", ""),
        chunks_retrieved=len(result_state.get("_chunks", [])),
        context_chars=len(result_state.get("_context", "")),
        ooda_confidence=result_state.get("confidence", 0.0),
        ooda_decision=result_state.get("decision", ""),
        audit_trail=result_state.get("audit_trail", []),
        matter_id=matter_id,
    )
