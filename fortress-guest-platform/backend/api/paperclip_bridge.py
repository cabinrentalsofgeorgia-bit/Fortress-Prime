"""
Paperclip BYOA bridge — control-plane webhooks into the sovereign execution plane.
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import logging
import os
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import AsyncSessionLocal, get_db
from backend.models.acquisition import FunnelStage
from backend.services.acquisition_advisory import (
    AcquisitionCandidateSchema,
    append_acquisition_intel_event,
    advance_acquisition_pipeline,
    draft_acquisition_outreach_sequence,
    enrich_owner_contacts_from_internal_registry,
    enrich_owner_psychology,
    list_acquisition_candidates,
    score_acquisition_property,
)
from backend.services.acquisition_ingestion import AcquisitionIngestionRequest
from backend.services.crog_concierge_engine import (
    run_guest_resolve_conflict,
    run_guest_send_sms,
    run_guest_triage,
)
from backend.services.hunter_reactivation import draft_reactivation_sequence
from backend.services.legal_council import get_session, run_council_deliberation
from backend.services.legal_discovery_engine import LegalDiscoveryEngine
from backend.services.legal_docgen import _extract_case_meta, generate_answer_and_defenses
from backend.services.legal_motion_drafter import (
    generate_motion_extension_docx,
    motion_extension_filename,
)
from backend.services.legal_deposition_outline_engine import (
    generate_deposition_outline,
    outline_artifact_filename,
)
from backend.services.legal_search_engine import synthesize_historic_search

router = APIRouter()
logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


async def verify_swarm_token(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    expected_token = str(settings.swarm_api_key or "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Swarm API key is not configured.",
        )

    if creds is None or (creds.scheme or "").lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer swarm token.",
        )

    token = creds.credentials.strip()
    if not token or not secrets.compare_digest(token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid swarm token.",
        )

    return token


class PaperclipWorkspace(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    cwd: str | None = None
    source: str | None = None


class PaperclipWakeContext(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    task_id: str | None = Field(default=None, alias="taskId")
    wake_reason: str | None = Field(default=None, alias="wakeReason")
    paperclip_workspace: PaperclipWorkspace | None = Field(
        default=None,
        alias="paperclipWorkspace",
    )


class PaperclipExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: str = Field(alias="runId", min_length=1, max_length=128)
    agent_id: str = Field(alias="agentId", min_length=1, max_length=128)
    company_id: str = Field(alias="companyId", min_length=1, max_length=128)
    task_id: str | None = Field(default=None, alias="taskId", max_length=128)
    issue_id: str | None = Field(default=None, alias="issueId", max_length=128)
    wake_reason: str = Field(alias="wakeReason", min_length=1, max_length=64)
    wake_comment_id: str | None = Field(default=None, alias="wakeCommentId", max_length=128)
    approval_id: str | None = Field(default=None, alias="approvalId", max_length=128)
    approval_status: str | None = Field(default=None, alias="approvalStatus", max_length=64)
    issue_ids: list[str] = Field(default_factory=list, alias="issueIds")
    context: PaperclipWakeContext


class PaperclipAcceptedResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal["accepted"]
    execution_id: str = Field(alias="executionId")


class PaperclipUsagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    input_tokens: int | None = Field(default=None, alias="inputTokens", ge=0)
    output_tokens: int | None = Field(default=None, alias="outputTokens", ge=0)
    cached_input_tokens: int | None = Field(default=None, alias="cachedInputTokens", ge=0)


class PaperclipCallbackPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["succeeded", "failed"]
    result: str | None = None
    error_message: str | None = Field(default=None, alias="errorMessage")
    usage: PaperclipUsagePayload | None = None
    cost_usd: float | None = Field(default=None, alias="costUsd", ge=0)
    model: str | None = None
    provider: str | None = None


class NemoClawResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str = Field(alias="task_id")
    status: str
    action_log: list[str] = Field(default_factory=list)
    result_payload: dict[str, Any] | None = Field(default=None, alias="result_payload")


class LegalSearchToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, description="The specific legal question.")
    case_slug: str = Field(..., min_length=1, description="The unique identifier for the case.")


class LegalSearchToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class LegalDocGenToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_brief: str = Field(
        ...,
        min_length=10,
        description="The case brief and metadata block used to draft the pleading.",
    )
    consensus: dict[str, Any] = Field(
        ...,
        description="The Legal Council consensus object containing defenses and risk factors.",
    )
    case_slug: str | None = Field(
        default=None,
        min_length=1,
        description="Optional legal case slug. When present, the generated DOCX can be saved into the NAS case vault.",
    )
    persist_to_vault: bool = Field(
        default=True,
        description="Persist the generated DOCX into the sovereign legal NAS vault when case_slug is provided.",
    )


class LegalDocGenToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class LegalDraftWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_slug: str = Field(..., min_length=1, description="Legal case slug in the sovereign vault.")
    query: str = Field(
        ...,
        min_length=1,
        description="Question or drafting objective used to reconstruct the case chronology and defense theory.",
    )
    case_brief: str | None = Field(
        default=None,
        min_length=10,
        description="Optional explicit case brief. If omitted, the workflow derives one from legal search output.",
    )
    context: str | None = Field(
        default=None,
        description="Optional operator notes or filing strategy context to feed into the Legal Council.",
    )
    case_number: str | None = Field(
        default=None,
        description="Optional explicit case number to stamp onto the generated pleading.",
    )
    trigger_type: str = Field(
        default="PAPERCLIP_TOOL",
        description="Audit tag recorded with the deliberation vault event.",
    )
    persist_to_vault: bool = Field(
        default=True,
        description="Persist the generated DOCX into the sovereign legal NAS vault.",
    )


class LegalDraftWorkflowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class LegalRawEvidenceIngestToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_slug: str = Field(..., min_length=1, max_length=255, description="Legal case slug in legal.cases.")
    pack_id: str = Field(
        ...,
        min_length=32,
        max_length=40,
        description="Existing legacy discovery draft pack UUID (legal.discovery_draft_packs).",
    )
    payload_text: str = Field(
        ...,
        min_length=1,
        description="Raw text or document body to extract entities, graph edges, and claims from.",
    )
    source_document: str | None = Field(
        default=None,
        max_length=500,
        description="Optional file name cited on extracted entities.",
    )
    source_ref: str | None = Field(
        default=None,
        max_length=500,
        description="Optional operator reference (deposition cite, bates range, etc.).",
    )
    v2_pack_id: str | None = Field(
        default=None,
        min_length=32,
        max_length=40,
        description="Optional v2 pack UUID; if omitted a new legal.discovery_draft_packs_v2 row is created.",
    )
    target_entity_for_v2_pack: str | None = Field(
        default=None,
        max_length=255,
        description="When creating a v2 pack, target_entity label (default RawEvidenceIngest).",
    )


class LegalRawEvidenceIngestToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class LegalDepositionOutlineToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_slug: str = Field(..., min_length=1, max_length=255, description="Legal case slug.")
    deponent_entity: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Deponent name as it appears on the case graph / caption.",
    )
    operator_focus: str | None = Field(
        default=None,
        max_length=4000,
        description="Optional operator notes (e.g. contradictory statements ingested yesterday).",
    )
    case_number: str | None = Field(
        default=None,
        max_length=64,
        description="Optional case number for artifact filename; defaults to case_slug.",
    )
    persist_to_vault: bool = Field(
        default=True,
        description="Persist outline JSON under LEGAL_VAULT_ROOT case filings/outgoing.",
    )


class LegalDepositionOutlineToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class CaseDeadline(BaseModel):
    deadline_date: str = Field(..., description="Hard stop date in ISO format.")
    days_remaining: int = Field(..., ge=0)
    deadline_type: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    is_hard_stop: bool = Field(default=True)
    presiding_judge: str = Field(default="Mary Beth Priest", max_length=255)
    jurisdiction: str = Field(default="Appalachian Judicial Circuit", max_length=255)

    @model_validator(mode="after")
    def _normalize_deadline_descriptor(self) -> CaseDeadline:
        if not (self.deadline_type or "").strip():
            self.deadline_type = (self.description or "").strip() or "Responsive Pleading"
        if not (self.description or "").strip():
            self.description = self.deadline_type
        return self


class DraftMotionExtensionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(default="draft_motion_extension")
    case_number: str = Field(..., pattern=r"^SUV\d+$")
    case_slug: str | None = Field(default=None, min_length=1, max_length=255)
    target_vault_path: str | None = Field(
        default=None,
        description="Optional explicit NAS directory for the motion artifact.",
    )
    motion_parameters: CaseDeadline
    persist_to_vault: bool = Field(default=True)


class DraftMotionExtensionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class AnalyzeOpposingFilingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(default="analyze_opposing_filing")
    case_number: str = Field(..., pattern=r"^SUV\d+$")
    case_slug: str | None = Field(default=None, min_length=1, max_length=255)
    filing_name: str | None = Field(default=None, max_length=255)
    filing_summary: str | None = Field(default=None, max_length=4000)
    target_vault_path: str | None = Field(default=None)
    persist_to_vault: bool = Field(default=True)


class AnalyzeOpposingFilingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class LegalThreatAssessorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(default="legal_threat_assessor")
    case_number: str = Field(..., pattern=r"^SUV\d+$")
    case_slug: str | None = Field(default=None, min_length=1, max_length=255)
    filing_name: str | None = Field(default=None, max_length=255)
    document_text: str = Field(..., min_length=1, max_length=500_000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    target_vault_path: str | None = Field(default=None)
    persist_to_vault: bool = Field(default=True)


class LegalThreatAssessorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class GuestTriageToolRequest(BaseModel):
    """Paperclip tool: resolve guest context and run 9-seat Concierge triage (+ draft reply)."""

    model_config = ConfigDict(extra="forbid")

    message_id: UUID | None = Field(
        default=None,
        description="Existing messages.id; focal text defaults to message body when inbound_message omitted.",
    )
    guest_id: UUID | None = None
    reservation_id: UUID | None = None
    guest_phone: str | None = Field(
        default=None,
        max_length=40,
        description="E.164-style phone; normalized server-side.",
    )
    inbound_message: str | None = Field(
        default=None,
        max_length=16000,
        description="Required when message_id is not provided.",
    )
    trigger_type: str = Field(
        default="PAPERCLIP_TOOL_GUEST_TRIAGE",
        max_length=64,
        description="Audit tag for future ledger integration.",
    )
    include_wifi_in_property_block: bool = Field(
        default=False,
        description="If true, include Wi‑Fi SSID/password in property payload (sensitive).",
    )

    @model_validator(mode="after")
    def _validate_guest_triage_inputs(self) -> GuestTriageToolRequest:
        has_anchor = any(
            [
                self.message_id is not None,
                self.guest_id is not None,
                self.reservation_id is not None,
                (self.guest_phone or "").strip(),
            ]
        )
        if not has_anchor:
            raise ValueError(
                "Provide at least one of message_id, guest_id, reservation_id, or guest_phone.",
            )
        if self.message_id is None and not (self.inbound_message or "").strip():
            raise ValueError("inbound_message is required when message_id is not provided.")
        return self


class GuestTriageToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class GuestResolveConflictToolRequest(GuestTriageToolRequest):
    """Paperclip tool: mediate guest complaint against field reality and work-order history."""


class GuestResolveConflictToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class GuestSendSmsToolRequest(BaseModel):
    """Paperclip tool: live outbound SMS dispatch for high-conviction Concierge resolutions."""

    model_config = ConfigDict(extra="forbid")

    guest_id: UUID | None = None
    reservation_id: UUID | None = None
    guest_phone: str | None = Field(default=None, max_length=40)
    body: str = Field(..., min_length=1, max_length=1600)
    consensus_conviction: float = Field(..., ge=0.0, le=1.0)
    minimum_conviction: float = Field(default=0.8, ge=0.0, le=1.0)
    session_id: str | None = Field(default=None, max_length=128)
    source_workflow: str | None = Field(default=None, max_length=64)
    trigger_type: str = Field(
        default="PAPERCLIP_TOOL_GUEST_SEND_SMS",
        max_length=64,
        description="Audit tag for the outbound autonomous send path.",
    )

    @model_validator(mode="after")
    def _validate_guest_send_sms_inputs(self) -> GuestSendSmsToolRequest:
        has_anchor = any(
            [
                self.guest_id is not None,
                self.reservation_id is not None,
                (self.guest_phone or "").strip(),
            ]
        )
        if not has_anchor:
            raise ValueError("Provide at least one of guest_id, reservation_id, or guest_phone.")
        return self


class GuestSendSmsToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class GuestReactivationToolRequest(BaseModel):
    """Paperclip tool: build a dormant-guest reactivation draft and enqueue it for review."""

    model_config = ConfigDict(extra="forbid")

    guest_id: UUID
    target_score: int = Field(..., ge=0, le=100)
    trigger_type: str = Field(
        default="PAPERCLIP_TOOL_DRAFT_REACTIVATION_SEQUENCE",
        max_length=64,
    )


class GuestReactivationToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class AcquisitionToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: dict[str, Any] | None = None
    error_message: str | None = None


class AcquisitionReadCandidatesToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=5, ge=1, le=25)


class AcquisitionCandidateReadToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    data: list[AcquisitionCandidateSchema] | None = None
    error_message: str | None = None


class AcquisitionScoreToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: UUID


class AcquisitionPsychologyToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_id: UUID
    property_id: UUID | None = None
    profile_patch: dict[str, Any] = Field(default_factory=dict)
    source_note: str | None = Field(default=None, max_length=1000)


class AcquisitionContactEnrichmentToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_id: UUID
    property_id: UUID | None = None


class AcquisitionAppendEventToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: UUID
    event_type: str = Field(..., min_length=1, max_length=100)
    event_description: str = Field(..., min_length=1, max_length=4000)
    raw_source_data: dict[str, Any] = Field(default_factory=dict)


class AcquisitionAdvanceStageToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: UUID
    stage: FunnelStage
    next_action_date: str | None = None
    rejection_reason: str | None = Field(default=None, max_length=4000)
    llm_viability_score: float | None = Field(default=None, ge=0.0, le=1.0)


class AcquisitionDraftOutreachToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: UUID


class AcquisitionIngestionToolRequest(AcquisitionIngestionRequest):
    model_config = ConfigDict(extra="forbid")


def _nemoclaw_execute_url() -> str:
    base_url = str(settings.nemoclaw_orchestrator_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("NemoClaw orchestrator URL is not configured.")
    return f"{base_url}/api/agent/execute"


def _nemoclaw_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = str(settings.nemoclaw_orchestrator_api_key or "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _verify_ssl(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or "").strip().lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_private or ip.is_loopback)


def _paperclip_control_plane_url() -> str:
    base_url = str(settings.paperclip_control_plane_url or "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("Paperclip control-plane URL is not configured.")
    return base_url


@lru_cache(maxsize=1)
def _load_hermes_system_prompt() -> str:
    prompt_path = Path(str(settings.hermes_system_prompt_path or "")).expanduser()
    if not prompt_path.is_absolute():
        prompt_path = (Path(__file__).resolve().parents[3] / prompt_path).resolve()
    try:
        prompt_text = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Unable to load Hermes system prompt from {prompt_path}: {exc}") from exc
    if not prompt_text:
        raise RuntimeError(f"Hermes system prompt is empty: {prompt_path}")
    return prompt_text


def _hermes_contract_payload() -> dict[str, str]:
    prompt_path = Path(str(settings.hermes_system_prompt_path or "")).expanduser()
    if not prompt_path.is_absolute():
        prompt_path = (Path(__file__).resolve().parents[3] / prompt_path).resolve()
    return {
        "source_path": str(prompt_path),
        "system_prompt": _load_hermes_system_prompt(),
    }


async def _create_arq_pool():
    from backend.core.queue import create_arq_pool

    return await create_arq_pool()


async def _enqueue_async_job(*args, **kwargs):
    from backend.services.async_jobs import enqueue_async_job

    return await enqueue_async_job(*args, **kwargs)


def _serialize_async_job(job):
    def _iso(value):
        return value.isoformat() if value is not None else None

    return {
        "id": str(getattr(job, "id")),
        "job_name": getattr(job, "job_name"),
        "queue_name": getattr(job, "queue_name"),
        "status": getattr(job, "status"),
        "requested_by": getattr(job, "requested_by", None),
        "tenant_id": getattr(job, "tenant_id", None),
        "request_id": getattr(job, "request_id", None),
        "arq_job_id": getattr(job, "arq_job_id", None),
        "attempts": getattr(job, "attempts", 0),
        "payload": getattr(job, "payload_json", {}) or {},
        "result": getattr(job, "result_json", {}) or {},
        "error": getattr(job, "error_text", None),
        "created_at": _iso(getattr(job, "created_at", None)),
        "started_at": _iso(getattr(job, "started_at", None)),
        "finished_at": _iso(getattr(job, "finished_at", None)),
        "updated_at": _iso(getattr(job, "updated_at", None)),
    }


def _paperclip_callback_headers() -> dict[str, str]:
    api_key = str(settings.paperclip_control_plane_api_key or "").strip()
    if not api_key:
        raise RuntimeError("Paperclip control-plane API key is not configured.")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _paperclip_callback_url(run_id: str) -> str:
    return f"{_paperclip_control_plane_url()}/api/heartbeat-runs/{run_id}/callback"


def _paperclip_callback_enabled() -> bool:
    return bool(
        str(settings.paperclip_control_plane_url or "").strip()
        and str(settings.paperclip_control_plane_api_key or "").strip()
    )


def _legal_vault_root() -> Path:
    return Path(str(settings.LEGAL_VAULT_ROOT or "/mnt/fortress_nas/sectors/legal")).expanduser()


def _sanitize_filename_component(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)
    safe = safe.strip("._")
    return safe or "artifact"


async def _case_slug_exists(db: AsyncSession, case_slug: str) -> bool:
    result = await db.execute(
        text("SELECT 1 FROM legal.cases WHERE case_slug = :slug"),
        {"slug": case_slug},
    )
    return result.scalar() is not None


async def _persist_case_artifact(
    db: AsyncSession,
    *,
    case_slug: str,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    validation_warning: str | None = None
    try:
        if not await _case_slug_exists(db, case_slug):
            validation_warning = f"Case slug '{case_slug}' was not found in legal.cases; persisted artifact by slug path anyway."
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        validation_warning = (
            "Case registry validation was skipped before persistence due to "
            f"{type(exc).__name__}: {str(exc)[:200]}"
        )
        logger.warning(
            "paperclip_case_artifact_validation_skipped",
            extra={"case_slug": case_slug, "error": str(exc)[:200]},
        )

    root = _legal_vault_root()
    case_dir = root / case_slug / "filings" / "outgoing"
    case_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stored_filename = f"{timestamp}_{_sanitize_filename_component(filename)}"
    root_resolved = root.resolve()
    target = (case_dir / stored_filename).resolve()

    if not str(target).startswith(str(root_resolved)):
        raise RuntimeError("Resolved artifact path escapes LEGAL_VAULT_ROOT")

    target.write_bytes(content)
    return {
        "stored_filename": stored_filename,
        "vault_path": str(target),
        "download_url": f"/api/internal/legal/cases/{case_slug}/download/{stored_filename}",
        "validation_warning": validation_warning,
    }


def _persist_explicit_vault_artifact(
    *,
    target_vault_path: str,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    root = _legal_vault_root().resolve()
    target_dir = Path(target_vault_path).expanduser().resolve()
    if not str(target_dir).startswith(str(root)):
        raise RuntimeError("target_vault_path must remain under LEGAL_VAULT_ROOT")
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stored_filename = f"{timestamp}_{_sanitize_filename_component(filename)}"
    target = (target_dir / stored_filename).resolve()
    if not str(target).startswith(str(root)):
        raise RuntimeError("Resolved artifact path escapes LEGAL_VAULT_ROOT")
    target.write_bytes(content)
    return {
        "stored_filename": stored_filename,
        "vault_path": str(target),
        "download_url": None,
        "validation_warning": None,
    }


async def _resolve_case_slug_and_meta(
    db: AsyncSession,
    *,
    case_number: str,
    case_slug: str | None = None,
) -> dict[str, Any]:
    if case_slug:
        row = (
            await db.execute(
                text(
                    """
                    SELECT case_slug, case_number, case_name, court, judge
                    FROM legal.cases
                    WHERE case_slug = :case_slug
                    LIMIT 1
                    """
                ),
                {"case_slug": case_slug},
            )
        ).mappings().first()
        if row:
            return dict(row)

    row = (
        await db.execute(
            text(
                """
                SELECT case_slug, case_number, case_name, court, judge
                FROM legal.cases
                WHERE case_number = :case_number
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"case_number": case_number},
        )
    ).mappings().first()
    if row:
        return dict(row)

    fallback_slug = (case_slug or case_number).strip()
    return {
        "case_slug": fallback_slug,
        "case_number": case_number,
        "case_name": f"Case {case_number}",
        "court": "Superior Court",
        "judge": None,
    }


