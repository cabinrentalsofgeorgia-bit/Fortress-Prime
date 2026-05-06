import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/store", () => ({
  useAppStore: (selector: (state: { user: { id: number; role: string } }) => unknown) =>
    selector({ user: { id: 1, role: "super_admin" } }),
}));

vi.mock("@/lib/roles", () => ({
  canManageLegalOps: () => true,
}));

vi.mock("@/components/access/role-gated-action", () => ({
  RoleGatedAction: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/legal-hooks", () => ({
  useCaseVaultDocuments: () => ({
    isLoading: false,
    error: null,
    data: {
      case_slug: "fortress-legal-production-review",
      total: 3,
      documents: [
        {
          id: "doc-1",
          file_name: "completed-a.pdf",
          mime_type: "application/pdf",
          file_size_bytes: 2048,
          chunk_count: 12,
          processing_status: "completed",
          created_at: "2026-05-06T01:54:00Z",
        },
        {
          id: "doc-2",
          file_name: "completed-b.pdf",
          mime_type: "application/pdf",
          file_size_bytes: 4096,
          chunk_count: 18,
          processing_status: "completed",
          created_at: "2026-05-06T01:55:00Z",
        },
        {
          id: "doc-3",
          file_name: "privileged.pdf",
          mime_type: "application/pdf",
          file_size_bytes: 1024,
          chunk_count: 4,
          processing_status: "locked_privileged",
          created_at: "2026-05-06T01:56:00Z",
        },
      ],
    },
  }),
  useCaseCorrespondence: () => ({ data: { correspondence: [], total: 0 }, isLoading: false }),
  useCaseTimeline: () => ({ data: [], isLoading: false }),
  useUpdateCorrespondenceStatus: () => ({ mutate: vi.fn(), isPending: false }),
  downloadCorrespondence: vi.fn(),
  copyCorrespondenceContent: vi.fn(),
}));

import { DocumentViewer } from "@/app/(dashboard)/legal/cases/[slug]/_components/document-viewer";
import type { LegalCase } from "@/lib/legal-types";

const legalCase: LegalCase = {
  id: 26,
  case_slug: "fortress-legal-production-review",
  case_number: "REVIEW-2026-05-05",
  case_name: "Fortress Legal Production Review",
  risk_score: null,
  extraction_status: "complete",
};

describe("DocumentViewer autonomous vault metadata", () => {
  it("renders autonomous intake document metadata and locked privileged rows without contents", () => {
    render(<DocumentViewer legalCase={legalCase} slug="fortress-legal-production-review" />);

    expect(screen.getByRole("tab", { name: /documents/i })).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("completed-a.pdf")).toBeInTheDocument();
    expect(screen.getByText("completed-b.pdf")).toBeInTheDocument();
    expect(screen.getByText("privileged.pdf")).toBeInTheDocument();
    expect(screen.getAllByText("2")).toHaveLength(1);
    expect(screen.getAllByText("1")).toHaveLength(1);
    expect(screen.getByText("locked/restricted")).toBeInTheDocument();
    expect(screen.getByText("Privileged content remains restricted. Metadata only.")).toBeInTheDocument();
    expect(screen.queryByText(/Synthetic review shell only/i)).not.toBeInTheDocument();
  });
});
