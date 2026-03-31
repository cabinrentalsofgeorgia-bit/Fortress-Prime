import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

const {
  askMutateAsync,
  forecastMutateAsync,
  maintenanceMutateAsync,
  listingMutateAsync,
} = vi.hoisted(() => ({
  askMutateAsync: vi.fn(),
  forecastMutateAsync: vi.fn(),
  maintenanceMutateAsync: vi.fn(),
  listingMutateAsync: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}));

vi.mock("@/lib/ai-hooks", () => ({
  buildAiForecastRequest: (reservations: Array<Record<string, unknown>> | undefined) => ({
    historical_data: reservations ?? [],
    forecast_months: 3,
  }),
  buildAiMaintenanceRequest: (
    workOrders: Array<Record<string, unknown>> | undefined,
    conversations: Array<Record<string, unknown>> | undefined,
  ) => ({
    work_orders: workOrders ?? [],
    messages: conversations ?? [],
  }),
  buildAiListingRequest: (properties: Array<Record<string, unknown>> | undefined) =>
    properties?.[0] ?? {
      property_name: "Fortress Prime Portfolio",
      bedrooms: 4,
      bathrooms: 3.5,
      max_guests: 10,
      amenities: ["hot tub", "mountain views", "fireplace", "fast wifi"],
      location: "Blue Ridge, GA",
    },
  useAiAsk: () => ({ mutateAsync: askMutateAsync, isPending: false }),
  useAiForecast: () => ({ mutateAsync: forecastMutateAsync, isPending: false }),
  useAiPredictMaintenance: () => ({ mutateAsync: maintenanceMutateAsync, isPending: false }),
  useAiOptimizeListing: () => ({ mutateAsync: listingMutateAsync, isPending: false }),
}));

vi.mock("@/lib/hooks", () => ({
  useProperties: () => ({
    data: [
      {
        property_name: "Ridgeline Cabin",
        bedrooms: 5,
        bathrooms: 4,
        max_guests: 12,
        amenities: [],
        location: "Blue Ridge, GA",
      },
    ],
  }),
  useReservations: () => ({
    data: [
      { month: "2026-01", revenue: 52500, reservation_count: 8 },
      { month: "2026-02", revenue: 48600, reservation_count: 7 },
    ],
  }),
  useWorkOrders: () => ({
    data: [
      {
        id: "wo-1",
        title: "HVAC inspection",
        status: "open",
      },
    ],
  }),
  useConversations: () => ({
    data: [
      {
        guest_id: "guest-1",
        last_message: "The upstairs heat is weak.",
        unread_count: 2,
      },
    ],
  }),
}));

import AiInsightsPage from "@/app/(dashboard)/analytics/insights/page";

describe("AiInsightsPage", () => {
  beforeEach(() => {
    askMutateAsync.mockReset();
    forecastMutateAsync.mockReset();
    maintenanceMutateAsync.mockReset();
    listingMutateAsync.mockReset();
  });

  it("sends the chat question using the backend ask contract", async () => {
    const user = userEvent.setup();
    askMutateAsync.mockResolvedValueOnce({ response: "Revenue is up 12%." });

    render(<AiInsightsPage />);

    await user.type(screen.getByPlaceholderText("Ask a question..."), "How is revenue?");
    await user.click(screen.getByRole("button", { name: "Send question" }));

    await waitFor(() =>
      expect(askMutateAsync).toHaveBeenCalledWith({
        question: "How is revenue?",
      }),
    );

    expect(await screen.findByText("Revenue is up 12%.")).toBeInTheDocument();
  });

  it("uses POST payloads for forecast, maintenance, and listing actions", async () => {
    const user = userEvent.setup();
    forecastMutateAsync.mockResolvedValueOnce({ summary: "Projected revenue remains strong." });
    maintenanceMutateAsync.mockResolvedValueOnce({ alerts: ["Watch HVAC units before summer turnover."] });
    listingMutateAsync.mockResolvedValueOnce({ suggestions: "Refine the listing headline and amenity framing." });

    render(<AiInsightsPage />);

    await user.click(screen.getByRole("button", { name: "Generate" }));
    await waitFor(() =>
      expect(forecastMutateAsync).toHaveBeenCalledWith({
        historical_data: [
          { month: "2026-01", revenue: 52500, reservation_count: 8 },
          { month: "2026-02", revenue: 48600, reservation_count: 7 },
        ],
        forecast_months: 3,
      }),
    );

    await user.click(screen.getByRole("button", { name: "Analyze" }));
    await waitFor(() =>
      expect(maintenanceMutateAsync).toHaveBeenCalledWith({
        work_orders: [
          {
            id: "wo-1",
            title: "HVAC inspection",
            status: "open",
          },
        ],
        messages: [
          {
            guest_id: "guest-1",
            last_message: "The upstairs heat is weak.",
            unread_count: 2,
          },
        ],
      }),
    );

    await user.click(screen.getByRole("button", { name: "Get Suggestions" }));
    await waitFor(() =>
      expect(listingMutateAsync).toHaveBeenCalledWith({
        property_name: "Ridgeline Cabin",
        bedrooms: 5,
        bathrooms: 4,
        max_guests: 12,
        amenities: [],
        location: "Blue Ridge, GA",
      }),
    );

    expect(await screen.findByText("Projected revenue remains strong.")).toBeInTheDocument();
    expect(await screen.findByText("Watch HVAC units before summer turnover.")).toBeInTheDocument();
    expect(await screen.findByText("Refine the listing headline and amenity framing.")).toBeInTheDocument();
  });
});
