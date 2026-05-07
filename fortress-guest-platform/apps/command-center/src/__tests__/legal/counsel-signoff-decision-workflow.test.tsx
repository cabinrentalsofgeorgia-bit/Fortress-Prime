import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useCounselSignoffDecision: () => ({
    isLoading: false,
    error: null,
    data: {
      execution_id: "fortress-signoff-decision-test",
      created_at: "2026-05-06T16:30:00Z",
      case_slug: "fortress-legal-production-review",
      decision_store: "file_manifest",
      status: "COUNSEL_SIGNOFF_DECISION_WORKFLOW_READY",
      counsel_status: "COUNSEL_SIGNOFF_PENDING",
      product_status: "COUNSEL_SIGNOFF_DECISION_WORKFLOW_READY",
      packet: {
        packet_execution_id: "fortress-limited-signoff-candidate-test",
        packet_version: 1,
        packet_hash: "34e942c10aed757ae31491b3d05c9c3ee951834dc2f50c0a40741d3bf0d8f892",
        included_verified_subset: 65,
        excluded_unresolved_items: 232,
        source_verified_subset_count: 65,
        unresolved_source_issue_count: 232,
        locked_restricted_count: 2,
      },
      decision_readiness: {
        decision_panel_visible: true,
        packet_checksum_required: true,
        explicit_scope_confirmation_required: true,
        unresolved_exclusions_acknowledgment_required: true,
        privilege_handling_acknowledgment_required: true,
        no_external_submission_authority_acknowledgment_required: true,
        auto_signoff_prevented: true,
        external_submission_authority_available: false,
        final_legal_conclusion_available: false,
      },
      decision_paths: [
        {
          decision_type: "operator_review_acknowledgment",
          label: "Operator acknowledgment only",
          records_counsel_signoff: false,
          resulting_counsel_status: "COUNSEL_SIGNOFF_PENDING",
        },
        {
          decision_type: "counsel_approved_for_internal_review_use",
          label: "Counsel approves limited packet for internal review use",
          records_counsel_signoff: true,
          resulting_counsel_status: "COUNSEL_SIGNOFF_RECORDED_FOR_APPROVED_REVIEW_SCOPE",
        },
        {
          decision_type: "counsel_requested_revisions",
          label: "Counsel requests revisions",
          records_counsel_signoff: false,
          resulting_counsel_status: "COUNSEL_REVIEW_IN_PROGRESS",
        },
      ],
      explicit_confirmation_checklist: [
        "I confirm I am deciding only for the selected approved review scope.",
        "I understand unresolved items remain excluded.",
        "I understand locked/restricted documents remain metadata-only.",
        "I understand this does not authorize filing, service, sending, or external submission.",
        "I understand this does not create unrestricted legal production approval.",
      ],
      decision_records: [],
      revision_requests: [],
      source_remediation_returns: [],
      audit_history: [],
    },
  }),
  useCounselSignoffDecisionAction: () => ({
    isPending: false,
    mutate: vi.fn(),
  }),
}));

import { CounselSignoffDecisionWorkflow } from "@/app/(dashboard)/legal/cases/[slug]/_components/counsel-signoff-decision-workflow";

describe("CounselSignoffDecisionWorkflow", () => {
  it("renders decision paths, checksum, and governance boundaries", () => {
    render(<CounselSignoffDecisionWorkflow slug="fortress-legal-production-review" />);

    expect(screen.getByText("Counsel Signoff Decision Workflow")).toBeInTheDocument();
    expect(screen.getAllByText("COUNSEL_SIGNOFF_PENDING").length).toBeGreaterThan(0);
    expect(screen.getByText("EXTERNAL_SUBMISSION_NOT_AUTHORIZED")).toBeInTheDocument();
    expect(screen.getByText("NOT FINAL LEGAL CONCLUSION")).toBeInTheDocument();
    expect(screen.getByText("Operator acknowledgment only")).toBeInTheDocument();
    expect(screen.getByText("Counsel approves limited packet for internal review use")).toBeInTheDocument();
    expect(screen.getByText("Packet Checksum")).toBeInTheDocument();
    expect(screen.getByText("No explicit decision has been recorded. Counsel signoff remains pending.")).toBeInTheDocument();
  });
});
