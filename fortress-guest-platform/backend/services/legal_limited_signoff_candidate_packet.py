"""Limited signoff candidate packet artifact store.

This phase turns the targeted-source verified subset into a counsel-review
candidate packet and tiers remaining source blockers. It uses only existing
derived manifest metadata. It does not read document body text, inspect locked
content, mutate schema/RLS, create vectors, or record signoff.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.legal_counsel_signoff_packet import (
    load_latest_signoff_packet,
    write_signoff_packet_manifest,
)
from backend.services.legal_counsel_validation import TARGET_SLUG, load_latest_validation
from backend.services.legal_counsel_workbench import AUDIT_DIR
from backend.services.legal_targeted_source_completion import load_latest_targeted_source_completion

LIMITED_SIGNOFF_PREFIX = "fortress-limited-signoff-candidate-"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def limited_signoff_candidate_manifest_path(execution_id: str) -> Path:
    return AUDIT_DIR / f"{execution_id}.json"


def _json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validation_map(validation: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not validation:
        return {}
    mapped: dict[str, dict[str, Any]] = {}
    for record in validation.get("records", []):
        validation_id = record.get("validation_id")
        if validation_id:
            mapped[str(validation_id)] = record
        item_id = record.get("item_id")
        if item_id:
            mapped.setdefault(str(item_id), record)
    return mapped


def _metadata_for(record: dict[str, Any], validations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return validations.get(str(record.get("source_validation_id"))) or validations.get(str(record.get("item_id"))) or {}


def _tier(record: dict[str, Any], meta: dict[str, Any]) -> str:
    item_type = str(record.get("item_type") or "")
    materiality = float(meta.get("materiality") or 0)
    if item_type in {"issue_matrix", "theory_packet", "contradiction_candidate"} or materiality >= 0.7:
        return "tier_1_high_materiality"
    if item_type in {"evidence_binder", "entity_dossier", "action_item", "counsel_question"}:
        return "tier_2_supporting_packet_gap"
    return "tier_3_low_materiality_or_optional"


def _outcome(record: dict[str, Any]) -> str:
    state = str(record.get("final_state") or "")
    item_type = str(record.get("item_type") or "")
    if state == "locked_or_privilege_limited" or record.get("locked_restricted_involved"):
        return "exclude_locked_or_privilege_limited"
    if item_type in {"theory_packet", "contradiction_candidate"}:
        return "exclude_pending_counsel_interpretation"
    if state == "unsupported":
        return "exclude_unsupported"
    if state == "needs_page_or_chunk_review":
        return "exclude_pending_source_fix"
    return "include_as_context_not_for_signoff"


def _blocker_type(record: dict[str, Any]) -> str:
    state = str(record.get("final_state") or "")
    if state == "locked_or_privilege_limited" or record.get("locked_restricted_involved"):
        return "locked_or_privilege_limited"
    if state == "unsupported":
        return "unsupported_source_gap"
    if state == "needs_page_or_chunk_review":
        return "page_or_chunk_review_needed"
    return state or "source_issue"


def _excluded_record(record: dict[str, Any], validations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    meta = _metadata_for(record, validations)
    tier = _tier(record, meta)
    outcome = _outcome(record)
    payload = {
        "limited_signoff_review_id": str(uuid4()),
        "source_record_id": record.get("targeted_source_completion_id"),
        "source_validation_id": record.get("source_validation_id"),
        "item_id": record.get("item_id"),
        "item_type": record.get("item_type"),
        "item_title": meta.get("item_title") or record.get("item_id"),
        "materiality": meta.get("materiality"),
        "confidence": meta.get("confidence_before") or meta.get("confidence"),
        "materiality_tier": tier,
        "blocker_type": _blocker_type(record),
        "source_status": record.get("final_state"),
        "candidate_outcome": outcome,
        "reason_excluded": "Unresolved source support prevents inclusion in limited signoff candidate packet.",
        "required_next_action": record.get("required_next_action"),
        "owner_placeholder": "counsel_or_operator_source_review",
        "counsel_review_required": True,
        "evidence_needed": outcome in {"exclude_unsupported", "exclude_pending_source_fix"},
        "can_proceed_without_this_item": tier != "tier_1_high_materiality",
        "signoff_impact": "blocks_full_packet_signoff" if tier == "tier_1_high_materiality" else "excluded_from_limited_subset",
        "locked_restricted_involved": bool(record.get("locked_restricted_involved")),
    }
    payload["audit_hash"] = _json_hash(payload)
    return payload


def _included_record(record: dict[str, Any]) -> dict[str, Any]:
    source_record_id = record.get("targeted_source_completion_id") or record.get("source_link_repair_id")
    payload = {
        "limited_signoff_item_id": str(uuid4()),
        "source_record_id": source_record_id,
        "item_id": record.get("item_id"),
        "item_type": record.get("item_type"),
        "source_status": record.get("final_state") or record.get("final_remediation_state"),
        "candidate_outcome": "include_in_limited_signoff_candidate",
        "source_refs_count": len(record.get("source_refs_after") or []),
        "counsel_review_required": True,
        "signoff_status": "COUNSEL_SIGNOFF_PENDING",
        "legal_conclusion_status": "NOT_FINAL_LEGAL_CONCLUSION",
        "locked_restricted_involved": bool(record.get("locked_restricted_involved")),
        "safe_note": "Included only as source-routed review-use candidate; counsel signoff remains pending.",
    }
    payload["audit_hash"] = _json_hash(payload)
    return payload


def _tier_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    tiers = Counter(record["materiality_tier"] for record in records)
    outcomes = Counter(record["candidate_outcome"] for record in records)
    blockers = Counter(record["blocker_type"] for record in records)
    return {
        "tier_1_count": tiers.get("tier_1_high_materiality", 0),
        "tier_2_count": tiers.get("tier_2_supporting_packet_gap", 0),
        "tier_3_count": tiers.get("tier_3_low_materiality_or_optional", 0),
        "excluded_from_packet": len(records),
        "requires_counsel_interpretation": outcomes.get("exclude_pending_counsel_interpretation", 0),
        "requires_more_evidence": outcomes.get("exclude_unsupported", 0) + outcomes.get("exclude_pending_source_fix", 0),
        "locked_privilege_limited": blockers.get("locked_or_privilege_limited", 0),
        "unsupported": blockers.get("unsupported_source_gap", 0),
        "hypothesis_context_only": outcomes.get("include_as_hypothesis_only", 0) + outcomes.get("include_as_context_not_for_signoff", 0),
    }


def _section_summary(included: list[dict[str, Any]], excluded: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: {"included": 0, "excluded": 0})
    for record in included:
        grouped[str(record.get("item_type"))]["included"] += 1
    for record in excluded:
        grouped[str(record.get("item_type"))]["excluded"] += 1
    return [
        {"item_type": item_type, **counts}
        for item_type, counts in sorted(grouped.items())
    ]


def create_limited_signoff_candidate_manifest(case_slug: str, execution_id: str) -> dict[str, Any]:
    if case_slug != TARGET_SLUG:
        raise ValueError("limited_signoff_candidate_scope_refused")
    targeted = load_latest_targeted_source_completion(case_slug)
    signoff = load_latest_signoff_packet(case_slug)
    validation = load_latest_validation(case_slug)
    if targeted is None:
        raise FileNotFoundError("targeted_source_completion_missing")
    if signoff is None:
        raise FileNotFoundError("signoff_packet_missing")

    validations = _validation_map(validation)
    prior_items = targeted.get("expanded_verified_subset", {}).get("prior_items", []) or []
    new_items = targeted.get("expanded_verified_subset", {}).get("new_items", []) or []
    included = [_included_record(record) for record in prior_items + new_items]
    excluded = [_excluded_record(record, validations) for record in targeted.get("refined_unresolved_register", [])]
    tier_summary = _tier_summary(excluded)
    packet_sections = [
        {
            "section_id": "scope-and-caveats",
            "title": "Scope and Caveats",
            "item_count": 1,
            "counsel_review_required": True,
            "signoff_status": "COUNSEL_SIGNOFF_PENDING",
        },
        {
            "section_id": "included-verified-items",
            "title": "Included Verified Items",
            "item_count": len(included),
            "counsel_review_required": True,
            "signoff_status": "COUNSEL_SIGNOFF_PENDING",
        },
        {
            "section_id": "excluded-unresolved-items",
            "title": "Excluded Unresolved Items",
            "item_count": len(excluded),
            "counsel_review_required": True,
            "signoff_status": "COUNSEL_SIGNOFF_PENDING",
        },
        {
            "section_id": "signoff-readiness-recommendation",
            "title": "Signoff Readiness Recommendation",
            "item_count": 1,
            "counsel_review_required": True,
            "signoff_status": "COUNSEL_SIGNOFF_PENDING",
        },
    ]
    payload = {
        "execution_id": execution_id,
        "created_at": now_iso(),
        "case_slug": case_slug,
        "targeted_source_completion_execution_id": targeted.get("execution_id"),
        "source_link_repair_execution_id": targeted.get("source_link_repair_execution_id"),
        "signoff_packet_execution_id": signoff.get("execution_id"),
        "status": "LIMITED_SIGNOFF_CANDIDATE_PACKET_READY",
        "packet_label": "LIMITED_SIGNOFF_CANDIDATE_PACKET",
        "governance_labels": [
            "COUNSEL_REVIEW_REQUIRED",
            "COUNSEL_SIGNOFF_PENDING",
            "NOT_FINAL_LEGAL_CONCLUSION",
        ],
        "packet_store": "file_manifest",
        "verified_subset_used": {
            "item_count": len(included),
            "source": targeted.get("expanded_verified_subset", {}).get("verified_subset_id"),
        },
        "high_materiality_source_review": {
            "items_reviewed": tier_summary["tier_1_count"],
            "items": [record for record in excluded if record["materiality_tier"] == "tier_1_high_materiality"],
        },
        "limited_signoff_candidate_packet": {
            "candidate_packet_id": str(uuid4()),
            "included_item_count": len(included),
            "excluded_item_count": len(excluded),
            "included_items": included,
            "packet_sections": packet_sections,
            "section_summary": _section_summary(included, excluded),
            "signoff_scope_recommendation": "LIMITED_SIGNOFF_CANDIDATE_PACKET_READY_FOR_COUNSEL_REVIEW",
            "counsel_signoff_pending": True,
            "explicit_signoff_recorded": False,
        },
        "unresolved_blocker_register_v2": excluded,
        "tier_summary": tier_summary,
        "signoff_readiness_addendum": {
            "limited_signoff_candidate_execution_id": execution_id,
            "limited_packet_available": len(included) > 0,
            "full_packet_ready": False,
            "remaining_unresolved": len(excluded),
            "readiness_recommendation": "LIMITED_SIGNOFF_CANDIDATE_PACKET_READY_FOR_COUNSEL_REVIEW",
            "counsel_signoff_pending": True,
            "explicit_signoff_recorded": False,
        },
        "rollback": {
            "delete_manifest_path": str(limited_signoff_candidate_manifest_path(execution_id)),
            "limited_signoff_item_ids": [record["limited_signoff_item_id"] for record in included],
            "excluded_register_ids": [record["limited_signoff_review_id"] for record in excluded],
            "signoff_packet_addendum_target": signoff.get("execution_id"),
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
        },
    }
    payload["manifest_checksum"] = _json_hash(payload)
    return payload


def write_limited_signoff_candidate_manifest(payload: dict[str, Any]) -> Path:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path = limited_signoff_candidate_manifest_path(str(payload["execution_id"]))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def apply_limited_signoff_candidate_addendum(payload: dict[str, Any]) -> dict[str, Any]:
    signoff = load_latest_signoff_packet(str(payload["case_slug"]))
    if signoff is None:
        raise FileNotFoundError("signoff_packet_missing")
    signoff["limited_signoff_candidate_addendum"] = {
        "limited_signoff_candidate_execution_id": payload["execution_id"],
        "status": payload["status"],
        "included_item_count": payload["limited_signoff_candidate_packet"]["included_item_count"],
        "excluded_item_count": payload["limited_signoff_candidate_packet"]["excluded_item_count"],
        "tier_summary": payload["tier_summary"],
        "readiness_recommendation": payload["signoff_readiness_addendum"]["readiness_recommendation"],
        "manifest_path": str(limited_signoff_candidate_manifest_path(str(payload["execution_id"]))),
        "updated_at": now_iso(),
    }
    signoff["readiness_status"] = payload["signoff_readiness_addendum"]["readiness_recommendation"]
    signoff["signoff_status"] = "COUNSEL_SIGNOFF_PENDING"
    signoff.setdefault("audit_history", []).append(
        {
            "audit_id": str(uuid4()),
            "action": "limited_signoff_candidate_addendum_attached",
            "created_at": now_iso(),
            "reviewer_identity_safe_label": "system:limited-signoff-candidate",
            "reviewer_role": "system",
            "limited_signoff_candidate_execution_id": payload["execution_id"],
            "audit_hash": _json_hash({"action": "limited_signoff_candidate_addendum_attached", "execution_id": payload["execution_id"]}),
        }
    )
    signoff["packet_checksum"] = _json_hash({k: v for k, v in signoff.items() if k != "packet_checksum"})
    write_signoff_packet_manifest(signoff)
    return signoff


def _candidate_manifests(case_slug: str) -> list[Path]:
    if not AUDIT_DIR.exists():
        return []
    candidates: list[Path] = []
    for path in AUDIT_DIR.glob(f"{LIMITED_SIGNOFF_PREFIX}*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if payload.get("case_slug") == case_slug:
            candidates.append(path)
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def load_latest_limited_signoff_candidate(case_slug: str) -> dict[str, Any] | None:
    for path in _candidate_manifests(case_slug):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["manifest_path"] = str(path)
        return payload
    return None
