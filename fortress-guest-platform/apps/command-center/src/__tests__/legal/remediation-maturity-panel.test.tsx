import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useRemediationMaturity: () => ({
    isLoading: false,
    error: null,
    data: {
      case_slug: "fortress-legal-production-review",
      status: "SOURCE_REMEDIATION_MATURITY_READY_FOR_REVIEW",
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
      },
      remediation_summary: {
        unresolved_total: 232,
        unsupported_or_missing_source: 230,
        locked_restricted_no_review: 2,
        evidence_needed: 230,
        counsel_review_required: 16,
        verified_subset_count: 65,
        limited_packet_available: true,
      },
      classification_counts: {
        by_item_type: [{ key: "timeline_event", count: 130 }],
        by_materiality_tier: [{ key: "tier_1_high_materiality", count: 21 }],
        by_confidence_state: [
          { state: "source_missing", count: 230 },
          { state: "restricted_metadata_only", count: 2 },
        ],
        by_review_lane: [
          { lane: "evidence_attachment_required", count: 230 },
          { lane: "locked_restricted_no_content_review", count: 2 },
        ],
      },
      priority_model: {
        name: "FORTRESS_SOURCE_REVIEW_PRIORITY_V1",
        factors: ["materiality_tier", "item_type"],
        automation_boundary: "ranking_only_no_source_resolution",
      },
      priority_queue: [
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
        },
      ],
      review_workflows: [],
      evidence_lineage: {
        lineage_chain: [
          "source_integrity",
          "source_remediation",
          "source_link_repair",
          "targeted_source_completion",
          "limited_signoff_candidate_packet",
          "remediation_maturity_read_model",
        ],
        mutation_model: "read_only_derived_view",
        rollback_model: "git_revert_and_manifest_recheck",
        silent_state_transitions_allowed: false,
      },
      observability: {
        metrics: ["unresolved_total"],
        checker_assertions: ["remediation_maturity_visible"],
      },
    },
  }),
}));

import { RemediationMaturityPanel } from "@/app/(dashboard)/legal/cases/[slug]/_components/remediation-maturity-panel";

describe("RemediationMaturityPanel", () => {
  it("renders governed review queue, confidence, lineage, and exclusion boundaries", () => {
    render(<RemediationMaturityPanel slug="fortress-legal-production-review" />);

    expect(screen.getByText("Remediation Maturity / Review Queue")).toBeInTheDocument();
    expect(screen.getByText("COUNSEL_SIGNOFF_PENDING")).toBeInTheDocument();
    expect(screen.getByText("NOT_AUTHORIZED")).toBeInTheDocument();
    expect(screen.getByText("Prioritized Human Review Queue")).toBeInTheDocument();
    expect(screen.getByText("Review Confidence")).toBeInTheDocument();
    expect(screen.getByText("Evidence Lineage")).toBeInTheDocument();
    expect(screen.getAllByText("excluded from relied-upon sections").length).toBeGreaterThan(0);
    expect(screen.getByText("metadata only restricted")).toBeInTheDocument();
    expect(screen.getByText(/ranking only no source resolution/i)).toBeInTheDocument();
    expect(screen.queryByText("FINAL_LEGAL_CONCLUSION")).not.toBeInTheDocument();
  });
});
