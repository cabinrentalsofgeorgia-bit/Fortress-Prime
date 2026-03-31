import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const push = vi.fn();
const syncLedgerMutate = vi.fn();
const syncLedgerMutateAsync = vi.fn();
const autoScheduleMutate = vi.fn();
const dispatchHunterMutate = vi.fn();
const setDefconMutate = vi.fn();
const refreshCaseGraphMutate = vi.fn();
const sanctionsSweepMutate = vi.fn();
const overrideDispatchMutate = vi.fn();
const updateWorkOrderMutate = vi.fn();
const updateWorkOrderMutateAsync = vi.fn();
let mockPathname = "/analytics";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn() }),
  usePathname: () => mockPathname,
}));

vi.mock("@/components/ui/command", async () => {
  const React = await import("react");

  return {
    CommandDialog: ({
      open,
      children,
    }: {
      open: boolean;
      children: React.ReactNode;
    }) => (open ? <div>{children}</div> : null),
    CommandEmpty: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    CommandGroup: ({
      heading,
      children,
    }: {
      heading: string;
      children: React.ReactNode;
    }) => (
      <section>
        <h2>{heading}</h2>
        {children}
      </section>
    ),
    CommandInput: ({
      placeholder,
      value,
      onValueChange,
    }: {
      placeholder?: string;
      value?: string;
      onValueChange?: (value: string) => void;
    }) => {
      (globalThis as typeof globalThis & { __commandInputHandler?: (value: string) => void }).__commandInputHandler =
        onValueChange;

      return (
        <input
          aria-label="command-input"
          placeholder={placeholder}
          value={value}
          onChange={(event) => onValueChange?.(event.currentTarget.value)}
        />
      );
    },
    CommandItem: ({
      children,
      onSelect,
      disabled,
      value,
    }: {
      children: React.ReactNode;
      onSelect?: () => void;
      disabled?: boolean;
      value?: string;
    }) => (
      <button onClick={onSelect} disabled={disabled} data-command-value={value}>
        {children}
      </button>
    ),
    CommandList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    CommandSeparator: () => <hr />,
  };
});

vi.mock("@/lib/hooks", () => ({
  useProperties: () => ({ data: [] }),
  useGuests: () => ({
    data: [
      {
        id: "guest-44",
        phone_number: "+17065551212",
        email: "lena@example.com",
        first_name: "Lena",
        last_name: "North",
        full_name: "Lena North",
        total_stays: 2,
        language_preference: "en",
        opt_in_marketing: true,
        created_at: "2026-01-01",
      },
      {
        id: "guest-77",
        phone_number: "+17065550077",
        email: "lena.hart@example.com",
        first_name: "Lena",
        last_name: "Hart",
        full_name: "Lena Hart",
        total_stays: 1,
        language_preference: "en",
        opt_in_marketing: true,
        created_at: "2026-01-02",
      },
    ],
  }),
  useSyncVrsLedger: () => ({ mutate: syncLedgerMutate, mutateAsync: syncLedgerMutateAsync }),
  useAutoScheduleHousekeeping: () => ({ mutate: autoScheduleMutate }),
  useDispatchHunterTarget: () => ({ mutate: dispatchHunterMutate }),
  useOverrideVrsDispatch: () => ({ mutate: overrideDispatchMutate }),
  useSetDefcon: () => ({ mutate: setDefconMutate, isPending: false }),
  useVrsHunterTargets: () => ({
    data: [
      {
        guest_id: "guest-1",
        full_name: "Avery Ridge",
        email: "avery@example.com",
        lifetime_value: 12000,
        last_stay_date: "2026-03-01",
        days_dormant: 28,
        target_score: 91,
      },
    ],
    isLoading: false,
  }),
  useUpdateWorkOrder: () => ({ mutate: updateWorkOrderMutate, mutateAsync: updateWorkOrderMutateAsync }),
  useWorkOrders: () => ({
    data: [
      {
        id: "wo-9",
        ticket_number: "WO-1092",
        property_id: "prop-1",
        title: "Replace smart lock battery",
        description: "Front door battery is low",
        category: "electrical",
        priority: "high",
        status: "open",
        created_at: "2026-01-01",
      },
      {
        id: "wo-11",
        ticket_number: "WO-2200",
        property_id: "prop-2",
        title: "Repair deck lighting",
        description: "Exterior lights are out",
        category: "electrical",
        priority: "medium",
        status: "open",
        created_at: "2026-01-02",
      },
    ],
  }),
}));

