import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/lib/hooks", () => ({
  useAdminInsights: () => ({
    data: {
      items: [
        {
          id: "operational_overview",
          title: "Operational overview",
          summary: "Live operational summary.",
          metrics: {
            occupancy_rate: 60,
            revenue_mtd: 18450.25,
            unread_messages: 7,
          },
        },
        {
          id: "revenue_signal",
          title: "Revenue signal",
          summary: "Recent monthly revenue.",
          metrics: {
            months: [
              { month: "2026-03", revenue: 11250 },
              { month: "2026-02", revenue: 9800 },
            ],
          },
        },
        {
          id: "automation_signal",
          title: "Automation signal",
          summary: "Messaging automation summary.",
          metrics: {
            automation_rate_7d: 50,
            auto_outbound_messages_7d: 11,
            unread_inbound_messages: 7,
          },
        },
        {
          id: "maintenance_signal",
          title: "Maintenance signal",
          summary: "Open maintenance demand.",
          metrics: {
            open_work_orders: 4,
            urgent_work_orders: 1,
            top_open_categories: [
              { category: "hvac", count: 2 },
              { category: "plumbing", count: 1 },
            ],
          },
        },
      ],
    },
  }),
  useFleetStatus: () => ({
    data: {
      fleet: [],
      global_totals: {
        total_owner_funds: 1000,
        total_operating_funds: 500,
        total_pm_revenue_mtd: 250,
        properties_in_overdraft: 0,
        pending_capex_items: 0,
      },
    },
    isLoading: false,
    error: null,
  }),
  useUpdateSplit: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateMarkup: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminPendingCapex: () => ({ data: { items: [] }, isLoading: false }),
  useAdminApproveCapex: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminRejectCapex: () => ({ mutate: vi.fn(), isPending: false }),
  useChannexSyncInventory: () => ({
    mutate: vi.fn(),
    isPending: false,
    data: null,
    variables: undefined,
  }),
  useChannexHealth: () => ({
    data: {
      property_count: 1,
      healthy_count: 1,
      shell_ready_count: 1,
      catalog_ready_count: 1,
      ari_ready_count: 1,
      duplicate_rate_plan_count: 0,
      properties: [
        {
          property_id: "prop-1",
          property_name: "Bear Creek",
          slug: "bear-creek",
          shell_present: true,
          preferred_room_type_present: true,
          preferred_rate_plan_present: true,
          ari_availability_present: true,
          ari_restrictions_present: true,
          room_type_count: 1,
          rate_plan_count: 1,
          duplicate_rate_plan_count: 0,
        },
      ],
    },
    isLoading: false,
    error: null,
  }),
  useChannexHistory: () => ({
    data: {
      items: [],
      recent_partial_failure_count: 0,
    },
    isLoading: false,
    error: null,
  }),
  useChannexRemediation: () => ({
    mutate: vi.fn(),
    isPending: false,
    data: null,
    variables: undefined,
  }),
  useDispatchCapitalCall: () => ({ mutate: vi.fn(), isPending: false }),
  useOnboardOwner: () => ({ mutate: vi.fn(), isPending: false }),
  useAdminMarketingBudgets: () => ({
    data: {
      fleet_totals: {
        total_escrow: 0,
        total_ad_spend: 0,
        properties_enrolled: 0,
        properties_total: 0,
      },
      properties: [],
    },
  }),
}));

vi.mock("@/lib/store", () => ({
  useAppStore: (selector: (state: { user: { role: string } }) => unknown) =>
    selector({ user: { role: "admin" } }),
}));

vi.mock("@/lib/roles", () => ({
  canManageAdminOps: () => true,
  canManageContracts: () => true,
  canManageDisputes: () => true,
}));

vi.mock("@/components/access/role-gated-action", () => ({
  RoleGatedAction: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock(
  "@/app/(dashboard)/admin/components/ContractManagementPanel",
  () => ({
    default: () => <div>Contract panel</div>,
  }),
);

vi.mock(
  "@/app/(dashboard)/admin/components/DisputeExceptionDesk",
  () => ({
    default: () => <div>Dispute desk</div>,
  }),
);

import AdminOperationsGlass from "@/app/(dashboard)/admin/page";

describe("AdminOperationsGlass", () => {
  it("renders derived admin insight cards", () => {
    render(<AdminOperationsGlass />);

    expect(screen.getByText("Operational overview")).toBeInTheDocument();
    expect(screen.getByText("Revenue signal")).toBeInTheDocument();
    expect(screen.getByText("Automation signal")).toBeInTheDocument();
    expect(screen.getByText("Maintenance signal")).toBeInTheDocument();

    expect(screen.getByText("Occupancy 60%")).toBeInTheDocument();
    expect(screen.getByText("Revenue MTD $18,450.25")).toBeInTheDocument();
    expect(screen.getByText("2026-03: $11,250.00")).toBeInTheDocument();
    expect(screen.getByText("Automation 50%")).toBeInTheDocument();
    expect(screen.getByText("hvac: 2")).toBeInTheDocument();
  });
});
