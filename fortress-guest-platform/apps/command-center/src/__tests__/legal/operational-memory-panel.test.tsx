import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/legal-hooks", () => ({
  useOperationalMemory: () => ({
    isLoading: false,
    error: null,
    data: {
      schemaVersion: "1.0.0",
      matterSlug: "fortress-legal-production-review",
      status: "OPERATIONAL_MEMORY_VISIBLE_READ_ONLY",
      standingLabels: {
        counselStatus: "COUNSEL_SIGNOFF_PENDING",
        externalSubmissionAuthority: "NOT_AUTHORIZED",
        legalAdviceStatus: "NOT FINAL LEGAL ADVICE",
      },
      governanceBoundaries: ["human_review_required", "registry_not_legal_authority"],
      validationStatus: { status: "PASS", registryValidation: true },
      summary: {
        capabilityCount: 10,
        evidenceDirectoryCount: 11,
        wikiKnowledgeEntries: 4,
        reviewerFeedbackEntries: 0,
        unresolvedSourceIssues: 232,
        reviewerLedgerMode: "empty_ledger_foundation",
        graphNodeCount: 16,
        graphEdgeCount: 13,
        graphValidationOk: true,
        governanceQueryCount: 18,
        contextPackCount: 7,
        agentAllowedActionCount: 15,
        agentForbiddenActionCount: 15,
        agentHardStopCount: 8,
        agentPlanCount: 1,
        agentReportCount: 1,
      },
      registries: {
        operational_state: {},
        capabilities: {
          capabilities: [
            {
              id: "human_operations",
              status: "complete_pending_review",
              maturityLevel: "controlled_operations",
              limitations: ["counsel_signoff_pending"],
            },
          ],
        },
        governance: {
          forbiddenOperations: [
            "auto_signoff",
            "final_legal_conclusion",
            "filing_service_email_external_submission",
          ],
          hardStops: ["secrets_exposure_risk"],
        },
        evidence: {
          evidenceDirectories: [{ phase: "capability_audit", path: "docs/evidence", status: "present" }],
        },
        remediation: {
          unresolvedSourceIssues: 232,
          unresolvedSourceExclusionStatus: "EXCLUDED_FROM_RELIED_UPON_SECTIONS",
          noAutoResolution: true,
          categories: ["missing_source", "contradictory_source"],
        },
        reviewer_feedback_ledger: {
          ledgerPurpose: "EMPTY_LEDGER_FOUNDATION",
          allowedFeedbackTypes: ["navigation_friction", "governance_boundary_question"],
          prohibitedFeedbackContent: ["confidential_legal_text", "auth_or_secret_values"],
          noFreeformLegalText: true,
          entries: [],
        },
        wiki_knowledge_index: {
          entries: [
            {
              path: "docs/architecture/fortress-legal-operational-index.md",
              category: "current_operational_index",
              freshness: "current",
            },
          ],
        },
        validation_report: { ok: true, errors: [], warnings: [] },
      },
      negativeControls: {
        noSecrets: true,
        noConfidentialText: true,
        noCounselSignoffAuthority: true,
        noFinalLegalConclusionAuthority: true,
        noExternalSubmissionAuthority: true,
        noSourcePromotion: true,
        noSchemaRlsPolicyMutation: true,
        noGraphLegalAuthority: true,
        readOnly: true,
      },
      graph: {
        status: "OPERATIONAL_GRAPH_VISIBLE_READ_ONLY",
        summary: {
          nodeCount: 16,
          edgeCount: 13,
          governanceNodes: 2,
          remediationNodes: 3,
          evidenceNodes: 1,
          deploymentNodes: 2,
          wikiGraphNodes: 8,
          evidenceGraphNodes: 11,
        },
        nodes: [
          { id: "governance:no_signoff", type: "governance_boundary", label: "No counsel signoff authority" },
          { id: "remediation:unresolved_232", type: "remediation_issue", label: "232 unresolved source issues excluded" },
        ],
        edges: [
          {
            id: "edge:remediation_excluded_by_governance",
            type: "excluded_by",
            from: "remediation:unresolved_232",
            to: "governance:no_signoff",
            label: "unresolved sources excluded by governance",
          },
        ],
        validation: {
          ok: true,
          nodeCount: 16,
          edgeCount: 13,
          noSecrets: true,
          noConfidentialText: true,
          governancePreserved: true,
        },
      },
      governanceQueryEngine: {
        status: "GOVERNANCE_QUERY_ENGINE_VISIBLE_READ_ONLY",
        queryCount: 18,
        queries: ["standing_state", "safe_next_actions", "agent_operating_context"],
        safeNextActions: [{ action: "Review operational graph and query engine evidence" }],
        forbiddenOperations: ["auto_signoff", "final_legal_conclusion", "filing_service_email_external_submission"],
        signoffBlockers: ["COUNSEL_SIGNOFF_PENDING", "232_unresolved_source_issues_excluded"],
        launchBlockers: ["NOT_AUTHORIZED", "public_launch_forbidden"],
        agentContext: {
          safeOperatingMode: "read_only_governance_query_engine_and_agent_context",
          nextRecommendedPhase: "controlled_governance_query_review_and_agent_context_use",
          readFirst: ["docs/architecture/governance-query-engine-architecture-2026-05-06.md"],
          validationCommands: ["node validate"],
          knownBlockers: ["232_unresolved_source_issues_excluded"],
        },
        contextPacks: [
          {
            contextPackType: "codex-session",
            readFirst: [],
            safeNextActions: [],
            forbiddenActionCount: 3,
            noSecrets: true,
            noConfidentialText: true,
          },
        ],
      },
      agentOrchestration: {
        status: "AGENT_ORCHESTRATION_VISIBLE_READ_ONLY",
        allowedActions: [
          { id: "read_operational_state", category: "read_only", riskClass: "safe_read_only" },
          { id: "run_checker", category: "validation", riskClass: "safe_validation_only" },
        ],
        forbiddenActions: [
          { id: "legal_signoff", category: "legal_authority", riskClass: "hard_stop" },
          { id: "external_submission", category: "external_authority", riskClass: "hard_stop" },
        ],
        hardStops: [
          { id: "secrets_exposure", trigger: "secret_or_auth_material_requested", requiredAction: "stop_and_report" },
          { id: "legal_authority", trigger: "signoff_final_advice_or_external_submission_requested", requiredAction: "stop_and_report" },
        ],
        riskClassifications: [
          { id: "safe_read_only", description: "Reads metadata-only operational memory.", humanReviewRequired: false },
          { id: "hard_stop", description: "Blocked by policy.", humanReviewRequired: true },
        ],
        validationGates: [
          { id: "validate_agent_orchestration", purpose: "Validate boundaries.", requiredFor: ["all"] },
        ],
        evidenceRequirements: [
          { id: "task_plan", description: "Task plan JSON.", prohibitedContent: ["secrets"] },
        ],
        latestPlans: [
          {
            planId: "agent-plan-test",
            taskId: "agent-task-test",
            riskClass: "safe_docs_only",
            validationGates: ["validate_agent_orchestration"],
            humanReviewRequired: true,
          },
        ],
        latestReports: [
          {
            reportId: "agent-report-test",
            taskId: "agent-task-test",
            planId: "agent-plan-test",
            hardStopsEncountered: [],
            humanReviewRequired: true,
          },
        ],
        validation: { ok: true, errors: [], warnings: [], governancePreserved: true },
        governanceAssertions: {
          noSecrets: true,
          noConfidentialText: true,
          noLegalAuthority: true,
          noExternalAuthority: true,
          noSchemaMutation: true,
          noSourcePromotion: true,
        },
      },
      autonomousRehearsal: {
        status: "AUTONOMOUS_REHEARSAL_VISIBLE_READ_ONLY",
        allowedCategories: ["validation-only", "governance-query", "rollback-tabletop"],
        forbiddenCategories: ["legal_signoff", "external_submission", "schema_mutation"],
        summary: {
          traceCount: 10,
          replayCount: 10,
          hardStopCount: 1,
          blockedActionCount: 0,
          validationGatePassCount: 40,
          allReplaysValidated: true,
        },
        latestTraces: [
          {
            dryRunId: "dry-run-validation-only-test",
            category: "validation-only",
            status: "simulated",
            hardStopsTriggered: [],
            blockedActions: [],
          },
          {
            dryRunId: "dry-run-external-submission-test",
            category: "external_submission",
            status: "hard_stop",
            hardStopsTriggered: ["external_authority_forbidden"],
            blockedActions: [],
          },
        ],
        latestReplays: [
          {
            replayId: "replay-dry-run-validation-only-test",
            dryRunId: "dry-run-validation-only-test",
            ok: true,
            governancePreserved: true,
          },
        ],
        governanceAssertions: {
          noSecrets: true,
          noConfidentialText: true,
          noLegalAuthority: true,
          noExternalAuthority: true,
          noSchemaMutation: true,
          noSourcePromotion: true,
          nonDestructiveDryRunOnly: true,
        },
      },
    },
  }),
}));

