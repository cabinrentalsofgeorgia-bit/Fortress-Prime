import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

let mockPathname = "/analytics";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

vi.mock("next/link", () => ({
  __esModule: true,
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

import { Sidebar } from "@/components/sidebar";
import { useAppStore } from "@/lib/store";

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("Sidebar", () => {
  beforeEach(() => {
    mockPathname = "/analytics";
    useAppStore.setState({
      user: {
        id: "1",
        email: "ops@example.com",
        first_name: "Ops",
        last_name: "Manager",
        role: "manager",
      },
      sidebarCollapsed: false,
    });
  });

  it("renders CROG-VRS navigation for an ops manager", () => {
    render(<Sidebar />, { wrapper: Wrapper });

    for (const label of [
      "Operations Dashboard",
      "Reservations & Calendar",
      "Guest CRM",
      "Communications",
      "Housekeeping Dispatch",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("hides restricted legal and telemetry routes for an ops manager", () => {
    render(<Sidebar />, { wrapper: Wrapper });

    expect(screen.queryByText("Iron Dome Ledger")).not.toBeInTheDocument();
    expect(screen.queryByText("E-Discovery Vault")).not.toBeInTheDocument();
    expect(screen.queryByText("Damage Claims")).not.toBeInTheDocument();
  });

  it("shows legal routes for a legal user and hides operations routes", () => {
    useAppStore.setState({
      user: {
        id: "2",
        email: "legal@example.com",
        first_name: "Legal",
        last_name: "Counsel",
        role: "legal",
      },
      sidebarCollapsed: false,
    });

    render(<Sidebar />, { wrapper: Wrapper });

    expect(screen.getByText("Active Dockets")).toBeInTheDocument();
    expect(screen.getByText("E-Discovery Vault")).toBeInTheDocument();
    expect(screen.queryByText("Reservations & Calendar")).not.toBeInTheDocument();
    expect(screen.queryByText("Iron Dome Ledger")).not.toBeInTheDocument();
  });
});
