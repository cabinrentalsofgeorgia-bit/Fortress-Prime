"""Source remediation maturity read model.

This service turns existing source-remediation artifacts into a governed,
summary-safe review queue. It does not inspect document body text, read locked
content, mutate schema/RLS, create vectors, resolve source issues, or record
signoff.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from backend.services.legal_counsel_validation import TARGET_SLUG
from backend.services.legal_limited_signoff_candidate_packet import (
    load_latest_limited_signoff_candidate,
)
from backend.services.legal_targeted_source_completion import (
    load_latest_targeted_source_completion,
)

ALLOWED_SLUG = TARGET_SLUG


def _priority_score(item: dict[str, Any]) -> int:
    tier = str(item.get("materiality_tier") or "")
    item_type = str(item.get("item_type") or "")
    locked = bool(item.get("locked_restricted_involved"))
    evidence_needed = bool(item.get("evidence_needed"))
    counsel = bool(item.get("counsel_review_required"))

    score = 0
    if "tier_1" in tier:
        score += 100
    elif "tier_2" in tier:
        score += 60
    else:
        score += 25

    if item_type in {"contradiction_candidate", "theory_packet", "issue_matrix"}:
        score += 25
    elif item_type in {"timeline_event", "evidence_binder"}:
        score += 12

    if evidence_needed:
        score += 10
    if counsel:
        score += 10
    if locked:
        score -= 20
    return score


def _confidence_state(item: dict[str, Any]) -> str:
    if item.get("locked_restricted_involved"):
        return "restricted_metadata_only"
    if item.get("evidence_needed"):
        return "source_missing"
    if item.get("counsel_review_required"):
        return "counsel_interpretation_required"
    return "unresolved_unsupported"


def _review_lane(item: dict[str, Any]) -> str:
    if item.get("locked_restricted_involved"):
        return "locked_restricted_no_content_review"
    item_type = str(item.get("item_type") or "")
    if item_type == "contradiction_candidate":
        return "contradiction_review"
    if item_type in {"issue_matrix", "theory_packet"}:
        return "high_materiality_source_review"
    if item.get("evidence_needed"):
        return "evidence_attachment_required"
    return "human_source_review"


def _safe_queue_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": item.get("item_id"),
        "item_type": item.get("item_type"),
        "materiality_tier": item.get("materiality_tier"),
        "blocker_type": item.get("blocker_type"),
        "source_status": item.get("source_status"),
        "confidence_state": _confidence_state(item),
        "review_lane": _review_lane(item),
        "priority_score": _priority_score(item),
        "counsel_review_required": bool(item.get("counsel_review_required")),
        "evidence_needed": bool(item.get("evidence_needed")),
        "locked_restricted_involved": bool(item.get("locked_restricted_involved")),
        "can_proceed_without_this_item": bool(item.get("can_proceed_without_this_item")),
        "signoff_impact": item.get("signoff_impact"),
        "required_next_action": item.get("required_next_action"),
    }


def _count_by(items: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    counts = Counter(str(item.get(field) or "unknown") for item in items)
    return [{"key": key, "count": counts[key]} for key in sorted(counts)]


def _lane_counts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(_review_lane(item) for item in items)
    return [{"lane": key, "count": counts[key]} for key in sorted(counts)]


def _confidence_counts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(_confidence_state(item) for item in items)
    return [{"state": key, "count": counts[key]} for key in sorted(counts)]


def build_remediation_maturity(case_slug: str) -> dict[str, Any] | None:
    if case_slug != ALLOWED_SLUG:
        raise ValueError("remediation_maturity_scope_refused")

    targeted = load_latest_targeted_source_completion(case_slug)
    limited = load_latest_limited_signoff_candidate(case_slug)
    if targeted is None or limited is None:
        return None

    unresolved = list(limited.get("unresolved_blocker_register_v2") or [])
    queue = [_safe_queue_item(item) for item in unresolved]
    queue.sort(key=lambda item: int(item["priority_score"]), reverse=True)

    locked_count = sum(1 for item in queue if item["locked_restricted_involved"])
    evidence_needed = sum(1 for item in queue if item["evidence_needed"])
    counsel_required = sum(1 for item in queue if item["counsel_review_required"])

    return {
        "case_slug": case_slug,
        "status": "SOURCE_REMEDIATION_MATURITY_READY_FOR_REVIEW",
        "source_manifests": {
            "targeted_source_completion_execution_id": targeted.get("execution_id"),
            "limited_signoff_candidate_execution_id": limited.get("execution_id"),
            "source_link_repair_execution_id": targeted.get("source_link_repair_execution_id"),
            "source_remediation_execution_id": targeted.get("source_remediation_execution_id"),
        },
        "governance": {
            "counsel_signoff": "COUNSEL_SIGNOFF_PENDING",
            "external_submission_authority": "NOT_AUTHORIZED",
            "final_legal_conclusions": "NOT_CREATED",
            "legal_advice_status": "NOT FINAL LEGAL ADVICE",
            "unresolved_items_excluded_from_relied_upon_sections": True,
            "locked_restricted_handling": "METADATA_ONLY",
            "auto_resolution": "DISABLED",
        },
        "remediation_summary": {
            "unresolved_total": len(queue),
            "unsupported_or_missing_source": max(len(queue) - locked_count, 0),
            "locked_restricted_no_review": locked_count,
            "evidence_needed": evidence_needed,
            "counsel_review_required": counsel_required,
            "verified_subset_count": targeted.get("completion_summary", {}).get("new_verified_subset_count", 0),
            "limited_packet_available": bool(
                limited.get("limited_signoff_candidate_packet", {}).get("included_item_count")
            ),
        },
        "classification_counts": {
            "by_item_type": _count_by(queue, "item_type"),
            "by_materiality_tier": _count_by(queue, "materiality_tier"),
            "by_confidence_state": _confidence_counts(unresolved),
            "by_review_lane": _lane_counts(unresolved),
        },
        "priority_model": {
            "name": "FORTRESS_SOURCE_REVIEW_PRIORITY_V1",
            "factors": [
                "materiality_tier",
                "item_type",
                "evidence_needed",
                "counsel_review_required",
                "locked_restricted_involved",
            ],
            "automation_boundary": "ranking_only_no_source_resolution",
        },
        "priority_queue": queue[:30],
        "review_workflows": [
            {
                "workflow": "human_source_review",
                "authority": "operator_or_counsel_review",
                "allowed_actions": ["attach_existing_source_reference", "exclude_from_relied_upon_sections", "return_for_revision"],
                "forbidden_actions": ["auto_signoff", "final_legal_conclusion", "locked_content_review"],
            },
            {
                "workflow": "locked_restricted_no_content_review",
                "authority": "counsel_only_metadata_review",
                "allowed_actions": ["preserve_metadata_only", "request_privilege_review"],
                "forbidden_actions": ["agent_content_access", "source_auto_resolution"],
            },
        ],
        "evidence_lineage": {
            "lineage_chain": [
                "source_integrity",
                "source_remediation",
                "source_link_repair",
                "targeted_source_completion",
                "limited_signoff_candidate_packet",
                "remediation_maturity_read_model",
            ],
            "mutation_model": "read_only_derived_view",
            "rollback_model": "git_revert_and_manifest_recheck",
            "silent_state_transitions_allowed": False,
        },
        "observability": {
            "metrics": [
                "unresolved_total",
                "review_lane_counts",
                "confidence_state_counts",
                "priority_queue_depth",
                "locked_restricted_count",
                "evidence_needed_count",
            ],
            "checker_assertions": [
                "remediation_maturity_visible",
                "review_confidence_visible",
                "evidence_lineage_visible",
                "unresolved_exclusion_visible",
            ],
        },
    }
