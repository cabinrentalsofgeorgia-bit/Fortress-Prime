import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useTargetedSourceCompletion: () => ({
    isLoading: false,
    error: null,
    data: {
      execution_id: "fortress-targeted-source-completion-test",
      source_link_repair_execution_id: "fortress-source-link-repair-test",
      source_remediation_execution_id: "fortress-source-remediation-test",
      source_integrity_execution_id: "fortress-source-integrity-test",
      signoff_packet_execution_id: "fortress-signoff-packet-test",
      status: "TARGETED_SOURCE_COMPLETION_VERIFIED_SUBSET_EXPANDED",
      completion_summary: {
        starting_unresolved: 282,
        items_processed: 282,
        prior_verified_subset_count: 15,
        new_items_verified: 50,
        new_verified_subset_count: 65,
        verified_subset_delta: 50,
        remaining_unresolved: 232,
        verified_for_review_use: 0,
        corrected_verified_for_review_use: 50,
        partially_supported: 0,
        unsupported: 230,
        conflicting_sources: 0,
        needs_page_or_chunk_review: 0,
        needs_more_evidence: 0,
        needs_counsel_review: 0,
        locked_or_privilege_limited: 2,
        unable_to_check_safely: 0,
        track_results: {
          track_a_page_chunk_review: {
            items: 50,
            verified: 0,
            corrected: 50,
            partial: 0,
            unresolved: 0,
          },
          track_b_unsupported_recheck: {
            items: 230,
            verified: 0,
            corrected: 0,
            partial: 0,
            still_unsupported: 230,
          },
          track_c_locked_privilege_limited: {
            items: 2,
            preserved_metadata_only: 2,
          },
        },
        counsel_signoff_pending: true,
      },
      packet_section_summary: [],
      expanded_verified_subset: {
        verified_subset_id: "subset-1",
        prior_item_count: 15,
        new_item_count: 65,
        delta: 50,
        item_ids: ["issue-01", "event-01"],
        new_item_ids: ["event-01"],
        packet_sections_covered: ["timeline_event"],
        excluded_item_count: 232,
        signoff_scope_recommendation: "LIMITED_TARGETED_SOURCE_COMPLETION_SIGNOFF_REVIEW_SUBSET_AVAILABLE",
        prior_items: [],
        new_items: [
          {
            targeted_source_completion_id: "tsc1",
            targeted_source_completion_execution_id: "fortress-targeted-source-completion-test",
            source_link_repair_id: "slr1",
            source_remediation_id: "r1",
            source_validation_id: "sv1",
            matter_slug: "fortress-legal-production-review",
            item_id: "event-01",
            item_type: "timeline_event",
            track: "track_a_page_chunk_review",
            prior_state: "needs_page_or_chunk_review",
            final_state: "corrected_verified_for_review_use",
            completion_outcome: "resolved_existing_page_chunk_source_link",
            verified_for_review_use: true,
            signoff_blocker_after: false,
            corrected_claim_summary: "Corrected source link.",
            source_refs_before: [],
            source_refs_after: [{ document_id: "d1" }],
            verification_method: "metadata",
            locked_restricted_involved: false,
            counsel_review_required: true,
            source_notes_safe: "Matched safely.",
            required_next_action: "Counsel review.",
            reviewer_safe_label: "system",
            version: 1,
            rollback_ref: "slr1",
          },
        ],
      },
      refined_unresolved_register: [],
      signoff_readiness_addendum: {
        targeted_source_completion_execution_id: "fortress-targeted-source-completion-test",
        status: "TARGETED_SOURCE_COMPLETION_COMPLETE",
        verified_subset_status: "VERIFIED_SUBSET_EXPANDED",
        full_packet_ready: false,
        limited_signoff_subset_available: true,
        readiness_recommendation: "LIMITED_SIGNOFF_SUBSET_AVAILABLE",
        counsel_signoff_pending: true,
        explicit_signoff_recorded: false,
      },
    },
  }),
}));

import { TargetedSourceCompletionPanel } from "@/app/(dashboard)/legal/cases/[slug]/_components/targeted-source-completion-panel";

describe("TargetedSourceCompletionPanel", () => {
  it("renders expanded subset and keeps signoff pending", () => {
    render(<TargetedSourceCompletionPanel slug="fortress-legal-production-review" />);

    expect(screen.getByText("Targeted Source Completion")).toBeInTheDocument();
    expect(screen.getByText("COUNSEL_SIGNOFF_PENDING")).toBeInTheDocument();
    expect(screen.getByText("+50")).toBeInTheDocument();
    expect(screen.getByText("LIMITED_TARGETED_SOURCE_COMPLETION_SIGNOFF_REVIEW_SUBSET_AVAILABLE")).toBeInTheDocument();
    expect(screen.queryByText("final_legal_conclusion")).not.toBeInTheDocument();
  });
});
