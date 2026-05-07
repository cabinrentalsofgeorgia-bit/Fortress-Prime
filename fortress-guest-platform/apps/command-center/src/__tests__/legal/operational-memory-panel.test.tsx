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
    expect(screen.getByText("EXCLUDED FROM RELIED UPON SECTIONS / no auto resolution true.")).toBeInTheDocument();
    expect(screen.getByText(/ledger foundation \/ no freeform legal text true\./i)).toBeInTheDocument();
  });
});
