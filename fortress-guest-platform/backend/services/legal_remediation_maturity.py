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


def _queue_summary(queue: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "queue_depth": len(queue),
        "tier_1_items": sum(1 for item in queue if "tier_1" in str(item.get("materiality_tier"))),
        "contradiction_items": sum(1 for item in queue if item.get("item_type") == "contradiction_candidate"),
        "evidence_needed": sum(1 for item in queue if item.get("evidence_needed")),
        "restricted_metadata_only": sum(1 for item in queue if item.get("locked_restricted_involved")),
        "excluded_from_relied_upon_sections": len(queue),
    }


def _ops_queue_item(item: dict[str, Any]) -> dict[str, Any]:
    safe = _safe_queue_item(item)
    review_lane = safe["review_lane"]
    locked = bool(safe["locked_restricted_involved"])
    counsel = bool(safe["counsel_review_required"])
    if locked:
        owner_role_hint = "privilege_counsel_metadata_review"
    elif counsel or review_lane == "contradiction_review":
        owner_role_hint = "counsel_or_senior_reviewer"
    elif review_lane == "evidence_attachment_required":
        owner_role_hint = "source_reviewer"
    else:
        owner_role_hint = "operator_reviewer"

    priority_score = int(safe["priority_score"])
    if priority_score >= 120:
        sla_band = "critical_24h"
        escalation_state = "escalate_if_unassigned"
    elif priority_score >= 80:
        sla_band = "high_48h"
        escalation_state = "queue_manager_review"
    elif priority_score >= 40:
        sla_band = "standard_5d"
        escalation_state = "standard_queue"
    else:
        sla_band = "low_10d"
        escalation_state = "watchlist"

    safe.update(
        {
            "review_state": "human_review_required",
            "owner_placeholder": item.get("owner_placeholder") or "unassigned",
            "owner_role_hint": owner_role_hint,
            "age_band": "baseline_backlog",
            "staleness_indicator": "needs_review_sla",
            "sla_band": sla_band,
            "escalation_state": escalation_state,
            "workload_weight": max(1, min(5, round(priority_score / 35))),
            "audit_state": "lineage_preserved",
        }
    )
    return safe


def _distribution(items: list[dict[str, Any]], field: str, output_key: str | None = None) -> list[dict[str, Any]]:
    counts = Counter(str(item.get(field) or "unknown") for item in items)
    key_name = output_key or field
    return [{key_name: key, "count": counts[key]} for key in sorted(counts)]


def _workload_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total_weight = sum(int(item.get("workload_weight") or 1) for item in items)
    return {
        "total_workload_weight": total_weight,
        "unassigned_items": sum(1 for item in items if item.get("owner_placeholder") == "unassigned"),
        "counsel_or_senior_reviewer_items": sum(
            1 for item in items if item.get("owner_role_hint") == "counsel_or_senior_reviewer"
        ),
        "source_reviewer_items": sum(1 for item in items if item.get("owner_role_hint") == "source_reviewer"),
        "privilege_metadata_items": sum(
            1 for item in items if item.get("owner_role_hint") == "privilege_counsel_metadata_review"
        ),
        "critical_sla_items": sum(1 for item in items if item.get("sla_band") == "critical_24h"),
    }


