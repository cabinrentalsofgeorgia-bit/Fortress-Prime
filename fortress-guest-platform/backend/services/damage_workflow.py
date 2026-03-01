"""
Damage Command Center — Multi-Agent Workflow Engine
=====================================================
Sequential agentic pipeline triggered when staff report property damage:

  Step 1 (Investigator):  Gather reservation, guest, property context +
                          RAG-retrieve the specific rental agreement clauses.

  Step 2 (Legal Drafter): Anthropic Opus 4.6 (or local DGX Reasoner) drafts
                          a formal damage claim email citing contract clauses.

  Step 3 (Council Review): A DIFFERENT Horseman (OpenAI GPT-4o) peer-reviews
                           the draft for tone, legal soundness, and accuracy.

  Step 4 (Persist):       Save the reviewed draft to damage_claims.legal_draft,
                          update status to pending_human_approval.

No email is ever sent automatically. A human reviews and approves before delivery.
"""

import time
from datetime import datetime, date
from typing import Optional, List, Dict
from uuid import UUID, uuid4

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models.reservation import Reservation
from backend.models.property import Property
from backend.models.guest import Guest
from backend.models.damage_claim import DamageClaim
from backend.models.rental_agreement import RentalAgreement
from backend.services.dgx_tools import query_local_rag, deep_reason_local
from backend.services.ai_engine import query_horseman, query_council
from backend.services.legal_auditor import audit_contract_violations, format_ruling_for_drafter
from backend.services.prompt_engineer import PromptEngineer

logger = structlog.get_logger()

GOLDEN_COLLECTION = "fgp_golden_claims"
EMBED_URL = "http://192.168.0.100/api/embeddings"
EMBED_MODEL = "nomic-embed-text"


DRAFTER_SYSTEM_PROMPT = """You are the Legal Response Coordinator for Cabin Rentals of Georgia (CROG),
a luxury cabin rental company in Blue Ridge, Georgia.

Draft a FORMAL DAMAGE CLAIM EMAIL to the guest regarding property damage or
policy violations discovered during post-checkout inspection.

MANDATORY REQUIREMENTS:
1. Address the guest by name.
2. State the property name and stay dates.
3. Describe the specific damage found, quoting the staff's inspection notes.
4. CITE THE EXACT RENTAL AGREEMENT CLAUSES provided below that the guest violated.
5. State what charges or deductions will apply per the agreement.
6. Provide a clear path forward (security deposit deduction, repair invoice, payment arrangement).
7. Maintain firm but professional Southern hospitality — fair, factual, never hostile.
8. Reference Georgia vacation rental law where applicable (O.C.G.A. § 44-7-30 et seq.).
9. Keep the email under 600 words.
10. Sign off as "Cabin Rentals of Georgia Management Team".

FORMAT: Ready-to-send email. No markdown headers. No explanatory preamble."""


REVIEWER_SYSTEM_PROMPT = """You are the Director of Guest Relations for Cabin Rentals of Georgia.

Review the following damage claim email drafted by your Legal Response Coordinator.
Your job is quality control:

1. Ensure the tone is professional, firm, and polite — never threatening or hostile.
2. Verify that cited contract clauses actually appear in the provided agreement context.
   If a clause is fabricated, REMOVE it and note the correction.
3. Do NOT hallucinate or invent dollar amounts, costs, or fees not mentioned in the source notes.
4. Ensure Georgia vacation rental law references are accurate.
5. Tighten any verbose language. The email should be concise and clear.
6. Ensure the guest is addressed by their correct name.
7. Ensure the sign-off is "Cabin Rentals of Georgia Management Team".

Return ONLY the final, polished email text. No commentary, no explanation, no preamble.
If the draft is already excellent, return it unchanged."""


