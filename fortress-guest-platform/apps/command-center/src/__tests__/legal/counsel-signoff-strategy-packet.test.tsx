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
      correction_queue: [],
      signoff_blockers: [],
      verified_subset: [],
      batch_results: [],
    },
  }),
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
      verified_subset: {
        verified_subset_id: "subset-1",
        item_count: 0,
        item_ids: [],
        packet_sections_covered: [],
        excluded_item_count: 297,
        signoff_scope_recommendation: "NO_LIMITED_SIGNOFF_SUBSET_READY",
        items: [],
      },
      refined_blocker_register: [],
      remediation_category_summary: [],
      signoff_readiness_addendum: {
        readiness_recommendation: "FULL_PACKET_NOT_READY_DUE_TO_UNRESOLVED_BLOCKERS",
        verified_subset_status: "NO_VERIFIED_SUBSET_READY",
        counsel_signoff_pending: true,
        explicit_signoff_recorded: false,
      },
    },
  }),
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
      packet_section_summary: [],
      verified_subset: {
        verified_subset_id: "subset-2",
        item_count: 65,
        item_ids: ["issue-01"],
        packet_sections_covered: ["issue_matrix"],
        excluded_item_count: 232,
        signoff_scope_recommendation: "LIMITED_SOURCE_LINK_SIGNOFF_REVIEW_SUBSET_AVAILABLE",
        items: [],
      },
      refined_unresolved_register: [],
      signoff_readiness_addendum: {
        readiness_recommendation: "VERIFIED_SUBSET_READY_FOR_COUNSEL_SIGNOFF_REVIEW",
        full_packet_ready: false,
        counsel_signoff_pending: true,
        explicit_signoff_recorded: false,
      },
    },
  }),
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
          track_a_page_chunk_review: { items: 50, verified: 0, corrected: 50, partial: 0, unresolved: 0 },
          track_b_unsupported_recheck: { items: 230, verified: 0, corrected: 0, partial: 0, still_unsupported: 230 },
          track_c_locked_privilege_limited: { items: 2, preserved_metadata_only: 2 },
        },
        counsel_signoff_pending: true,
      },
      packet_section_summary: [],
      expanded_verified_subset: {
        verified_subset_id: "subset-3",
        prior_item_count: 15,
        new_item_count: 65,
        delta: 50,
        item_ids: ["issue-01", "event-01"],
        new_item_ids: ["event-01"],
        packet_sections_covered: ["timeline_event"],
        excluded_item_count: 232,
        signoff_scope_recommendation: "LIMITED_TARGETED_SOURCE_COMPLETION_SIGNOFF_REVIEW_SUBSET_AVAILABLE",
        prior_items: [],
        new_items: [],
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

import { CounselSignoffStrategyPacket } from "@/app/(dashboard)/legal/cases/[slug]/_components/counsel-signoff-strategy-packet";

describe("CounselSignoffStrategyPacket", () => {
  it("renders strategy packet, source integrity, pending signoff, and requires scope confirmation", () => {
    render(<CounselSignoffStrategyPacket slug="fortress-legal-production-review" />);

    expect(screen.getByText("Strategy Packet / Counsel Signoff")).toBeInTheDocument();
    expect(screen.getAllByText("DRAFT / COUNSEL REVIEW REQUIRED").length).toBeGreaterThan(0);
    expect(screen.getByText("NOT FINAL LEGAL CONCLUSION")).toBeInTheDocument();
    expect(screen.getByText("Validated / Unvalidated Issue Matrix")).toBeInTheDocument();
    expect(screen.getByText("Source Integrity Matrix")).toBeInTheDocument();
    expect(screen.getByText("Source Blocker Remediation")).toBeInTheDocument();
    expect(screen.getByText("Source Link Repair")).toBeInTheDocument();
    expect(screen.getByText("Targeted Source Completion")).toBeInTheDocument();
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
