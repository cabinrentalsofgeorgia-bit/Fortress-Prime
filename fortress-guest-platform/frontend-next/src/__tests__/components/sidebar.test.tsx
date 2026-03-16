import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

vi.mock("next/link", () => ({
  __esModule: true,
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

import { Sidebar } from "@/components/sidebar";

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("Sidebar", () => {
  it("renders core navigation links (mobile + desktop duplicates)", () => {
    render(<Sidebar />, { wrapper: Wrapper });

    for (const label of ["Reservations", "Properties", "Guests", "Messages", "Housekeeping"]) {
      const items = screen.getAllByText(label);
      expect(items.length).toBeGreaterThanOrEqual(1);
    }
  });

  it("renders damage claims link", () => {
    render(<Sidebar />, { wrapper: Wrapper });
    const items = screen.getAllByText("Damage Claims");
    expect(items.length).toBeGreaterThanOrEqual(1);
  });
});
