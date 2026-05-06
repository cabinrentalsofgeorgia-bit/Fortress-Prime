import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const signoffMutate = vi.fn();
const reopenMutate = vi.fn();

vi.mock("@/lib/legal-hooks", () => ({
  useCounselSignoffPacket: () => ({
    isLoading: false,
    error: null,
    data: {
      execution_id: "fortress-signoff-packet-test",
      packet_version: 1,
      packet_checksum: "abcdef1234567890",
      source_validation_execution_id: "fortress-validation-test",
      source_workbench_execution_id: "fortress-counsel-review-test",
      source_intelligence_execution_id: "fortress-intel-test",
      status: "DRAFT / COUNSEL REVIEW REQUIRED",
      signoff_status: "COUNSEL_SIGNOFF_PENDING",
      readiness_status: "SIGNOFF_PACKET_READY_WITH_UNRESOLVED_ITEMS",
      sections: [
        {
          section_id: "reviewed-issue-matrix",
          title: "Validated / Unvalidated Issue Matrix",
          item_count: 20,
          readiness_status: "incomplete",
          unresolved_count: 20,
          signoff_status: "signoff_pending",
          counsel_review_required: true,
          notes: "Issue packet.",
          source_refs_summary: {
            items: 20,
            with_source_refs: 12,
            without_source_refs: 8,
            total_source_refs: 40,
            locked_restricted_related: 0,
            source_check_status_counts: {},
          },
        },
        {
          section_id: "source-integrity-matrix",
          title: "Source Support / Citation Integrity Matrix",
          item_count: 297,
          readiness_status: "incomplete",
          unresolved_count: 200,
          signoff_status: "signoff_pending",
          counsel_review_required: true,
          notes: "Sources.",
          source_refs_summary: {
            items: 297,
            with_source_refs: 50,
            without_source_refs: 247,
            total_source_refs: 120,
            locked_restricted_related: 0,
            source_check_status_counts: {},
          },
        },
        {
          section_id: "signoff-capture",
          title: "Signoff Page / Signoff Capture Block",
          item_count: 0,
          readiness_status: "not_started",
          unresolved_count: 0,
          signoff_status: "signoff_pending",
          counsel_review_required: true,
          notes: "Explicit signoff required.",
          source_refs_summary: {
            items: 0,
            with_source_refs: 0,
            without_source_refs: 0,
            total_source_refs: 0,
            locked_restricted_related: 0,
            source_check_status_counts: {},
          },
        },
      ],
      source_integrity_matrix: {
        material_items: 297,
        items_with_source_refs: 50,
        items_missing_source_refs: 247,
        items_needing_source_check: 260,
        locked_restricted_source_involved: 2,
        unsupported_assertions_marked_final: false,
        recommended_action: "Source-check before signoff.",
      },
      signoff_readiness_checklist: [
        { check_id: "no-locked-content-used", title: "No locked content used", passed: true },
        { check_id: "signoff-pending", title: "Signoff pending", passed: true },
      ],
      unresolved_items_register: [{ item_id: "issue-01", item_type: "issue_matrix", title: "Issue", validation_status: "needs_counsel_review", source_check_status: "not_checked", counsel_review_required: true }],
      export_snapshot: {
        snapshot_id: "snap-1",
        exportable: true,
        format: "manifest_json",
        contains_document_body_text: false,
        contains_locked_content: false,
      },
      signoff_capture: {
        signoff_recorded: false,
        scope_confirmation_required: true,
      },
      audit_history: [
        { audit_id: "audit-1", action: "signoff_packet_created", created_at: "2026-05-06T12:00:00Z", reviewer_identity_safe_label: "system", reviewer_role: "system" },
      ],
    },
  }),
  useCounselSignoffAction: () => ({ mutate: signoffMutate, isPending: false }),
  useCounselSignoffReopen: () => ({ mutate: reopenMutate, isPending: false }),
}));

import { CounselSignoffStrategyPacket } from "@/app/(dashboard)/legal/cases/[slug]/_components/counsel-signoff-strategy-packet";

describe("CounselSignoffStrategyPacket", () => {
  it("renders strategy packet, source integrity, pending signoff, and requires scope confirmation", () => {
    render(<CounselSignoffStrategyPacket slug="fortress-legal-production-review" />);

    expect(screen.getByText("Strategy Packet / Counsel Signoff")).toBeInTheDocument();
    expect(screen.getByText("DRAFT / COUNSEL REVIEW REQUIRED")).toBeInTheDocument();
    expect(screen.getByText("NOT FINAL LEGAL CONCLUSION")).toBeInTheDocument();
    expect(screen.getByText("Validated / Unvalidated Issue Matrix")).toBeInTheDocument();
    expect(screen.getByText("Source Integrity Matrix")).toBeInTheDocument();
    expect(screen.getByText(/Export snapshot contains no document body text and no locked content/)).toBeInTheDocument();

    const operatorButton = screen.getByText("Operator Acknowledge");
    expect(operatorButton).toBeDisabled();

    fireEvent.click(screen.getByLabelText(/approved review scope only/i));
    fireEvent.click(operatorButton);

    expect(signoffMutate).toHaveBeenCalledWith({
      signoff_type: "operator_review_acknowledgment",
      scope_confirmed: true,
      notes: "Operator review acknowledgment captured from Strategy Packet panel.",
    });
  });
});
