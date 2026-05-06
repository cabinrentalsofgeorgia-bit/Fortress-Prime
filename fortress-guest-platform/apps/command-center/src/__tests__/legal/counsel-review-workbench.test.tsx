import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useCounselWorkbench: () => ({
    isLoading: false,
    error: null,
    data: {
      execution_id: "fortress-counsel-review-20260506-123456",
      source_intelligence_execution_id: "fortress-intel-20260506-041839",
      issue_matrix: [
        {
          id: "issue-01",
          title: "Purchase and sale agreement formation",
          issue_type: "contract",
          confidence_score: 0.7,
          materiality_score: 0.8,
          status: "DRAFT / COUNSEL REVIEW REQUIRED",
          counsel_review_required: true,
          recommended_next_review_step: "Review sources.",
        },
      ],
      evidence_binders: [
        {
          id: "binder-01",
          title: "Core pleadings",
          purpose: "Core records.",
          document_count: 4,
          review_priority: "normal",
          locked_restricted_handling: "metadata-only",
        },
      ],
      contradiction_triage: [
        {
          id: "triage-01",
          contradiction_id: "alert-1",
          conflict_type: "tension",
          materiality_score: 0.75,
          confidence_score: 62,
          status: "DRAFT_CONTRADICTION_CANDIDATE",
          counsel_review_required: true,
          suggested_counsel_question: "Review?",
        },
      ],
      entity_dossier: [],
      counsel_questions: [
        {
          id: "question-01",
          category: "chronology verification",
          title: "Which chronology events are dispositive?",
          priority: "high",
          counsel_review_required: true,
        },
      ],
      action_checklist: [],
      consolidated_review_queue: [
        {
          id: "review-001",
          category: "locked/restricted metadata-only item",
          title: "Counsel-only locked document review",
          reason: "Locked document.",
          priority: "high",
          recommended_next_action: "Counsel review.",
          counsel_review_required: true,
        },
      ],
      privileged_locked_handling: {
        locked_restricted_count: 2,
        content_analyzed: false,
        handling: "metadata-only",
      },
    },
  }),
}));

import { CounselReviewWorkbench } from "@/app/(dashboard)/legal/cases/[slug]/_components/counsel-review-workbench";

describe("CounselReviewWorkbench", () => {
  it("renders draft counsel-review workbench panels and locked metadata handling", () => {
    render(<CounselReviewWorkbench slug="fortress-legal-production-review" />);

    expect(screen.getByText("Counsel Review Workbench")).toBeInTheDocument();
    expect(screen.getByText("DRAFT / COUNSEL REVIEW REQUIRED")).toBeInTheDocument();
    expect(screen.getByText("Claims / Defenses / Issues Matrix")).toBeInTheDocument();
    expect(screen.getAllByText("Evidence Binders").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Contradiction Triage").length).toBeGreaterThan(0);
    expect(screen.getByText("Counsel Questions / Actions")).toBeInTheDocument();
    expect(screen.getByText(/Locked\/restricted documents remain metadata-only/)).toBeInTheDocument();
  });
});
