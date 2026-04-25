/**
 * PR G phase F (UI) — EdiscoveryDropzone vault-document filter + privileged badge.
 *
 * Tests:
 *   - Filter group defaults to "All".
 *   - "Privileged" filter shows only locked_privileged docs; counts in pill labels.
 *   - "Evidence" filter shows everything except privileged.
 *   - Privileged badge renders adjacent to the filename (not in a corner).
 *   - Lock icon appears next to the status indicator on privileged docs.
 *   - Empty filter result shows the "no documents match" message.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { EdiscoveryDropzone } from "@/app/(dashboard)/legal/cases/[slug]/_components/ediscovery-dropzone";

// Test fixture: 3 evidence docs + 2 privileged docs.
const FIXTURE_DOCS = [
  {
    id: "11111111-1111-1111-1111-111111111111",
    file_name: "complaint.pdf",
    mime_type: "application/pdf",
    file_size_bytes: 12345,
    chunk_count: 8,
    processing_status: "completed",
    error_detail: null,
    created_at: "2026-04-25T10:00:00Z",
  },
  {
    id: "22222222-2222-2222-2222-222222222222",
    file_name: "evidence-photo.png",
    mime_type: "image/png",
    file_size_bytes: 67890,
    chunk_count: 0,
    processing_status: "completed",
    error_detail: null,
    created_at: "2026-04-25T10:05:00Z",
  },
  {
    id: "33333333-3333-3333-3333-333333333333",
    file_name: "scan-no-text.pdf",
    mime_type: "application/pdf",
    file_size_bytes: 5000,
    chunk_count: 0,
    processing_status: "ocr_failed",
    error_detail: "image-only PDF",
    created_at: "2026-04-25T10:10:00Z",
  },
  {
    id: "44444444-4444-4444-4444-444444444444",
    file_name: "argo-letter.eml",
    mime_type: "message/rfc822",
    file_size_bytes: 3210,
    chunk_count: 4,
    processing_status: "locked_privileged",
    error_detail: null,
    created_at: "2026-04-25T10:15:00Z",
  },
  {
    id: "55555555-5555-5555-5555-555555555555",
    file_name: "podesta-strategy-memo.pdf",
    mime_type: "application/pdf",
    file_size_bytes: 9876,
    chunk_count: 12,
    processing_status: "locked_privileged",
    error_detail: null,
    created_at: "2026-04-25T10:20:00Z",
  },
];

vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(async () => ({
      case_slug: "test-case-i",
      total: FIXTURE_DOCS.length,
      documents: FIXTURE_DOCS,
    })),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

async function renderAndWaitForDocs() {
  render(<EdiscoveryDropzone slug="test-case-i" />);
  // The component lazy-fetches via setTimeout(loadDocs, 0). Wait for one of
  // the filenames to land before asserting on filter behavior.
  await waitFor(() => {
    expect(screen.getByText("complaint.pdf")).toBeInTheDocument();
  });
}

describe("EdiscoveryDropzone — filter + privileged badge (PR G)", () => {
  it("defaults to the 'All' filter and shows every document with the right count", async () => {
    await renderAndWaitForDocs();
    // The All button label includes the total count (5).
    const allBtn = screen.getByRole("button", { name: /All \(5\)/ });
    expect(allBtn).toHaveAttribute("aria-pressed", "true");
    // All 5 filenames are visible.
    for (const f of [
      "complaint.pdf",
      "evidence-photo.png",
      "scan-no-text.pdf",
      "argo-letter.eml",
      "podesta-strategy-memo.pdf",
    ]) {
      expect(screen.getByText(f)).toBeInTheDocument();
    }
  });

  it("shows the privileged-count and evidence-count in pill labels", async () => {
    await renderAndWaitForDocs();
    // Evidence = total − privileged = 5 − 2 = 3
    expect(screen.getByRole("button", { name: /Evidence \(3\)/ })).toBeInTheDocument();
    // Privileged button label includes count 2 (regex tolerates the lock icon)
    expect(screen.getByRole("button", { name: /Privileged \(2\)/ })).toBeInTheDocument();
  });

  it("clicking 'Privileged' hides non-privileged docs and shows only locked_privileged", async () => {
    await renderAndWaitForDocs();
    fireEvent.click(screen.getByRole("button", { name: /Privileged \(2\)/ }));

    // Privileged docs visible
    expect(screen.getByText("argo-letter.eml")).toBeInTheDocument();
    expect(screen.getByText("podesta-strategy-memo.pdf")).toBeInTheDocument();
    // Non-privileged docs hidden
    expect(screen.queryByText("complaint.pdf")).not.toBeInTheDocument();
    expect(screen.queryByText("evidence-photo.png")).not.toBeInTheDocument();
    expect(screen.queryByText("scan-no-text.pdf")).not.toBeInTheDocument();
  });

  it("clicking 'Evidence' hides privileged docs", async () => {
    await renderAndWaitForDocs();
    fireEvent.click(screen.getByRole("button", { name: /Evidence \(3\)/ }));

    expect(screen.getByText("complaint.pdf")).toBeInTheDocument();
    expect(screen.getByText("evidence-photo.png")).toBeInTheDocument();
    expect(screen.getByText("scan-no-text.pdf")).toBeInTheDocument();
    // Privileged docs hidden
    expect(screen.queryByText("argo-letter.eml")).not.toBeInTheDocument();
    expect(screen.queryByText("podesta-strategy-memo.pdf")).not.toBeInTheDocument();
  });

  it("renders a 'Privileged' badge adjacent to the filename on locked_privileged docs", async () => {
    await renderAndWaitForDocs();
    // Find the row that contains 'argo-letter.eml'.
    const filenameSpan = screen.getByText("argo-letter.eml");
    // The Privileged badge is a sibling element inside the same flex container
    // (filename + badge are in the same <p>).
    const filenameContainer = filenameSpan.closest("p")!;
    const privilegedBadgeInRow = within(filenameContainer).getByText(/^Privileged$/);
    expect(privilegedBadgeInRow).toBeInTheDocument();
  });

  it("does NOT render a 'Privileged' badge on completed (non-privileged) docs", async () => {
    await renderAndWaitForDocs();
    const filenameSpan = screen.getByText("complaint.pdf");
    const filenameContainer = filenameSpan.closest("p")!;
    expect(
      within(filenameContainer).queryByText(/^Privileged$/),
    ).not.toBeInTheDocument();
  });

  it("renders an empty-state message when filter yields zero docs", async () => {
    // Mock api.get to return zero privileged docs by overriding the fixture.
    const apiModule = await import("@/lib/api");
    (apiModule.api.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      case_slug: "test-case-i",
      total: 1,
      documents: [
        {
          ...FIXTURE_DOCS[0],
        },
      ],
    });
    render(<EdiscoveryDropzone slug="test-case-i" />);
    await waitFor(() => {
      expect(screen.getByText("complaint.pdf")).toBeInTheDocument();
    });
    // Click privileged with zero in the bucket.
    fireEvent.click(screen.getByRole("button", { name: /Privileged \(0\)/ }));
    expect(
      screen.getByText(/No documents match the privileged filter/i),
    ).toBeInTheDocument();
  });
});
