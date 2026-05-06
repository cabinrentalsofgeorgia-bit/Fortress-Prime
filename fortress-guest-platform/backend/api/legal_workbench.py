"""Counsel Review Workbench API.

All routes are staff-authenticated through the legal API router dependency and
return derived work product only. Raw document bodies and locked content are
not read or returned here.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from backend.core.security import require_manager_or_admin
from backend.services.legal_counsel_validation import (
    apply_validation_action,
    load_latest_validation,
)
from backend.services.legal_counsel_signoff_packet import (
    capture_signoff_action,
    load_latest_signoff_packet,
    reopen_signoff_packet,
)
from backend.services.legal_counsel_signoff_decision import (
    load_latest_decision_workflow,
    record_decision,
)
from backend.services.legal_autonomous_learning_loop import (
    load_latest_learning_loop,
    record_feedback,
)
from backend.services.legal_counsel_workbench import load_latest_workbench
from backend.services.legal_limited_signoff_candidate_packet import load_latest_limited_signoff_candidate
from backend.services.legal_source_integrity_validation import load_latest_source_integrity
from backend.services.legal_source_link_repair import load_latest_source_link_repair
from backend.services.legal_source_remediation import load_latest_source_remediation
from backend.services.legal_targeted_source_completion import load_latest_targeted_source_completion

router = APIRouter(dependencies=[Depends(require_manager_or_admin)])


class CounselValidationActionRequest(BaseModel):
    item_id: str = Field(..., min_length=1, max_length=160)
    action: str = Field(..., min_length=1, max_length=64)
    validation_status: str | None = Field(default=None, max_length=64)
    source_check_status: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=1200)
    correction_summary: str | None = Field(default=None, max_length=1200)


class CounselSignoffActionRequest(BaseModel):
    signoff_type: str = Field(..., min_length=1, max_length=80)
    scope_confirmed: bool = False
    notes: str | None = Field(default=None, max_length=1200)


class CounselSignoffReopenRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=1200)


class CounselSignoffDecisionRequest(BaseModel):
    decision_type: str = Field(..., min_length=1, max_length=96)
    decision_scope: str = Field(default="limited_packet", min_length=1, max_length=160)
    item_ids_or_section_ids: list[str] = Field(default_factory=list, max_length=300)
    signer_affiliation: str | None = Field(default=None, max_length=160)
    explicit_scope_confirmed: bool = False
    unresolved_exclusions_acknowledged: bool = False
    privilege_handling_acknowledged: bool = False
    no_external_submission_authority_acknowledged: bool = False
    decision_notes: str | None = Field(default=None, max_length=1200)
    revision_requests: list[str] = Field(default_factory=list, max_length=300)
    source_remediation_returns: list[str] = Field(default_factory=list, max_length=300)


class AutonomousLearningFeedbackRequest(BaseModel):
    item_id: str = Field(..., min_length=1, max_length=160)
    item_type: str = Field(..., min_length=1, max_length=80)
    feedback_type: str = Field(..., min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=1200)
    severity: str = Field(default="medium", min_length=1, max_length=40)
    linked_source_refs: list[dict[str, object]] = Field(default_factory=list, max_length=50)
    action_requested: str | None = Field(default=None, max_length=240)


@router.get("/cases/{slug}/counsel-workbench", summary="Get counsel review workbench packet")
async def get_counsel_workbench(slug: str):
    packet = load_latest_workbench(slug)
    if packet is None:
        raise HTTPException(status_code=404, detail="Counsel workbench packet not found.")
    return packet


@router.get("/cases/{slug}/counsel-validation", summary="Get counsel validation workflow")
async def get_counsel_validation(slug: str):
    packet = load_latest_validation(slug)
    if packet is None:
        raise HTTPException(status_code=404, detail="Counsel validation workflow not found.")
    return packet


@router.post("/cases/{slug}/counsel-validation/actions", summary="Apply counsel validation action")
async def post_counsel_validation_action(
    slug: str,
    body: CounselValidationActionRequest,
    user=Depends(require_manager_or_admin),
):
    role = str(getattr(user, "role", "staff") or "staff")
    reviewer = f"staff:{role}"
    try:
        return apply_validation_action(
            slug,
            item_id=body.item_id,
            action=body.action,
            validation_status=body.validation_status,
            source_check_status=body.source_check_status,
            note=body.note,
            correction_summary=body.correction_summary,
            reviewer_identity_safe_label=reviewer,
            reviewer_role=role,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Counsel validation workflow not found.") from None
    except KeyError:
        raise HTTPException(status_code=404, detail="Validation item not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/cases/{slug}/counsel-signoff-packet", summary="Get counsel signoff strategy packet")
async def get_counsel_signoff_packet(slug: str):
    packet = load_latest_signoff_packet(slug)
    if packet is None:
        raise HTTPException(status_code=404, detail="Counsel signoff packet not found.")
    return packet


@router.post("/cases/{slug}/counsel-signoff-packet/signoff", summary="Capture explicit counsel signoff action")
async def post_counsel_signoff_action(
    slug: str,
    body: CounselSignoffActionRequest,
    user=Depends(require_manager_or_admin),
):
    role = str(getattr(user, "role", "staff") or "staff")
    signer = f"staff:{role}"
    try:
        return capture_signoff_action(
            slug,
            signoff_type=body.signoff_type,
            signer_safe_label=signer,
            signer_role=role,
            scope_confirmed=body.scope_confirmed,
            notes=body.notes,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Counsel signoff packet not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/cases/{slug}/counsel-signoff-packet/reopen", summary="Reopen or supersede counsel signoff packet")
async def post_counsel_signoff_reopen(
    slug: str,
    body: CounselSignoffReopenRequest,
    user=Depends(require_manager_or_admin),
):
    role = str(getattr(user, "role", "staff") or "staff")
    reviewer = f"staff:{role}"
    try:
        return reopen_signoff_packet(
            slug,
            reviewer_safe_label=reviewer,
            reviewer_role=role,
            notes=body.notes,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Counsel signoff packet not found.") from None


@router.get("/cases/{slug}/source-integrity", summary="Get source integrity validation results")
async def get_source_integrity(slug: str):
    packet = load_latest_source_integrity(slug)
    if packet is None:
        raise HTTPException(status_code=404, detail="Source integrity validation not found.")
    return packet


@router.get("/cases/{slug}/source-remediation", summary="Get source blocker remediation results")
async def get_source_remediation(slug: str):
    packet = load_latest_source_remediation(slug)
    if packet is None:
        raise HTTPException(status_code=404, detail="Source remediation not found.")
    return packet


@router.get("/cases/{slug}/source-link-repair", summary="Get source link repair results")
async def get_source_link_repair(slug: str):
    packet = load_latest_source_link_repair(slug)
    if packet is None:
        raise HTTPException(status_code=404, detail="Source link repair not found.")
    return packet


@router.get("/cases/{slug}/targeted-source-completion", summary="Get targeted source completion results")
async def get_targeted_source_completion(slug: str):
    packet = load_latest_targeted_source_completion(slug)
    if packet is None:
        raise HTTPException(status_code=404, detail="Targeted source completion not found.")
    return packet


@router.get("/cases/{slug}/limited-signoff-candidate", summary="Get limited signoff candidate packet")
async def get_limited_signoff_candidate(slug: str):
    packet = load_latest_limited_signoff_candidate(slug)
    if packet is None:
        raise HTTPException(status_code=404, detail="Limited signoff candidate packet not found.")
    return packet


@router.get("/cases/{slug}/counsel-signoff-decision", summary="Get counsel signoff decision workflow")
async def get_counsel_signoff_decision(slug: str):
    packet = load_latest_decision_workflow(slug)
    if packet is None:
        raise HTTPException(status_code=404, detail="Counsel signoff decision workflow not found.")
    return packet


@router.post("/cases/{slug}/counsel-signoff-decision/decisions", summary="Record explicit limited packet decision")
async def post_counsel_signoff_decision(
    slug: str,
    body: CounselSignoffDecisionRequest,
    user=Depends(require_manager_or_admin),
):
    role = str(getattr(user, "role", "staff") or "staff")
    signer = f"staff:{role}"
    try:
        return record_decision(
            slug,
            decision_type=body.decision_type,
            decision_scope=body.decision_scope,
            item_ids_or_section_ids=body.item_ids_or_section_ids,
            signer_safe_label=signer,
            signer_role=role,
            signer_affiliation=body.signer_affiliation,
            explicit_scope_confirmed=body.explicit_scope_confirmed,
            unresolved_exclusions_acknowledged=body.unresolved_exclusions_acknowledged,
            privilege_handling_acknowledged=body.privilege_handling_acknowledged,
            no_external_submission_authority_acknowledged=body.no_external_submission_authority_acknowledged,
            decision_notes=body.decision_notes,
            revision_requests=body.revision_requests,
            source_remediation_returns=body.source_remediation_returns,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Counsel signoff decision workflow not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/cases/{slug}/autonomous-learning", summary="Get autonomous learning loop state")
async def get_autonomous_learning(slug: str):
    packet = load_latest_learning_loop(slug)
    if packet is None:
        raise HTTPException(status_code=404, detail="Autonomous learning loop not found.")
    return packet


@router.post("/cases/{slug}/autonomous-learning/feedback", summary="Capture autonomous learning feedback")
async def post_autonomous_learning_feedback(
    slug: str,
    body: AutonomousLearningFeedbackRequest,
    user=Depends(require_manager_or_admin),
):
    role = str(getattr(user, "role", "staff") or "staff")
    reviewer = f"staff:{role}"
    try:
        return record_feedback(
            slug,
            item_id=body.item_id,
            item_type=body.item_type,
            feedback_type=body.feedback_type,
            note=body.note,
            severity=body.severity,
            reviewer_safe_label=reviewer,
            reviewer_role=role,
            linked_source_refs=body.linked_source_refs,
            action_requested=body.action_requested,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Autonomous learning loop not found.") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
