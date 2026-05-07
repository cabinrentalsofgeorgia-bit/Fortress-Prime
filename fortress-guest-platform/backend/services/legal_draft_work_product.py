"""Draft work product generation from the limited verified subset only.

Outputs are internal draft review artifacts. They use source-routing metadata
from verified/corrected items and never read document body text or locked
content.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.legal_counsel_validation import TARGET_SLUG
from backend.services.legal_counsel_workbench import AUDIT_DIR
from backend.services.legal_limited_signoff_candidate_packet import load_latest_limited_signoff_candidate
from backend.services.legal_targeted_source_completion import load_latest_targeted_source_completion
from backend.services.legal_autonomous_learning_loop import load_latest_learning_loop

DRAFT_WORK_PRODUCT_PREFIX = "fortress-draft-work-product-"
GOVERNANCE_LABELS = [
    "DRAFT / COUNSEL REVIEW REQUIRED",
    "NOT FINAL LEGAL ADVICE",
    "NOT AUTHORIZED FOR FILING, SERVICE, SENDING, EMAIL, OR EXTERNAL SUBMISSION",
    "SOURCE-VERIFIED SUBSET ONLY",
    "COUNSEL_SIGNOFF_PENDING",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def draft_manifest_path(execution_id: str) -> Path:
    return AUDIT_DIR / f"{execution_id}.json"


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _source_refs(record: dict[str, Any]) -> list[dict[str, Any]]:
    refs = record.get("source_refs_after") or record.get("source_refs_before") or []
    safe_refs: list[dict[str, Any]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        safe_refs.append(
            {
                "document_id": ref.get("document_id"),
                "file_name": ref.get("file_name") or ref.get("source_ref"),
                "processing_status": ref.get("processing_status"),
                "locked_restricted": bool(ref.get("locked_restricted")),
                "page_chunk_status": ref.get("page_chunk_status"),
                "event_id": ref.get("event_id"),
                "event_date": ref.get("event_date"),
            }
        )
    return safe_refs


def _safe_included_item(record: dict[str, Any]) -> dict[str, Any]:
    source_refs = _source_refs(record)
    source_status = record.get("final_state") or record.get("final_remediation_state") or record.get("source_status")
    payload = {
        "draft_item_id": str(uuid4()),
        "source_record_id": record.get("targeted_source_completion_id") or record.get("source_link_repair_id") or record.get("source_record_id"),
        "item_id": record.get("item_id"),
        "item_type": record.get("item_type"),
        "source_status": source_status,
        "corrected_claim_summary": record.get("corrected_claim_summary") or "Source-routed review-use item; counsel review required before reliance.",
        "source_refs": source_refs,
        "source_refs_count": len(source_refs) or int(record.get("source_refs_count") or 0),
        "locked_restricted_involved": bool(record.get("locked_restricted_involved")),
        "counsel_review_required": True,
        "governance_labels": GOVERNANCE_LABELS,
        "inclusion_status": "included_source_verified_subset" if not record.get("locked_restricted_involved") else "excluded_locked_or_restricted",
    }
    payload["audit_hash"] = _json_hash(payload)
    return payload


def _excluded_item(record: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "excluded_item_id": str(uuid4()),
        "source_record_id": record.get("targeted_source_completion_id") or record.get("source_validation_id"),
        "item_id": record.get("item_id"),
        "item_type": record.get("item_type"),
        "source_status": record.get("final_state") or record.get("source_status"),
        "reason": record.get("required_next_action") or "Unresolved source support; excluded from relied-upon draft work product.",
        "locked_restricted_involved": bool(record.get("locked_restricted_involved")),
        "counsel_review_required": True,
        "appendix_section": "Excluded / Unresolved Source Issues Appendix",
    }
    payload["audit_hash"] = _json_hash(payload)
    return payload


def _section(section_id: str, title: str, items: list[dict[str, Any]], notes: str) -> dict[str, Any]:
    payload = {
        "section_id": section_id,
        "title": title,
        "status": "DRAFT / COUNSEL REVIEW REQUIRED",
        "legal_advice_status": "NOT_FINAL_LEGAL_ADVICE",
        "external_use_status": "NOT_AUTHORIZED_FOR_FILING_SERVICE_SENDING_EMAIL_OR_EXTERNAL_SUBMISSION",
        "source_basis": "SOURCE_VERIFIED_SUBSET_ONLY",
        "item_count": len(items),
        "items": items,
        "notes": notes,
        "counsel_review_required": True,
    }
    payload["section_hash"] = _json_hash(payload)
    return payload


def _group_by_type(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[str(item.get("item_type") or "unknown")].append(item)
    return grouped


def create_draft_work_product_manifest(case_slug: str, execution_id: str) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("draft_work_product_scope_refused")
    limited = load_latest_limited_signoff_candidate(case_slug)
    targeted = load_latest_targeted_source_completion(case_slug)
    learning = load_latest_learning_loop(case_slug)
    if limited is None:
        raise FileNotFoundError("limited_signoff_candidate_missing")
    if targeted is None:
        raise FileNotFoundError("targeted_source_completion_missing")

    expanded = targeted.get("expanded_verified_subset", {})
    verified_source_records = (expanded.get("prior_items") or []) + (expanded.get("new_items") or [])
    included = [_safe_included_item(record) for record in verified_source_records if not record.get("locked_restricted_involved")]
    excluded = [_excluded_item(record) for record in targeted.get("refined_unresolved_register", [])]
    grouped = _group_by_type(included)
    type_counts = Counter(item["item_type"] for item in included)
    refs_total = sum(item["source_refs_count"] for item in included)

    facts = [
        {
            "fact_id": str(uuid4()),
            "fact_statement": item["corrected_claim_summary"],
            "source_refs": item["source_refs"],
            "source_status": item["source_status"],
            "item_id": item["item_id"],
            "item_type": item["item_type"],
            "counsel_review_required": True,
            "inclusion_status": item["inclusion_status"],
        }
        for item in included
    ]
    chronology = grouped.get("timeline_event", [])
    issues = grouped.get("issue_matrix", [])
    contradictions = grouped.get("contradiction_candidate", [])
    binders = grouped.get("evidence_binder", [])
    entities = grouped.get("entity_dossier", [])
    actions = grouped.get("action_item", []) + grouped.get("counsel_question", [])

    motion_status = "deferred_source_support_insufficient" if len(issues) < 3 else "draft_outline_available_for_counsel_review"
    sections = [
        _section("draft-internal-case-assessment-memo", "Draft Internal Case Assessment Memo", included[:12], "Executive assessment is limited to source-routed review-use items; counsel must review legal effect."),
        _section("draft-source-backed-statement-of-facts", "Draft Source-Backed Statement of Facts", facts, "Each fact is a concise metadata-backed draft statement tied to available source refs."),
        _section("draft-chronology-exhibit", "Draft Chronology Exhibit / Timeline Packet", chronology, "Unsupported or ambiguous chronology items remain excluded."),
        _section("draft-issue-analysis", "Draft Issue-by-Issue Analysis", issues, "Issue analysis is draft and does not state final legal conclusions."),
        _section("draft-evidence-binder-index", "Draft Evidence Binder Index", binders, "Binder index includes metadata and source routing only; no document body text."),
        _section("draft-contradiction-tension-memo", "Draft Contradiction / Tension Memo", contradictions, "No final contradiction findings are made."),
        _section("draft-case-theory", "Draft Case Theory Memo", included[:8], "Theory is hypothesis-labeled and source-limited."),
        _section("draft-counter-theory", "Draft Counter-Theory / Opposing Narrative Memo", included[:8], "Counter-theory is hypothesis-labeled and source-limited."),
        _section("draft-deposition-outline", "Draft Deposition / Examination Outline", chronology[:12] + contradictions[:8] + entities[:8], "Questions are for counsel review and source clarification only."),
        _section("draft-discovery-gap-plan", "Draft Discovery / Evidence Gap Plan", excluded[:40], "Unresolved blockers are prioritized for future source/counsel review."),
        _section("draft-motion-response-outline", "Draft Motion / Response Outline", issues[:6], f"Motion/response outline status: {motion_status}; no filing language generated."),
        _section("draft-counsel-action-plan", "Draft Counsel Questions / Action Plan", actions[:24] + excluded[:12], "Action plan preserves counsel signoff pending."),
        _section("excluded-unresolved-source-issues", "Excluded / Unresolved Source Issues Appendix", excluded, "Unresolved source issues are not relied on as facts."),
        _section("privilege-locked-handling", "Privilege / Locked Handling Appendix", [item for item in excluded if item["locked_restricted_involved"]], "Locked/restricted items remain metadata-only."),
        _section("draft-packet-source-map", "Draft Packet Manifest and Source Map", included, "Source map contains metadata references only, not excerpts."),
    ]
    payload = {
        "execution_id": execution_id,
        "created_at": now_iso(),
        "case_slug": case_slug,
        "status": "DRAFT_WORK_PRODUCT_READY_FOR_COUNSEL_REVIEW",
        "draft_packet_store": "file_manifest",
        "source_manifests": {
            "limited_signoff_candidate": limited.get("execution_id"),
            "targeted_source_completion": targeted.get("execution_id"),
            "autonomous_learning": learning.get("execution_id") if learning else None,
        },
        "source_basis": {
            "included_verified_item_count": len(included),
            "excluded_unresolved_item_count": len(excluded),
            "source_refs_total": refs_total,
            "item_type_counts": dict(type_counts),
            "locked_restricted_used_for_content": False,
        },
        "governance_labels": GOVERNANCE_LABELS,
        "draft_packet": {
            "packet_id": str(uuid4()),
            "sections_generated": len(sections),
            "sections": sections,
            "motion_response_outline_status": motion_status,
            "counsel_signoff_pending": True,
            "final_legal_conclusions_created": False,
            "external_submission_authorized": False,
        },
        "source_map": {
            "source_map_id": str(uuid4()),
            "included_item_ids": [item["item_id"] for item in included],
            "excluded_item_ids": [item["item_id"] for item in excluded],
            "source_ref_count": refs_total,
            "contains_document_body_text": False,
            "contains_locked_content": False,
        },
        "rollback": {
            "delete_manifest_path": str(draft_manifest_path(execution_id)),
            "draft_section_ids": [section["section_id"] for section in sections],
            "raw_documents_touched": False,
            "qdrant_vectors_touched": False,
            "schema_changed": False,
            "rls_policy_changed": False,
            "signoff_auto_created": False,
        },
        "mutation_invariants": {
            "new_raw_document_upload": False,
            "new_ingest": False,
            "new_document_rows": False,
            "new_qdrant_document_vectors": False,
            "schema_changes": False,
            "rls_policy_changes": False,
            "locked_content_analyzed": False,
            "signoff_auto_created": False,
            "explicit_signoff_recorded": False,
            "final_legal_conclusions_created": False,
            "external_submission_authorized": False,
        },
    }
    payload["manifest_checksum"] = _json_hash(payload)
    return payload


def write_draft_work_product_manifest(payload: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = draft_manifest_path(str(payload["execution_id"]))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _draft_manifests(case_slug: str) -> list[Path]:
    if not AUDIT_DIR.exists():
        return []
    candidates: list[Path] = []
    for path in AUDIT_DIR.glob(f"{DRAFT_WORK_PRODUCT_PREFIX}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("case_slug") == case_slug:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_draft_work_product(case_slug: str) -> dict[str, Any] | None:
    for path in _draft_manifests(case_slug):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(path)
        return payload
    return None