def _build_docgen_result_payload(
    *,
    case_meta: dict[str, Any],
    consensus: dict[str, Any],
    filename: str,
    docx_bytes: bytes,
) -> dict[str, Any]:
    encoded_docx = base64.b64encode(docx_bytes).decode("ascii")
    return {
        "filename": filename,
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "content_base64": encoded_docx,
        "size_bytes": len(docx_bytes),
        "case_number": case_meta["case_number"],
        "court": case_meta["court"],
        "plaintiff": case_meta["plaintiff"],
        "defendant": case_meta["defendant"],
        "consensus_signal": consensus.get("consensus_signal"),
        "defense_count": len(consensus.get("top_defense_arguments", []) or []),
        "risk_count": len(consensus.get("top_risk_factors", []) or []),
    }


def _build_workflow_case_brief(
    *,
    case_slug: str,
    query: str,
    search_result: dict[str, Any],
    case_number: str | None,
    case_brief: str | None,
) -> str:
    if case_brief:
        return case_brief

    lines = []
    if case_number:
        lines.append(f"CASE NUMBER: {case_number}")
    lines.append(f"CASE SLUG: {case_slug}")
    lines.append(f"LEGAL QUESTION: {query}")
    lines.append("")
    lines.append("RECONSTRUCTED CASE BRIEF:")
    lines.append((search_result.get("answer") or "").strip())
    return "\n".join(lines).strip()


