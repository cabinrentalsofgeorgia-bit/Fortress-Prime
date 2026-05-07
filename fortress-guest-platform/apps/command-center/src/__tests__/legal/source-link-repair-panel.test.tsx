import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useSourceLinkRepair: () => ({
    isLoading: false,
    error: null,
    data: {
      execution_id: "fortress-source-link-repair-test",
      source_remediation_execution_id: "fortress-source-remediation-test",
      source_integrity_execution_id: "fortress-source-integrity-test",
      signoff_packet_execution_id: "fortress-signoff-packet-test",
      status: "SOURCE_LINK_REPAIR_COMPLETE_VERIFIED_SUBSET_READY",
      repair_summary: {
        total_blockers_processed: 297,
        verified_for_review_use: 0,
        corrected_verified_for_review_use: 65,
        partially_supported: 0,
        unsupported: 230,
        conflicting_sources: 0,
        needs_page_or_chunk_review: 0,
        needs_more_evidence: 0,
        needs_counsel_review: 0,
        locked_or_privilege_limited: 2,
        unable_to_check_safely: 0,
        remaining_unresolved: 232,
        verified_subset_count: 65,
        counsel_signoff_pending: true,
      },
      packet_section_summary: [
        { item_type: "issue_matrix", item_count: 20, verified_subset_count: 15, unresolved_count: 5 },
      ],
      verified_subset: {
        verified_subset_id: "subset-1",
        item_count: 65,
        item_ids: ["issue-01"],
        packet_sections_covered: ["issue_matrix"],
        excluded_item_count: 232,
        signoff_scope_recommendation: "LIMITED_SOURCE_LINK_SIGNOFF_REVIEW_SUBSET_AVAILABLE",
        items: [
          {
            source_link_repair_id: "slr1",
            source_link_repair_execution_id: "fortress-source-link-repair-test",
            source_remediation_id: "r1",
            source_validation_id: "sv1",
            matter_slug: "fortress-legal-production-review",
            item_id: "issue-01",
            item_type: "issue_matrix",
            prior_remediation_outcome: "unresolved_needs_page_or_chunk_review",
            final_remediation_state: "corrected_verified_for_review_use",
            repair_outcome: "resolved_source_link_repaired",
            verified_for_review_use: true,
            signoff_blocker_after: false,
            corrected_claim_summary: "Source link only.",
            source_refs_before: [],
            source_refs_after: [{ document_id: "d1" }],
            verification_method: "metadata",
            locked_restricted_involved: false,
            counsel_review_required: true,
            source_notes_safe: "Link verified.",
            required_next_action: "Counsel review.",
            reviewer_safe_label: "system",
            version: 1,
            rollback_ref: "r1",
          },
        ],
      },
      refined_unresolved_register: [],
      signoff_readiness_addendum: {
        source_link_repair_execution_id: "fortress-source-link-repair-test",
        readiness_recommendation: "VERIFIED_SUBSET_READY_FOR_COUNSEL_SIGNOFF_REVIEW",
        full_packet_ready: false,
        counsel_signoff_pending: true,
        explicit_signoff_recorded: false,
      },
    },
  }),
}));

import { SourceLinkRepairPanel } from "@/app/(dashboard)/legal/cases/[slug]/_components/source-link-repair-panel";

describe("SourceLinkRepairPanel", () => {
  it("renders verified subset and keeps signoff pending", () => {
    render(<SourceLinkRepairPanel slug="fortress-legal-production-review" />);

    expect(screen.getByText("Source Link Repair")).toBeInTheDocument();
    expect(screen.getByText("COUNSEL_SIGNOFF_PENDING")).toBeInTheDocument();
    expect(screen.getAllByText("Verified Subset").length).toBeGreaterThan(0);
    expect(screen.getByText("LIMITED_SOURCE_LINK_SIGNOFF_REVIEW_SUBSET_AVAILABLE")).toBeInTheDocument();
    expect(screen.queryByText("final_legal_conclusion")).not.toBeInTheDocument();
  });
});
