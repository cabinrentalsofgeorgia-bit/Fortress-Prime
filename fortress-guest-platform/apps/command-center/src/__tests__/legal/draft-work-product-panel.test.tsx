import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useDraftWorkProduct: () => ({
    isLoading: false,
    error: null,
    data: {
      execution_id: "fortress-draft-work-product-test",
      created_at: "2026-05-06T18:00:00Z",
      case_slug: "fortress-legal-production-review",
      status: "DRAFT_WORK_PRODUCT_READY_FOR_COUNSEL_REVIEW",
      draft_packet_store: "file_manifest",
      source_manifests: {
        limited_signoff_candidate: "fortress-limited-signoff-candidate-test",
        targeted_source_completion: "fortress-targeted-source-completion-test",
        autonomous_learning: "fortress-learning-loop-test",
      },
      source_basis: {
        included_verified_item_count: 65,
        excluded_unresolved_item_count: 232,
        source_refs_total: 320,
        item_type_counts: { issue_matrix: 10 },
        locked_restricted_used_for_content: false,
      },
      governance_labels: [
        "DRAFT / COUNSEL REVIEW REQUIRED",
        "NOT FINAL LEGAL ADVICE",
        "NOT AUTHORIZED FOR FILING, SERVICE, SENDING, EMAIL, OR EXTERNAL SUBMISSION",
        "SOURCE-VERIFIED SUBSET ONLY",
        "COUNSEL_SIGNOFF_PENDING",
      ],
      draft_packet: {
        packet_id: "draft-packet",
        sections_generated: 15,
        motion_response_outline_status: "draft_outline_available_for_counsel_review",
        counsel_signoff_pending: true,
        final_legal_conclusions_created: false,
        external_submission_authorized: false,
        sections: [
          {
            section_id: "draft-internal-case-assessment-memo",
            title: "Draft Internal Case Assessment Memo",
            status: "DRAFT / COUNSEL REVIEW REQUIRED",
            legal_advice_status: "NOT_FINAL_LEGAL_ADVICE",
            external_use_status: "NOT_AUTHORIZED",
            source_basis: "SOURCE_VERIFIED_SUBSET_ONLY",
            item_count: 3,
            items: [],
            notes: "Limited to source-routed items.",
            counsel_review_required: true,
            section_hash: "hash-1",
          },
          {
            section_id: "draft-source-backed-statement-of-facts",
            title: "Draft Source-Backed Statement of Facts",
            status: "DRAFT / COUNSEL REVIEW REQUIRED",
            legal_advice_status: "NOT_FINAL_LEGAL_ADVICE",
            external_use_status: "NOT_AUTHORIZED",
            source_basis: "SOURCE_VERIFIED_SUBSET_ONLY",
            item_count: 65,
            items: [],
            notes: "Facts tie to source refs.",
            counsel_review_required: true,
            section_hash: "hash-2",
          },
          {
            section_id: "excluded-unresolved-source-issues",
            title: "Excluded / Unresolved Source Issues Appendix",
            status: "DRAFT / COUNSEL REVIEW REQUIRED",
            legal_advice_status: "NOT_FINAL_LEGAL_ADVICE",
            external_use_status: "NOT_AUTHORIZED",
            source_basis: "SOURCE_VERIFIED_SUBSET_ONLY",
            item_count: 232,
            items: [],
            notes: "Unresolved source issues are not relied on as facts.",
            counsel_review_required: true,
            section_hash: "hash-3",
          },
        ],
      },
      source_map: {
        source_map_id: "source-map",
        included_item_ids: ["issue-01"],
        excluded_item_ids: ["issue-99"],
        source_ref_count: 320,
        contains_document_body_text: false,
        contains_locked_content: false,
      },
      rollback: {},
      mutation_invariants: {},
      manifest_checksum: "1234567890abcdef",
    },
  }),
}));

import { DraftWorkProductPanel } from "@/app/(dashboard)/legal/cases/[slug]/_components/draft-work-product-panel";

describe("DraftWorkProductPanel", () => {
  it("renders draft work product with source-only and no-external-use labels", () => {
    render(<DraftWorkProductPanel slug="fortress-legal-production-review" />);

    expect(screen.getByText("Draft Work Product Packet")).toBeInTheDocument();
    expect(screen.getAllByText("DRAFT / COUNSEL REVIEW REQUIRED").length).toBeGreaterThan(0);
    expect(screen.getAllByText("NOT FINAL LEGAL ADVICE").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SOURCE-VERIFIED SUBSET ONLY").length).toBeGreaterThan(0);
    expect(screen.getAllByText("COUNSEL_SIGNOFF_PENDING").length).toBeGreaterThan(0);
    expect(screen.getByText("Draft Source-Backed Statement of Facts")).toBeInTheDocument();
    expect(screen.getByText("Excluded / Unresolved Source Issues Appendix")).toBeInTheDocument();
    expect(screen.getByText("NO DOCUMENT BODY TEXT")).toBeInTheDocument();
  });
});