async def _retrieve_golden_examples(staff_notes: str, top_k: int = 2) -> str:
    """Search fgp_golden_claims for similar historical damage cases.

    Returns formatted few-shot examples, or empty string if unavailable.
    """
    qdrant_url = settings.qdrant_url.rstrip("/")
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Check collection exists
            check = await client.get(
                f"{qdrant_url}/collections/{GOLDEN_COLLECTION}", headers=headers,
            )
            if check.status_code != 200:
                return ""

            # Embed the staff notes as query vector
            embed_resp = await client.post(
                EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": staff_notes[:4000]},
                timeout=30,
            )
            embed_resp.raise_for_status()
            vec = embed_resp.json().get("embedding", [])
            if len(vec) != 768:
                return ""

            # Similarity search
            search_resp = await client.post(
                f"{qdrant_url}/collections/{GOLDEN_COLLECTION}/points/search",
                json={
                    "vector": vec,
                    "limit": top_k,
                    "with_payload": True,
                    "with_vector": False,
                },
                headers=headers,
            )
            search_resp.raise_for_status()
            results = search_resp.json().get("result", [])

            if not results:
                return ""

            examples = []
            for i, pt in enumerate(results, 1):
                p = pt.get("payload", {})
                score = pt.get("score", 0)
                desc = p.get("damage_description", "")
                resolution = p.get("resolution", "")
                draft = p.get("legal_draft", "")
                prop = p.get("property_name", "")

                block = f"EXAMPLE {i} (similarity: {score:.2f}, property: {prop}):\n"
                if desc:
                    block += f"  Damage: {desc[:300]}\n"
                if resolution:
                    block += f"  Resolution: {resolution[:300]}\n"
                if draft:
                    block += f"  Response sent:\n  {draft[:500]}\n"
                examples.append(block)

            logger.info(
                "golden_memory_retrieved",
                examples=len(examples),
                top_score=results[0].get("score", 0),
            )
            return "\n".join(examples)

    except Exception as e:
        logger.warning("golden_memory_retrieval_failed", error=str(e)[:200])
        return ""


