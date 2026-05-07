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
              age_band: "baseline_backlog",
              staleness_indicator: "needs_review_sla",
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
              age_band: "baseline_backlog",
              staleness_indicator: "needs_review_sla",
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
              age_band: "baseline_backlog",
              staleness_indicator: "needs_review_sla",
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
              age_band: "baseline_backlog",
              staleness_indicator: "needs_review_sla",
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
    expect(screen.getByText("Review Queue Operations")).toBeInTheDocument();
    expect(screen.getByText("Contradiction Review")).toBeInTheDocument();
    expect(screen.getByText("Evidence Navigator")).toBeInTheDocument();
    expect(screen.getByText("Review Analytics")).toBeInTheDocument();
    expect(screen.getByText("Controlled Pilot Readiness")).toBeInTheDocument();
    expect(screen.getByText("COUNSEL_SIGNOFF_PENDING")).toBeInTheDocument();
    expect(screen.getByText("NOT_AUTHORIZED")).toBeInTheDocument();
    expect(screen.getByText("NOT FINAL LEGAL ADVICE")).toBeInTheDocument();
    expect(screen.getAllByText("excluded from relied-upon sections").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/metadata only restricted/i).length).toBeGreaterThan(0);
    expect(screen.queryByText("FINAL_LEGAL_CONCLUSION")).not.toBeInTheDocument();
  });
});