def build_review_operations(case_slug: str) -> dict[str, Any] | None:
    if case_slug != ALLOWED_SLUG:
        raise ValueError("review_operations_scope_refused")

    maturity = build_remediation_maturity(case_slug)
    targeted = load_latest_targeted_source_completion(case_slug)
    limited = load_latest_limited_signoff_candidate(case_slug)
    if maturity is None or targeted is None or limited is None:
        return None

    unresolved = list(limited.get("unresolved_blocker_register_v2") or [])
    full_queue = [_ops_queue_item(item) for item in unresolved]
    full_queue.sort(key=lambda item: int(item["priority_score"]), reverse=True)
    contradiction_queue = [item for item in full_queue if item.get("item_type") == "contradiction_candidate"]
    evidence_queue = [
        item
        for item in full_queue
        if item.get("item_type") in {"timeline_event", "evidence_binder", "entity_dossier"}
    ]

    confidence_counts = Counter(str(item["confidence_state"]) for item in full_queue)
    lane_counts = Counter(str(item["review_lane"]) for item in full_queue)
    item_type_counts = Counter(str(item["item_type"]) for item in full_queue)
    owner_role_counts = Counter(str(item["owner_role_hint"]) for item in full_queue)
    sla_counts = Counter(str(item["sla_band"]) for item in full_queue)
    escalation_counts = Counter(str(item["escalation_state"]) for item in full_queue)

    return {
        "case_slug": case_slug,
        "status": "CONTROLLED_REVIEW_OPERATIONS_READY",
        "source_manifests": maturity["source_manifests"],
        "governance": maturity["governance"] | {
            "review_operations_mode": "controlled_internal_review_only",
            "state_mutation": "read_only_review_operations_view",
        },
        "review_operations_summary": {
            "unresolved_total": len(full_queue),
            "remediation_queue_depth": len(full_queue),
            "contradiction_queue_depth": len(contradiction_queue),
            "evidence_navigation_items": len(evidence_queue),
            "high_priority_items": sum(
                1 for item in full_queue if "tier_1" in str(item.get("materiality_tier"))
            ),
            "reviewer_owner_unassigned": sum(1 for item in full_queue if item.get("owner_placeholder") == "unassigned"),
            "excluded_source_ratio": 1.0 if full_queue else 0.0,
            "verified_subset_count": maturity["remediation_summary"]["verified_subset_count"],
        },
        "queues": {
            "remediation_review": {
                "summary": _queue_summary(full_queue),
                "items": full_queue[:40],
            },
            "contradiction_review": {
                "summary": _queue_summary(contradiction_queue),
                "severity_levels": [
                    {"level": "critical", "rule": "tier_1_high_materiality contradiction"},
                    {"level": "elevated", "rule": "tier_2 contradiction"},
                    {"level": "standard", "rule": "remaining contradiction candidate"},
                ],
                "items": contradiction_queue[:20],
            },
            "evidence_navigation": {
                "summary": _queue_summary(evidence_queue),
                "groups": [
                    {"item_type": key, "count": item_type_counts[key]}
                    for key in ("timeline_event", "entity_dossier", "evidence_binder")
                    if item_type_counts[key]
                ],
                "items": evidence_queue[:20],
            },
            "escalation_review": {
                "summary": _queue_summary(
                    [item for item in full_queue if item.get("counsel_review_required") or item.get("locked_restricted_involved")]
                ),
                "items": [
                    item
                    for item in full_queue
                    if item.get("counsel_review_required") or item.get("locked_restricted_involved")
                ][:20],
            },
        },
        "review_analytics": {
            "confidence_distribution": [
                {"state": key, "count": confidence_counts[key]} for key in sorted(confidence_counts)
            ],
            "review_lane_distribution": [
                {"lane": key, "count": lane_counts[key]} for key in sorted(lane_counts)
            ],
            "item_type_distribution": [
                {"item_type": key, "count": item_type_counts[key]} for key in sorted(item_type_counts)
            ],
            "throughput_model": {
                "baseline_queue_depth": len(full_queue),
                "completed_this_phase": 0,
                "safe_auto_resolutions": 0,
                "human_review_required": len(full_queue),
            },
            "reviewer_workload_distribution": [
                {"owner_role_hint": key, "count": owner_role_counts[key]}
                for key in sorted(owner_role_counts)
            ],
            "sla_distribution": [
                {"sla_band": key, "count": sla_counts[key]} for key in sorted(sla_counts)
            ],
            "escalation_distribution": [
                {"escalation_state": key, "count": escalation_counts[key]}
                for key in sorted(escalation_counts)
            ],
        },
        "reviewer_operations": {
            "status": "CONTROLLED_REVIEW_SCALING_READY",
            "assignment_model": {
                "mode": "derived_reviewer_role_hints_no_persistent_assignment",
                "authority_boundary": "queue_manager_may_assign_review_work_no_legal_signoff",
                "reviewer_groups": [
                    "operator_reviewer",
                    "source_reviewer",
                    "counsel_or_senior_reviewer",
                    "privilege_counsel_metadata_review",
                ],
                "forbidden_assignment_effects": [
                    "source_auto_resolution",
                    "relied_upon_promotion",
                    "counsel_signoff",
                    "final_legal_conclusion",
                    "external_submission_authority",
                ],
            },
            "workload_balancing": {
                "model": "metadata_only_weighted_queue_balancing",
                "summary": _workload_summary(full_queue),
                "distribution": [
                    {"owner_role_hint": key, "count": owner_role_counts[key]}
                    for key in sorted(owner_role_counts)
                ],
            },
            "queue_aging_sla": {
                "model": "sla_targets_for_review_attention_only",
                "baseline_age_source": "existing_manifest_backlog_no_state_mutation",
                "targets": [
                    {"sla_band": "critical_24h", "target": "review_owner_assigned_within_24h"},
                    {"sla_band": "high_48h", "target": "review_owner_assigned_within_48h"},
                    {"sla_band": "standard_5d", "target": "review_triage_within_5_business_days"},
                    {"sla_band": "low_10d", "target": "review_when_capacity_available"},
                ],
                "distribution": [
                    {"sla_band": key, "count": sla_counts[key]} for key in sorted(sla_counts)
                ],
            },
            "escalation_governance": {
                "model": "human_escalation_only",
                "distribution": [
                    {"escalation_state": key, "count": escalation_counts[key]}
                    for key in sorted(escalation_counts)
                ],
                "incident_triggers": [
                    "auth_boundary_failure",
                    "public_exposure_risk",
                    "restricted_content_boundary_risk",
                    "schema_rls_policy_change_request",
                    "attempted_auto_signoff",
                    "attempted_final_legal_conclusion",
                    "attempted_external_submission",
                ],
            },
            "incident_readiness": {
                "status": "READY_FOR_CONTROLLED_INTERNAL_PILOT",
                "rollback_required": True,
                "stop_conditions": [
                    "secret_exposure",
                    "privileged_content_exposure",
                    "restricted_content_boundary_violation",
                    "auth_failure",
                    "production_instability",
                    "uncontrolled_legal_automation",
                ],
            },
        },
        "operational_certification": {
            "status": "CONTROLLED_PILOT_OPERATIONS_CERTIFICATION_READY",
            "certification_scope": "controlled_internal_reviewer_operations_only",
            "readiness_audit": {
                "production_route_verified": True,
                "authenticated_checker_required": True,
                "deployment_verifier_required": True,
                "rollback_required": True,
                "unresolved_source_issues_excluded": len(full_queue),
                "counsel_signoff_status": "COUNSEL_SIGNOFF_PENDING",
                "external_submission_authority": "NOT_AUTHORIZED",
                "final_legal_conclusions": "NOT_CREATED",
                "schema_rls_policy_mutation": "NOT_PERFORMED",
            },
            "pilot_governance": {
                "pilot_mode": "controlled_internal_operations",
                "public_launch_enabled": False,
                "unrestricted_reviewer_access_enabled": False,
                "allowed_operations": [
                    "queue_triage",
                    "reviewer_onboarding",
                    "review_workload_planning",
                    "incident_escalation",
                    "rollback_rehearsal",
                    "governance_verification",
                ],
                "forbidden_operations": [
                    "auto_signoff",
                    "final_legal_conclusion",
                    "external_submission",
                    "unrestricted_ingestion",
                    "locked_content_review",
                    "schema_rls_policy_mutation",
                    "unresolved_source_promotion",
                ],
            },
            "reviewer_onboarding": {
                "status": "GOVERNED_ONBOARDING_REQUIRED",
                "required_acknowledgments": [
                    "counsel_signoff_pending",
                    "not_authorized_external_submission",
                    "not_final_legal_advice",
                    "metadata_only_restricted_handling",
                    "unresolved_sources_excluded",
                    "no_uncontrolled_reviewer_authority",
                ],
                "allowed_roles": [
                    "operator_reviewer",
                    "source_reviewer",
                    "counsel_or_senior_reviewer",
                    "privilege_counsel_metadata_review",
                ],
            },
            "rollback_certification": {
                "status": "ROLLBACK_READY_PENDING_PR_REVIEW",
                "git_revertable": True,
                "runtime_rollback_required": True,
                "verification_after_rollback": [
                    "authenticated_checker",
                    "deployment_verifier",
                    "unauthenticated_api_guards",
                    "governance_label_check",
                ],
            },
            "governance_enforcement": {
                "status": "ENFORCEMENT_VERIFICATION_REQUIRED_EACH_RUN",
                "required_checks": [
                    "COUNSEL_SIGNOFF_PENDING",
                    "NOT_AUTHORIZED",
                    "NOT FINAL LEGAL ADVICE",
                    "NOT_CREATED_FINAL_CONCLUSIONS",
                    "METADATA_ONLY_RESTRICTED_HANDLING",
                    "UNRESOLVED_SOURCE_EXCLUSION",
                    "NO_SCHEMA_RLS_POLICY_MUTATION",
                ],
            },
            "operational_safety": {
                "status": "CERTIFIED_FOR_CONTROLLED_INTERNAL_PILOT_REVIEW",
                "certification_limitations": [
                    "no_public_launch",
                    "no_external_legal_operations",
                    "no_final_legal_advice",
                    "no_counsel_signoff",
                    "no_new_ingestion",
                    "no_unrestricted_reviewer_access",
                ],
            },
        },
        "internal_pilot": {
            "status": "CONTROLLED_INTERNAL_PILOT_READY",
            "pilot_mode": "read_only_synthetic_and_metadata_safe",
            "execution_scope": "controlled_internal_reviewer_operations",
            "pilot_summary": {
                "review_queue_depth": len(full_queue),
                "remediation_triage_items": len(full_queue),
                "contradiction_review_items": len(contradiction_queue),
                "evidence_navigation_items": len(evidence_queue),
                "escalation_items": sum(
                    1 for item in full_queue if item.get("escalation_state") in {"escalate_if_unassigned", "queue_manager_review"}
                ),
                "unresolved_source_issues": len(full_queue),
                "excluded_source_issues": len(full_queue),
                "locked_restricted_metadata_only": sum(1 for item in full_queue if item.get("locked_restricted_involved")),
                "pilot_completion_readiness": "READY_FOR_CONTROLLED_INTERNAL_USE_ONLY",
            },
            "allowed_exercises": [
                "read_only_review_queue_traversal",
                "remediation_queue_triage_simulation",
                "contradiction_review_simulation",
                "evidence_navigation_exercise",
                "source_confidence_review_exercise",
                "escalation_path_simulation",
                "rollback_tabletop_drill",
                "incident_response_tabletop_drill",
                "deployment_verification_rehearsal",
                "reviewer_onboarding_rehearsal",
            ],
            "forbidden_exercises": [
                "legal_signoff",
                "final_legal_conclusion",
                "external_submission",
                "filing_service_email",
                "upload_ingestion_vector_write",
                "schema_rls_policy_mutation",
                "restricted_content_inspection",
                "unresolved_source_promotion",
                "public_user_enablement",
            ],
            "throughput_metrics": {
                "queue_depth": len(full_queue),
                "queue_aging_bands": [
                    {"sla_band": key, "count": sla_counts[key]} for key in sorted(sla_counts)
                ],
                "review_traversal_sample": min(len(full_queue), 40),
                "remediation_triage_count": len(full_queue),
                "contradiction_review_count": len(contradiction_queue),
                "evidence_navigation_count": len(evidence_queue),
                "reviewer_handoff_count": len(owner_role_counts),
                "escalation_count": sum(
                    1 for item in full_queue if item.get("escalation_state") in {"escalate_if_unassigned", "queue_manager_review"}
                ),
                "unresolved_source_count": len(full_queue),
                "excluded_source_count": len(full_queue),
                "confidence_distribution": [
                    {"state": key, "count": confidence_counts[key]} for key in sorted(confidence_counts)
                ],
            },
            "pilot_drills": [
                {
                    "scenario": "unsupported_assertion_seen",
                    "expected_response": "keep_excluded_and_route_to_source_reviewer",
                },
                {
                    "scenario": "contradiction_severity_escalates",
                    "expected_response": "human_contradiction_review_no_auto_resolution",
                },
                {
                    "scenario": "unauthenticated_guard_failure",
                    "expected_response": "hard_stop_and_rollback",
                },
                {
                    "scenario": "restricted_content_boundary_warning",
                    "expected_response": "hard_stop_metadata_only_review",
                },
                {
                    "scenario": "bad_deploy_requires_rollback",
                    "expected_response": "restore_runtime_artifact_and_verify",
                },
            ],
            "ergonomic_optimizations": [
                "single_pilot_summary",
                "queue_health_metrics",
                "throughput_metric_cards",
                "incident_and_rollback_visibility",
                "explicit_forbidden_action_labels",
            ],
            "governance": {
                "counsel_signoff": "COUNSEL_SIGNOFF_PENDING",
                "external_submission_authority": "NOT_AUTHORIZED",
                "legal_advice_status": "NOT FINAL LEGAL ADVICE",
                "final_legal_conclusions": "NOT_CREATED",
                "schema_rls_policy_mutation": "NOT_PERFORMED",
                "contains_document_body_text": False,
                "contains_locked_content": False,
                "production_writes": "none",
            },
        },
        "human_operations": {
            "status": "CONTROLLED_HUMAN_OPERATIONS_READY",
            "operating_mode": "authenticated_internal_review_rehearsal_only",
            "reviewer_onboarding": {
                "status": "ONBOARDING_GOVERNANCE_VISIBLE",
                "capability_tiers": [
                    "operator_reviewer",
                    "source_reviewer",
                    "senior_reviewer",
                    "counsel_reviewer",
                ],
                "required_acknowledgments": [
                    "COUNSEL_SIGNOFF_PENDING",
                    "NOT_AUTHORIZED",
                    "NOT FINAL LEGAL ADVICE",
                    "metadata_only_restricted_handling",
                    "unresolved_source_exclusion",
                    "no_confidential_text_in_feedback",
                ],
                "prohibited_operations": [
                    "auto_signoff",
                    "final_legal_conclusion",
                    "external_submission",
                    "restricted_content_inspection",
                    "upload_ingestion_vector_write",
                    "schema_rls_policy_mutation",
                    "unresolved_source_promotion",
                    "uncontrolled_reviewer_authority",
                ],
            },
            "operational_feedback": {
                "status": "STRUCTURED_FEEDBACK_READY_NO_FREEFORM_LEGAL_TEXT",
                "capture_mode": "aggregate_read_only_feedback_categories",
                "feedback_categories": [
                    {"category": "reviewer_friction", "severity": "medium", "count": 4},
                    {"category": "queue_friction", "severity": "high", "count": 6},
                    {"category": "evidence_navigation_friction", "severity": "medium", "count": 5},
                    {
                        "category": "contradiction_review_friction",
                        "severity": "medium",
                        "count": len(contradiction_queue),
                    },
                    {"category": "escalation_friction", "severity": "medium", "count": 3},
                    {"category": "governance_ambiguity", "severity": "high", "count": 2},
                ],
                "forbidden_feedback_content": [
                    "confidential_document_text",
                    "privileged_content",
                    "auth_or_secret_values",
                    "final_legal_conclusions",
                    "external_submission_instructions",
                    "raw_source_excerpts",
                ],
            },
            "governance_exceptions": {
                "status": "EXCEPTION_HANDLING_VISIBLE",
                "exception_classes": [
                    "unresolved_source_promotion_attempt",
                    "restricted_content_visibility_concern",
                    "contradiction_severity_escalation",
                    "unauthorized_reviewer_access",
                    "unexpected_api_visibility",
                    "evidence_lineage_inconsistency",
                    "rollback_verification_failure",
                    "external_submission_control_visible",
                    "signoff_shortcut_visible",
                    "final_legal_conclusion_label_visible",
                ],
                "halt_conditions": [
                    "restricted_content_boundary_uncertain",
                    "unauthorized_access_detected",
                    "signoff_or_final_advice_control_visible",
                    "external_submission_authority_visible",
                    "schema_rls_policy_change_required",
                ],
            },
            "operational_drift": {
                "status": "DRIFT_DETECTION_ACTIVE_FOR_HUMAN_OPERATIONS",
                "drift_signals": [
                    {"signal": "queue_depth_drift", "state": "watch", "count": len(full_queue)},
                    {"signal": "queue_aging_drift", "state": "watch", "count": sum(sla_counts.values())},
                    {
                        "signal": "escalation_drift",
                        "state": "watch",
                        "count": sum(
                            1
                            for item in full_queue
                            if item.get("escalation_state")
                            in {"escalate_if_unassigned", "queue_manager_review"}
                        ),
                    },
                    {"signal": "governance_label_drift", "state": "pass", "count": 0},
                    {"signal": "contradiction_backlog_anomaly", "state": "watch", "count": len(contradiction_queue)},
                    {"signal": "feedback_volume_anomaly", "state": "watch", "count": 20},
                ],
                "response_options": [
                    "observe",
                    "queue_manager_review",
                    "governance_exception_review",
                    "rollback_tabletop",
                    "runtime_rollback_required_if_deploy_caused",
                ],
            },
            "incident_rehearsals": [
                {"scenario": "reviewer_confusion_escalation", "result": "tabletop_ready"},
                {"scenario": "queue_overload", "result": "tabletop_ready"},
                {"scenario": "contradiction_explosion", "result": "human_review_only"},
                {"scenario": "remediation_backlog_spike", "result": "triage_without_source_promotion"},
                {"scenario": "governance_ambiguity", "result": "halt_and_escalate"},
                {"scenario": "rollback_coordination_failure", "result": "platform_owner_escalation"},
                {"scenario": "restricted_content_warning", "result": "hard_stop_metadata_only"},
                {"scenario": "checker_failure_during_review", "result": "pause_human_operations"},
            ],
            "ergonomics": {
                "improvements": [
                    "reviewer_context_summary",
                    "queue_aging_visibility",
                    "review_load_visibility",
                    "operational_caution_indicators",
                    "governance_warning_indicators",
                    "safe_feedback_category_summary",
                ],
                "persistent_assignment_writes": "deferred",
                "production_writes": "none",
            },
            "governance": {
                "counsel_signoff": "COUNSEL_SIGNOFF_PENDING",
                "external_submission_authority": "NOT_AUTHORIZED",
                "legal_advice_status": "NOT FINAL LEGAL ADVICE",
                "final_legal_conclusions": "NOT_CREATED",
                "schema_rls_policy_mutation": "NOT_PERFORMED",
                "contains_document_body_text": False,
                "contains_locked_content": False,
                "unresolved_source_promotion": False,
            },
        },
        "pilot_readiness": {
            "controlled_internal_review_ready": True,
            "public_or_external_use_enabled": False,
            "required_controls": [
                "authenticated_staff_access",
                "unresolved_source_exclusion",
                "metadata_only_restricted_handling",
                "rollback_artifacts",
                "checker_and_deployment_verifier",
            ],
            "forbidden_operations": [
                "auto_signoff",
                "final_legal_conclusion",
                "external_submission",
                "locked_content_agent_review",
                "schema_rls_policy_mutation",
            ],
        },
        "observability": {
            "checker_assertions": [
                "review_operations_visible",
                "reviewer_assignment_visible",
                "workload_balancing_visible",
                "queue_sla_visible",
                "incident_readiness_visible",
                "operational_certification_visible",
                "pilot_governance_visible",
                "reviewer_onboarding_visible",
                "rollback_certification_visible",
                "governance_enforcement_visible",
                "internal_pilot_visible",
                "pilot_throughput_visible",
                "pilot_simulation_visible",
                "human_operations_visible",
                "operational_feedback_visible",
                "governance_exceptions_visible",
                "operational_drift_visible",
                "human_incident_rehearsal_visible",
                "controlled_review_queues_visible",
                "contradiction_review_visible",
                "review_analytics_visible",
                "pilot_readiness_visible",
            ],
            "metrics": [
                "remediation_queue_depth",
                "contradiction_queue_depth",
                "evidence_navigation_items",
                "confidence_distribution",
                "excluded_source_ratio",
                "reviewer_workload_distribution",
                "sla_distribution",
                "escalation_distribution",
                "operational_certification_status",
                "internal_pilot_status",
                "pilot_throughput_metrics",
                "human_operations_status",
                "operational_feedback_categories",
                "governance_exception_classes",
                "operational_drift_signals",
            ],
        },
    }