async def process_damage_claim(
    reservation_id: UUID,
    staff_notes: str,
    db: AsyncSession,
    reported_by: str = "staff",
    damage_areas: Optional[list[str]] = None,
    estimated_cost: Optional[float] = None,
    photo_urls: Optional[list[str]] = None,
) -> dict:
    """Execute the full Damage Command Center workflow.

    Returns a dict with workflow results including the claim_id
    and status of each step.
    """
    t0 = time.perf_counter()
    workflow = {
        "reservation_id": str(reservation_id),
        "steps": {},
        "claim_id": None,
        "status": "started",
    }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  STEP 1: The Investigator — Context Gathering
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    logger.info("damage_workflow_step1_investigator", reservation_id=str(reservation_id))

    reservation = await db.get(Reservation, reservation_id)
    if not reservation:
        workflow["status"] = "failed"
        workflow["error"] = "Reservation not found"
        return workflow

    guest = await db.get(Guest, reservation.guest_id)
    prop = await db.get(Property, reservation.property_id)

    guest_name = f"{guest.first_name or ''} {guest.last_name or ''}".strip() if guest else "Guest"
    property_name = prop.name if prop else "the property"
    check_in = str(reservation.check_in_date) if reservation.check_in_date else "N/A"
    check_out = str(reservation.check_out_date) if reservation.check_out_date else "N/A"

    # RAG: Retrieve rental agreement clauses from Qdrant
    rag_query = f"rental agreement damage liability security deposit clauses {property_name}"
    agreement_context = await query_local_rag(
        search_term=rag_query,
        property_id=str(reservation.property_id) if reservation.property_id else None,
        db=db,
    )

    # Also check for a signed agreement in the DB
    agreement_result = await db.execute(
        select(RentalAgreement)
        .where(
            RentalAgreement.reservation_id == reservation_id,
            RentalAgreement.agreement_type == "rental_agreement",
        )
        .order_by(RentalAgreement.signed_at.desc().nullslast())
        .limit(1)
    )
    signed_agreement = agreement_result.scalar_one_or_none()
    agreement_text = ""
    if signed_agreement and signed_agreement.rendered_content:
        agreement_text = signed_agreement.rendered_content[:6000]

    combined_clauses = ""
    if agreement_text:
        combined_clauses = f"SIGNED RENTAL AGREEMENT (on file):\n{agreement_text}"
    if agreement_context and agreement_context != "[NO RESULTS]":
        combined_clauses += f"\n\nADDITIONAL PROPERTY KNOWLEDGE (from RAG):\n{agreement_context}"
    if not combined_clauses:
        combined_clauses = "No rental agreement on file. Use standard CROG damage policy and Georgia law."

    workflow["steps"]["investigator"] = {
        "guest": guest_name,
        "property": property_name,
        "check_in": check_in,
        "check_out": check_out,
        "has_agreement": bool(agreement_text),
        "rag_results": bool(agreement_context and agreement_context != "[NO RESULTS]"),
    }
    logger.info(
        "damage_workflow_step1_complete",
        guest=guest_name,
        property=property_name,
        has_agreement=bool(agreement_text),
    )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  STEP 1b: Golden Memory — Few-Shot Historical Examples
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    logger.info("damage_workflow_step1b_golden_memory")
    golden_examples = await _retrieve_golden_examples(staff_notes, top_k=2)

    golden_section = ""
    if golden_examples:
        golden_section = (
            "\n\nHISTORICAL PRECEDENTS — Here are examples of how we have successfully "
            "handled similar damage in the past. Match this tone and structure:\n\n"
            f"{golden_examples}"
        )
        workflow["steps"]["golden_memory"] = {
            "status": "injected",
            "examples_found": golden_examples.count("EXAMPLE"),
        }
    else:
        workflow["steps"]["golden_memory"] = {"status": "no_examples_found"}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  STEP 1c: Contract Auditor — Legal Logic Engine (NIM FP8)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    logger.info("damage_workflow_step1c_contract_audit")
    ruling = await audit_contract_violations(
        staff_notes=staff_notes,
        rental_agreement_text=agreement_text,
    )

    ruling_section = ""
    if ruling:
        ruling_section = "\n\n" + format_ruling_for_drafter(ruling)
        workflow["steps"]["contract_auditor"] = {
            "status": "complete",
            "breached": ruling.contract_breached,
            "clauses_cited": len(ruling.violated_clauses),
            "severity": ruling.severity,
            "charges": ruling.permissible_charges,
        }
    else:
        ruling_section = (
            "\n\nCONTRACT AUDIT: Unavailable — draft using general Georgia property law "
            "(O.C.G.A. § 44-7-30 et seq.) and standard CROG damage policy."
        )
        workflow["steps"]["contract_auditor"] = {"status": "unavailable"}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  STEP 2: The Legal Drafter — Heavy Reasoning (via Prompt Engineer)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    logger.info("damage_workflow_step2_drafter")

    raw_drafter_prompt = (
        f"GUEST: {guest_name}\n"
        f"PROPERTY: {property_name}\n"
        f"STAY: {check_in} to {check_out}\n"
        f"CONFIRMATION: {reservation.confirmation_code or 'N/A'}\n\n"
        f"CRITICAL INSTRUCTION: Base the email ENTIRELY on the Contract Audit Ruling. "
        f"Only cite clauses the auditor confirmed were violated. Only charge fees the "
        f"auditor listed as permissible. Do not invent additional charges.\n\n"
        f"Draft the formal damage claim email to the guest now."
    )

    drafter_data = {
        "staff_inspection_notes": staff_notes,
        "contract_audit_ruling": ruling_section,
        "rental_agreement_clauses": combined_clauses,
    }
    if golden_section:
        drafter_data["historical_precedents"] = golden_section

    known_names = [guest_name]
    if prop and prop.owner_name:
        known_names.append(prop.owner_name)

    draft_text = None
    draft_model = "unknown"
    drafter_pe = None

    # Try Anthropic Opus first (primary orchestrator)
    drafter_pe = PromptEngineer("anthropic", settings.anthropic_model)
    sys_compiled, usr_compiled = drafter_pe.build(
        DRAFTER_SYSTEM_PROMPT, raw_drafter_prompt, drafter_data, known_names,
    )
    draft_text = await query_horseman(
        "anthropic", prompt=usr_compiled, system_message=sys_compiled,
        max_tokens=2048, temperature=0.3,
    )
    if draft_text:
        draft_text = drafter_pe.rehydrate(draft_text)
        draft_model = settings.anthropic_model

    # Fallback: Local DGX Reasoner (no sanitization needed — local)
    if not draft_text:
        draft_text = await deep_reason_local(
            complex_text=f"{DRAFTER_SYSTEM_PROMPT}\n\n{combined_clauses}",
            query=f"Draft a damage claim email for guest {guest_name} at {property_name}.\n\nSTAFF NOTES:\n{staff_notes}",
        )
        if draft_text and not draft_text.startswith("[ERROR]"):
            draft_model = settings.dgx_reasoner_model
            drafter_pe = None
        else:
            draft_text = None

    # Fallback: Council cascade (each call goes through PE)
    if not draft_text:
        for horseman_name in ["gemini", "xai", "openai"]:
            pe = PromptEngineer(horseman_name, getattr(settings, f"{horseman_name}_model", ""))
            s, u = pe.build(DRAFTER_SYSTEM_PROMPT, raw_drafter_prompt, drafter_data, known_names)
            result = await query_horseman(
                horseman_name, prompt=u, system_message=s, max_tokens=2048, temperature=0.3,
            )
            if result:
                draft_text = pe.rehydrate(result)
                draft_model = horseman_name
                drafter_pe = pe
                break

    if not draft_text:
        workflow["status"] = "failed"
        workflow["error"] = "All LLM providers failed during drafting"
        workflow["steps"]["drafter"] = {"status": "failed"}
        return workflow

    pii_sanitized = drafter_pe.was_sanitized if drafter_pe else False
    workflow["steps"]["drafter"] = {
        "status": "complete",
        "model": draft_model,
        "draft_length": len(draft_text),
        "pii_sanitized": pii_sanitized,
    }
    logger.info(
        "damage_workflow_step2_complete",
        model=draft_model,
        draft_chars=len(draft_text),
        pii_sanitized=pii_sanitized,
    )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  STEP 3: The Council Review — Peer Review by a Different Model
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    logger.info("damage_workflow_step3_review")

    raw_review_prompt = "Review and return the final polished email."
    review_data = {
        "draft_email_to_review": draft_text,
        "original_staff_notes": staff_notes,
        "agreement_clauses_for_verification": combined_clauses[:3000],
    }

    # Use a DIFFERENT model for review to avoid self-confirmation bias
    reviewer = "openai" if draft_model != settings.openai_model else "gemini"
    reviewed_text = None

    for candidate in [reviewer, "xai", "gemini", "openai"]:
        if reviewed_text:
            break
        model_name = getattr(settings, f"{candidate}_model", "")
        pe = PromptEngineer(candidate, model_name)
        s, u = pe.build(REVIEWER_SYSTEM_PROMPT, raw_review_prompt, review_data, known_names)
        result = await query_horseman(
            candidate, prompt=u, system_message=s, max_tokens=2048, temperature=0.2,
        )
        if result:
            reviewed_text = pe.rehydrate(result)
            reviewer = candidate

    final_draft = reviewed_text or draft_text
    review_status = "reviewed" if reviewed_text else "unreviewed"

    workflow["steps"]["reviewer"] = {
        "status": review_status,
        "model": reviewer if reviewed_text else "none",
        "final_length": len(final_draft),
    }
    logger.info(
        "damage_workflow_step3_complete",
        review_status=review_status,
        reviewer_model=reviewer if reviewed_text else "skipped",
    )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  STEP 4: Database Persist
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    logger.info("damage_workflow_step4_persist")

    # Check for existing claim on this reservation
    existing = await db.execute(
        select(DamageClaim).where(DamageClaim.reservation_id == reservation_id).limit(1)
    )
    claim = existing.scalar_one_or_none()

    claim_number = None
    if claim:
        claim.legal_draft = final_draft
        claim.legal_draft_model = f"drafter={draft_model}, reviewer={reviewer}"
        claim.legal_draft_at = datetime.utcnow()
        claim.status = "pending_human_approval"
        if staff_notes and (not claim.damage_description or len(staff_notes) > len(claim.damage_description)):
            claim.damage_description = staff_notes
        if damage_areas:
            claim.damage_areas = damage_areas
        if estimated_cost is not None:
            claim.estimated_cost = estimated_cost
        claim_number = claim.claim_number
    else:
        ts = int(time.time())
        short = str(uuid4())[:6].upper()
        claim_number = f"DC-{ts}-{short}"

        claim = DamageClaim(
            claim_number=claim_number,
            reservation_id=reservation_id,
            property_id=reservation.property_id,
            guest_id=reservation.guest_id,
            damage_description=staff_notes,
            damage_areas=damage_areas,
            estimated_cost=estimated_cost,
            photo_urls=photo_urls,
            reported_by=reported_by,
            inspection_date=reservation.check_out_date or date.today(),
            legal_draft=final_draft,
            legal_draft_model=f"drafter={draft_model}, reviewer={reviewer}",
            legal_draft_at=datetime.utcnow(),
            rental_agreement_id=signed_agreement.id if signed_agreement else None,
            agreement_clauses={
                "workflow": "damage_command_center",
                "drafter_model": draft_model,
                "reviewer_model": reviewer,
                "review_status": review_status,
                "has_signed_agreement": bool(signed_agreement),
                "rag_used": bool(agreement_context and agreement_context != "[NO RESULTS]"),
                "golden_memory_used": bool(golden_examples),
                "contract_audit": ruling.model_dump() if ruling else None,
            },
            status="pending_human_approval",
        )
        db.add(claim)

    await db.commit()
    await db.refresh(claim)

    elapsed = (time.perf_counter() - t0) * 1000

    workflow["claim_id"] = str(claim.id)
    workflow["claim_number"] = claim_number
    workflow["status"] = "pending_human_approval"
    workflow["elapsed_ms"] = round(elapsed)
    workflow["steps"]["persist"] = {"status": "saved", "claim_number": claim_number}

    logger.info(
        "damage_workflow_complete",
        claim_number=claim_number,
        claim_id=str(claim.id),
        elapsed_ms=round(elapsed),
        drafter=draft_model,
        reviewer=reviewer,
        review_status=review_status,
    )

    return workflow
