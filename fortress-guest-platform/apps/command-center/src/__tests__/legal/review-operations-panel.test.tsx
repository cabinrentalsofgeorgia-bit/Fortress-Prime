import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useReviewOperations: () => ({
    isLoading: false,
    error: null,
    data: {
      case_slug: "fortress-legal-production-review",
      status: "CONTROLLED_REVIEW_OPERATIONS_READY",
      source_manifests: {
        targeted_source_completion_execution_id: "fortress-targeted-source-completion-test",
        limited_signoff_candidate_execution_id: "fortress-limited-signoff-candidate-test",
        source_link_repair_execution_id: "fortress-source-link-repair-test",
        source_remediation_execution_id: "fortress-source-remediation-test",
      },
      governance: {
        counsel_signoff: "COUNSEL_SIGNOFF_PENDING",
        external_submission_authority: "NOT_AUTHORIZED",
        final_legal_conclusions: "NOT_CREATED",
        legal_advice_status: "NOT FINAL LEGAL ADVICE",
        unresolved_items_excluded_from_relied_upon_sections: true,
        locked_restricted_handling: "METADATA_ONLY",
        auto_resolution: "DISABLED",
        review_operations_mode: "controlled_internal_review_only",
        state_mutation: "read_only_review_operations_view",
      },
      review_operations_summary: {
        unresolved_total: 232,
        remediation_queue_depth: 232,
        contradiction_queue_depth: 14,
        evidence_navigation_items: 90,
        high_priority_items: 21,
        reviewer_owner_unassigned: 232,
        excluded_source_ratio: 1,
        verified_subset_count: 65,
      },
      queues: {
        remediation_review: {
          summary: { queue_depth: 232 },
          items: [
            {
              item_id: "contradiction-01",
              item_type: "contradiction_candidate",
              materiality_tier: "tier_1_high_materiality",
              blocker_type: "unsupported",
              source_status: "unsupported",
              confidence_state: "source_missing",
              review_lane: "contradiction_review",
              priority_score: 135,
              counsel_review_required: true,
              evidence_needed: true,
              locked_restricted_involved: false,
              can_proceed_without_this_item: false,
              signoff_impact: "blocks_full_packet",
              required_next_action: "Attach source or exclude.",
              review_state: "human_review_required",
              owner_placeholder: "unassigned",
              owner_role_hint: "counsel_or_senior_reviewer",
              age_band: "baseline_backlog",
              staleness_indicator: "needs_review_sla",
              sla_band: "critical_24h",
              escalation_state: "escalate_if_unassigned",
              workload_weight: 4,
              audit_state: "lineage_preserved",
            },
            {
              item_id: "locked-01",
              item_type: "entity_dossier",
              materiality_tier: "tier_3_low_materiality_or_optional",
              blocker_type: "locked_or_privilege_limited",
              source_status: "locked_or_privilege_limited",
              confidence_state: "restricted_metadata_only",
              review_lane: "locked_restricted_no_content_review",
              priority_score: 5,
              counsel_review_required: true,
              evidence_needed: false,
              locked_restricted_involved: true,
              can_proceed_without_this_item: true,
              signoff_impact: "excluded",
              required_next_action: "Counsel metadata review.",
              review_state: "human_review_required",
              owner_placeholder: "unassigned",
              owner_role_hint: "counsel_or_senior_reviewer",
              age_band: "baseline_backlog",
              staleness_indicator: "needs_review_sla",
              sla_band: "critical_24h",
              escalation_state: "escalate_if_unassigned",
              workload_weight: 4,
              audit_state: "lineage_preserved",
            },
          ],
        },
        contradiction_review: {
          summary: { queue_depth: 14 },
          severity_levels: [
            { level: "critical", rule: "tier_1_high_materiality contradiction" },
          ],
          items: [
            {
              item_id: "contradiction-01",
              item_type: "contradiction_candidate",
              materiality_tier: "tier_1_high_materiality",
              blocker_type: "unsupported",
              source_status: "unsupported",
              confidence_state: "source_missing",
              review_lane: "contradiction_review",
              priority_score: 135,
              counsel_review_required: true,
              evidence_needed: true,
              locked_restricted_involved: false,
              can_proceed_without_this_item: false,
              signoff_impact: "blocks_full_packet",
              required_next_action: "Attach source or exclude.",
              review_state: "human_review_required",
              owner_placeholder: "unassigned",
              owner_role_hint: "counsel_or_senior_reviewer",
              age_band: "baseline_backlog",
              staleness_indicator: "needs_review_sla",
              sla_band: "critical_24h",
              escalation_state: "escalate_if_unassigned",
              workload_weight: 4,
              audit_state: "lineage_preserved",
            },
          ],
        },
        evidence_navigation: {
          summary: { queue_depth: 1 },
          groups: [{ item_type: "entity_dossier", count: 1 }],
          items: [
            {
              item_id: "locked-01",
              item_type: "entity_dossier",
              materiality_tier: "tier_3_low_materiality_or_optional",
              blocker_type: "locked_or_privilege_limited",
              source_status: "locked_or_privilege_limited",
              confidence_state: "restricted_metadata_only",
              review_lane: "locked_restricted_no_content_review",
              priority_score: 5,
              counsel_review_required: true,
              evidence_needed: false,
              locked_restricted_involved: true,
              can_proceed_without_this_item: true,
              signoff_impact: "excluded",
              required_next_action: "Counsel metadata review.",
              review_state: "human_review_required",
              owner_placeholder: "unassigned",
              owner_role_hint: "counsel_or_senior_reviewer",
              age_band: "baseline_backlog",
              staleness_indicator: "needs_review_sla",
              sla_band: "critical_24h",
              escalation_state: "escalate_if_unassigned",
              workload_weight: 4,
              audit_state: "lineage_preserved",
            },
          ],
        },
        escalation_review: { summary: { queue_depth: 1 }, items: [] },
      },
      review_analytics: {
        confidence_distribution: [
          { state: "source_missing", count: 230 },
          { state: "restricted_metadata_only", count: 2 },
        ],
        review_lane_distribution: [{ lane: "contradiction_review", count: 14 }],
        item_type_distribution: [{ item_type: "contradiction_candidate", count: 14 }],
        throughput_model: {
          baseline_queue_depth: 232,
          completed_this_phase: 0,
          safe_auto_resolutions: 0,
          human_review_required: 232,
        },
        reviewer_workload_distribution: [{ owner_role_hint: "counsel_or_senior_reviewer", count: 16 }],
        sla_distribution: [{ sla_band: "critical_24h", count: 21 }],
        escalation_distribution: [{ escalation_state: "escalate_if_unassigned", count: 21 }],
      },
      reviewer_operations: {
        status: "CONTROLLED_REVIEW_SCALING_READY",
        assignment_model: {
          mode: "derived_reviewer_role_hints_no_persistent_assignment",
          authority_boundary: "queue_manager_may_assign_review_work_no_legal_signoff",
          reviewer_groups: [
            "operator_reviewer",
            "source_reviewer",
            "counsel_or_senior_reviewer",
            "privilege_counsel_metadata_review",
          ],
          forbidden_assignment_effects: [
            "source_auto_resolution",
            "relied_upon_promotion",
            "counsel_signoff",
            "final_legal_conclusion",
            "external_submission_authority",
          ],
        },
        workload_balancing: {
          model: "metadata_only_weighted_queue_balancing",
          summary: {
            total_workload_weight: 400,
            unassigned_items: 232,
            counsel_or_senior_reviewer_items: 16,
            source_reviewer_items: 214,
            privilege_metadata_items: 2,
            critical_sla_items: 21,
          },
          distribution: [{ owner_role_hint: "source_reviewer", count: 214 }],
        },
        queue_aging_sla: {
          model: "sla_targets_for_review_attention_only",
          baseline_age_source: "existing_manifest_backlog_no_state_mutation",
          targets: [{ sla_band: "critical_24h", target: "review_owner_assigned_within_24h" }],
          distribution: [{ sla_band: "critical_24h", count: 21 }],
        },
        escalation_governance: {
          model: "human_escalation_only",
          distribution: [{ escalation_state: "escalate_if_unassigned", count: 21 }],
          incident_triggers: ["auth_boundary_failure"],
        },
        incident_readiness: {
          status: "READY_FOR_CONTROLLED_INTERNAL_PILOT",
          rollback_required: true,
          stop_conditions: ["secret_exposure", "uncontrolled_legal_automation"],
        },
      },
      operational_certification: {
        status: "CONTROLLED_PILOT_OPERATIONS_CERTIFICATION_READY",
        certification_scope: "controlled_internal_reviewer_operations_only",
        readiness_audit: {
          production_route_verified: true,
          authenticated_checker_required: true,
          deployment_verifier_required: true,
          rollback_required: true,
          unresolved_source_issues_excluded: 232,
          counsel_signoff_status: "COUNSEL_SIGNOFF_PENDING",
          external_submission_authority: "NOT_AUTHORIZED",
          final_legal_conclusions: "NOT_CREATED",
          schema_rls_policy_mutation: "NOT_PERFORMED",
        },
        pilot_governance: {
          pilot_mode: "controlled_internal_operations",
          public_launch_enabled: false,
          unrestricted_reviewer_access_enabled: false,
          allowed_operations: ["queue_triage", "reviewer_onboarding"],
          forbidden_operations: ["auto_signoff", "final_legal_conclusion", "external_submission"],
        },
        reviewer_onboarding: {
          status: "GOVERNED_ONBOARDING_REQUIRED",
          required_acknowledgments: [
            "counsel_signoff_pending",
            "not_authorized_external_submission",
            "not_final_legal_advice",
          ],
          allowed_roles: ["operator_reviewer", "source_reviewer"],
        },
        rollback_certification: {
          status: "ROLLBACK_READY_PENDING_PR_REVIEW",
          git_revertable: true,
          runtime_rollback_required: true,
          verification_after_rollback: ["authenticated_checker", "deployment_verifier"],
        },
        governance_enforcement: {
          status: "ENFORCEMENT_VERIFICATION_REQUIRED_EACH_RUN",
          required_checks: [
            "COUNSEL_SIGNOFF_PENDING",
            "NOT_AUTHORIZED",
            "NOT FINAL LEGAL ADVICE",
          ],
        },
        operational_safety: {
          status: "CERTIFIED_FOR_CONTROLLED_INTERNAL_PILOT_REVIEW",
          certification_limitations: ["no_public_launch", "no_counsel_signoff", "no_new_ingestion"],
        },
      },
      internal_pilot: {
        status: "CONTROLLED_INTERNAL_PILOT_READY",
        pilot_mode: "read_only_synthetic_and_metadata_safe",
        execution_scope: "controlled_internal_reviewer_operations",
        pilot_summary: {
          review_queue_depth: 232,
          remediation_triage_items: 232,
          contradiction_review_items: 14,
          evidence_navigation_items: 90,
          escalation_items: 21,
          unresolved_source_issues: 232,
          excluded_source_issues: 232,
          locked_restricted_metadata_only: 2,
          pilot_completion_readiness: "READY_FOR_CONTROLLED_INTERNAL_USE_ONLY",
        },
        allowed_exercises: ["read_only_review_queue_traversal", "rollback_tabletop_drill"],
        forbidden_exercises: ["legal_signoff", "final_legal_conclusion", "external_submission"],
        throughput_metrics: {
          queue_depth: 232,
          queue_aging_bands: [{ sla_band: "critical_24h", count: 21 }],
          review_traversal_sample: 40,
          remediation_triage_count: 232,
          contradiction_review_count: 14,
          evidence_navigation_count: 90,
          reviewer_handoff_count: 4,
          escalation_count: 21,
          unresolved_source_count: 232,
          excluded_source_count: 232,
          confidence_distribution: [{ state: "source_missing", count: 230 }],
        },
        pilot_drills: [
          { scenario: "unsupported_assertion_seen", expected_response: "keep_excluded_and_route_to_source_reviewer" },
        ],
        ergonomic_optimizations: ["single_pilot_summary", "queue_health_metrics"],
        governance: {
          counsel_signoff: "COUNSEL_SIGNOFF_PENDING",
          external_submission_authority: "NOT_AUTHORIZED",
          legal_advice_status: "NOT FINAL LEGAL ADVICE",
          final_legal_conclusions: "NOT_CREATED",
          schema_rls_policy_mutation: "NOT_PERFORMED",
          contains_document_body_text: false,
          contains_locked_content: false,
          production_writes: "none",
        },
      },
      human_operations: {
        status: "CONTROLLED_HUMAN_OPERATIONS_READY",
        operating_mode: "authenticated_internal_review_rehearsal_only",
        reviewer_onboarding: {
          status: "ONBOARDING_GOVERNANCE_VISIBLE",
          capability_tiers: ["operator_reviewer", "source_reviewer"],
          required_acknowledgments: ["COUNSEL_SIGNOFF_PENDING", "NOT_AUTHORIZED", "NOT FINAL LEGAL ADVICE"],
          prohibited_operations: ["auto_signoff", "external_submission", "unresolved_source_promotion"],
        },
        operational_feedback: {
          status: "STRUCTURED_FEEDBACK_READY_NO_FREEFORM_LEGAL_TEXT",
          capture_mode: "aggregate_read_only_feedback_categories",
          feedback_categories: [{ category: "queue_friction", severity: "high", count: 6 }],
          forbidden_feedback_content: ["confidential_document_text", "privileged_content", "auth_or_secret_values"],
        },
        governance_exceptions: {
          status: "EXCEPTION_HANDLING_VISIBLE",
          exception_classes: ["unresolved_source_promotion_attempt", "restricted_content_visibility_concern"],
          halt_conditions: ["restricted_content_boundary_uncertain", "unauthorized_access_detected"],
        },
        operational_drift: {
          status: "DRIFT_DETECTION_ACTIVE_FOR_HUMAN_OPERATIONS",
          drift_signals: [{ signal: "queue_depth_drift", state: "watch", count: 232 }],
          response_options: ["observe", "governance_exception_review"],
        },
        incident_rehearsals: [{ scenario: "reviewer_confusion_escalation", result: "tabletop_ready" }],
        ergonomics: {
          improvements: ["reviewer_context_summary", "queue_aging_visibility"],
          persistent_assignment_writes: "deferred",
          production_writes: "none",
        },
        governance: {
          counsel_signoff: "COUNSEL_SIGNOFF_PENDING",
          external_submission_authority: "NOT_AUTHORIZED",
          legal_advice_status: "NOT FINAL LEGAL ADVICE",
          final_legal_conclusions: "NOT_CREATED",
          schema_rls_policy_mutation: "NOT_PERFORMED",
          contains_document_body_text: false,
          contains_locked_content: false,
          unresolved_source_promotion: false,
        },
      },
      pilot_readiness: {
        controlled_internal_review_ready: true,
        public_or_external_use_enabled: false,
        required_controls: ["authenticated_staff_access", "unresolved_source_exclusion"],
        forbidden_operations: ["auto_signoff", "external_submission"],
      },
      observability: {
        checker_assertions: ["review_operations_visible"],
        metrics: ["remediation_queue_depth"],
      },
    },
  }),
}));