vi.mock("@/lib/legal-hooks", () => ({
  useRefreshGraphMutation: () => ({ mutate: refreshCaseGraphMutate }),
  useRunSanctionsSweep: () => ({ mutate: sanctionsSweepMutate }),
  useLegalCases: () => ({
    data: {
      cases: [
        {
          case_slug: "generali-case",
          case_number: "2026-CV-100",
          case_name: "Generali v. Fortress Prime",
          risk_score: 74,
          extraction_status: "complete",
        },
      ],
    },
  }),
}));

import { useAppStore } from "@/lib/store";
import { CommandSearch } from "@/components/command-search";

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("CommandSearch", () => {
  beforeEach(() => {
    push.mockReset();
    syncLedgerMutate.mockReset();
    syncLedgerMutateAsync.mockReset();
    syncLedgerMutateAsync.mockResolvedValue(undefined);
    autoScheduleMutate.mockReset();
    dispatchHunterMutate.mockReset();
    setDefconMutate.mockReset();
    refreshCaseGraphMutate.mockReset();
    sanctionsSweepMutate.mockReset();
    overrideDispatchMutate.mockReset();
    updateWorkOrderMutate.mockReset();
    updateWorkOrderMutateAsync.mockReset();
    updateWorkOrderMutateAsync.mockImplementation(async (args) => {
      updateWorkOrderMutate(args);
      return undefined;
    });
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
      recentCommandHistory: [],
      commandAuditTrail: [],
      activeAdjudicationContext: null,
      activeWorkOrderContext: null,
      activeConversationContext: null,
      pinnedOperatorFocusKind: null,
      activeAdjudicationContextUpdatedAt: 0,
      activeWorkOrderContextUpdatedAt: 0,
      activeConversationContextUpdatedAt: 0,
    });
  });

  it("executes backend command actions from the palette", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /sync adjudication ledger/i }));

    expect(syncLedgerMutateAsync).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
  });

  it("still routes page commands through the router", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    expect(screen.getByText("> mode:root")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /operations dashboard/i }));

    expect(push).toHaveBeenCalledWith("/analytics");
  });

  it("surfaces recent replayable commands in the palette", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /system health/i }));

    await user.click(screen.getByRole("button", { name: /execute command/i }));

    const recentHeading = screen.getByText("RECENT");
    const recentGroup = recentHeading.parentElement;
    expect(recentGroup).not.toBeNull();
    expect(within(recentGroup!).getByText("System Health")).toBeInTheDocument();
    expect(within(recentGroup!).getByText(/20:navigated/i)).toBeInTheDocument();
    expect(within(recentGroup!).getByText(/just now/i)).toBeInTheDocument();
  });

  it("offers and replays the last safe command", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /system health/i }));

    push.mockClear();
    await user.click(screen.getByRole("button", { name: /execute command/i }));
    expect(screen.getByText("LAST SAFE")).toBeInTheDocument();
    const lastSafeHeading = screen.getByText("LAST SAFE");
    const lastSafeGroup = lastSafeHeading.parentElement;
    expect(lastSafeGroup).not.toBeNull();
    const repeatButton = within(lastSafeGroup!).getByRole("button", {
      name: /repeat last safe command/i,
    });
    expect(repeatButton).toBeInTheDocument();

    await user.click(repeatButton);

    expect(push).toHaveBeenCalledWith("/system-health");
  });

  it("shows an audit trail entry for palette navigation", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /system health/i }));

    await user.click(screen.getByRole("button", { name: /execute command/i }));

    const auditHeading = screen.getByText("AUDIT TRAIL");
    const auditGroup = auditHeading.parentElement;
    expect(auditGroup).not.toBeNull();
    expect(within(auditGroup!).getByText("System Health")).toBeInTheDocument();
    expect(within(auditGroup!).getByText(/navigated · just now/i)).toBeInTheDocument();
  });

  it("records replayed commands distinctly in the audit trail", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /system health/i }));

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    const recentHeading = screen.getByText("RECENT");
    const recentGroup = recentHeading.parentElement;
    await user.click(within(recentGroup!).getByRole("button", { name: /system health/i }));

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    const auditHeading = screen.getByText("AUDIT TRAIL");
    const auditGroup = auditHeading.parentElement;
    expect(auditGroup).not.toBeNull();
    expect(within(auditGroup!).getByText(/replayed · just now/i)).toBeInTheDocument();
  });

  it("supports audit scope filtering from the input", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /system health/i }));

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "audit:");

    expect(screen.getByText("AUDIT TRAIL")).toBeInTheDocument();
    expect(screen.queryByText("SHADOW OPS")).not.toBeInTheDocument();
    expect(screen.queryByText("RECENT")).not.toBeInTheDocument();
  });

  it("supports help scope filtering and shows command syntax", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "help:");

    expect(screen.getByText("HELP")).toBeInTheDocument();
    expect(screen.getByText(/`route:` filter routes only/i)).toBeInTheDocument();
    expect(screen.getByText(/repeat last safe command/i)).toBeInTheDocument();
    expect(screen.queryByText("SHADOW OPS")).not.toBeInTheDocument();
  });

  it("resolves guest crm quick targets from shell-like input", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "crm lena");

    const quickTargetsHeading = screen.getByText("QUICK TARGETS");
    const quickTargetsGroup = quickTargetsHeading.parentElement;
    expect(quickTargetsGroup).not.toBeNull();
    expect(within(quickTargetsGroup!).getByText("lena@example.com")).toBeInTheDocument();
    await user.click(within(quickTargetsGroup!).getByRole("button", { name: /lena north/i }));

    expect(push).toHaveBeenCalledWith("/guests/guest-44");
  });

  it("chains guest target resolution into direct crm open", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "crm lena open");

    expect(screen.getByText("CHAINED ACTION")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /open guest crm/i }));

    expect(push).toHaveBeenCalledWith("/guests/guest-44");
  });

  it("resolves work order quick targets from shell-like input", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "wo 1092");

    const quickTargetsHeading = screen.getByText("QUICK TARGETS");
    const quickTargetsGroup = quickTargetsHeading.parentElement;
    expect(quickTargetsGroup).not.toBeNull();
    expect(within(quickTargetsGroup!).getByText(/WO-1092 · high/i)).toBeInTheDocument();
    await user.click(within(quickTargetsGroup!).getByRole("button", { name: /replace smart lock battery/i }));

    expect(push).toHaveBeenCalledWith("/work-orders");
  });

  it("accepts numbered quick targets with ctrl digit", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "crm lena");

    const quickTargetsHeading = screen.getByText("QUICK TARGETS");
    const quickTargetsGroup = quickTargetsHeading.parentElement;
    expect(quickTargetsGroup).not.toBeNull();
    expect(within(quickTargetsGroup!).getByText("[1]")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "1", ctrlKey: true });

    expect(push).toHaveBeenCalledWith("/guests/guest-44");
  });

  it("opens a dedicated target resolver mode for multi-hit target sets", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "crm lena");

    expect(screen.getByText("RESOLVER")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /open target resolver/i }));

    expect(screen.getByText("> mode:target-resolver/guest")).toBeInTheDocument();
    expect(screen.getByText("RESOLVED TARGETS")).toBeInTheDocument();
  });

  it("opens target actions from the resolver for a guest", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "crm lena");
    await user.click(screen.getByRole("button", { name: /open target resolver/i }));

    const resolvedHeading = screen.getByText("RESOLVED TARGETS");
    const resolvedGroup = resolvedHeading.parentElement;
    expect(resolvedGroup).not.toBeNull();
    await user.click(within(resolvedGroup!).getAllByRole("button", { name: /lena north/i })[0]);

    expect(screen.getByText("> mode:target-actions/guest")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open guest crm/i })).toBeInTheDocument();
  });

  it("chains work order target resolution into completion", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "wo 1092 complete");

    expect(screen.getByText("CHAINED ACTION")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /complete work order/i }));

    expect(updateWorkOrderMutate).toHaveBeenCalledWith({
      id: "wo-9",
      status: "completed",
    });
  });

  it("shows inline succeeded feedback in target actions mode", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "wo e");
    await user.click(screen.getByRole("button", { name: /open target resolver/i }));

    const resolvedHeading = screen.getByText("RESOLVED TARGETS");
    const resolvedGroup = resolvedHeading.parentElement;
    expect(resolvedGroup).not.toBeNull();
    await user.click(within(resolvedGroup!).getAllByRole("button", { name: /replace smart lock battery/i })[0]);

    await user.click(screen.getByRole("button", { name: /complete work order/i }));

    expect(screen.getByText("ACTION STATUS")).toBeInTheDocument();
    expect(screen.getByText("succeeded")).toBeInTheDocument();
  });

  it("shows inline failed feedback in target actions mode", async () => {
    const user = userEvent.setup();
    updateWorkOrderMutateAsync.mockRejectedValueOnce(new Error("work order failed"));

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "wo e");
    await user.click(screen.getByRole("button", { name: /open target resolver/i }));

    const resolvedHeading = screen.getByText("RESOLVED TARGETS");
    const resolvedGroup = resolvedHeading.parentElement;
    expect(resolvedGroup).not.toBeNull();
    await user.click(within(resolvedGroup!).getAllByRole("button", { name: /replace smart lock battery/i })[0]);

    await user.click(screen.getByRole("button", { name: /complete work order/i }));

    expect(screen.getByText("ACTION STATUS")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("resolves war room quick targets from shell-like input", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "warroom generali");

    const quickTargetsHeading = screen.getByText("QUICK TARGETS");
    const quickTargetsGroup = quickTargetsHeading.parentElement;
    expect(quickTargetsGroup).not.toBeNull();
    expect(within(quickTargetsGroup!).getByText(/2026-CV-100 · generali-case/i)).toBeInTheDocument();
    await user.click(within(quickTargetsGroup!).getByRole("button", { name: /generali v\. fortress prime/i }));

    expect(push).toHaveBeenCalledWith("/legal/cases/generali-case/war-room");
  });

  it("adds shorthand aliases and intent phrases to command search values", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "1",
        email: "ops@example.com",
        first_name: "Ops",
        last_name: "Manager",
        role: "manager",
      },
      sidebarCollapsed: false,
      recentCommandHistory: [],
      commandAuditTrail: [],
      activeAdjudicationContext: null,
      activeWorkOrderContext: {
        id: "wo-9",
        title: "Replace smart lock battery",
        ticketNumber: "WO-1092",
        status: "open",
        priority: "high",
        propertyName: "Cabin Blackpine",
        assignedTo: "Field Team",
      },
      activeConversationContext: null,
      pinnedOperatorFocusKind: null,
      activeAdjudicationContextUpdatedAt: 0,
      activeWorkOrderContextUpdatedAt: 400,
      activeConversationContextUpdatedAt: 0,
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));

    const workOrderButton = screen.getByRole("button", { name: /open selected work order/i });
    const workOrderCompleteButton = screen.getByRole("button", {
      name: /mark selected work order completed/i,
    });

    expect(workOrderButton).toHaveAttribute("data-command-value", expect.stringContaining("wo"));
    expect(workOrderButton).toHaveAttribute("data-command-value", expect.stringContaining("wo open"));
    expect(workOrderCompleteButton).toHaveAttribute(
      "data-command-value",
      expect.stringContaining("wo complete"),
    );
  });

  it("biases command ordering toward intent phrase matches", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "ledger sync");

    const paperclipHeading = screen.getByText("PAPERCLIP AI");
    const paperclipGroup = paperclipHeading.parentElement;
    expect(paperclipGroup).not.toBeNull();

    const groupButtons = within(paperclipGroup!).getAllByRole("button");
    const labels = groupButtons.map((button) => button.textContent ?? "");

    expect(labels[0]).toContain("Sync Adjudication Ledger");
  });

  it("surfaces did-you-mean suggestions for close intent matches", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "dispatch");

    const suggestionHeading = screen.getByText("DID YOU MEAN");
    const suggestionGroup = suggestionHeading.parentElement;
    expect(suggestionGroup).not.toBeNull();
    expect(within(suggestionGroup!).getByRole("button", { name: /dispatch hunter target/i })).toBeInTheDocument();
    expect(within(suggestionGroup!).getByRole("button", { name: /housekeeping dispatch/i })).toBeInTheDocument();
  });

  it("accepts the top suggestion with Tab", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.type(screen.getByLabelText("command-input"), "dispatch");

    const suggestionHeading = screen.getByText("DID YOU MEAN");
    const suggestionGroup = suggestionHeading.parentElement;
    expect(suggestionGroup).not.toBeNull();
    expect(within(suggestionGroup!).getByRole("button", { name: /accept top suggestion/i })).toBeInTheDocument();
    const suggestionButtons = within(suggestionGroup!).getAllByRole("button");
    expect(suggestionButtons[1]?.textContent).toContain("Housekeeping Dispatch");

    fireEvent.keyDown(document, { key: "Tab" });

    expect(push).toHaveBeenCalledWith("/housekeeping");
  });

  it("shows terminal status for scope, focus, and repeat readiness", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "1",
        email: "ops@example.com",
        first_name: "Ops",
        last_name: "Manager",
        role: "manager",
      },
      sidebarCollapsed: false,
      recentCommandHistory: [
        {
          commandKey: "route:/system-health",
          label: "System Health",
          scope: "navigation",
          type: "route",
          href: "/system-health",
          executedAt: Date.now(),
        },
      ],
      commandAuditTrail: [],
      activeAdjudicationContext: null,
      activeWorkOrderContext: null,
      activeConversationContext: {
        guestId: "guest-44",
        guestName: "Lena North",
        guestPhone: "+17065551212",
        propertyName: "Cabin Emberfall",
        lastMessage: "Can we get a late checkout?",
        unreadCount: 2,
      },
      pinnedOperatorFocusKind: null,
      activeAdjudicationContextUpdatedAt: 0,
      activeWorkOrderContextUpdatedAt: 0,
      activeConversationContextUpdatedAt: 500,
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));

    expect(screen.getByText("scope:all")).toBeInTheDocument();
    expect(screen.getByText("focus:live")).toBeInTheDocument();
    expect(screen.getByText("last:00:idle")).toBeInTheDocument();
    expect(screen.getByText("repeat:armed")).toBeInTheDocument();
  });

  it("updates terminal status with the last command outcome", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    expect(screen.getByText("last:00:idle")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /system health/i }));
    await user.click(screen.getByRole("button", { name: /execute command/i }));

    expect(screen.getByText("last:20:navigated")).toBeInTheDocument();
  });

  it("opens a second-step target picker for Hunter dispatch actions", async () => {
    const user = userEvent.setup();
    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /dispatch hunter target/i }));
    await user.click(screen.getByRole("button", { name: /avery ridge/i }));

    expect(dispatchHunterMutate).toHaveBeenCalledWith({
      guestId: "guest-1",
      fullName: "Avery Ridge",
      targetScore: 91,
    });
  });

  it("requires the DEFCON phrase before executing the guarded action", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "9",
        email: "root@example.com",
        first_name: "Root",
        last_name: "Admin",
        role: "admin",
      },
      sidebarCollapsed: false,
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /switch defcon mode/i }));
    await user.click(screen.getByRole("button", { name: /fortress_legal/i }));
    expect(screen.getByText("> mode:defcon-confirm/fortress_legal")).toBeInTheDocument();

    const input = screen.getByLabelText("command-input");
    await user.type(input, "ENGAGE FORTRESS_LEGAL");
    await user.click(screen.getByRole("button", { name: /authorize defcon switch/i }));

    expect(setDefconMutate).toHaveBeenCalledWith({
      mode: "fortress_legal",
      override_authorization: true,
    });
  });

  it("reports rejected commands in the footer when guarded auth fails", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "9",
        email: "root@example.com",
        first_name: "Root",
        last_name: "Admin",
        role: "admin",
      },
      sidebarCollapsed: false,
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /switch defcon mode/i }));
    await user.click(screen.getByRole("button", { name: /fortress_legal/i }));
    await user.type(screen.getByLabelText("command-input"), "NOPE");
    await user.click(screen.getByRole("button", { name: /authorize defcon switch/i }));

    expect(screen.getByText("last:41:rejected")).toBeInTheDocument();
  });

  it("reports failed commands in the footer when async actions reject", async () => {
    const user = userEvent.setup();
    syncLedgerMutateAsync.mockRejectedValueOnce(new Error("ledger failed"));

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /sync adjudication ledger/i }));

    expect(await screen.findByText("last:50:failed")).toBeInTheDocument();
  });

  it("shows current legal case context commands and routes into the war room", async () => {
    const user = userEvent.setup();
    mockPathname = "/legal/cases/generali-case";

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /open current docket war room/i }));

    expect(push).toHaveBeenCalledWith("/legal/cases/generali-case/war-room");
  });

  it("executes current legal case graph actions from context", async () => {
    const user = userEvent.setup();
    mockPathname = "/legal/cases/generali-case/war-room";

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /refresh current case graph/i }));

    expect(refreshCaseGraphMutate).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
  });

  it("executes active adjudication actions from shared store context", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "1",
        email: "ops@example.com",
        first_name: "Ops",
        last_name: "Manager",
        role: "manager",
      },
      sidebarCollapsed: false,
      activeAdjudicationContext: {
        id: "adj-17",
        guestName: "Morgan Vale",
        propertyName: "Cabin Blackpine",
        consensusSignal: "RESOLVE",
        consensusConviction: 0.82,
        draftBody: "We are dispatching an immediate recovery action.",
      },
      activeAdjudicationContextUpdatedAt: 300,
      activeWorkOrderContext: null,
      activeWorkOrderContextUpdatedAt: 0,
      activeConversationContext: null,
      activeConversationContextUpdatedAt: 0,
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    expect(screen.getByText(/live · morgan vale/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /dispatch selected adjudication override/i }));

    expect(overrideDispatchMutate).toHaveBeenCalledWith({
      id: "adj-17",
      body: "We are dispatching an immediate recovery action.",
      consensusConviction: 0.82,
      minimumConviction: 0,
    });
  });

  it("routes back into the selected work order from shared store context", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "1",
        email: "ops@example.com",
        first_name: "Ops",
        last_name: "Manager",
        role: "manager",
      },
      sidebarCollapsed: false,
      activeAdjudicationContext: null,
      activeWorkOrderContext: {
        id: "wo-9",
        title: "Replace smart lock battery",
        ticketNumber: "WO-1092",
        status: "open",
        priority: "high",
        propertyName: "Cabin Blackpine",
        assignedTo: "Field Team",
      },
      activeAdjudicationContextUpdatedAt: 0,
      activeWorkOrderContextUpdatedAt: 400,
      activeConversationContext: null,
      activeConversationContextUpdatedAt: 0,
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /open selected work order/i }));

    expect(push).toHaveBeenCalledWith("/work-orders");
  });

  it("updates the selected work order from shared store context", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "1",
        email: "ops@example.com",
        first_name: "Ops",
        last_name: "Manager",
        role: "manager",
      },
      sidebarCollapsed: false,
      activeAdjudicationContext: null,
      activeWorkOrderContext: {
        id: "wo-9",
        title: "Replace smart lock battery",
        ticketNumber: "WO-1092",
        status: "open",
        priority: "high",
        propertyName: "Cabin Blackpine",
        assignedTo: "Field Team",
      },
      activeAdjudicationContextUpdatedAt: 0,
      activeWorkOrderContextUpdatedAt: 400,
      activeConversationContext: null,
      activeConversationContextUpdatedAt: 0,
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /mark selected work order in progress/i }));

    expect(updateWorkOrderMutate).toHaveBeenCalledWith({
      id: "wo-9",
      status: "in_progress",
    });
  });

  it("routes back into the active conversation from shared store context", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "1",
        email: "ops@example.com",
        first_name: "Ops",
        last_name: "Manager",
        role: "manager",
      },
      sidebarCollapsed: false,
      activeAdjudicationContext: null,
      activeWorkOrderContext: null,
      activeConversationContext: {
        guestId: "guest-44",
        guestName: "Lena North",
        guestPhone: "+17065551212",
        propertyName: "Cabin Emberfall",
        lastMessage: "Can we get a late checkout?",
        unreadCount: 2,
      },
      activeAdjudicationContextUpdatedAt: 0,
      activeWorkOrderContextUpdatedAt: 0,
      activeConversationContextUpdatedAt: 500,
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /open active conversation thread/i }));

    expect(push).toHaveBeenCalledWith("/messages");
  });

  it("routes from the active conversation into guest crm", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "1",
        email: "ops@example.com",
        first_name: "Ops",
        last_name: "Manager",
        role: "manager",
      },
      sidebarCollapsed: false,
      activeAdjudicationContext: null,
      activeWorkOrderContext: null,
      activeConversationContext: {
        guestId: "guest-44",
        guestName: "Lena North",
        guestPhone: "+17065551212",
        propertyName: "Cabin Emberfall",
        lastMessage: "Can we get a late checkout?",
        unreadCount: 2,
      },
      activeAdjudicationContextUpdatedAt: 0,
      activeWorkOrderContextUpdatedAt: 0,
      activeConversationContextUpdatedAt: 500,
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /open active guest crm/i }));

    expect(push).toHaveBeenCalledWith("/guests/guest-44");
  });

  it("prioritizes the most recently touched operator focus", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "1",
        email: "ops@example.com",
        first_name: "Ops",
        last_name: "Manager",
        role: "manager",
      },
      sidebarCollapsed: false,
      activeAdjudicationContext: {
        id: "adj-17",
        guestName: "Morgan Vale",
        propertyName: "Cabin Blackpine",
        consensusSignal: "RESOLVE",
        consensusConviction: 0.82,
        draftBody: "We are dispatching an immediate recovery action.",
      },
      activeAdjudicationContextUpdatedAt: 100,
      activeWorkOrderContext: {
        id: "wo-9",
        title: "Replace smart lock battery",
        ticketNumber: "WO-1092",
        status: "open",
        priority: "high",
        propertyName: "Cabin Blackpine",
        assignedTo: "Field Team",
      },
      activeWorkOrderContextUpdatedAt: 200,
      activeConversationContext: {
        guestId: "guest-44",
        guestName: "Lena North",
        guestPhone: "+17065551212",
        propertyName: "Cabin Emberfall",
        lastMessage: "Can we get a late checkout?",
        unreadCount: 2,
      },
      activeConversationContextUpdatedAt: 300,
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));

    expect(screen.getByText(/focus status/i)).toBeInTheDocument();
    expect(screen.getByText(/live · lena north/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open active guest crm/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dispatch selected adjudication override/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mark selected work order in progress/i })).not.toBeInTheDocument();
  });

  it("uses pinned operator focus over recency until unpinned", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "1",
        email: "ops@example.com",
        first_name: "Ops",
        last_name: "Manager",
        role: "manager",
      },
      sidebarCollapsed: false,
      activeAdjudicationContext: {
        id: "adj-17",
        guestName: "Morgan Vale",
        propertyName: "Cabin Blackpine",
        consensusSignal: "RESOLVE",
        consensusConviction: 0.82,
        draftBody: "We are dispatching an immediate recovery action.",
      },
      activeAdjudicationContextUpdatedAt: 100,
      activeWorkOrderContext: {
        id: "wo-9",
        title: "Replace smart lock battery",
        ticketNumber: "WO-1092",
        status: "open",
        priority: "high",
        propertyName: "Cabin Blackpine",
        assignedTo: "Field Team",
      },
      activeWorkOrderContextUpdatedAt: 200,
      activeConversationContext: {
        guestId: "guest-44",
        guestName: "Lena North",
        guestPhone: "+17065551212",
        propertyName: "Cabin Emberfall",
        lastMessage: "Can we get a late checkout?",
        unreadCount: 2,
      },
      activeConversationContextUpdatedAt: 300,
      pinnedOperatorFocusKind: "workOrder",
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    expect(screen.getByText(/pinned · wo-1092/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /execute command/i }));

    expect(screen.getByText(/focus status/i)).toBeInTheDocument();
    expect(screen.getByText(/pinned · wo-1092/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /unpin operator focus/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /mark selected work order in progress/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open active guest crm/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /unpin operator focus/i }));

    expect(useAppStore.getState().pinnedOperatorFocusKind).toBeNull();
  });

  it("clears focus context back to pure route mode", async () => {
    const user = userEvent.setup();
    useAppStore.setState({
      user: {
        id: "1",
        email: "ops@example.com",
        first_name: "Ops",
        last_name: "Manager",
        role: "manager",
      },
      sidebarCollapsed: false,
      activeAdjudicationContext: null,
      activeAdjudicationContextUpdatedAt: 0,
      activeWorkOrderContext: {
        id: "wo-9",
        title: "Replace smart lock battery",
        ticketNumber: "WO-1092",
        status: "open",
        priority: "high",
        propertyName: "Cabin Blackpine",
        assignedTo: "Field Team",
      },
      activeWorkOrderContextUpdatedAt: 200,
      activeConversationContext: {
        guestId: "guest-44",
        guestName: "Lena North",
        guestPhone: "+17065551212",
        propertyName: "Cabin Emberfall",
        lastMessage: "Can we get a late checkout?",
        unreadCount: 2,
      },
      activeConversationContextUpdatedAt: 300,
      pinnedOperatorFocusKind: "workOrder",
    });

    render(<CommandSearch />, { wrapper: Wrapper });

    await user.click(screen.getByRole("button", { name: /execute command/i }));
    await user.click(screen.getByRole("button", { name: /clear focus context/i }));

    const state = useAppStore.getState();
    expect(state.pinnedOperatorFocusKind).toBeNull();
    expect(state.activeAdjudicationContext).toBeNull();
    expect(state.activeWorkOrderContext).toBeNull();
    expect(state.activeConversationContext).toBeNull();
  });
});
