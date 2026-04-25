/**
 * PR G phase F (UI) — Legal Council page FOR YOUR EYES ONLY warning rendering.
 *
 * Tests:
 *   - Banner does NOT render when contains_privileged=false (default state).
 *   - Banner renders when the hook flips contains_privileged=true.
 *   - Banner uses role="alert" + aria-live="polite" for screen readers.
 *   - Banner falls back to canonical text when the SSE payload didn't ship
 *     privileged_warning explicitly.
 *   - Banner uses the SSE-provided text when present.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

import LegalCouncilPage from "@/app/(dashboard)/legal/council/page";

// Mock the useCouncilStream hook so we can dial state directly.
const mockHookState = {
  jobId: null,
  sessionId: null,
  lastEventId: null,
  connectionState: "idle" as const,
  isStreaming: false,
  error: null,
  events: [],
  opinions: [],
  consensus: null,
  finalResult: null,
  contextFrozen: null,
  vaulted: null,
  containsPrivileged: false,
  privilegedWarning: null as string | null,
  hasActiveJob: false,
  streamLines: [] as Array<{ id: string; label: string; type: string; at: number }>,
  start: vi.fn(),
  stop: vi.fn(),
  reset: vi.fn(),
};
vi.mock("@/lib/use-council-stream", () => ({
  useCouncilStream: () => mockHookState,
}));

beforeEach(() => {
  // Reset state to baseline before each test.
  mockHookState.containsPrivileged = false;
  mockHookState.privilegedWarning = null;
});

describe("LegalCouncilPage — FYEO warning banner (PR G)", () => {
  it("does NOT render the FYEO banner when contains_privileged is false", () => {
    mockHookState.containsPrivileged = false;
    render(<LegalCouncilPage />);
    expect(screen.queryByText(/FOR YOUR EYES ONLY/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders the FYEO banner the moment contains_privileged flips true", () => {
    mockHookState.containsPrivileged = true;
    render(<LegalCouncilPage />);
    // Header text + warning body
    expect(screen.getByText(/FOR YOUR EYES ONLY/i)).toBeInTheDocument();
    expect(
      screen.getByText(/attorney-client privileged communications/i),
    ).toBeInTheDocument();
  });

  it("uses role=alert and aria-live=polite for accessibility (UI must announce when flag flips mid-deliberation)", () => {
    mockHookState.containsPrivileged = true;
    render(<LegalCouncilPage />);
    const banner = screen.getByRole("alert");
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveAttribute("aria-live", "polite");
  });

  it("falls back to canonical warning text when privilegedWarning is null", () => {
    mockHookState.containsPrivileged = true;
    mockHookState.privilegedWarning = null;
    render(<LegalCouncilPage />);
    expect(
      screen.getByText(
        /Do not use this output in court filings, share with opposing parties/i,
      ),
    ).toBeInTheDocument();
  });

  it("uses the SSE-provided privileged_warning text when present (so backend can change wording without UI redeploy)", () => {
    mockHookState.containsPrivileged = true;
    mockHookState.privilegedWarning =
      "CUSTOM WARNING TEXT — backend-provided override for testing.";
    render(<LegalCouncilPage />);
    expect(
      screen.getByText(/CUSTOM WARNING TEXT — backend-provided override/i),
    ).toBeInTheDocument();
  });

  it("renders a Privileged badge inside the banner header (visual cue separate from prose)", () => {
    mockHookState.containsPrivileged = true;
    render(<LegalCouncilPage />);
    // Badge text is "Privileged" — exact match, not part of the warning prose.
    const badges = screen.getAllByText(/^Privileged$/);
    expect(badges.length).toBeGreaterThanOrEqual(1);
  });
});
