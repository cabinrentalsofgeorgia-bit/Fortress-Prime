import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useSourceRemediation: () => ({
    isLoading: false,
    error: null,
    data: {
      execution_id: "fortress-source-remediation-test",
      source_integrity_execution_id: "fortress-source-integrity-test",
      signoff_packet_execution_id: "fortress-signoff-packet-test",
      status: "SOURCE_REMEDIATION_COMPLETE_NO_SIGNOFF_SUBSET_READY",
      remediation_summary: {
        total_blockers_processed: 297,
        resolved_source_verified: 0,
        resolved_corrected_for_review_use: 0,
        resolved_duplicate_or_superseded: 0,
        unresolved_partially_supported: 0,
        unresolved_unsupported: 230,
        unresolved_conflicting_sources: 0,
        unresolved_needs_page_or_chunk_review: 65,
        unresolved_needs_more_evidence: 0,
        unresolved_needs_counsel_review: 0,
        unresolved_locked_or_privilege_limited: 2,
        unresolved_wrong_source: 0,
        unable_to_check_safely: 0,
        remaining_blockers: 297,
        verified_subset_count: 0,
        limited_signoff_subset_available: false,
        counsel_signoff_pending: true,
      },
      remediation_category_summary: [
        {
          blocker_type: "missing_source_ref",
          item_count: 230,
          high_materiality_count: 0,
          automated_remediation_safe: true,
          counsel_review_required: true,
          blocks_signoff: true,
          remediation_strategy: "Attach source reference.",
        },
      ],
      verified_subset: {
        verified_subset_id: "subset-1",
        item_count: 0,
        item_ids: [],
        packet_sections_covered: [],
        excluded_item_count: 297,
        signoff_scope_recommendation: "NO_LIMITED_SIGNOFF_SUBSET_READY",
        items: [],
      },
      refined_blocker_register: [
        {
          remediation_id: "r1",
          source_remediation_execution_id: "fortress-source-remediation-test",
          source_validation_id: "sv1",
          matter_slug: "fortress-legal-production-review",
          item_id: "issue-01",
          item_type: "issue_matrix",
          blocker_type: "missing_source_ref",
          original_status: "source_missing",
          remediation_outcome: "unresolved_unsupported",
          remediated_status: "unsupported",
          support_status_after: "source_missing",
          signoff_blocker_after: true,
          correction_needed: true,
          source_refs_before: [],
          source_refs_after: [],
          verification_method: "metadata_only",
          locked_restricted_involved: false,
          counsel_review_required: true,
          source_notes_safe: "No claimed source reference is available.",
          required_next_action: "Add source reference or mark item out of signoff subset.",
          reviewer_safe_label: "system",
          version: 1,
          rollback_ref: "sv1",
        },
      ],
      signoff_readiness_addendum: {
        readiness_recommendation: "FULL_PACKET_NOT_READY_DUE_TO_UNRESOLVED_BLOCKERS",
        verified_subset_status: "NO_VERIFIED_SUBSET_READY",
        counsel_signoff_pending: true,
        explicit_signoff_recorded: false,
      },
    },
  }),
}));

import { SourceRemediationPanel } from "@/app/(dashboard)/legal/cases/[slug]/_components/source-remediation-panel";

describe("SourceRemediationPanel", () => {
  it("renders remediation results without signoff or final legal conclusion", () => {
    render(<SourceRemediationPanel slug="fortress-legal-production-review" />);

    expect(screen.getByText("Source Blocker Remediation")).toBeInTheDocument();
    expect(screen.getByText("DRAFT / COUNSEL REVIEW REQUIRED")).toBeInTheDocument();
    expect(screen.getByText("COUNSEL_SIGNOFF_PENDING")).toBeInTheDocument();
    expect(screen.getAllByText("Verified Subset").length).toBeGreaterThan(0);
    expect(screen.getByText("Refined Blocker Register")).toBeInTheDocument();
    expect(screen.getByText("FULL_PACKET_NOT_READY_DUE_TO_UNRESOLVED_BLOCKERS")).toBeInTheDocument();
    expect(screen.queryByText("final_legal_conclusion")).not.toBeInTheDocument();
  });
});