import { OperationalMemoryPanel } from "@/app/(dashboard)/legal/cases/[slug]/_components/operational-memory-panel";

describe("OperationalMemoryPanel", () => {
  it("renders machine-readable operational memory with governance boundaries", () => {
    render(<OperationalMemoryPanel slug="fortress-legal-production-review" />);

    expect(screen.getByText("Operational Memory / Machine-Readable Cognition")).toBeInTheDocument();
    expect(screen.getByText("COUNSEL_SIGNOFF_PENDING")).toBeInTheDocument();
    expect(screen.getByText("NOT_AUTHORIZED")).toBeInTheDocument();
    expect(screen.getByText("NOT FINAL LEGAL ADVICE")).toBeInTheDocument();
    expect(screen.getByText("Governance Registry")).toBeInTheDocument();
    expect(screen.getByText("Remediation Registry")).toBeInTheDocument();
    expect(screen.getByText("Reviewer Feedback Ledger Foundation")).toBeInTheDocument();
    expect(screen.getByText("Capability Registry")).toBeInTheDocument();
    expect(screen.getByText("Evidence Registry")).toBeInTheDocument();
    expect(screen.getByText("Wiki / App / Evidence Knowledge Index")).toBeInTheDocument();
    expect(screen.getByText("Operational Knowledge Graph / Queryable Governance")).toBeInTheDocument();
    expect(screen.getByText("operationalGraph true")).toBeInTheDocument();
    expect(screen.getByText("graph-as-operational-cognition, not legal authority")).toBeInTheDocument();
    expect(screen.getByText("Graph Entities")).toBeInTheDocument();
    expect(screen.getByText("Graph Relationships")).toBeInTheDocument();
    expect(screen.getByText("Governance Query Engine / Agent Operating Context")).toBeInTheDocument();
    expect(screen.getByText("governanceQueryEngine true")).toBeInTheDocument();
    expect(screen.getByText("query-engine-as-operational-guidance, not legal authority")).toBeInTheDocument();
    expect(screen.getAllByText("Safe Next Actions").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Forbidden Actions").length).toBeGreaterThan(0);
    expect(screen.getByText("Agent Operating Context")).toBeInTheDocument();
    expect(screen.getByText("Agent Execution Governance / Safe Task Orchestration")).toBeInTheDocument();
    expect(screen.getByText("agentOrchestration true")).toBeInTheDocument();
    expect(screen.getByText("governed operations, not legal authority")).toBeInTheDocument();
    expect(screen.getByText("Allowed Agent Actions")).toBeInTheDocument();
    expect(screen.getByText("Hard Stop Policies")).toBeInTheDocument();
    expect(screen.getByText("Task Risk Classifier / Plan Validation")).toBeInTheDocument();
    expect(screen.getByText("Latest Agent Plans")).toBeInTheDocument();
    expect(screen.getByText("Execution Reports")).toBeInTheDocument();
    expect(screen.getByText("Autonomous Operations Rehearsal / Governed Dry-Runs")).toBeInTheDocument();
    expect(screen.getByText("autonomousRehearsal true")).toBeInTheDocument();
    expect(screen.getByText("dryRunExecution true")).toBeInTheDocument();
    expect(screen.getByText("dry-run-only, not legal authority")).toBeInTheDocument();
    expect(screen.getByText("Allowed Dry-Run Categories")).toBeInTheDocument();
    expect(screen.getByText("Forbidden Dry-Run Categories")).toBeInTheDocument();
    expect(screen.getByText("hardStopEnforcement true")).toBeInTheDocument();
    expect(screen.getByText("blockedActionHandling true")).toBeInTheDocument();
    expect(screen.getByText("governanceAssertionVisibility true")).toBeInTheDocument();
    expect(screen.getAllByText("Replay Validation").length).toBeGreaterThan(0);
    expect(screen.getByText("EXCLUDED FROM RELIED UPON SECTIONS / no auto resolution true.")).toBeInTheDocument();
    expect(screen.getByText(/ledger foundation \/ no freeform legal text true\./i)).toBeInTheDocument();
  });
});
