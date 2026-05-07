import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mutate = vi.fn();

vi.mock("@/lib/legal-hooks", () => ({
  useCounselValidation: () => ({
    isLoading: false,
    error: null,
    data: {
      execution_id: "fortress-validation-test",
      source_workbench_execution_id: "fortress-counsel-review-20260506-073330",
      status: "DRAFT / COUNSEL REVIEW REQUIRED",
      summary: {
        total_workbench_items: 299,
        validation_complete_percent: 0,
        accepted_for_review_use: 0,
        needs_source_check: 194,
        needs_counsel_review: 103,
        progress_label: "VALIDATION_NOT_STARTED",
      },
      queues: [
        {
          queue_id: "issue-matrix-validation",
          title: "Issue Matrix Validation",
          item_count: 20,
          needs_source_check_count: 0,
          needs_counsel_review_count: 20,
          high_priority_count: 5,
        },
        {
          queue_id: "privilege-locked-metadata-review",
          title: "Privilege / Locked Metadata Review",
          item_count: 2,
          needs_source_check_count: 0,
          needs_counsel_review_count: 0,
          high_priority_count: 0,
        },
      ],
      records: [
        {
          validation_id: "v1",
          item_id: "issue-01",
          item_title: "Purchase and sale agreement formation",
          item_type: "issue_matrix",
          version: 1,
          validation_status: "needs_counsel_review",
          source_check_status: "not_checked",
          source_refs: [{ document_id: "d1" }],
          locked_restricted_related: false,
        },
        {
          validation_id: "v2",
          item_id: "locked-restricted-01",
          item_title: "Locked/restricted metadata item 1",
          item_type: "locked_restricted_metadata",
          version: 1,
          validation_status: "privileged_locked_metadata_only",
          source_check_status: "not_checked",
          source_refs: [],
          locked_restricted_related: true,
        },
      ],
      audit_history: [
        {
          audit_id: "a1",
          action: "validation_initialized",
          created_at: "2026-05-06T12:00:00Z",
          reviewer_identity_safe_label: "system:validation-initializer",
          reviewer_role: "system",
        },
      ],
    },
  }),
  useCounselValidationAction: () => ({ mutate, isPending: false }),
}));

import { CounselValidationWorkflow } from "@/app/(dashboard)/legal/cases/[slug]/_components/counsel-validation-workflow";

describe("CounselValidationWorkflow", () => {
  it("renders validation queues, controls, audit trail, and draft posture", () => {
    render(<CounselValidationWorkflow slug="fortress-legal-production-review" />);

    expect(screen.getByText("Counsel Validation Workflow")).toBeInTheDocument();
    expect(screen.getByText("DRAFT / COUNSEL REVIEW REQUIRED")).toBeInTheDocument();
    expect(screen.getByText("Issue Matrix Validation")).toBeInTheDocument();
    expect(screen.getByText("Privilege / Locked Metadata Review")).toBeInTheDocument();
    expect(screen.getByText("Purchase and sale agreement formation")).toBeInTheDocument();
    expect(screen.getByText("Locked/restricted metadata item 1")).toBeInTheDocument();
    expect(screen.getByText("Validation Audit Trail")).toBeInTheDocument();
    expect(screen.getAllByText("Accept").length).toBeGreaterThan(0);

    fireEvent.click(screen.getAllByText("Accept")[0]);
    expect(mutate).toHaveBeenCalledWith({ item_id: "issue-01", action: "accept" });
    expect(screen.queryByText("final_legal_conclusion")).not.toBeInTheDocument();
  });
});