def _extract_ranked_sentences(text: str, *, limit: int) -> list[str]:
    candidates = [
        segment.strip(" -\t")
        for segment in re.split(r"[\n\r]+|(?<=[.?!])\s+", text)
        if segment and segment.strip()
    ]
    cleaned: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if len(candidate) < 24:
            continue
        normalized = candidate.rstrip(".")
        if normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        cleaned.append(candidate if candidate.endswith(".") else f"{candidate}.")
        if len(cleaned) >= limit:
            break
    return cleaned


def _fallback_consensus_from_search(
    *,
    case_slug: str,
    query: str,
    search_result: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    answer = (search_result.get("answer") or "").strip()
    defenses = _extract_ranked_sentences(answer, limit=3)
    if not defenses:
        defenses = [
            f"Plaintiff's allegations tied to case slug {case_slug} require strict proof.",
            "Defendant reserves all defenses pending discovery and authenticated records review.",
            "Any chronology or causation theory must be tested against the underlying file record.",
        ]
    risks = _extract_ranked_sentences(answer, limit=2)
    risks = risks[:2] if risks else []
    risks.append(f"Fallback consensus used because the Legal Council service was unavailable: {reason}.")
    return {
        "status": "fallback",
        "consensus_signal": "DEFENSE",
        "consensus_conviction": 0.51,
        "top_defense_arguments": defenses,
        "top_risk_factors": risks,
        "top_recommended_actions": [
            "Escalate the generated draft for human legal review before filing.",
            f"Re-run full council deliberation for {case_slug} once the persona roster is restored.",
        ],
        "fallback_reason": reason,
        "fallback_query": query,
        "total_voters": 0,
        "agreement_rate": 0.0,
    }


def _directive_task_id(payload: PaperclipExecuteRequest) -> str:
    return payload.task_id or payload.issue_id or f"paperclip-run-{payload.run_id}"


def _directive_intent(payload: PaperclipExecuteRequest) -> str:
    return (
        f"Paperclip heartbeat wake={payload.wake_reason} "
        f"agent={payload.agent_id} "
        f"company={payload.company_id}"
    )


def _directive_payload(payload: PaperclipExecuteRequest) -> dict[str, Any]:
    return {
        "task_id": _directive_task_id(payload),
        "intent": _directive_intent(payload),
        "context_payload": {
            "bridge_source": "paperclip_http_adapter",
            "paperclip_run_id": payload.run_id,
            "paperclip_agent_id": payload.agent_id,
            "paperclip_company_id": payload.company_id,
            "paperclip_task_id": payload.task_id,
            "paperclip_issue_id": payload.issue_id,
            "paperclip_issue_ids": payload.issue_ids,
            "paperclip_wake_reason": payload.wake_reason,
            "paperclip_wake_comment_id": payload.wake_comment_id,
            "paperclip_approval_id": payload.approval_id,
            "paperclip_approval_status": payload.approval_status,
            "paperclip_context": payload.context.model_dump(by_alias=True),
            "paperclip_request": payload.model_dump(by_alias=True),
            "hermes_contract": _hermes_contract_payload(),
        },
    }


def _hermes_tool_base_url() -> str:
    port = int(os.getenv("HERMES_PORT", "8310"))
    return f"http://127.0.0.1:{port}/api/agent/tools"


def _hermes_tool_headers() -> dict[str, str]:
    token = str(settings.swarm_api_key or "").strip()
    if not token:
        raise RuntimeError("Swarm API key is not configured.")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _call_hermes_tool(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{_hermes_tool_base_url()}/{tool_name}"
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        response = await client.post(url, json=payload, headers=_hermes_tool_headers())
        response.raise_for_status()
        body = response.json()
    if body.get("status") != "success":
        raise RuntimeError(body.get("error_message") or f"{tool_name} failed")
    return body.get("data") or {}


def _callback_result_text(
    payload: PaperclipExecuteRequest,
    nemoclaw: NemoClawResponse,
) -> str:
    envelope = {
        "runId": payload.run_id,
        "agentId": payload.agent_id,
        "taskId": _directive_task_id(payload),
        "wakeReason": payload.wake_reason,
        "nemoclawStatus": nemoclaw.status,
        "actionLog": nemoclaw.action_log,
        "resultPayload": nemoclaw.result_payload or {},
    }
    return json.dumps(envelope, default=str, sort_keys=True)


def _is_hermes_underwriter_run(payload: PaperclipExecuteRequest) -> bool:
    return payload.wake_reason.strip().lower() == "paperclip_heartbeat"


def _underwriter_stage_plan(score: float, *, has_contact_data: bool = False) -> tuple[FunnelStage, str, date]:
    if score >= 0.75 or (has_contact_data and score >= 0.70):
        return FunnelStage.TARGET_LOCKED, "advance_to_target_locked", date.today() + timedelta(days=3)
    if score >= 0.45:
        return FunnelStage.RADAR, "continue_signal_collection", date.today() + timedelta(days=3)
    return FunnelStage.RADAR, "monitor_only", date.today() + timedelta(days=14)


async def _run_hermes_underwriter_heartbeat(
    db: AsyncSession,
    payload: PaperclipExecuteRequest,
) -> NemoClawResponse:
    candidates = await list_acquisition_candidates(db, limit=5)
    processed: list[dict[str, Any]] = []
    action_log: list[str] = []
    isolated_sessions = isinstance(db, AsyncSession)

    for candidate in candidates:
        property_id = UUID(candidate.property_id)
        contact_enrichment: dict[str, Any] | None = None
        score_data: dict[str, Any]
        score: float
        recommended_action: str
        heartbeat_action: str
        next_action_date: date
        event: dict[str, Any]
        pipeline: dict[str, Any]

        if isolated_sessions:
            if not candidate.owner.contacts and candidate.owner.id:
                contact_enrichment = await _call_hermes_tool(
                    "acquisition-enrich-owner-contacts",
                    {
                        "owner_id": candidate.owner.id,
                        "property_id": candidate.property_id,
                    },
                )

            score_data = await _call_hermes_tool(
                "acquisition-score-viability",
                {"property_id": candidate.property_id},
            )
            score = float(score_data["viability_score"])
            recommended_action = str(score_data["recommended_action"])
            has_contact_data = bool((contact_enrichment or {}).get("added_contacts")) or bool(candidate.owner.contacts)
            stage, heartbeat_action, next_action_date = _underwriter_stage_plan(
                score,
                has_contact_data=has_contact_data,
            )
            event = await _call_hermes_tool(
                "acquisition-append-intel-event",
                {
                    "property_id": candidate.property_id,
                    "event_type": "HERMES_UNDERWRITING_REVIEW",
                    "event_description": (
                        f"Hermes scored parcel {candidate.parcel.parcel_id or candidate.property_id} at {score:.2f} "
                        f"and recommended {recommended_action}."
                    ),
                    "raw_source_data": {
                        "run_id": payload.run_id,
                        "agent_id": payload.agent_id,
                        "recommended_action": recommended_action,
                        "heartbeat_action": heartbeat_action,
                        "viability_score": score,
                        "score_components": score_data.get("score_components") or {},
                    },
                },
            )
            pipeline = await _call_hermes_tool(
                "acquisition-advance-pipeline-stage",
                {
                    "property_id": candidate.property_id,
                    "stage": stage.value,
                    "next_action_date": next_action_date.isoformat(),
                    "llm_viability_score": score,
                    "rejection_reason": None,
                },
            )
        else:
            if not candidate.owner.contacts and candidate.owner.id:
                contact_enrichment = await enrich_owner_contacts_from_internal_registry(
                    db,
                    owner_id=UUID(candidate.owner.id),
                    property_id=property_id,
                )
                await db.commit()
            score_data = await score_acquisition_property(db, property_id)
            score = float(score_data["viability_score"])
            recommended_action = str(score_data["recommended_action"])
            has_contact_data = bool((contact_enrichment or {}).get("added_contacts")) or bool(candidate.owner.contacts)
            stage, heartbeat_action, next_action_date = _underwriter_stage_plan(
                score,
                has_contact_data=has_contact_data,
            )
            event = await append_acquisition_intel_event(
                db,
                property_id=property_id,
                event_type="HERMES_UNDERWRITING_REVIEW",
                event_description=(
                    f"Hermes scored parcel {candidate.parcel.parcel_id or candidate.property_id} at {score:.2f} "
                    f"and recommended {recommended_action}."
                ),
                raw_source_data={
                    "run_id": payload.run_id,
                    "agent_id": payload.agent_id,
                    "recommended_action": recommended_action,
                    "heartbeat_action": heartbeat_action,
                    "viability_score": score,
                    "score_components": score_data.get("score_components") or {},
                },
            )
            pipeline = await advance_acquisition_pipeline(
                db,
                property_id=property_id,
                stage=stage,
                next_action_date=next_action_date,
                llm_viability_score=Decimal(str(score)),
            )
            await db.commit()

        action_log.append(
            f"Processed {candidate.parcel.parcel_id or candidate.property_id}: "
            f"score={score:.2f}, stage={pipeline.get('stage')}, next_action_date={pipeline.get('next_action_date')}"
        )
        processed.append(
            {
                "property_id": candidate.property_id,
                "parcel_id": candidate.parcel.parcel_id,
                "score": score,
                "recommended_action": recommended_action,
                "stage": pipeline.get("stage"),
                "next_action_date": pipeline.get("next_action_date"),
                "event_id": event.get("id"),
                "contact_enrichment": contact_enrichment,
            }
        )

    if not processed:
        action_log.append("No unevaluated CROG acquisition candidates were available.")

    return NemoClawResponse(
        task_id=_directive_task_id(payload),
        status="succeeded",
        action_log=action_log,
        result_payload={
            "workflow": "hermes_underwriter_heartbeat",
            "processed_count": len(processed),
            "processed": processed,
        },
    )


async def _send_paperclip_callback(
    run_id: str,
    callback_payload: PaperclipCallbackPayload,
) -> None:
    callback_url = _paperclip_callback_url(run_id)
    async with httpx.AsyncClient(timeout=30.0, verify=_verify_ssl(callback_url)) as client:
        response = await client.post(
            callback_url,
            json=callback_payload.model_dump(by_alias=True, exclude_none=True),
            headers=_paperclip_callback_headers(),
        )
        response.raise_for_status()


async def _process_paperclip_run(payload: PaperclipExecuteRequest) -> None:
    execute_url = _nemoclaw_execute_url()
    logger.info(
        "paperclip_bridge_dispatch_started",
        extra={
            "run_id": payload.run_id,
            "agent_id": payload.agent_id,
            "task_id": _directive_task_id(payload),
            "wake_reason": payload.wake_reason,
        },
    )

    try:
        if _is_hermes_underwriter_run(payload):
            async with AsyncSessionLocal() as db:
                try:
                    nemoclaw = await _run_hermes_underwriter_heartbeat(db, payload)
                except Exception:
                    await db.rollback()
                    raise
        else:
            async with httpx.AsyncClient(timeout=300.0, verify=_verify_ssl(execute_url)) as client:
                response = await client.post(
                    execute_url,
                    json=_directive_payload(payload),
                    headers=_nemoclaw_headers(),
                )
                response.raise_for_status()
                nemoclaw = NemoClawResponse.model_validate(response.json())

        normalized_status = nemoclaw.status.strip().lower()
        callback_payload = PaperclipCallbackPayload(
            status="failed" if normalized_status in {"failed", "error"} else "succeeded",
            result=_callback_result_text(payload, nemoclaw),
            errorMessage=None if normalized_status not in {"failed", "error"} else _callback_result_text(payload, nemoclaw),
        )
        if _paperclip_callback_enabled():
            await _send_paperclip_callback(payload.run_id, callback_payload)
        else:
            logger.info(
                "paperclip_bridge_callback_skipped",
                extra={"run_id": payload.run_id, "reason": "control_plane_not_configured"},
            )
        logger.info(
            "paperclip_bridge_dispatch_completed",
            extra={
                "run_id": payload.run_id,
                "agent_id": payload.agent_id,
                "task_id": nemoclaw.task_id,
                "status": nemoclaw.status,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "paperclip_bridge_dispatch_failed",
            extra={
                "run_id": payload.run_id,
                "agent_id": payload.agent_id,
                "wake_reason": payload.wake_reason,
            },
        )
        callback_payload = PaperclipCallbackPayload(
            status="failed",
            errorMessage=str(exc)[:500],
        )
        if _paperclip_callback_enabled():
            try:
                await _send_paperclip_callback(payload.run_id, callback_payload)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "paperclip_bridge_callback_failed",
                    extra={"run_id": payload.run_id},
                )


@router.post(
    "/execute",
    response_model=PaperclipAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def execute_paperclip_run(
    payload: PaperclipExecuteRequest,
    _swarm_token: str = Depends(verify_swarm_token),
) -> PaperclipAcceptedResponse:
    try:
        _hermes_contract_payload()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    asyncio.create_task(_process_paperclip_run(payload))
    return PaperclipAcceptedResponse(status="accepted", executionId=payload.run_id)


@router.post(
    "/tools/legal-search",
    response_model=LegalSearchToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_legal_search(
    payload: LegalSearchToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> LegalSearchToolResponse:
    """
    Paperclip BYOA Tool: Synchronous execution of the legal search engine.
    """
    logger.info(
        "paperclip_tool_legal_search_invoked",
        extra={"case_slug": payload.case_slug, "query_length": len(payload.query)},
    )

    try:
        result = await synthesize_historic_search(
            db=db,
            query=payload.query,
            case_slug=payload.case_slug,
        )

        logger.info(
            "paperclip_tool_legal_search_success",
            extra={
                "case_slug": payload.case_slug,
                "records_searched": result.get("records_searched", 0),
                "latency_ms": result.get("latency_ms", 0),
            },
        )
        return LegalSearchToolResponse(status="success", data=result)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "paperclip_tool_legal_search_failed",
            extra={"case_slug": payload.case_slug},
        )
        return LegalSearchToolResponse(
            status="error",
            error_message=f"Search engine failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/legal-docgen",
    response_model=LegalDocGenToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_legal_docgen(
    payload: LegalDocGenToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> LegalDocGenToolResponse:
    """
    Paperclip BYOA Tool: Synchronous DOCX pleading generation.
    """
    logger.info(
        "paperclip_tool_legal_docgen_invoked",
        extra={
            "brief_length": len(payload.case_brief),
            "consensus_signal": payload.consensus.get("consensus_signal"),
        },
    )

    try:
        case_meta = _extract_case_meta(payload.case_brief)
        docx_bytes = generate_answer_and_defenses(
            case_brief=payload.case_brief,
            consensus=payload.consensus,
        )
        filename = f"Answer_and_Defenses_{case_meta['case_number']}.docx"
        result = _build_docgen_result_payload(
            case_meta=case_meta,
            consensus=payload.consensus,
            filename=filename,
            docx_bytes=docx_bytes,
        )
        if payload.persist_to_vault and payload.case_slug:
            result.update(
                await _persist_case_artifact(
                    db,
                    case_slug=payload.case_slug,
                    filename=filename,
                    content=docx_bytes,
                )
            )

        logger.info(
            "paperclip_tool_legal_docgen_success",
            extra={
                "case_slug": payload.case_slug,
                "case_number": case_meta["case_number"],
                "attachment_filename": filename,
                "size_bytes": len(docx_bytes),
            },
        )
        return LegalDocGenToolResponse(status="success", data=result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("paperclip_tool_legal_docgen_failed")
        return LegalDocGenToolResponse(
            status="error",
            error_message=f"DocGen failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/legal-motion-drafter",
    response_model=DraftMotionExtensionResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_legal_motion_drafter(
    payload: DraftMotionExtensionAction,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> DraftMotionExtensionResponse:
    logger.info(
        "paperclip_tool_legal_motion_drafter_invoked",
        extra={"case_number": payload.case_number, "case_slug": payload.case_slug},
    )
    try:
        case_meta = await _resolve_case_slug_and_meta(
            db,
            case_number=payload.case_number,
            case_slug=payload.case_slug,
        )
        deadline = payload.motion_parameters
        docx_bytes = generate_motion_extension_docx(
            case_number=case_meta["case_number"],
            case_name=case_meta.get("case_name") or payload.case_number,
            court=case_meta.get("court") or "Superior Court",
            judge=deadline.presiding_judge or case_meta.get("judge") or "Mary Beth Priest",
            jurisdiction=deadline.jurisdiction,
            deadline_date=deadline.deadline_date,
            deadline_type=deadline.deadline_type or deadline.description or "Responsive Pleading",
            days_remaining=deadline.days_remaining,
            supporting_context=deadline.description,
        )
        filename = motion_extension_filename(case_number=case_meta["case_number"])
        result: dict[str, Any] = {
            "filename": filename,
            "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "size_bytes": len(docx_bytes),
            "case_slug": case_meta["case_slug"],
            "case_number": case_meta["case_number"],
            "deadline_date": deadline.deadline_date,
            "deadline_type": deadline.deadline_type,
            "presiding_judge": deadline.presiding_judge,
            "jurisdiction": deadline.jurisdiction,
        }
        if payload.persist_to_vault:
            if payload.target_vault_path:
                result.update(
                    _persist_explicit_vault_artifact(
                        target_vault_path=payload.target_vault_path,
                        filename=filename,
                        content=docx_bytes,
                    )
                )
            else:
                result.update(
                    await _persist_case_artifact(
                        db,
                        case_slug=case_meta["case_slug"],
                        filename=filename,
                        content=docx_bytes,
                    )
                )
        logger.info(
            "paperclip_tool_legal_motion_drafter_success",
            extra={"case_number": case_meta["case_number"], "attachment_filename": filename},
        )
        return DraftMotionExtensionResponse(status="success", data=result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("paperclip_tool_legal_motion_drafter_failed")
        return DraftMotionExtensionResponse(
            status="error",
            error_message=f"Legal motion drafter failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/legal-opposing-filing-analysis",
    response_model=AnalyzeOpposingFilingResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_legal_opposing_filing_analysis(
    payload: AnalyzeOpposingFilingAction,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> AnalyzeOpposingFilingResponse:
    logger.info(
        "paperclip_tool_legal_opposing_filing_analysis_invoked",
        extra={"case_number": payload.case_number, "case_slug": payload.case_slug},
    )
    try:
        case_meta = await _resolve_case_slug_and_meta(
            db,
            case_number=payload.case_number,
            case_slug=payload.case_slug,
        )
        query = (
            f"Analyze the latest opposing filing for case {case_meta['case_number']}. "
            f"Filing name: {payload.filing_name or 'unknown'}. "
            f"Operator summary: {payload.filing_summary or 'No filing summary supplied.'} "
            f"Identify strategic vulnerabilities, contradictions, and recommended counters."
        )
        search = await synthesize_historic_search(
            db=db,
            query=query,
            case_slug=case_meta["case_slug"],
        )
        artifact = {
            "case_slug": case_meta["case_slug"],
            "case_number": case_meta["case_number"],
            "filing_name": payload.filing_name,
            "filing_summary": payload.filing_summary,
            "threat_assessment": search.get("answer"),
            "records_searched": search.get("records_searched", 0),
            "inference_source": search.get("inference_source"),
            "latency_ms": search.get("latency_ms"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        content = json.dumps(artifact, ensure_ascii=False, indent=2).encode("utf-8")
        filename = f"Opposing_Filing_Threat_Assessment_{_sanitize_filename_component(case_meta['case_number'])}.json"
        result: dict[str, Any] = {
            "artifact": artifact,
            "artifact_filename": filename,
            "size_bytes": len(content),
            "media_type": "application/json",
        }
        if payload.persist_to_vault:
            if payload.target_vault_path:
                result.update(
                    _persist_explicit_vault_artifact(
                        target_vault_path=payload.target_vault_path,
                        filename=filename,
                        content=content,
                    )
                )
            else:
                result.update(
                    await _persist_case_artifact(
                        db,
                        case_slug=case_meta["case_slug"],
                        filename=filename,
                        content=content,
                    )
                )
        logger.info(
            "paperclip_tool_legal_opposing_filing_analysis_success",
            extra={"case_number": case_meta["case_number"], "attachment_filename": filename},
        )
        return AnalyzeOpposingFilingResponse(status="success", data=result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("paperclip_tool_legal_opposing_filing_analysis_failed")
        return AnalyzeOpposingFilingResponse(
            status="error",
            error_message=f"Opposing filing analysis failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/legal-threat-assessor",
    response_model=LegalThreatAssessorResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_legal_threat_assessor(
    payload: LegalThreatAssessorRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> LegalThreatAssessorResponse:
    logger.info(
        "paperclip_tool_legal_threat_assessor_invoked",
        extra={"case_number": payload.case_number, "case_slug": payload.case_slug},
    )
    try:
        case_meta = await _resolve_case_slug_and_meta(
            db,
            case_number=payload.case_number,
            case_slug=payload.case_slug,
        )
        sanitized_text = " ".join(str(payload.document_text or "").split())
        excerpt = sanitized_text[:20_000]
        metadata = payload.metadata or {}
        query = (
            f"You are reviewing a sanitized hostile filing for case {case_meta['case_number']}. "
            f"Filing name: {payload.filing_name or 'unknown'}. "
            f"Metadata: {json.dumps(metadata, ensure_ascii=True, sort_keys=True)} "
            f"Sanitized filing text follows:\n{excerpt}\n\n"
            "Provide a strategic threat assessment, contradictions, likely procedural weaknesses, "
            "and recommended counters for counsel."
        )
        search = await synthesize_historic_search(
            db=db,
            query=query,
            case_slug=case_meta["case_slug"],
        )
        artifact = {
            "case_slug": case_meta["case_slug"],
            "case_number": case_meta["case_number"],
            "filing_name": payload.filing_name,
            "threat_assessment": search.get("answer"),
            "records_searched": search.get("records_searched", 0),
            "inference_source": search.get("inference_source"),
            "latency_ms": search.get("latency_ms"),
            "sanitized_chars": len(sanitized_text),
            "text_excerpt": sanitized_text[:2000],
            "metadata": metadata,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        content = json.dumps(artifact, ensure_ascii=False, indent=2).encode("utf-8")
        filename = (
            f"Legal_Threat_Assessment_"
            f"{_sanitize_filename_component(case_meta['case_number'])}.json"
        )
        result: dict[str, Any] = {
            "artifact": artifact,
            "artifact_filename": filename,
            "size_bytes": len(content),
            "media_type": "application/json",
        }
        if payload.persist_to_vault:
            if payload.target_vault_path:
                result.update(
                    _persist_explicit_vault_artifact(
                        target_vault_path=payload.target_vault_path,
                        filename=filename,
                        content=content,
                    )
                )
            else:
                result.update(
                    await _persist_case_artifact(
                        db,
                        case_slug=case_meta["case_slug"],
                        filename=filename,
                        content=content,
                    )
                )
        logger.info(
            "paperclip_tool_legal_threat_assessor_success",
            extra={"case_number": case_meta["case_number"], "attachment_filename": filename},
        )
        return LegalThreatAssessorResponse(status="success", data=result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("paperclip_tool_legal_threat_assessor_failed")
        return LegalThreatAssessorResponse(
            status="error",
            error_message=f"Legal threat assessor failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/legal-council",
    response_model=LegalDraftWorkflowResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_legal_council(
    payload: LegalDraftWorkflowRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> LegalDraftWorkflowResponse:
    """
    Paperclip BYOA Tool alias: 9-seat council workflow surfaced as a standalone legal action.
    Reuses the draft-answer workflow so council reasoning, deliberation ledger writes,
    and optional artifact persistence stay on the same sovereign path.
    """
    return await tool_legal_draft_answer(payload=payload, db=db, _swarm_token=_swarm_token)


@router.post(
    "/tools/legal-draft-answer",
    response_model=LegalDraftWorkflowResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_legal_draft_answer(
    payload: LegalDraftWorkflowRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> LegalDraftWorkflowResponse:
    """
    Paperclip BYOA Tool: Search -> Council deliberation -> DOCX generation -> NAS vault.
    """
    logger.info(
        "paperclip_tool_legal_draft_answer_invoked",
        extra={"case_slug": payload.case_slug, "query_length": len(payload.query)},
    )

    try:
        search_result = await synthesize_historic_search(
            db=db,
            query=payload.query,
            case_slug=payload.case_slug,
        )
        derived_case_brief = _build_workflow_case_brief(
            case_slug=payload.case_slug,
            query=payload.query,
            search_result=search_result,
            case_number=payload.case_number,
            case_brief=payload.case_brief,
        )
        deliberation_context = "\n\n".join(
            chunk for chunk in [payload.context or "", search_result.get("answer", "")] if chunk
        )
        session_id = f"paperclip-legal-{uuid.uuid4()}"
        council_result = await run_council_deliberation(
            session_id=session_id,
            case_brief=derived_case_brief,
            context=deliberation_context,
            progress_callback=None,
            case_slug=payload.case_slug,
            case_number=payload.case_number or "",
            trigger_type=payload.trigger_type,
        )
        if not isinstance(council_result, dict):
            session_state = get_session(session_id) or {}
            fallback_reason = str(session_state.get("error") or "Legal Council returned no result")
            logger.warning(
                "paperclip_tool_legal_draft_answer_fallback_consensus",
                extra={"case_slug": payload.case_slug, "reason": fallback_reason},
            )
            council_result = _fallback_consensus_from_search(
                case_slug=payload.case_slug,
                query=payload.query,
                search_result=search_result,
                reason=fallback_reason,
            )
        elif not council_result.get("consensus_signal"):
            fallback_reason = str(council_result.get("error") or "Consensus signal missing")
            logger.warning(
                "paperclip_tool_legal_draft_answer_fallback_consensus",
                extra={"case_slug": payload.case_slug, "reason": fallback_reason},
            )
            council_result = {
                **_fallback_consensus_from_search(
                    case_slug=payload.case_slug,
                    query=payload.query,
                    search_result=search_result,
                    reason=fallback_reason,
                ),
                "council_payload": council_result,
            }

        case_meta = _extract_case_meta(derived_case_brief)
        docx_bytes = generate_answer_and_defenses(
            case_brief=derived_case_brief,
            consensus=council_result,
        )
        filename = f"Answer_and_Defenses_{case_meta['case_number']}.docx"
        artifact = _build_docgen_result_payload(
            case_meta=case_meta,
            consensus=council_result,
            filename=filename,
            docx_bytes=docx_bytes,
        )
        if payload.persist_to_vault:
            artifact.update(
                await _persist_case_artifact(
                    db,
                    case_slug=payload.case_slug,
                    filename=filename,
                    content=docx_bytes,
                )
            )

        result = {
            "workflow": "draft_answer_from_case_slug",
            "case_slug": payload.case_slug,
            "query": payload.query,
            "search": {
                "records_searched": search_result.get("records_searched", 0),
                "latency_ms": search_result.get("latency_ms", 0),
                "answer": search_result.get("answer"),
            },
            "council": {
                "session_id": council_result.get("session_id"),
                "consensus_signal": council_result.get("consensus_signal"),
                "consensus_conviction": council_result.get("consensus_conviction"),
                "defense_count": len(council_result.get("top_defense_arguments", []) or []),
                "risk_count": len(council_result.get("top_risk_factors", []) or []),
                "event_id": council_result.get("event_id"),
                "sha256_signature": council_result.get("sha256_signature"),
            },
            "artifact": artifact,
        }

        logger.info(
            "paperclip_tool_legal_draft_answer_success",
            extra={
                "case_slug": payload.case_slug,
                "case_number": case_meta["case_number"],
                "attachment_filename": filename,
            },
        )
        return LegalDraftWorkflowResponse(status="success", data=result)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "paperclip_tool_legal_draft_answer_failed",
            extra={"case_slug": payload.case_slug},
        )
        return LegalDraftWorkflowResponse(
            status="error",
            error_message=f"Legal workflow failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/legal-raw-evidence-ingest",
    response_model=LegalRawEvidenceIngestToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_legal_raw_evidence_ingest(
    payload: LegalRawEvidenceIngestToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> LegalRawEvidenceIngestToolResponse:
    """
    Paperclip BYOA Tool: extract entities/claims from raw text and dual-write graph + discovery tables.
    """
    logger.info(
        "paperclip_tool_legal_raw_evidence_ingest_invoked",
        extra={"case_slug": payload.case_slug, "payload_chars": len(payload.payload_text or "")},
    )

    try:
        legacy_pack_id = uuid.UUID(str(payload.pack_id).strip())
    except ValueError:
        return LegalRawEvidenceIngestToolResponse(
            status="error",
            error_message="Invalid pack_id: must be a UUID.",
        )

    v2_opt: uuid.UUID | None = None
    if payload.v2_pack_id:
        try:
            v2_opt = uuid.UUID(str(payload.v2_pack_id).strip())
        except ValueError:
            return LegalRawEvidenceIngestToolResponse(
                status="error",
                error_message="Invalid v2_pack_id: must be a UUID.",
            )

    try:
        data = await LegalDiscoveryEngine.ingest_raw_evidence(
            db,
            case_slug=payload.case_slug.strip(),
            legacy_pack_id=legacy_pack_id,
            payload_text=payload.payload_text,
            source_document=payload.source_document,
            source_ref=payload.source_ref,
            v2_pack_id=v2_opt,
            target_entity_for_v2_pack=payload.target_entity_for_v2_pack,
        )
        logger.info(
            "paperclip_tool_legal_raw_evidence_ingest_success",
            extra={
                "case_slug": payload.case_slug,
                "nodes": data.get("nodes_persisted"),
                "claims": data.get("claims_persisted"),
            },
        )
        return LegalRawEvidenceIngestToolResponse(status="success", data=data)
    except HTTPException as exc:
        detail = exc.detail
        msg = detail if isinstance(detail, str) else json.dumps(detail, default=str)
        logger.warning(
            "paperclip_tool_legal_raw_evidence_ingest_http_error",
            extra={"case_slug": payload.case_slug, "status": exc.status_code, "detail": msg[:300]},
        )
        return LegalRawEvidenceIngestToolResponse(status="error", error_message=msg)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "paperclip_tool_legal_raw_evidence_ingest_failed",
            extra={"case_slug": payload.case_slug},
        )
        return LegalRawEvidenceIngestToolResponse(
            status="error",
            error_message=f"Raw evidence ingest failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/legal-deposition-outline",
    response_model=LegalDepositionOutlineToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_legal_deposition_outline(
    payload: LegalDepositionOutlineToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> LegalDepositionOutlineToolResponse:
    """
    Paperclip BYOA Tool: graph + sanctions + council risks → structured deposition outline JSON (+ optional NAS vault).

    Exposed at ``POST /api/agent/tools/legal-deposition-outline`` and
    ``POST /api/paperclip/tools/legal-deposition-outline`` (swarm Bearer; whitelisted in public API paths).

    Register the tool in the Paperclip control-plane/agent catalog separately; that UI lives outside this repo.
    """
    logger.info(
        "paperclip_tool_legal_deposition_outline_invoked",
        extra={
            "case_slug": payload.case_slug,
            "deponent_len": len(payload.deponent_entity or ""),
        },
    )
    try:
        outline = await generate_deposition_outline(
            db,
            case_slug=payload.case_slug.strip(),
            deponent_entity=payload.deponent_entity.strip(),
            operator_focus=(payload.operator_focus or "").strip() or None,
        )
        filename = outline_artifact_filename(
            deponent_entity=payload.deponent_entity.strip(),
            case_slug=payload.case_slug.strip(),
            case_number=payload.case_number,
        )
        content = json.dumps(outline, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        result: dict[str, Any] = {
            "outline": outline,
            "artifact_filename": filename,
            "size_bytes": len(content),
            "media_type": "application/json",
        }
        if payload.persist_to_vault:
            result.update(
                await _persist_case_artifact(
                    db,
                    case_slug=payload.case_slug.strip(),
                    filename=filename,
                    content=content,
                )
            )
        logger.info(
            "paperclip_tool_legal_deposition_outline_success",
            extra={"case_slug": payload.case_slug, "attachment_filename": filename},
        )
        return LegalDepositionOutlineToolResponse(status="success", data=result)
    except ValueError as exc:
        return LegalDepositionOutlineToolResponse(
            status="error",
            error_message=str(exc)[:500],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "paperclip_tool_legal_deposition_outline_failed",
            extra={"case_slug": payload.case_slug},
        )
        return LegalDepositionOutlineToolResponse(
            status="error",
            error_message=f"Deposition outline failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/guest-triage",
    response_model=GuestTriageToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_guest_triage(
    payload: GuestTriageToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> GuestTriageToolResponse:
    """
    Paperclip BYOA Tool: Division 1 — guest communication triage.

    Pulls live guest / reservation / property / message thread + property knowledge,
    runs the 9-seat Concierge matrix, returns structured triage and a draft SMS reply.
    Does not mutate reservations or send messages.

    Exposed at ``POST /api/agent/tools/guest-triage`` and
    ``POST /api/paperclip/tools/guest-triage`` (swarm Bearer).
    """
    logger.info(
        "paperclip_tool_guest_triage_invoked",
        extra={
            "message_id": str(payload.message_id) if payload.message_id else None,
            "guest_id": str(payload.guest_id) if payload.guest_id else None,
            "reservation_id": str(payload.reservation_id) if payload.reservation_id else None,
            "has_phone": bool((payload.guest_phone or "").strip()),
        },
    )
    try:
        data = await run_guest_triage(
            db,
            guest_id=payload.guest_id,
            reservation_id=payload.reservation_id,
            message_id=payload.message_id,
            guest_phone=(payload.guest_phone or "").strip() or None,
            inbound_message=(payload.inbound_message or "").strip() or None,
            trigger_type=payload.trigger_type,
            include_wifi_in_property_block=payload.include_wifi_in_property_block,
        )
        logger.info(
            "paperclip_tool_guest_triage_success",
            extra={
                "session_id": data.get("session_id"),
                "consensus": (data.get("triage") or {}).get("consensus_signal"),
            },
        )
        return GuestTriageToolResponse(status="success", data=data)
    except ValueError as exc:
        logger.warning(
            "paperclip_tool_guest_triage_validation",
            extra={"error": str(exc)[:300]},
        )
        return GuestTriageToolResponse(
            status="error",
            error_message=str(exc)[:500],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("paperclip_tool_guest_triage_failed")
        return GuestTriageToolResponse(
            status="error",
            error_message=f"Guest triage failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/guest-resolve-conflict",
    response_model=GuestResolveConflictToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_guest_resolve_conflict(
    payload: GuestResolveConflictToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> GuestResolveConflictToolResponse:
    """
    Paperclip BYOA Tool: Division 1 — Maintenance Adjudicator / conflict mediator.

    Cross-references guest complaint context with recent work orders and the
    Concierge 9-seat matrix to determine whether the complaint aligns with field
    reality, whether corrective scheduling is justified, and how refund posture
    should be framed.
    """
    logger.info(
        "paperclip_tool_guest_resolve_conflict_invoked",
        extra={
            "message_id": str(payload.message_id) if payload.message_id else None,
            "guest_id": str(payload.guest_id) if payload.guest_id else None,
            "reservation_id": str(payload.reservation_id) if payload.reservation_id else None,
            "has_phone": bool((payload.guest_phone or "").strip()),
        },
    )
    try:
        data = await run_guest_resolve_conflict(
            db,
            guest_id=payload.guest_id,
            reservation_id=payload.reservation_id,
            message_id=payload.message_id,
            guest_phone=(payload.guest_phone or "").strip() or None,
            inbound_message=(payload.inbound_message or "").strip() or None,
            trigger_type=payload.trigger_type,
            include_wifi_in_property_block=payload.include_wifi_in_property_block,
        )
        logger.info(
            "paperclip_tool_guest_resolve_conflict_success",
            extra={
                "session_id": data.get("session_id"),
                "consensus": (data.get("conflict_resolution") or {}).get("consensus_signal"),
                "legitimacy": (data.get("conflict_resolution") or {}).get("complaint_legitimacy"),
            },
        )
        return GuestResolveConflictToolResponse(status="success", data=data)
    except ValueError as exc:
        logger.warning(
            "paperclip_tool_guest_resolve_conflict_validation",
            extra={"error": str(exc)[:300]},
        )
        return GuestResolveConflictToolResponse(
            status="error",
            error_message=str(exc)[:500],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("paperclip_tool_guest_resolve_conflict_failed")
        return GuestResolveConflictToolResponse(
            status="error",
            error_message=f"Guest conflict resolution failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/guest-send-sms",
    response_model=GuestSendSmsToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_guest_send_sms(
    payload: GuestSendSmsToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> GuestSendSmsToolResponse:
    """
    Paperclip BYOA Tool: Division 1 live outbound SMS dispatch.

    Sends a consensus-drafted Concierge response only when conviction exceeds
    the configured/requested threshold and current Strike / auto-reply safety
    gates allow autonomous communication.
    """
    logger.info(
        "paperclip_tool_guest_send_sms_invoked",
        extra={
            "guest_id": str(payload.guest_id) if payload.guest_id else None,
            "reservation_id": str(payload.reservation_id) if payload.reservation_id else None,
            "has_phone": bool((payload.guest_phone or "").strip()),
            "consensus_conviction": payload.consensus_conviction,
            "minimum_conviction": payload.minimum_conviction,
        },
    )
    try:
        data = await run_guest_send_sms(
            db,
            guest_id=payload.guest_id,
            reservation_id=payload.reservation_id,
            guest_phone=(payload.guest_phone or "").strip() or None,
            body=payload.body,
            consensus_conviction=payload.consensus_conviction,
            minimum_conviction=payload.minimum_conviction,
            session_id=(payload.session_id or "").strip() or None,
            source_workflow=(payload.source_workflow or "").strip() or None,
            trigger_type=payload.trigger_type,
        )
        logger.info(
            "paperclip_tool_guest_send_sms_success",
            extra={
                "message_id": (data.get("delivery") or {}).get("message_id"),
                "audit_status": (data.get("audit_log") or {}).get("status"),
            },
        )
        return GuestSendSmsToolResponse(status="success", data=data)
    except ValueError as exc:
        logger.warning(
            "paperclip_tool_guest_send_sms_validation",
            extra={"error": str(exc)[:300]},
        )
        return GuestSendSmsToolResponse(status="error", error_message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001
        logger.exception("paperclip_tool_guest_send_sms_failed")
        return GuestSendSmsToolResponse(
            status="error",
            error_message=f"Guest send SMS failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/draft-reactivation-sequence",
    response_model=GuestReactivationToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_draft_reactivation_sequence(
    payload: GuestReactivationToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> GuestReactivationToolResponse:
    """
    Paperclip BYOA Tool: draft personalized dormant-guest outreach and park it in AgentQueue.
    """
    logger.info(
        "paperclip_tool_draft_reactivation_sequence_invoked",
        extra={"guest_id": str(payload.guest_id), "target_score": payload.target_score},
    )
    try:
        data = await draft_reactivation_sequence(
            db,
            guest_id=payload.guest_id,
            target_score=payload.target_score,
            trigger_type=payload.trigger_type,
        )
        await db.commit()
        logger.info(
            "paperclip_tool_draft_reactivation_sequence_success",
            extra={
                "guest_id": str(payload.guest_id),
                "queue_entry_id": (data.get("queue_entry") or {}).get("id"),
            },
        )
        return GuestReactivationToolResponse(status="success", data=data)
    except ValueError as exc:
        await db.rollback()
        logger.warning(
            "paperclip_tool_draft_reactivation_sequence_validation",
            extra={"guest_id": str(payload.guest_id), "error": str(exc)[:300]},
        )
        return GuestReactivationToolResponse(status="error", error_message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("paperclip_tool_draft_reactivation_sequence_failed")
        return GuestReactivationToolResponse(
            status="error",
            error_message=f"Reactivation draft failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/acquisition-read-candidates",
    response_model=AcquisitionCandidateReadToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_acquisition_read_candidates(
    payload: AcquisitionReadCandidatesToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> AcquisitionCandidateReadToolResponse:
    logger.info(
        "paperclip_tool_acquisition_read_candidates_invoked",
        extra={"limit": payload.limit},
    )
    try:
        data = await list_acquisition_candidates(db, limit=payload.limit)
        logger.info(
            "paperclip_tool_acquisition_read_candidates_success",
            extra={"count": len(data), "limit": payload.limit},
        )
        return AcquisitionCandidateReadToolResponse(status="success", data=data)
    except Exception as exc:  # noqa: BLE001
        logger.exception("paperclip_tool_acquisition_read_candidates_failed")
        return AcquisitionCandidateReadToolResponse(
            status="error",
            error_message=f"Acquisition candidate read failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/acquisition-score-viability",
    response_model=AcquisitionToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_acquisition_score_viability(
    payload: AcquisitionScoreToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> AcquisitionToolResponse:
    logger.info(
        "paperclip_tool_acquisition_score_viability_invoked",
        extra={"property_id": str(payload.property_id)},
    )
    try:
        data = await score_acquisition_property(db, payload.property_id)
        await db.commit()
        logger.info(
            "paperclip_tool_acquisition_score_viability_success",
            extra={"property_id": str(payload.property_id), "score": data.get("viability_score")},
        )
        return AcquisitionToolResponse(status="success", data=data)
    except ValueError as exc:
        await db.rollback()
        return AcquisitionToolResponse(status="error", error_message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("paperclip_tool_acquisition_score_viability_failed")
        return AcquisitionToolResponse(
            status="error",
            error_message=f"Acquisition viability scoring failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/acquisition-enrich-owner-psychology",
    response_model=AcquisitionToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_acquisition_enrich_owner_psychology(
    payload: AcquisitionPsychologyToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> AcquisitionToolResponse:
    logger.info(
        "paperclip_tool_acquisition_enrich_owner_psychology_invoked",
        extra={"owner_id": str(payload.owner_id), "property_id": str(payload.property_id) if payload.property_id else None},
    )
    try:
        data = await enrich_owner_psychology(
            db,
            owner_id=payload.owner_id,
            property_id=payload.property_id,
            profile_patch=payload.profile_patch,
            source_note=payload.source_note,
        )
        await db.commit()
        logger.info(
            "paperclip_tool_acquisition_enrich_owner_psychology_success",
            extra={"owner_id": str(payload.owner_id)},
        )
        return AcquisitionToolResponse(status="success", data=data)
    except ValueError as exc:
        await db.rollback()
        return AcquisitionToolResponse(status="error", error_message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("paperclip_tool_acquisition_enrich_owner_psychology_failed")
        return AcquisitionToolResponse(
            status="error",
            error_message=f"Owner psychology enrichment failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/acquisition-enrich-owner-contacts",
    response_model=AcquisitionToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_acquisition_enrich_owner_contacts(
    payload: AcquisitionContactEnrichmentToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> AcquisitionToolResponse:
    logger.info(
        "paperclip_tool_acquisition_enrich_owner_contacts_invoked",
        extra={"owner_id": str(payload.owner_id), "property_id": str(payload.property_id) if payload.property_id else None},
    )
    try:
        data = await enrich_owner_contacts_from_internal_registry(
            db,
            owner_id=payload.owner_id,
            property_id=payload.property_id,
        )
        await db.commit()
        logger.info(
            "paperclip_tool_acquisition_enrich_owner_contacts_success",
            extra={"owner_id": str(payload.owner_id), "added_count": len(data.get("added_contacts") or [])},
        )
        return AcquisitionToolResponse(status="success", data=data)
    except ValueError as exc:
        await db.rollback()
        return AcquisitionToolResponse(status="error", error_message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("paperclip_tool_acquisition_enrich_owner_contacts_failed")
        return AcquisitionToolResponse(
            status="error",
            error_message=f"Owner contact enrichment failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/acquisition-append-intel-event",
    response_model=AcquisitionToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_acquisition_append_intel_event(
    payload: AcquisitionAppendEventToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> AcquisitionToolResponse:
    logger.info(
        "paperclip_tool_acquisition_append_intel_event_invoked",
        extra={"property_id": str(payload.property_id), "event_type": payload.event_type},
    )
    try:
        data = await append_acquisition_intel_event(
            db,
            property_id=payload.property_id,
            event_type=payload.event_type,
            event_description=payload.event_description,
            raw_source_data=payload.raw_source_data,
        )
        await db.commit()
        logger.info(
            "paperclip_tool_acquisition_append_intel_event_success",
            extra={"property_id": str(payload.property_id), "event_type": payload.event_type},
        )
        return AcquisitionToolResponse(status="success", data=data)
    except ValueError as exc:
        await db.rollback()
        return AcquisitionToolResponse(status="error", error_message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("paperclip_tool_acquisition_append_intel_event_failed")
        return AcquisitionToolResponse(
            status="error",
            error_message=f"Acquisition intel append failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/acquisition-advance-pipeline-stage",
    response_model=AcquisitionToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_acquisition_advance_pipeline_stage(
    payload: AcquisitionAdvanceStageToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> AcquisitionToolResponse:
    logger.info(
        "paperclip_tool_acquisition_advance_pipeline_stage_invoked",
        extra={"property_id": str(payload.property_id), "stage": payload.stage.value},
    )
    try:
        parsed_next_action_date = (
            datetime.fromisoformat(payload.next_action_date).date()
            if payload.next_action_date
            else None
        )
        data = await advance_acquisition_pipeline(
            db,
            property_id=payload.property_id,
            stage=payload.stage,
            next_action_date=parsed_next_action_date,
            rejection_reason=payload.rejection_reason,
            llm_viability_score=(
                None if payload.llm_viability_score is None else Decimal(str(payload.llm_viability_score))
            ),
        )
        await db.commit()
        logger.info(
            "paperclip_tool_acquisition_advance_pipeline_stage_success",
            extra={"property_id": str(payload.property_id), "stage": payload.stage.value},
        )
        return AcquisitionToolResponse(status="success", data=data)
    except ValueError as exc:
        await db.rollback()
        return AcquisitionToolResponse(status="error", error_message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("paperclip_tool_acquisition_advance_pipeline_stage_failed")
        return AcquisitionToolResponse(
            status="error",
            error_message=f"Acquisition stage advance failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/acquisition-draft-outreach-sequence",
    response_model=AcquisitionToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_acquisition_draft_outreach_sequence(
    payload: AcquisitionDraftOutreachToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> AcquisitionToolResponse:
    logger.info(
        "paperclip_tool_acquisition_draft_outreach_sequence_invoked",
        extra={"property_id": str(payload.property_id)},
    )
    try:
        data = await draft_acquisition_outreach_sequence(
            db,
            property_id=payload.property_id,
        )
        logger.info(
            "paperclip_tool_acquisition_draft_outreach_sequence_success",
            extra={"property_id": str(payload.property_id), "channel": data.get("recommended_channel")},
        )
        return AcquisitionToolResponse(status="success", data=data)
    except ValueError as exc:
        return AcquisitionToolResponse(status="error", error_message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001
        logger.exception("paperclip_tool_acquisition_draft_outreach_sequence_failed")
        return AcquisitionToolResponse(
            status="error",
            error_message=f"Acquisition outreach drafting failure: {str(exc)[:500]}",
        )


@router.post(
    "/tools/acquisition-run-ingestion",
    response_model=AcquisitionToolResponse,
    status_code=status.HTTP_200_OK,
)
async def tool_acquisition_run_ingestion(
    payload: AcquisitionIngestionToolRequest,
    db: AsyncSession = Depends(get_db),
    _swarm_token: str = Depends(verify_swarm_token),
) -> AcquisitionToolResponse:
    logger.info(
        "paperclip_tool_acquisition_run_ingestion_invoked",
        extra={"county_name": payload.county_name, "dry_run": payload.dry_run},
    )
    redis = await _create_arq_pool()
    try:
        job = await _enqueue_async_job(
            db,
            worker_name="run_acquisition_ingestion_job",
            job_name="acquisition_ingestion_cycle",
            payload=payload.model_dump(mode="json"),
            requested_by="paperclip_bridge",
            tenant_id=None,
            request_id=f"paperclip-acquisition-{uuid.uuid4()}",
            redis=redis,
        )
        logger.info(
            "paperclip_tool_acquisition_run_ingestion_success",
            extra={"job_id": str(job.id), "county_name": payload.county_name},
        )
        return AcquisitionToolResponse(
            status="success",
            data={
                "job": _serialize_async_job(job),
                "queued": True,
            },
        )
    except ValueError as exc:
        await db.rollback()
        return AcquisitionToolResponse(status="error", error_message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        logger.exception("paperclip_tool_acquisition_run_ingestion_failed")
        return AcquisitionToolResponse(
            status="error",
            error_message=f"Acquisition ingestion enqueue failure: {str(exc)[:500]}",
        )
    finally:
        await redis.aclose()