import { ReviewOperationsPanel } from "@/app/(dashboard)/legal/cases/[slug]/_components/review-operations-panel";

describe("ReviewOperationsPanel", () => {
  it("renders controlled review queues, contradiction workflow, analytics, and governance boundaries", () => {
    render(<ReviewOperationsPanel slug="fortress-legal-production-review" />);

    expect(screen.getByText("Controlled Review Operations")).toBeInTheDocument();
    expect(screen.getByText("Operational Readiness Certification")).toBeInTheDocument();
    expect(screen.getByText("Controlled Internal Pilot Operations")).toBeInTheDocument();
    expect(screen.getByText("Allowed Pilot Exercises")).toBeInTheDocument();
    expect(screen.getByText("Forbidden Pilot Actions")).toBeInTheDocument();
    expect(screen.getByText("Pilot Throughput Metrics")).toBeInTheDocument();
    expect(screen.getByText("Controlled Human Operations")).toBeInTheDocument();
    expect(screen.getAllByText("Reviewer Onboarding Governance").length).toBeGreaterThan(0);
    expect(screen.getByText("Operational Feedback Capture")).toBeInTheDocument();
    expect(screen.getByText("Governance Exception Handling")).toBeInTheDocument();
    expect(screen.getByText("Operational Drift Detection")).toBeInTheDocument();
    expect(screen.getByText("Human Incident Rehearsal")).toBeInTheDocument();
    expect(screen.getByText("Pilot Governance")).toBeInTheDocument();
    expect(screen.getAllByText("Reviewer Onboarding Governance").length).toBeGreaterThan(0);
    expect(screen.getByText("Rollback Certification")).toBeInTheDocument();
    expect(screen.getByText("Governance Enforcement Verification")).toBeInTheDocument();
    expect(screen.getByText("Operational Safety Certification")).toBeInTheDocument();
    expect(screen.getByText("Review Queue Operations")).toBeInTheDocument();
    expect(screen.getByText("Reviewer Assignment")).toBeInTheDocument();
    expect(screen.getByText("Workload Balancing")).toBeInTheDocument();
    expect(screen.getByText("Queue Aging / SLA")).toBeInTheDocument();
    expect(screen.getAllByText("Contradiction Review").length).toBeGreaterThan(0);
    expect(screen.getByText("Evidence Navigator")).toBeInTheDocument();
    expect(screen.getByText("Review Analytics")).toBeInTheDocument();
    expect(screen.getByText("Controlled Pilot Readiness")).toBeInTheDocument();
    expect(screen.getByText("Escalation & Incident Readiness")).toBeInTheDocument();
    expect(screen.getByText("COUNSEL_SIGNOFF_PENDING")).toBeInTheDocument();
    expect(screen.getByText("NOT_AUTHORIZED")).toBeInTheDocument();
    expect(screen.getAllByText("NOT FINAL LEGAL ADVICE").length).toBeGreaterThan(0);
    expect(screen.getAllByText("excluded from relied-upon sections").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/metadata only restricted/i).length).toBeGreaterThan(0);
    expect(screen.queryByText("FINAL_LEGAL_CONCLUSION")).not.toBeInTheDocument();
  });
});
