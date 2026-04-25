/**
 * PR G phase F (UI) — Case Detail header rendering of privilege metadata.
 *
 * Tests verify the header section renders:
 *   - privileged_counsel_domains as one purple badge per domain
 *   - related_matters as in-app links to the peer case slug
 *   - case_phase as an outline pill
 *   - Nothing privileged-related when arrays are empty/null/undefined
 *
 * Strategy: render CaseDetailShell with all hooks mocked so render doesn't
 * cascade. Sub-components that aren't part of the assertion target are
 * stubbed to no-op divs.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ── Mock every hook + sub-component case-detail-shell pulls in.
//    Sub-components are stubbed to keep DOM small + assertions fast.
vi.mock("@/lib/legal-hooks", () => ({
  useCaseGraph: () => ({ data: null, isLoading: false }),
  useCaseDetail: () => ({ data: null, isLoading: false, error: null }),
  useCaseExtractionPoll: () => ({ data: null, refetch: vi.fn() }),
  useDiscoveryPacks: () => ({ data: [], isLoading: false }),
  useGenerateDiscoveryDraftPack: () => ({ mutate: vi.fn(), isPending: false }),
  useDepositionKillSheets: () => ({ data: [], isLoading: false }),
  useSanctionsAlerts: () => ({ data: [], isLoading: false }),
  downloadKillSheetMarkdown: vi.fn(),
}));
vi.mock("@/lib/store", () => ({
  useAppStore: (selector: (state: { user: { id: number; role: string } }) => unknown) =>
    selector({ user: { id: 1, role: "admin" } }),
}));
vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/lib/roles", () => ({
  canManageLegalOps: () => true,
}));
vi.mock("@tanstack/react-query", async () => {
  const actual: Record<string, unknown> = await vi.importActual("@tanstack/react-query");
  return { ...actual, useQueryClient: () => ({ invalidateQueries: vi.fn() }) };
});
// Stub heavy sub-components to keep tests fast + focused on the header.
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/graph-snapshot-card", () => ({
  GraphSnapshotCard: () => <div data-testid="graph-snapshot-card" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/master-timeline", () => ({
  MasterTimeline: () => <div data-testid="master-timeline" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/inference-radar", () => ({
  InferenceRadar: () => <div data-testid="inference-radar" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/evidence-upload", () => ({
  EvidenceUpload: () => <div data-testid="evidence-upload" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/counsel-threat-matrix", () => ({
  CounselThreatMatrix: () => <div data-testid="counsel-threat-matrix" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/discovery-draft-panel", () => ({
  DiscoveryDraftPanel: () => <div data-testid="discovery-draft-panel" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/deposition-prep-panel", () => ({
  DepositionPrepPanel: () => <div data-testid="deposition-prep-panel" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/sanctions-tripwire-panel", () => ({
  SanctionsTripwirePanel: () => <div data-testid="sanctions-tripwire-panel" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/deposition-war-room", () => ({
  DepositionWarRoomModal: () => <div data-testid="deposition-war-room" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/jurisprudence-radar", () => ({
  JurisprudenceRadar: () => <div data-testid="jurisprudence-radar" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/document-viewer", () => ({
  DocumentViewer: () => <div data-testid="document-viewer" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/extraction-panel", () => ({
  ExtractionPanel: () => <div data-testid="extraction-panel" />,
}));
vi.mock("@/app/(dashboard)/legal/cases/[slug]/_components/hitl-deadline-queue", () => ({
  HitlDeadlineQueue: () => <div data-testid="hitl-deadline-queue" />,
}));
vi.mock("@/components/access/role-gated-action", () => ({
  RoleGatedAction: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import { CaseDetailShell } from "@/app/(dashboard)/legal/cases/[slug]/_components/case-detail-shell";
import * as legalHooks from "@/lib/legal-hooks";

const BASE_CASE_FIELDS = {
  id: 99,
  case_slug: "test-case-i",
  case_number: "1:99-cv-99999-XXX",
  case_name: "Test Case I",
  court: "U.S. District Court NDGA",
  judge: "Hon. Test Judge",
  case_type: "civil",
  our_role: "defendant",
  status: "closed_judgment_against",
  risk_score: 5,
  extraction_status: "complete" as const,
  extracted_entities: { risk_score: 5, parties: [], amounts: [], key_claims: [], deadlines: [] },
  critical_date: null,
  critical_note: null,
  notes: null,
  our_claim_basis: null,
  days_remaining: null,
};

function setUseCaseDetail(caseFields: Record<string, unknown>): void {
  vi.spyOn(legalHooks, "useCaseDetail").mockReturnValue({
    data: {
      case: { ...BASE_CASE_FIELDS, ...caseFields },
      deadlines: [],
      recent_actions: [],
      evidence: [],
    },
    isLoading: false,
    error: null,
    // Tests don't exercise these but the type expects them; cast through unknown.
  } as unknown as ReturnType<typeof legalHooks.useCaseDetail>);
}

describe("CaseDetailShell — privilege metadata in header (PR G)", () => {
  it("renders one badge per privileged_counsel_domain in the header", () => {
    setUseCaseDetail({
      privileged_counsel_domains: ["mhtlegal.com", "fgplaw.com", "dralaw.com"],
    });
    render(<CaseDetailShell slug="test-case-i" />);
    // The "Privileged counsel:" label should be present
    expect(screen.getByText(/Privileged counsel:/i)).toBeInTheDocument();
    // One badge per domain
    expect(screen.getByText("mhtlegal.com")).toBeInTheDocument();
    expect(screen.getByText("fgplaw.com")).toBeInTheDocument();
    expect(screen.getByText("dralaw.com")).toBeInTheDocument();
  });

  it("renders nothing for the privileged-counsel block when the array is empty", () => {
    setUseCaseDetail({ privileged_counsel_domains: [] });
    render(<CaseDetailShell slug="test-case-i" />);
    expect(screen.queryByText(/Privileged counsel:/i)).not.toBeInTheDocument();
  });

  it("renders nothing for the privileged-counsel block when the field is null/undefined", () => {
    setUseCaseDetail({ privileged_counsel_domains: null });
    render(<CaseDetailShell slug="test-case-i" />);
    expect(screen.queryByText(/Privileged counsel:/i)).not.toBeInTheDocument();
  });

  it("renders related_matters as anchor links pointing at /legal/cases/<slug>", () => {
    setUseCaseDetail({
      related_matters: ["test-case-ii", "test-case-iii"],
    });
    render(<CaseDetailShell slug="test-case-i" />);
    const link1 = screen.getByRole("link", { name: "test-case-ii" });
    expect(link1).toHaveAttribute("href", "/legal/cases/test-case-ii");
    const link2 = screen.getByRole("link", { name: "test-case-iii" });
    expect(link2).toHaveAttribute("href", "/legal/cases/test-case-iii");
  });

  it("renders nothing for related_matters when the array is empty", () => {
    setUseCaseDetail({ related_matters: [] });
    render(<CaseDetailShell slug="test-case-i" />);
    expect(screen.queryByText(/Related matters:/i)).not.toBeInTheDocument();
  });

  it("renders case_phase as a badge with underscores transformed to spaces", () => {
    setUseCaseDetail({ case_phase: "counsel_search" });
    render(<CaseDetailShell slug="test-case-i" />);
    // Header pill: "counsel search" (the " " replacement of underscores).
    expect(screen.getByText("counsel search")).toBeInTheDocument();
  });

  it("renders nothing for case_phase when null", () => {
    setUseCaseDetail({ case_phase: null });
    render(<CaseDetailShell slug="test-case-i" />);
    // No phase pill — but other content (case_name) still rendered, so smoke-check that.
    expect(screen.getByText("Test Case I")).toBeInTheDocument();
    // The phase string we'd expect under the spec ("counsel search") is absent.
    expect(screen.queryByText(/^counsel search$/)).not.toBeInTheDocument();
  });
});
