import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useSourceIntegrity: () => ({
    isLoading: false,
    error: null,
    data: {
      execution_id: "fortress-source-integrity-test",
      signoff_packet_execution_id: "fortress-signoff-packet-test",
      source_integrity_summary: {
        total_material_items: 297,
        checked: 297,
        source_verified_for_review_use: 0,
        partially_supported: 0,
        unsupported: 0,
        conflicting_sources: 0,
        wrong_source: 0,
        source_missing: 230,
        needs_page_or_chunk_review: 67,
        locked_or_privilege_limited: 0,
        needs_counsel_review: 0,
        signoff_blockers: 297,
        source_validation_complete_percent: 100,
        verified_subset_count: 0,
        signoff_readiness_recommendation: "READY_FOR_COUNSEL_SOURCE_REVIEW",
        counsel_signoff_pending: true,
      },
      correction_queue: [
        {
          queue_id: "q1",
          source_validation_id: "sv1",
          item_id: "issue-01",
          item_type: "issue_matrix",
          issue_category: "reviewed-issue-matrix",
          source_support_status: "source_missing",
          reason: "No safe source reference is attached.",
          suggested_correction: "Repair source citation.",
          required_next_action: "Add or verify page/chunk source support before signoff.",
          priority: "high",
          signoff_blocker: true,
          counsel_review_required: true,
          linked_source_refs: [],
          locked_restricted_flag: false,
        },
      ],
      signoff_blockers: [
        {
          source_validation_id: "sv1",
          item_id: "issue-01",
          item_type: "issue_matrix",
          item_title: "Purchase agreement issue",
          packet_section: "reviewed-issue-matrix",
          source_refs_checked: [],
          source_support_status: "source_missing",
          signoff_blocker: true,
        },
      ],
      verified_subset: [],
      batch_results: [
        {
          item_type: "issue_matrix",
          items_total: 20,
          checked: 20,
          verified: 0,
          partial: 0,
          unsupported: 3,
          conflicting: 0,
          locked_or_privilege_limited: 0,
          needs_page_or_chunk_review: 17,
          needs_counsel_review: 0,
          signoff_blockers: 20,
        },
      ],
    },
  }),
}));

import { SourceIntegrityValidationPanel } from "@/app/(dashboard)/legal/cases/[slug]/_components/source-integrity-validation-panel";

describe("SourceIntegrityValidationPanel", () => {
  it("renders classified source-check status without final-signoff language", () => {
    render(<SourceIntegrityValidationPanel slug="fortress-legal-production-review" />);

    expect(screen.getByText("Source Integrity Validation")).toBeInTheDocument();
    expect(screen.getByText("DRAFT / COUNSEL REVIEW REQUIRED")).toBeInTheDocument();
    expect(screen.getByText("COUNSEL_SIGNOFF_PENDING")).toBeInTheDocument();
    expect(screen.getByText("297/297")).toBeInTheDocument();
    expect(screen.getByText("Correction Queue")).toBeInTheDocument();
    expect(screen.getAllByText("Signoff Blockers").length).toBeGreaterThan(0);
    expect(screen.getByText("Verified Subset")).toBeInTheDocument();
    expect(screen.getAllByText("source missing").length).toBeGreaterThan(0);
    expect(screen.queryByText("final_legal_conclusion")).not.toBeInTheDocument();
  });
});
