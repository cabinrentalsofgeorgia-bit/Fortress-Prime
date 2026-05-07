import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useAutonomousLearning: () => ({
    isLoading: false,
    error: null,
    data: {
      execution_id: "fortress-learning-loop-test",
      created_at: "2026-05-06T17:00:00Z",
      case_slug: "fortress-legal-production-review",
      status: "AUTONOMOUS_LEARNING_LOOP_ACTIVE",
      cycle_cap: 3,
      cycles_completed: 2,
      learning_registry: {
        store: "file_manifest",
        signal_count: 2,
        signals: [
          {
            signal_id: "s1",
            signal_type: "source_link_failure",
            source_phase: "source_integrity",
            linked_item_id: "blockers",
            severity: "high",
            confidence: 0.9,
            suggested_improvement: "Review blockers",
            safe_auto_apply_eligible: false,
            human_approval_required: true,
            reason: "232 unresolved source issues remain.",
            status: "observed",
            created_at: "2026-05-06T17:00:00Z",
          },
        ],
      },
      evaluation_suite: {
        eval_count: 2,
        summary: { pass: 1, needs_human_review: 1 },
        results: [
          {
            eval_id: "auth-route-guard",
            category: "Auth",
            assertion: "unauthenticated legal APIs return 401/403",
            status: "pass",
            evidence: "401",
          },
        ],
      },
      improvement_proposals: {
        proposal_count: 2,
        safe_auto_apply_count: 1,
        human_approval_required_count: 1,
        blocked_count: 1,
        gate_results: [],
        proposals: [
          {
            proposal_id: "p1",
            proposal_type: "test_addition",
            title: "Add autonomous learning dashboard and API regression tests",
            description: "test",
            expected_benefit: "coverage",
            risk_level: "low",
            safe_auto_apply_eligible: true,
            human_approval_required: false,
            affected_files_or_routes: [],
            test_plan: [],
            rollback_plan: "revert",
            status: "safe_auto_apply_queue",
          },
        ],
      },
      safe_auto_apply_gate: {
        enabled: true,
        auto_apply_runtime_mutations: false,
        safe_auto_apply_proposal_ids: ["p1"],
        human_approval_required_proposal_ids: [],
      },
      feedback_capture: {
        enabled: true,
        feedback_records: [],
        note_policy: "no_secrets_no_full_document_text_no_locked_content",
      },
      next_best_actions: [
        {
          rank: 1,
          action: "Gary/counsel explicit decision on limited packet",
          reason: "pending",
          expected_impact: "decision",
          required_authority: "Gary/operator or counsel authenticated action",
          safe_auto_apply: false,
          rollback_plan: "versioned",
        },
      ],
      cycle_summaries: [],
    },
  }),
  useAutonomousLearningFeedback: () => ({
    isPending: false,
    mutate: vi.fn(),
  }),
}));

import { AutonomousLearningLoopPanel } from "@/app/(dashboard)/legal/cases/[slug]/_components/autonomous-learning-loop-panel";

describe("AutonomousLearningLoopPanel", () => {
  it("renders learning loop status and safety labels", () => {
    render(<AutonomousLearningLoopPanel slug="fortress-legal-production-review" />);

    expect(screen.getByText("Autonomous Learning Loop")).toBeInTheDocument();
    expect(screen.getByText("COUNSEL_SIGNOFF_PENDING")).toBeInTheDocument();
    expect(screen.getByText("NO EXTERNAL MODEL TRAINING")).toBeInTheDocument();
    expect(screen.getByText("EXTERNAL_SUBMISSION_NOT_AUTHORIZED")).toBeInTheDocument();
    expect(screen.getByText("Learning Signals")).toBeInTheDocument();
    expect(screen.getByText("Evaluation Suite Status")).toBeInTheDocument();
    expect(screen.getByText("Improvement Proposal Queue")).toBeInTheDocument();
    expect(screen.getByText("Feedback Capture")).toBeInTheDocument();
  });
});
