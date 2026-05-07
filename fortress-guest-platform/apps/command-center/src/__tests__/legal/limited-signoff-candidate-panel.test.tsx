import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useLimitedSignoffCandidate: () => ({
    isLoading: false,
    error: null,
    data: {
      execution_id: "fortress-limited-signoff-candidate-test",
      targeted_source_completion_execution_id: "fortress-targeted-source-completion-test",
      source_link_repair_execution_id: "fortress-source-link-repair-test",
      signoff_packet_execution_id: "fortress-signoff-packet-test",
      status: "LIMITED_SIGNOFF_CANDIDATE_PACKET_READY",
      packet_label: "LIMITED_SIGNOFF_CANDIDATE_PACKET",
      governance_labels: ["COUNSEL_REVIEW_REQUIRED", "COUNSEL_SIGNOFF_PENDING"],
      packet_store: "file_manifest",
      verified_subset_used: { item_count: 65, source: "subset-1" },
      high_materiality_source_review: {
        items_reviewed: 21,
        items: [
          {
            limited_signoff_review_id: "r1",
            source_record_id: "s1",
            source_validation_id: "v1",
            item_id: "issue-02",
            item_type: "issue_matrix",
            item_title: "Issue",
            materiality_tier: "tier_1_high_materiality",
            blocker_type: "unsupported_source_gap",
            source_status: "unsupported",
            candidate_outcome: "exclude_unsupported",
            reason_excluded: "Unresolved source support.",
            required_next_action: "Attach source reference.",
            owner_placeholder: "counsel",
            counsel_review_required: true,
            evidence_needed: true,
            can_proceed_without_this_item: false,
            signoff_impact: "blocks_full_packet_signoff",
            locked_restricted_involved: false,
          },
        ],
      },
      limited_signoff_candidate_packet: {
        candidate_packet_id: "candidate-1",
        included_item_count: 65,
        excluded_item_count: 232,
        included_items: [],
        packet_sections: [],
        section_summary: [],
        signoff_scope_recommendation: "LIMITED_SIGNOFF_CANDIDATE_PACKET_READY_FOR_COUNSEL_REVIEW",
        counsel_signoff_pending: true,
        explicit_signoff_recorded: false,
      },
      unresolved_blocker_register_v2: [],
      tier_summary: {
        tier_1_count: 21,
        tier_2_count: 81,
        tier_3_count: 130,
        excluded_from_packet: 232,
        requires_counsel_interpretation: 16,
        requires_more_evidence: 230,
        locked_privilege_limited: 2,
        unsupported: 230,
        hypothesis_context_only: 0,
      },
      signoff_readiness_addendum: {
        limited_signoff_candidate_execution_id: "fortress-limited-signoff-candidate-test",
        limited_packet_available: true,
        full_packet_ready: false,
        remaining_unresolved: 232,
        readiness_recommendation: "LIMITED_SIGNOFF_CANDIDATE_PACKET_READY_FOR_COUNSEL_REVIEW",
        counsel_signoff_pending: true,
        explicit_signoff_recorded: false,
      },
    },
  }),
}));

import { LimitedSignoffCandidatePanel } from "@/app/(dashboard)/legal/cases/[slug]/_components/limited-signoff-candidate-panel";

describe("LimitedSignoffCandidatePanel", () => {
  it("renders limited packet scope and pending signoff", () => {
    render(<LimitedSignoffCandidatePanel slug="fortress-legal-production-review" />);

    expect(screen.getByText("Limited Signoff Candidate Packet")).toBeInTheDocument();
    expect(screen.getByText("COUNSEL_SIGNOFF_PENDING")).toBeInTheDocument();
    expect(screen.getByText("LIMITED_SIGNOFF_CANDIDATE_PACKET_READY_FOR_COUNSEL_REVIEW")).toBeInTheDocument();
    expect(screen.getAllByText("65").length).toBeGreaterThan(0);
    expect(screen.queryByText("final_legal_conclusion")).not.toBeInTheDocument();
  });
});
