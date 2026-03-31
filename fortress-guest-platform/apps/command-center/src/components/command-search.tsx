"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { toast } from "sonner";
import {
  useAutoScheduleHousekeeping,
  useDispatchHunterTarget,
  useGuests,
  useOverrideVrsDispatch,
  useProperties,
  useSetDefcon,
  useSyncVrsLedger,
  useUpdateWorkOrder,
  useVrsHunterTargets,
  useWorkOrders,
} from "@/lib/hooks";
import type { CommandAuditEntry, RecentCommandEntry } from "@/lib/store";
import { getOperatorFocus, useAppStore } from "@/lib/store";
import type { Guest, VrsHunterTarget, WorkOrder } from "@/lib/types";
import {
  useLegalCases,
  useRefreshGraphMutation,
  useRunSanctionsSweep,
} from "@/lib/legal-hooks";
import type { LegalCase } from "@/lib/legal-types";
import {
  filterCommandHierarchy,
  getNavHref,
  getRoleFromUser,
  type NavCommandItem,
} from "@/config/navigation";
import { cn } from "@/lib/utils";

type CommandMode =
  | { kind: "root" }
  | { kind: "hunter-targets" }
  | {
      kind: "target-resolver";
      targetKind: "guest" | "workOrder" | "warRoom";
      targets: QuickTargetItem[];
    }
  | { kind: "target-actions"; target: QuickTargetItem; targets: QuickTargetItem[] }
  | { kind: "defcon-select" }
  | { kind: "defcon-confirm"; targetMode: "swarm" | "fortress_legal" };

type RootScopeFilter =
  | "all"
  | "route"
  | "action"
  | "focus"
  | "recent"
  | "audit"
  | "help";

function getModeLabel(
  mode: CommandMode,
  rootScopeFilter: RootScopeFilter,
): string {
  if (mode.kind === "root") {
    return rootScopeFilter === "all" ? "root" : `root/${rootScopeFilter}`;
  }

  if (mode.kind === "defcon-confirm") {
    return `defcon-confirm/${mode.targetMode}`;
  }

  if (mode.kind === "target-resolver") {
    return `target-resolver/${mode.targetKind}`;
  }

  if (mode.kind === "target-actions") {
    return `target-actions/${mode.target.targetKind}`;
  }

  return mode.kind;
}

function getDefconDisplay(mode: "swarm" | "fortress_legal"): string {
  return mode === "fortress_legal" ? "FORTRESS_LEGAL" : "SWARM";
}

function getLegalCaseSlug(pathname: string): string | null {
  const match = pathname.match(/^\/legal\/cases\/([^/]+)(?:\/.*)?$/);
  return match?.[1] ?? null;
}

function getGuestDisplayName(guest: Guest): string {
  const fullName = guest.full_name?.trim();
  if (fullName) return fullName;
  const combined = `${guest.first_name ?? ""} ${guest.last_name ?? ""}`.trim();
  return combined || "Guest";
}

function formatRecentTimestamp(executedAt: number): string {
  const delta = Math.max(0, Date.now() - executedAt);
  const minutes = Math.floor(delta / 60000);
  if (minutes < 1) return "just now";
  if (minutes === 1) return "1 min ago";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours === 1) return "1 hr ago";
  return `${hours} hr ago`;
}

function formatAuditTimestamp(createdAt: number): string {
  return formatRecentTimestamp(createdAt);
}

function createAuditKey(prefix: string, commandKey: string): string {
  return `${prefix}:${commandKey}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

function getCommandAliases(label: string): string[] {
  const normalized = label.toLowerCase();

  if (normalized.includes("work order")) return ["wo", "workorder", "ticket"];
  if (normalized.includes("guest crm")) return ["crm", "guest"];
  if (normalized.includes("ledger")) return ["ledger", "sync"];
  if (normalized.includes("defcon")) return ["defcon", "alert"];
  if (normalized.includes("war room")) return ["warroom", "docket"];
  if (normalized.includes("adjudication")) return ["glass", "queue"];
  if (normalized.includes("conversation")) return ["comms", "thread", "inbox"];

  return [];
}

function getCommandIntentPhrases(label: string): string[] {
  const normalized = label.toLowerCase();

  if (normalized.includes("mark selected work order completed")) {
    return ["wo complete", "ticket close", "workorder complete"];
  }
  if (normalized.includes("mark selected work order in progress")) {
    return ["wo start", "ticket start", "workorder in progress"];
  }
  if (normalized.includes("open selected work order")) {
    return ["wo open", "ticket open"];
  }
  if (normalized.includes("open active guest crm")) {
    return ["crm open", "guest open", "guest profile"];
  }
  if (normalized.includes("sync adjudication ledger")) {
    return ["ledger sync", "sync ledger", "queue sync"];
  }
  if (normalized.includes("dispatch selected adjudication override")) {
    return ["queue dispatch", "glass dispatch", "adjudication send"];
  }
  if (normalized.includes("switch defcon mode")) {
    return ["defcon switch", "alert mode", "ops mode"];
  }
  if (normalized.includes("open current docket war room")) {
    return ["warroom open", "docket open", "case warroom"];
  }
  if (normalized.includes("refresh current case graph")) {
    return ["graph refresh", "case graph", "legal graph"];
  }
  if (normalized.includes("run current case sanctions sweep")) {
    return ["sanctions sweep", "tripwire run", "legal sanctions"];
  }
  if (normalized.includes("open active conversation thread")) {
    return ["comms open", "thread open", "inbox open"];
  }
  if (normalized.includes("dispatch hunter target")) {
    return ["hunter dispatch", "reactivation dispatch"];
  }

  return [];
}

function withAliases(value: string, label: string): string {
  return [value, ...getCommandAliases(label), ...getCommandIntentPhrases(label)].join(" ");
}

function getIntentScore(query: string, value: string): number {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return 0;
  }

  const normalizedValue = value.toLowerCase();
  const queryTokens = normalizedQuery.split(/\s+/).filter(Boolean);
  let score = 0;

  if (normalizedValue.includes(normalizedQuery)) {
    score += 100;
  }

  const matchedTokens = queryTokens.filter((token) => normalizedValue.includes(token));
  score += matchedTokens.length * 10;

  if (queryTokens.length > 1 && matchedTokens.length === queryTokens.length) {
    score += 50;
  }

  return score;
}

function rankByIntent<T extends { value: string }>(items: T[], query: string): T[] {
  if (!query.trim()) {
    return items;
  }

  return [...items].sort((a, b) => getIntentScore(query, b.value) - getIntentScore(query, a.value));
}

function getDisambiguationCandidates<
  T extends { value: string; label: string }
>(
  items: T[],
  query: string,
): T[] {
  const normalizedQuery = query.trim();
  if (!normalizedQuery) {
    return [];
  }

  const scored = items
    .map((item) => ({
      item,
      score: getIntentScore(query, item.value),
    }))
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score);

  if (scored.length < 2) {
    return [];
  }

  const [first, second] = scored;
  if (first.score - second.score > 20) {
    return [];
  }

  return [first.item, second.item];
}

function isRepeatSafeCommand(entry: RecentCommandEntry): boolean {
  if (entry.type === "route") {
    return true;
  }

  return (
    entry.actionId === "sync-vrs-ledger" ||
    entry.actionId === "auto-schedule-housekeeping"
  );
}

function getOperatorFocusSummary(
  focus: ReturnType<typeof getOperatorFocus>,
  pinnedKind: ReturnType<typeof useAppStore.getState>["pinnedOperatorFocusKind"],
): string | null {
  if (!focus) {
    return null;
  }

  const prefix = pinnedKind === focus.kind ? "PINNED" : "LIVE";

  switch (focus.kind) {
    case "adjudication":
      return `${prefix} · ${focus.context.guestName}`;
    case "workOrder":
      return `${prefix} · ${focus.context.ticketNumber}`;
    case "conversation":
      return `${prefix} · ${focus.context.guestName}`;
    default:
      return prefix;
  }
}

function getOperatorFocusStateLabel(
  focus: ReturnType<typeof getOperatorFocus>,
  pinnedKind: ReturnType<typeof useAppStore.getState>["pinnedOperatorFocusKind"],
): string {
  if (!focus) {
    return "none";
  }

  return pinnedKind === focus.kind ? "pinned" : "live";
}

function getLastOutcomeCode(
  outcome: "idle" | CommandAuditEntry["outcome"],
): string {
  switch (outcome) {
    case "succeeded":
      return "21";
    case "navigated":
      return "20";
    case "issued":
      return "10";
    case "replayed":
      return "30";
    case "rejected":
      return "41";
    case "failed":
      return "50";
    case "idle":
    default:
      return "00";
  }
}

function getLastOutcomeTone(
  outcome: "idle" | CommandAuditEntry["outcome"],
): string {
  switch (outcome) {
    case "succeeded":
      return "text-emerald-300";
    case "navigated":
      return "text-emerald-400";
    case "issued":
      return "text-amber-400";
    case "replayed":
      return "text-sky-400";
    case "rejected":
      return "text-orange-400";
    case "failed":
      return "text-red-400";
    case "idle":
    default:
      return "text-neutral-600";
  }
}

function getOutcomeBadgeLabel(
  outcome: CommandAuditEntry["outcome"] | undefined,
): string {
  if (!outcome) {
    return "--";
  }

  return `${getLastOutcomeCode(outcome)}:${outcome}`;
}

async function runMutationWithFallback<TArgs>(
  mutation: {
    mutate?: (args: TArgs) => void;
    mutateAsync?: (args: TArgs) => Promise<unknown>;
  },
  args: TArgs,
): Promise<void> {
  if (typeof mutation.mutateAsync === "function") {
    await mutation.mutateAsync(args);
    return;
  }

  mutation.mutate?.(args);
}

function getRootScopeFilter(value: string): RootScopeFilter {
  const normalized = value.trim().toLowerCase();

  if (normalized.startsWith("route:")) return "route";
  if (normalized.startsWith("action:")) return "action";
  if (normalized.startsWith("focus:")) return "focus";
  if (normalized.startsWith("recent:")) return "recent";
  if (normalized.startsWith("audit:")) return "audit";
  if (normalized.startsWith("help:")) return "help";

  return "all";
}

type DynamicIntent =
  | { kind: "guest"; query: string }
  | { kind: "workOrder"; query: string }
  | { kind: "warRoom"; query: string };

type DynamicIntentAction =
  | { kind: "guest"; action: "open"; targetQuery: string }
  | { kind: "workOrder"; action: "open" | "in_progress" | "completed"; targetQuery: string }
  | { kind: "warRoom"; action: "open"; targetQuery: string };

type QuickTargetItem = {
  key: string;
  value: string;
  targetKind: "guest" | "workOrder" | "warRoom";
  primary: string;
  secondary: string;
  tag: string;
  onSelect: () => void;
  onResolve: () => void;
};

function parseDynamicIntent(value: string): DynamicIntent | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }

  const normalized = trimmed.toLowerCase();
  const pairs: Array<{ prefixes: string[]; kind: DynamicIntent["kind"] }> = [
    { prefixes: ["crm ", "guest ", "guestcrm "], kind: "guest" },
    { prefixes: ["wo ", "ticket ", "workorder "], kind: "workOrder" },
    { prefixes: ["warroom ", "war room ", "docket ", "case "], kind: "warRoom" },
  ];

  for (const { prefixes, kind } of pairs) {
    const prefix = prefixes.find((candidate) => normalized.startsWith(candidate));
    if (prefix) {
      const query = trimmed.slice(prefix.length).trim();
      return query ? { kind, query } : null;
    }
  }

  return null;
}

function matchesTarget(query: string, ...values: Array<string | null | undefined>): boolean {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return false;
  }

  return values.some((value) => value?.toLowerCase().includes(normalizedQuery));
}

function stripBoundaryVerb(
  query: string,
  verbs: string[],
): { action: string; targetQuery: string } | null {
  const trimmed = query.trim();
  const normalized = trimmed.toLowerCase();

  for (const verb of verbs) {
    if (normalized === verb) {
      return null;
    }

    if (normalized.startsWith(`${verb} `)) {
      return {
        action: verb,
        targetQuery: trimmed.slice(verb.length).trim(),
      };
    }

    if (normalized.endsWith(` ${verb}`)) {
      return {
        action: verb,
        targetQuery: trimmed.slice(0, trimmed.length - verb.length).trim(),
      };
    }
  }

  return null;
}

function parseDynamicIntentAction(intent: DynamicIntent | null): DynamicIntentAction | null {
  if (!intent) {
    return null;
  }

  if (intent.kind === "guest") {
    const parsed = stripBoundaryVerb(intent.query, ["open"]);
    if (parsed && parsed.targetQuery) {
      return { kind: "guest", action: "open", targetQuery: parsed.targetQuery };
    }
    return null;
  }

  if (intent.kind === "workOrder") {
    const parsed = stripBoundaryVerb(intent.query, [
      "open",
      "complete",
      "completed",
      "close",
      "start",
      "progress",
    ]);
    if (!parsed || !parsed.targetQuery) {
      return null;
    }

    if (parsed.action === "open") {
      return { kind: "workOrder", action: "open", targetQuery: parsed.targetQuery };
    }

    if (parsed.action === "start" || parsed.action === "progress") {
      return { kind: "workOrder", action: "in_progress", targetQuery: parsed.targetQuery };
    }

    return { kind: "workOrder", action: "completed", targetQuery: parsed.targetQuery };
  }

  const parsed = stripBoundaryVerb(intent.query, ["open"]);
  if (parsed && parsed.targetQuery) {
    return { kind: "warRoom", action: "open", targetQuery: parsed.targetQuery };
  }

  return null;
}

export function CommandSearch() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<CommandMode>({ kind: "root" });
  const [inputValue, setInputValue] = useState("");
  const [inlineActionFeedback, setInlineActionFeedback] = useState<{
    commandKey: string;
    status: "pending" | "succeeded" | "failed";
  } | null>(null);
  const router = useRouter();
  const pathname = usePathname();
  const user = useAppStore((s) => s.user);
  const activeAdjudicationContext = useAppStore((s) => s.activeAdjudicationContext);
  const activeWorkOrderContext = useAppStore((s) => s.activeWorkOrderContext);
  const activeConversationContext = useAppStore((s) => s.activeConversationContext);
  const pinnedOperatorFocusKind = useAppStore((s) => s.pinnedOperatorFocusKind);
  const activeAdjudicationContextUpdatedAt = useAppStore((s) => s.activeAdjudicationContextUpdatedAt);
  const activeWorkOrderContextUpdatedAt = useAppStore((s) => s.activeWorkOrderContextUpdatedAt);
  const activeConversationContextUpdatedAt = useAppStore((s) => s.activeConversationContextUpdatedAt);
  const pinOperatorFocus = useAppStore((s) => s.pinOperatorFocus);
  const clearPinnedOperatorFocus = useAppStore((s) => s.clearPinnedOperatorFocus);
  const clearOperatorFocus = useAppStore((s) => s.clearOperatorFocus);
  const setActiveWorkOrderContext = useAppStore((s) => s.setActiveWorkOrderContext);
  const recentCommandHistory = useAppStore((s) => s.recentCommandHistory);
  const recordRecentCommand = useAppStore((s) => s.recordRecentCommand);
  const commandAuditTrail = useAppStore((s) => s.commandAuditTrail);
  const recordCommandAudit = useAppStore((s) => s.recordCommandAudit);
  const { data: properties } = useProperties();
  const { data: guests } = useGuests();
  const { data: workOrders } = useWorkOrders();
  const legalCasesQuery = useLegalCases();
  const syncVrsLedger = useSyncVrsLedger();
  const autoScheduleHousekeeping = useAutoScheduleHousekeeping();
  const dispatchHunterTarget = useDispatchHunterTarget();
  const overrideVrsDispatch = useOverrideVrsDispatch();
  const updateWorkOrder = useUpdateWorkOrder();
  const setDefcon = useSetDefcon();
  const legalCaseSlug = getLegalCaseSlug(pathname);
  const refreshCaseGraph = useRefreshGraphMutation(legalCaseSlug ?? "");
  const runSanctionsSweep = useRunSanctionsSweep(legalCaseSlug ?? "");
  const hunterTargetsQuery = useVrsHunterTargets(mode.kind === "hunter-targets");
  const visibleGroups = filterCommandHierarchy(getRoleFromUser(user));
  const isWarRoomPath = Boolean(legalCaseSlug && pathname.endsWith("/war-room"));
  const operatorFocus = useMemo(
    () =>
      getOperatorFocus({
        activeAdjudicationContext,
        activeWorkOrderContext,
        activeConversationContext,
        pinnedOperatorFocusKind,
        activeAdjudicationContextUpdatedAt,
        activeWorkOrderContextUpdatedAt,
        activeConversationContextUpdatedAt,
      }),
    [
      activeAdjudicationContext,
      activeWorkOrderContext,
      activeConversationContext,
      pinnedOperatorFocusKind,
      activeAdjudicationContextUpdatedAt,
      activeWorkOrderContextUpdatedAt,
      activeConversationContextUpdatedAt,
    ],
  );
  const operatorFocusSummary = useMemo(
    () => getOperatorFocusSummary(operatorFocus, pinnedOperatorFocusKind),
    [operatorFocus, pinnedOperatorFocusKind],
  );
  const operatorFocusStateLabel = useMemo(
    () => getOperatorFocusStateLabel(operatorFocus, pinnedOperatorFocusKind),
    [operatorFocus, pinnedOperatorFocusKind],
  );
  const rootScopeFilter = useMemo(
    () => (mode.kind === "root" ? getRootScopeFilter(inputValue) : "all"),
    [inputValue, mode.kind],
  );
  const dynamicIntent = useMemo(() => parseDynamicIntent(inputValue), [inputValue]);
  const dynamicIntentAction = useMemo(
    () => parseDynamicIntentAction(dynamicIntent),
    [dynamicIntent],
  );
  const guestTargets = useMemo(
    () =>
      dynamicIntent?.kind === "guest"
        ? (guests ?? []).filter((guest) =>
            matchesTarget(
              dynamicIntentAction?.kind === "guest"
                ? dynamicIntentAction.targetQuery
                : dynamicIntent.query,
              guest.full_name,
              `${guest.first_name ?? ""} ${guest.last_name ?? ""}`.trim(),
              guest.email,
              guest.phone_number,
            ),
          )
        : [],
    [dynamicIntent, dynamicIntentAction, guests],
  );
  const workOrderTargets = useMemo(
    () =>
      dynamicIntent?.kind === "workOrder"
        ? (workOrders ?? []).filter((workOrder) =>
            matchesTarget(
              dynamicIntentAction?.kind === "workOrder"
                ? dynamicIntentAction.targetQuery
                : dynamicIntent.query,
              workOrder.ticket_number,
              workOrder.title,
              workOrder.description,
            ),
          )
        : [],
    [dynamicIntent, dynamicIntentAction, workOrders],
  );
  const legalCaseTargets = useMemo(
    () =>
      dynamicIntent?.kind === "warRoom"
        ? ((legalCasesQuery.data?.cases ?? []) as LegalCase[]).filter((legalCase) =>
            matchesTarget(
              dynamicIntentAction?.kind === "warRoom"
                ? dynamicIntentAction.targetQuery
                : dynamicIntent.query,
              legalCase.case_name,
              legalCase.case_slug,
              legalCase.case_number,
            ),
          )
        : [],
    [dynamicIntent, dynamicIntentAction, legalCasesQuery.data?.cases],
  );
  const modeLabel = useMemo(
    () => getModeLabel(mode, rootScopeFilter),
    [mode, rootScopeFilter],
  );
  const latestAuditByCommandKey = useMemo(() => {
    const map = new Map<string, CommandAuditEntry["outcome"]>();
    for (const entry of commandAuditTrail) {
      if (!map.has(entry.commandKey)) {
        map.set(entry.commandKey, entry.outcome);
      }
    }
    return map;
  }, [commandAuditTrail]);
  const lastSafeRecentCommand = useMemo(
    () => recentCommandHistory.find(isRepeatSafeCommand) ?? null,
    [recentCommandHistory],
  );
  const lastCommandOutcome = useMemo(
    () => commandAuditTrail[0]?.outcome ?? "idle",
    [commandAuditTrail],
  );
  const primaryGuestTarget = guestTargets[0];
  const primaryWorkOrderTarget = workOrderTargets[0];
  const primaryLegalCaseTarget = legalCaseTargets[0];
  const rootCommandEntries = useMemo(
    () =>
      visibleGroups.flatMap((group) =>
        group.items.map((item) => ({
          ...item,
          sector: group.sector,
          value: withAliases(`${item.type}: ${item.label}`, item.label),
        })),
      ),
    [visibleGroups],
  );
  const didYouMeanEntries = useMemo(() => {
    if (
      mode.kind !== "root" ||
      (rootScopeFilter !== "all" && rootScopeFilter !== "route" && rootScopeFilter !== "action")
    ) {
      return [];
    }

    const scoped = rootCommandEntries.filter((item) => {
      if (rootScopeFilter === "route") return item.type === "route";
      if (rootScopeFilter === "action") return item.type === "action";
      return true;
    });

    return getDisambiguationCandidates(scoped, inputValue);
  }, [inputValue, mode.kind, rootCommandEntries, rootScopeFilter]);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey) && !e.shiftKey) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  const handleOpenChange = useCallback((nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      setMode({ kind: "root" });
      setInputValue("");
    }
  }, []);

  const go = useCallback(
    (href: string) => {
      setOpen(false);
      setMode({ kind: "root" });
      setInputValue("");
      router.push(href);
    },
    [router],
  );

  const quickTargetItems = useMemo<QuickTargetItem[]>(() => {
    if (dynamicIntent?.kind === "guest") {
      return guestTargets.slice(0, 6).map((guest) => ({
        key: `guest-target-${guest.id}`,
        value: `target: guest ${getGuestDisplayName(guest)} ${guest.email ?? ""}`,
        targetKind: "guest" as const,
        primary: getGuestDisplayName(guest),
        secondary: guest.email || guest.phone_number,
        tag: "guest",
        onSelect: () => go(`/guests/${guest.id}`),
        onResolve: () => {},
      }));
    }

    if (dynamicIntent?.kind === "workOrder") {
      return workOrderTargets.slice(0, 6).map((workOrder: WorkOrder) => ({
        key: `work-order-target-${workOrder.id}`,
        value: `target: wo ${workOrder.ticket_number} ${workOrder.title}`,
        targetKind: "workOrder" as const,
        primary: workOrder.title,
        secondary: `${workOrder.ticket_number} · ${workOrder.priority}`,
        tag: "wo",
        onSelect: () => {
          setActiveWorkOrderContext({
            id: workOrder.id,
            title: workOrder.title,
            ticketNumber: workOrder.ticket_number,
            status: workOrder.status,
            priority: workOrder.priority,
            assignedTo: workOrder.assigned_to,
          });
          go("/work-orders");
        },
        onResolve: () => {},
      }));
    }

    if (dynamicIntent?.kind === "warRoom") {
      return legalCaseTargets.slice(0, 6).map((legalCase) => ({
        key: `legal-case-target-${legalCase.case_slug}`,
        value: `target: warroom ${legalCase.case_slug} ${legalCase.case_name}`,
        targetKind: "warRoom" as const,
        primary: legalCase.case_name,
        secondary: `${legalCase.case_number} · ${legalCase.case_slug}`,
        tag: "case",
        onSelect: () => go(`/legal/cases/${legalCase.case_slug}/war-room`),
        onResolve: () => {},
      }));
    }

    return [];
  }, [
    dynamicIntent?.kind,
    guestTargets,
    go,
    legalCaseTargets,
    setActiveWorkOrderContext,
    workOrderTargets,
  ]);
  const activeResolverTargets = useMemo(() => {
    if (mode.kind === "target-resolver" || mode.kind === "target-actions") {
      return mode.targets;
    }

    return quickTargetItems;
  }, [mode, quickTargetItems]);

  const executeHunterDispatch = useCallback(
    (target: VrsHunterTarget) => {
      dispatchHunterTarget.mutate({
        guestId: target.guest_id,
        fullName: target.full_name,
        targetScore: target.target_score,
      });
      setOpen(false);
      setMode({ kind: "root" });
      setInputValue("");
    },
    [dispatchHunterTarget],
  );

  const enterMode = useCallback((nextMode: CommandMode, preserveInput = false) => {
    setMode(nextMode);
    setInlineActionFeedback(null);
    if (!preserveInput) {
      setInputValue("");
    }
  }, []);

  const auditCommand = useCallback(
    (entry: Omit<CommandAuditEntry, "createdAt">) => {
      recordCommandAudit(entry);
    },
    [recordCommandAudit],
  );

  const executeDefconSwitch = useCallback(() => {
    if (mode.kind !== "defcon-confirm") {
      return;
    }

    const requiredPhrase = `ENGAGE ${getDefconDisplay(mode.targetMode)}`;
    if (inputValue.trim() !== requiredPhrase) {
      auditCommand({
        auditKey: createAuditKey("reject", "action:switch-defcon-mode"),
        commandKey: "action:switch-defcon-mode",
        label: "Switch DEFCON Mode",
        scope: "navigation",
        outcome: "rejected",
      });
      toast.error("Authorization phrase mismatch.");
      return;
    }

    setDefcon.mutate({
      mode: mode.targetMode,
      override_authorization: true,
    });
    setOpen(false);
    setMode({ kind: "root" });
    setInputValue("");
  }, [auditCommand, inputValue, mode, setDefcon]);

  const recordPaletteCommand = useCallback(
    ({
      commandKey,
      label,
      scope,
      type,
      href,
      actionId,
      outcome,
    }: {
      commandKey: string;
      label: string;
      scope: "navigation" | "context" | "focus";
      type: "route" | "action";
      href?: string;
      actionId?: string;
      outcome: "issued" | "navigated";
    }) => {
      recordRecentCommand({
        commandKey,
        label,
        scope,
        type,
        href,
        actionId,
      });
      auditCommand({
        auditKey: createAuditKey("execute", commandKey),
        commandKey,
        label,
        scope,
        outcome,
      });
    },
    [auditCommand, recordRecentCommand],
  );

  const executeAuditedAction = useCallback(
    async <TArgs,>({
      commandKey,
      label,
      scope,
      actionId,
      mutation,
      args,
      closeOnSuccess = true,
      onStatusChange,
    }: {
      commandKey: string;
      label: string;
      scope: "navigation" | "context" | "focus";
      actionId?: string;
      mutation: {
        mutate?: (args: TArgs) => void;
        mutateAsync?: (args: TArgs) => Promise<unknown>;
      };
      args: TArgs;
      closeOnSuccess?: boolean;
      onStatusChange?: (status: "pending" | "succeeded" | "failed") => void;
    }) => {
      onStatusChange?.("pending");
      recordPaletteCommand({
        commandKey,
        label,
        scope,
        type: "action",
        actionId,
        outcome: "issued",
      });

      try {
        await runMutationWithFallback(mutation, args);
        auditCommand({
          auditKey: createAuditKey("success", commandKey),
          commandKey,
          label,
          scope,
          outcome: "succeeded",
        });
        onStatusChange?.("succeeded");
        if (closeOnSuccess) {
          handleOpenChange(false);
        }
      } catch {
        auditCommand({
          auditKey: createAuditKey("failed", commandKey),
          commandKey,
          label,
          scope,
          outcome: "failed",
        });
        onStatusChange?.("failed");
      }
    },
    [auditCommand, handleOpenChange, recordPaletteCommand],
  );

  const runRecentCommand = useCallback(
    (entry: RecentCommandEntry) => {
      recordRecentCommand({
        commandKey: entry.commandKey,
        label: entry.label,
        scope: entry.scope,
        type: entry.type,
        sector: entry.sector,
        href: entry.href,
        actionId: entry.actionId,
      });
      auditCommand({
        auditKey: createAuditKey("replay", entry.commandKey),
        commandKey: entry.commandKey,
        label: entry.label,
        scope: entry.scope,
        outcome: "replayed",
      });

      if (entry.type === "route" && entry.href) {
        go(entry.href);
        return;
      }

      if (entry.actionId) {
        switch (entry.actionId) {
          case "sync-vrs-ledger":
            syncVrsLedger.mutate();
            handleOpenChange(false);
            return;
          case "auto-schedule-housekeeping":
            autoScheduleHousekeeping.mutate();
            handleOpenChange(false);
            return;
          case "dispatch-hunter-target":
            enterMode({ kind: "hunter-targets" });
            return;
          case "switch-defcon-mode":
            enterMode({ kind: "defcon-select" });
            return;
          default:
            break;
        }
      }

      switch (entry.commandKey) {
        case "context:open-current-war-room":
          if (legalCaseSlug) go(`/legal/cases/${legalCaseSlug}/war-room`);
          else toast.error("Current legal case context is unavailable.");
          return;
        case "context:refresh-current-case-graph":
          if (legalCaseSlug) {
            refreshCaseGraph.mutate();
            handleOpenChange(false);
          } else {
            toast.error("Current legal case context is unavailable.");
          }
          return;
        case "context:run-current-case-sanctions-sweep":
          if (legalCaseSlug) {
            runSanctionsSweep.mutate();
            handleOpenChange(false);
          } else {
            toast.error("Current legal case context is unavailable.");
          }
          return;
        case "focus:open-adjudication-glass":
          if (operatorFocus?.kind === "adjudication") go("/vrs");
          else toast.error("Adjudication focus is unavailable.");
          return;
        case "focus:dispatch-adjudication-override":
          if (operatorFocus?.kind === "adjudication" && operatorFocus.context.draftBody.trim()) {
            overrideVrsDispatch.mutate({
              id: operatorFocus.context.id,
              body: operatorFocus.context.draftBody,
              consensusConviction: operatorFocus.context.consensusConviction,
              minimumConviction: 0,
            });
            handleOpenChange(false);
          } else {
            toast.error("Adjudication focus is unavailable.");
          }
          return;
        case "focus:open-work-order":
          if (operatorFocus?.kind === "workOrder") go("/work-orders");
          else toast.error("Work order focus is unavailable.");
          return;
        case "focus:mark-work-order-in-progress":
          if (operatorFocus?.kind === "workOrder") {
            updateWorkOrder.mutate({ id: operatorFocus.context.id, status: "in_progress" });
            handleOpenChange(false);
          } else {
            toast.error("Work order focus is unavailable.");
          }
          return;
        case "focus:mark-work-order-completed":
          if (operatorFocus?.kind === "workOrder") {
            updateWorkOrder.mutate({ id: operatorFocus.context.id, status: "completed" });
            handleOpenChange(false);
          } else {
            toast.error("Work order focus is unavailable.");
          }
          return;
        case "focus:open-conversation-thread":
          if (operatorFocus?.kind === "conversation") go("/messages");
          else toast.error("Conversation focus is unavailable.");
          return;
        case "focus:open-active-guest-crm":
          if (operatorFocus?.kind === "conversation") {
            go(`/guests/${operatorFocus.context.guestId}`);
          } else {
            toast.error("Conversation focus is unavailable.");
          }
          return;
        default:
          toast.info("Recent command can no longer be replayed.");
      }
    },
    [
      autoScheduleHousekeeping,
      auditCommand,
      enterMode,
      go,
      handleOpenChange,
      legalCaseSlug,
      operatorFocus,
      overrideVrsDispatch,
      recordRecentCommand,
      refreshCaseGraph,
      runSanctionsSweep,
      syncVrsLedger,
      updateWorkOrder,
    ],
  );

  useEffect(() => {
    if (open) {
      return;
    }

    const down = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey) && e.shiftKey) {
        e.preventDefault();
        if (lastSafeRecentCommand) {
          runRecentCommand(lastSafeRecentCommand);
        } else {
          toast.info("No safe command available to repeat.");
        }
      }
    };

    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [lastSafeRecentCommand, open, runRecentCommand]);

  useEffect(() => {
    if (!open || !["root", "target-resolver"].includes(mode.kind) || activeResolverTargets.length === 0) {
      return;
    }

    const down = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) {
        return;
      }

      const index = Number.parseInt(e.key, 10);
      if (Number.isNaN(index) || index < 1 || index > activeResolverTargets.length) {
        return;
      }

      e.preventDefault();
      activeResolverTargets[index - 1]?.onSelect();
    };

    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [activeResolverTargets, mode.kind, open]);

  const executeCommand = useCallback(
    (item: NavCommandItem) => {
      const commandKey = item.type === "route" ? `route:${item.href}` : `action:${item.actionId}`;

      recordPaletteCommand({
        commandKey,
        label: item.label,
        scope: "navigation",
        type: item.type,
        href: item.href,
        actionId: item.actionId,
        outcome: item.type === "route" ? "navigated" : "issued",
      });

      if (item.type === "route") {
        const href = getNavHref(item);
        if (href) {
          go(href);
        }
        return;
      }

      switch (item.actionId) {
        case "sync-vrs-ledger":
          void executeAuditedAction({
            commandKey,
            label: item.label,
            scope: "navigation",
            actionId: item.actionId,
            mutation: syncVrsLedger,
            args: undefined,
          });
          return;
        case "auto-schedule-housekeeping":
          void executeAuditedAction({
            commandKey,
            label: item.label,
            scope: "navigation",
            actionId: item.actionId,
            mutation: autoScheduleHousekeeping,
            args: undefined,
          });
          return;
        case "dispatch-hunter-target":
          enterMode({ kind: "hunter-targets" });
          return;
        case "switch-defcon-mode":
          enterMode({ kind: "defcon-select" });
          return;
        default:
          toast.info("Command action is not wired yet.");
          setOpen(false);
          setMode({ kind: "root" });
          setInputValue("");
      }
    },
    [
      autoScheduleHousekeeping,
      enterMode,
      executeAuditedAction,
      go,
      recordPaletteCommand,
      syncVrsLedger,
    ],
  );

  const acceptTopSuggestion = useCallback(() => {
    const topSuggestion = didYouMeanEntries[0];
    if (!topSuggestion) {
      return;
    }

    executeCommand({
      ...topSuggestion,
      sector: topSuggestion.sector,
    });
  }, [didYouMeanEntries, executeCommand]);

  const enterTargetActions = useCallback((target: QuickTargetItem, targets: QuickTargetItem[]) => {
    setInlineActionFeedback(null);
    setMode({ kind: "target-actions", target, targets });
  }, []);

  useEffect(() => {
    if (!open || mode.kind !== "root" || didYouMeanEntries.length === 0) {
      return;
    }

    const down = (e: KeyboardEvent) => {
      if (e.key === "Tab") {
        e.preventDefault();
        acceptTopSuggestion();
      }
    };

    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [acceptTopSuggestion, didYouMeanEntries.length, mode.kind, open]);

  return (
    <>
      <button
        onClick={() => handleOpenChange(true)}
        className="flex w-96 items-center gap-3 rounded-none border border-neutral-800 bg-black px-3 py-2 text-sm text-neutral-400 transition-colors hover:bg-neutral-950 hover:text-neutral-200"
      >
        <span aria-hidden="true" className="font-mono text-xs text-neutral-600">
          {">"}
        </span>
        <span className="flex-1 text-left font-mono uppercase tracking-[0.18em]">
          <span className="block">Execute Command</span>
          {operatorFocusSummary && (
            <span className="block text-[10px] tracking-[0.16em] text-neutral-600">
              {operatorFocusSummary}
            </span>
          )}
        </span>
        <kbd className="pointer-events-none hidden h-5 select-none items-center gap-1 rounded-none border border-neutral-800 bg-neutral-950 px-1.5 font-mono text-[10px] font-medium text-neutral-500 sm:flex">
          <span className="text-xs">⌘</span>K
        </kbd>
      </button>

      <CommandDialog open={open} onOpenChange={handleOpenChange}>
        <CommandInput
          value={inputValue}
          onValueChange={setInputValue}
          placeholder={
            mode.kind === "hunter-targets"
              ? "Select Hunter target..."
              : mode.kind === "defcon-select"
                ? "Select DEFCON mode..."
                : mode.kind === "defcon-confirm"
                  ? `Type ENGAGE ${getDefconDisplay(mode.targetMode)}`
              : "Route or execute... (`help:` for syntax)"
          }
        />
        <div className="border-b border-neutral-800 bg-black px-3 py-2 font-mono text-[10px] uppercase tracking-[0.18em] text-neutral-500">
          {">"} mode:{modeLabel}
        </div>
        <CommandList>
          <CommandEmpty>No results found.</CommandEmpty>

          {mode.kind === "root" ? (
            <>
              {(rootScopeFilter === "all" || rootScopeFilter === "help") && (
                <>
                  <CommandGroup heading="HELP">
                    <CommandItem value="help: route prefix" disabled>
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        ?
                      </span>
                      `route:` filter routes only
                      <span className="ml-auto text-xs text-muted-foreground">
                        prefix
                      </span>
                    </CommandItem>
                    <CommandItem value="help: action prefix" disabled>
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        ?
                      </span>
                      `action:` filter actions only
                      <span className="ml-auto text-xs text-muted-foreground">
                        prefix
                      </span>
                    </CommandItem>
                    <CommandItem value="help: focus prefix" disabled>
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        ?
                      </span>
                      `focus:` filter operator focus only
                      <span className="ml-auto text-xs text-muted-foreground">
                        prefix
                      </span>
                    </CommandItem>
                    <CommandItem value="help: recent prefix" disabled>
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        ?
                      </span>
                      `recent:` filter recent commands
                      <span className="ml-auto text-xs text-muted-foreground">
                        prefix
                      </span>
                    </CommandItem>
                    <CommandItem value="help: audit prefix" disabled>
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        ?
                      </span>
                      `audit:` filter audit entries
                      <span className="ml-auto text-xs text-muted-foreground">
                        prefix
                      </span>
                    </CommandItem>
                    <CommandItem value="help: help prefix" disabled>
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        ?
                      </span>
                      `help:` show command help only
                      <span className="ml-auto text-xs text-muted-foreground">
                        prefix
                      </span>
                    </CommandItem>
                    <CommandItem value="help: open shortcut" disabled>
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        ?
                      </span>
                      Open command palette
                      <span className="ml-auto text-xs text-muted-foreground">
                        ⌘/Ctrl+K
                      </span>
                    </CommandItem>
                    <CommandItem value="help: repeat shortcut" disabled>
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        ?
                      </span>
                      Repeat last safe command
                      <span className="ml-auto text-xs text-muted-foreground">
                        ⌘/Ctrl+Shift+K
                      </span>
                    </CommandItem>
                  </CommandGroup>
                  <CommandSeparator />
                </>
              )}
              {dynamicIntentAction?.kind === "guest" && primaryGuestTarget && (
                <>
                  <CommandGroup heading="CHAINED ACTION">
                    <CommandItem
                      value={`chain: crm ${getGuestDisplayName(primaryGuestTarget)} open`}
                      onSelect={() => go(`/guests/${primaryGuestTarget.id}`)}
                    >
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        !
                      </span>
                      Open Guest CRM
                      <span className="ml-auto text-xs text-muted-foreground">
                        {getGuestDisplayName(primaryGuestTarget)}
                      </span>
                    </CommandItem>
                  </CommandGroup>
                  <CommandSeparator />
                </>
              )}
              {dynamicIntentAction?.kind === "workOrder" && primaryWorkOrderTarget && (
                <>
                  <CommandGroup heading="CHAINED ACTION">
                    <CommandItem
                      value={`chain: wo ${primaryWorkOrderTarget.ticket_number} ${dynamicIntentAction.action}`}
                      onSelect={() => {
                        if (dynamicIntentAction.action === "open") {
                          setActiveWorkOrderContext({
                            id: primaryWorkOrderTarget.id,
                            title: primaryWorkOrderTarget.title,
                            ticketNumber: primaryWorkOrderTarget.ticket_number,
                            status: primaryWorkOrderTarget.status,
                            priority: primaryWorkOrderTarget.priority,
                            assignedTo: primaryWorkOrderTarget.assigned_to,
                          });
                          go("/work-orders");
                          return;
                        }

                        void executeAuditedAction({
                          commandKey: `chain:work-order:${dynamicIntentAction.action}`,
                          label:
                            dynamicIntentAction.action === "completed"
                              ? "Mark Selected Work Order Completed"
                              : "Mark Selected Work Order In Progress",
                          scope: "focus",
                          mutation: updateWorkOrder,
                          args: {
                            id: primaryWorkOrderTarget.id,
                            status: dynamicIntentAction.action,
                          },
                        });
                      }}
                    >
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        !
                      </span>
                      {dynamicIntentAction.action === "completed"
                        ? "Complete Work Order"
                        : dynamicIntentAction.action === "in_progress"
                          ? "Start Work Order"
                          : "Open Work Order"}
                      <span className="ml-auto text-xs text-muted-foreground">
                        {primaryWorkOrderTarget.ticket_number}
                      </span>
                    </CommandItem>
                  </CommandGroup>
                  <CommandSeparator />
                </>
              )}
              {dynamicIntentAction?.kind === "warRoom" && primaryLegalCaseTarget && (
                <>
                  <CommandGroup heading="CHAINED ACTION">
                    <CommandItem
                      value={`chain: warroom ${primaryLegalCaseTarget.case_slug} open`}
                      onSelect={() => go(`/legal/cases/${primaryLegalCaseTarget.case_slug}/war-room`)}
                    >
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        !
                      </span>
                      Open War Room
                      <span className="ml-auto text-xs text-muted-foreground">
                        {primaryLegalCaseTarget.case_slug}
                      </span>
                    </CommandItem>
                  </CommandGroup>
                  <CommandSeparator />
                </>
              )}
              {quickTargetItems.length > 0 && (
                <>
                  {quickTargetItems.length > 1 && (
                    <>
                      <CommandGroup heading="RESOLVER">
                        <CommandItem
                          value={`resolver: ${dynamicIntent?.kind ?? "target"}`}
                          onSelect={() =>
                            enterMode(
                              {
                                kind: "target-resolver",
                                targetKind: (dynamicIntent?.kind ?? "guest") as
                                  | "guest"
                                  | "workOrder"
                                  | "warRoom",
                                targets: quickTargetItems,
                              },
                              true,
                            )
                          }
                        >
                          <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                            {">"}
                          </span>
                          Open Target Resolver
                          <span className="ml-auto text-xs text-muted-foreground">
                            Enter
                          </span>
                        </CommandItem>
                      </CommandGroup>
                      <CommandSeparator />
                    </>
                  )}
                  <CommandGroup heading="QUICK TARGETS">
                    {quickTargetItems.map((target, index) => (
                      <CommandItem
                        key={target.key}
                        value={target.value}
                        onSelect={target.onSelect}
                      >
                        <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                          [{index + 1}]
                        </span>
                        <div className="flex min-w-0 flex-1 flex-col">
                          <span className="truncate">{target.primary}</span>
                          <span className="truncate text-[11px] text-muted-foreground">
                            {target.secondary}
                          </span>
                        </div>
                        <span className="ml-auto text-xs text-muted-foreground">
                          {target.tag}
                        </span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                  <CommandSeparator />
                </>
              )}
              {didYouMeanEntries.length > 0 && (
                <>
                  <CommandGroup heading="DID YOU MEAN">
                    <CommandItem
                      key={`did-you-mean-accept-${didYouMeanEntries[0].label}`}
                      value={`suggest: accept ${didYouMeanEntries[0].label}`}
                      onSelect={acceptTopSuggestion}
                    >
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        {">"}
                      </span>
                      Accept Top Suggestion
                      <span className="ml-auto text-xs text-muted-foreground">
                        Tab
                      </span>
                    </CommandItem>
                    {didYouMeanEntries.map((item) => (
                      <CommandItem
                        key={`did-you-mean-${item.sector}-${item.label}`}
                        value={item.value}
                        onSelect={() =>
                          executeCommand({
                            ...item,
                            sector: item.sector,
                          })
                        }
                      >
                        <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                          ~
                        </span>
                        {item.label}
                        <span className="ml-auto text-xs text-muted-foreground">
                          {item.type}
                        </span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                  <CommandSeparator />
                </>
              )}
              {commandAuditTrail.length > 0 && (rootScopeFilter === "all" || rootScopeFilter === "audit") && (
                <>
                  <CommandGroup heading="AUDIT TRAIL">
                    {commandAuditTrail.slice(0, 6).map((entry) => (
                      <CommandItem key={entry.auditKey} value={`audit: ${entry.label}`} disabled>
                        <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                          ;
                        </span>
                        {entry.label}
                        <span className="ml-auto text-xs text-muted-foreground">
                          {entry.outcome} · {formatAuditTimestamp(entry.createdAt)}
                        </span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                  <CommandSeparator />
                </>
              )}
              {lastSafeRecentCommand && (rootScopeFilter === "all" || rootScopeFilter === "recent") && (
                <>
                  <CommandGroup heading="LAST SAFE">
                    <CommandItem
                      key={`last-safe-${lastSafeRecentCommand.commandKey}`}
                      value={withAliases(
                        `recent: repeat ${lastSafeRecentCommand.label}`,
                        "Repeat Last Safe Command",
                      )}
                      onSelect={() => runRecentCommand(lastSafeRecentCommand)}
                    >
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        !
                      </span>
                      Repeat Last Safe Command
                      <span className="ml-auto text-xs text-muted-foreground">
                        {getOutcomeBadgeLabel(
                          latestAuditByCommandKey.get(lastSafeRecentCommand.commandKey),
                        )} ·{" "}
                        ⌘⇧K
                      </span>
                    </CommandItem>
                  </CommandGroup>
                  <CommandSeparator />
                </>
              )}
              {recentCommandHistory.length > 0 && (rootScopeFilter === "all" || rootScopeFilter === "recent") && (
                <>
                  <CommandGroup heading="RECENT">
                    {rankByIntent(
                      recentCommandHistory.map((entry) => ({
                        ...entry,
                        value: withAliases(`recent: ${entry.label}`, entry.label),
                      })),
                      inputValue,
                    ).map((entry) => (
                      <CommandItem
                        key={entry.commandKey}
                        value={entry.value}
                        onSelect={() => runRecentCommand(entry)}
                      >
                        <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                          :
                        </span>
                        {entry.label}
                        <span className="ml-auto text-xs text-muted-foreground">
                          {getOutcomeBadgeLabel(latestAuditByCommandKey.get(entry.commandKey))} ·{" "}
                          {formatRecentTimestamp(entry.executedAt)}
                        </span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                  <CommandSeparator />
                </>
              )}
              {(rootScopeFilter === "all" || rootScopeFilter === "route" || rootScopeFilter === "action") &&
                visibleGroups.map((group, groupIndex) => {
                  const scopedItems = rankByIntent(
                    rootCommandEntries.filter((item) => {
                      if (item.sector !== group.sector) return false;
                      if (rootScopeFilter === "route") return item.type === "route";
                      if (rootScopeFilter === "action") return item.type === "action";
                      return true;
                    }),
                    inputValue,
                  );

                  if (scopedItems.length === 0) {
                    return null;
                  }

                  return (
                <div key={group.sector}>
                  {groupIndex > 0 && <CommandSeparator />}
                  <CommandGroup heading={group.sector}>
                    {scopedItems.map((item) => (
                      <CommandItem
                        key={`${group.sector}-${item.label}`}
                        value={item.value}
                        onSelect={() =>
                          executeCommand({
                            ...item,
                            sector: group.sector,
                          })
                        }
                      >
                        <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                          {item.type === "route" ? ">" : "+"}
                        </span>
                        <span className={item.isMono ? "font-mono text-[13px]" : ""}>
                          {item.label}
                        </span>
                        <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                          {item.type}
                        </span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </div>
                  );
                })}
            </>
          ) : mode.kind === "hunter-targets" ? (
            <>
              <CommandGroup heading="PAPERCLIP AI">
                <CommandItem onSelect={() => enterMode({ kind: "root" })}>
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    {"<"}
                  </span>
                  Back To Command Index
                </CommandItem>
              </CommandGroup>
              <CommandSeparator />
              <CommandGroup heading="SELECT HUNTER TARGET">
                {hunterTargetsQuery.isLoading && (
                  <CommandItem
                    key="loading-hunter-targets"
                    value="loading-hunter-targets"
                    disabled
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] text-muted-foreground">
                      ..
                    </span>
                    Loading dispatch targets...
                  </CommandItem>
                )}
                {!hunterTargetsQuery.isLoading &&
                  (hunterTargetsQuery.data ?? []).slice(0, 12).map((target) => (
                    <CommandItem
                      key={target.guest_id}
                      onSelect={() => executeHunterDispatch(target)}
                    >
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        @
                      </span>
                      <span>{target.full_name}</span>
                      <span className="ml-auto text-xs text-muted-foreground">
                        {Math.round(target.target_score)} score
                      </span>
                    </CommandItem>
                  ))}
                {!hunterTargetsQuery.isLoading &&
                  (hunterTargetsQuery.data ?? []).length === 0 && (
                    <CommandItem key="no-hunter-targets" value="no-hunter-targets" disabled>
                      <span className="mr-2 w-4 font-mono text-[10px] text-muted-foreground">
                        --
                      </span>
                      No dispatchable Hunter targets found.
                    </CommandItem>
                  )}
              </CommandGroup>
            </>
          ) : mode.kind === "target-resolver" ? (
            <>
              <CommandGroup heading="TARGET RESOLVER">
                <CommandItem onSelect={() => enterMode({ kind: "root" })}>
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    {"<"}
                  </span>
                  Back To Command Index
                </CommandItem>
              </CommandGroup>
              <CommandSeparator />
              <CommandGroup heading="RESOLVED TARGETS">
                {quickTargetItems.map((target, index) => (
                  <CommandItem
                    key={`resolver-${target.key}`}
                    value={target.value}
                    onSelect={() => enterTargetActions(target, activeResolverTargets)}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      [{index + 1}]
                    </span>
                    <div className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate">{target.primary}</span>
                      <span className="truncate text-[11px] text-muted-foreground">
                        {target.secondary}
                      </span>
                    </div>
                    <span className="ml-auto text-xs text-muted-foreground">
                      {target.tag}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          ) : mode.kind === "target-actions" ? (
            <>
              <CommandGroup heading="TARGET ACTIONS">
                <CommandItem
                  onSelect={() =>
                    enterMode(
                      {
                        kind: "target-resolver",
                        targetKind: mode.target.targetKind,
                        targets: mode.targets,
                      },
                      true,
                    )
                  }
                >
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    {"<"}
                  </span>
                  Back To Resolved Targets
                </CommandItem>
              </CommandGroup>
              <CommandSeparator />
              {inlineActionFeedback && (
                <>
                  <CommandGroup heading="ACTION STATUS">
                    <CommandItem value={`status:${inlineActionFeedback.commandKey}`} disabled>
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        :
                      </span>
                      {inlineActionFeedback.commandKey}
                      <span className="ml-auto text-xs text-muted-foreground">
                        {inlineActionFeedback.status}
                      </span>
                    </CommandItem>
                  </CommandGroup>
                  <CommandSeparator />
                </>
              )}
              <CommandGroup heading={mode.target.primary.toUpperCase()}>
                {mode.target.targetKind === "guest" && (
                  <CommandItem
                    value={withAliases("route: Open Guest CRM", "Open Guest CRM")}
                    onSelect={mode.target.onSelect}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      {">"}
                    </span>
                    Open Guest CRM
                    <span className="ml-auto text-xs text-muted-foreground">
                      guest
                    </span>
                  </CommandItem>
                )}
                {mode.target.targetKind === "workOrder" && (
                  <>
                    <CommandItem
                      value={withAliases("route: Open Work Order", "Open Work Order")}
                      onSelect={mode.target.onSelect}
                    >
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        {">"}
                      </span>
                      Open Work Order
                      <span className="ml-auto text-xs text-muted-foreground">
                        route
                      </span>
                    </CommandItem>
                    <CommandItem
                      value={withAliases("action: Start Work Order", "Start Work Order")}
                      onSelect={() => {
                        const target = workOrderTargets.find((item) => item.id === mode.target.key.replace("work-order-target-", ""));
                        if (!target) return;
                        void executeAuditedAction({
                          commandKey: "resolver:mark-work-order-in-progress",
                          label: "Mark Selected Work Order In Progress",
                          scope: "focus",
                          mutation: updateWorkOrder,
                          args: {
                            id: target.id,
                            status: "in_progress",
                          },
                          closeOnSuccess: false,
                          onStatusChange: (status) =>
                            setInlineActionFeedback({
                              commandKey: "resolver:mark-work-order-in-progress",
                              status,
                            }),
                        });
                      }}
                    >
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        +
                      </span>
                      Start Work Order
                      <span className="ml-auto text-xs text-muted-foreground">
                        action
                      </span>
                    </CommandItem>
                    <CommandItem
                      value={withAliases("action: Complete Work Order", "Complete Work Order")}
                      onSelect={() => {
                        const target = workOrderTargets.find((item) => item.id === mode.target.key.replace("work-order-target-", ""));
                        if (!target) return;
                        void executeAuditedAction({
                          commandKey: "resolver:mark-work-order-completed",
                          label: "Mark Selected Work Order Completed",
                          scope: "focus",
                          mutation: updateWorkOrder,
                          args: {
                            id: target.id,
                            status: "completed",
                          },
                          closeOnSuccess: false,
                          onStatusChange: (status) =>
                            setInlineActionFeedback({
                              commandKey: "resolver:mark-work-order-completed",
                              status,
                            }),
                        });
                      }}
                    >
                      <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                        +
                      </span>
                      Complete Work Order
                      <span className="ml-auto text-xs text-muted-foreground">
                        action
                      </span>
                    </CommandItem>
                  </>
                )}
                {mode.target.targetKind === "warRoom" && (
                  <CommandItem
                    value={withAliases("route: Open War Room", "Open War Room")}
                    onSelect={mode.target.onSelect}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      {">"}
                    </span>
                    Open War Room
                    <span className="ml-auto text-xs text-muted-foreground">
                      case
                    </span>
                  </CommandItem>
                )}
              </CommandGroup>
            </>
          ) : mode.kind === "defcon-select" ? (
            <>
              <CommandGroup heading="SHADOW OPS">
                <CommandItem onSelect={() => enterMode({ kind: "root" })}>
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    {"<"}
                  </span>
                  Back To Command Index
                </CommandItem>
              </CommandGroup>
              <CommandSeparator />
              <CommandGroup heading="SELECT DEFCON MODE">
                <CommandItem onSelect={() => enterMode({ kind: "defcon-confirm", targetMode: "swarm" })}>
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    !
                  </span>
                  SWARM
                </CommandItem>
                <CommandItem
                  onSelect={() =>
                    enterMode({ kind: "defcon-confirm", targetMode: "fortress_legal" })
                  }
                >
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    !
                  </span>
                  FORTRESS_LEGAL
                </CommandItem>
              </CommandGroup>
            </>
          ) : (
            <div className="border-t border-neutral-800">
              <div className="border-b border-neutral-800 px-4 py-3">
                <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                  SHADOW OPS
                </p>
                <p className="mt-1 text-sm text-foreground">
                  Confirm DEFCON switch to{" "}
                  <span className="font-mono">{getDefconDisplay(mode.targetMode)}</span>
                </p>
                <p className="mt-2 font-mono text-[11px] text-muted-foreground">
                  Type ENGAGE {getDefconDisplay(mode.targetMode)}
                </p>
              </div>
              <div className="space-y-3 px-4 py-4">
                <button
                  type="button"
                  onClick={executeDefconSwitch}
                  disabled={setDefcon.isPending}
                  className="flex w-full items-center justify-between border border-neutral-800 px-3 py-2 text-left text-sm text-neutral-200 transition-colors disabled:cursor-not-allowed disabled:opacity-40 hover:bg-neutral-950"
                >
                  <span>Authorize DEFCON Switch</span>
                  <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-500">
                    {setDefcon.isPending ? "pending" : "execute"}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => enterMode({ kind: "defcon-select" })}
                  className="flex w-full items-center justify-between border border-neutral-900 px-3 py-2 text-left text-sm text-neutral-400 transition-colors hover:bg-neutral-950 hover:text-neutral-200"
                >
                  <span>Back To Mode Select</span>
                  <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-600">
                    cancel
                  </span>
                </button>
              </div>
            </div>
          )}

          {mode.kind === "root" &&
            legalCaseSlug &&
            (rootScopeFilter === "all" || rootScopeFilter === "route" || rootScopeFilter === "action") && (
            <>
              <CommandSeparator />
              <CommandGroup heading="CURRENT CONTEXT">
                {!isWarRoomPath && rootScopeFilter !== "action" && (
                  <CommandItem
                    value={withAliases(
                      "route: Open Current Docket War Room",
                      "Open Current Docket War Room",
                    )}
                    onSelect={() => go(`/legal/cases/${legalCaseSlug}/war-room`)}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      {">"}
                    </span>
                    Open Current Docket War Room
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      route
                    </span>
                  </CommandItem>
                )}
                {rootScopeFilter !== "route" && <CommandItem
                  value={withAliases(
                    "action: Refresh Current Case Graph",
                    "Refresh Current Case Graph",
                  )}
                  onSelect={() => {
                    void executeAuditedAction({
                      commandKey: "context:refresh-current-case-graph",
                      label: "Refresh Current Case Graph",
                      scope: "context",
                      mutation: refreshCaseGraph,
                      args: undefined,
                    });
                  }}
                >
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    +
                  </span>
                  Refresh Current Case Graph
                  <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    action
                  </span>
                </CommandItem>}
                {rootScopeFilter !== "route" && <CommandItem
                  value={withAliases(
                    "action: Run Current Case Sanctions Sweep",
                    "Run Current Case Sanctions Sweep",
                  )}
                  onSelect={() => {
                    void executeAuditedAction({
                      commandKey: "context:run-current-case-sanctions-sweep",
                      label: "Run Current Case Sanctions Sweep",
                      scope: "context",
                      mutation: runSanctionsSweep,
                      args: undefined,
                    });
                  }}
                >
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    +
                  </span>
                  Run Current Case Sanctions Sweep
                  <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    action
                  </span>
                </CommandItem>}
              </CommandGroup>
            </>
          )}

          {mode.kind === "root" && rootScopeFilter !== "route" && rootScopeFilter !== "action" && operatorFocus?.kind === "adjudication" && (
            <>
              <CommandSeparator />
              <CommandGroup heading="OPERATOR FOCUS">
                <CommandItem
                  value={withAliases("focus: Clear Focus Context", "Clear Focus Context")}
                  onSelect={() => {
                    clearOperatorFocus();
                    handleOpenChange(false);
                  }}
                >
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    -
                  </span>
                  Clear Focus Context
                  <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    reset
                  </span>
                </CommandItem>
                <CommandItem value="focus-status-adjudication" disabled>
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    :
                  </span>
                  Focus Status
                  <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    {pinnedOperatorFocusKind === operatorFocus.kind ? "pinned" : "live"}
                  </span>
                </CommandItem>
                {pinnedOperatorFocusKind === operatorFocus.kind ? (
                  <CommandItem
                    value={withAliases("focus: Unpin Operator Focus", "Unpin Operator Focus")}
                    onSelect={() => clearPinnedOperatorFocus()}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      x
                    </span>
                    Unpin Operator Focus
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      focus
                    </span>
                  </CommandItem>
                ) : (
                  <CommandItem
                    value={withAliases("focus: Pin Current Focus", "Pin Current Focus")}
                    onSelect={() => pinOperatorFocus(operatorFocus.kind)}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      !
                    </span>
                    Pin Current Focus
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      focus
                    </span>
                  </CommandItem>
                )}
                {!pathname.startsWith("/vrs") && (
                  <CommandItem
                    value={withAliases("route: Open Adjudication Glass", "Open Adjudication Glass")}
                    onSelect={() => go("/vrs")}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      {">"}
                    </span>
                    Open Adjudication Glass
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      route
                    </span>
                  </CommandItem>
                )}
                <CommandItem
                  value={withAliases(
                    "action: Dispatch Selected Adjudication Override",
                    "Dispatch Selected Adjudication Override",
                  )}
                  onSelect={() => {
                    void executeAuditedAction({
                      commandKey: "focus:dispatch-adjudication-override",
                      label: "Dispatch Selected Adjudication Override",
                      scope: "focus",
                      mutation: overrideVrsDispatch,
                      args: {
                        id: operatorFocus.context.id,
                        body: operatorFocus.context.draftBody,
                        consensusConviction: operatorFocus.context.consensusConviction,
                        minimumConviction: 0,
                      },
                    });
                  }}
                  disabled={!operatorFocus.context.draftBody.trim()}
                >
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    +
                  </span>
                  Dispatch Selected Adjudication Override
                  <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    action
                  </span>
                </CommandItem>
                <CommandItem value={`adjudication-${operatorFocus.context.id}`} disabled>
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    @
                  </span>
                  {operatorFocus.context.guestName}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {operatorFocus.context.consensusSignal || "NO_SIGNAL"}
                  </span>
                </CommandItem>
              </CommandGroup>
            </>
          )}

          {mode.kind === "root" && rootScopeFilter !== "route" && rootScopeFilter !== "action" && operatorFocus?.kind === "workOrder" && (
            <>
              <CommandSeparator />
              <CommandGroup heading="OPERATOR FOCUS">
                <CommandItem
                  value={withAliases("focus: Clear Focus Context", "Clear Focus Context")}
                  onSelect={() => {
                    clearOperatorFocus();
                    handleOpenChange(false);
                  }}
                >
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    -
                  </span>
                  Clear Focus Context
                  <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    reset
                  </span>
                </CommandItem>
                <CommandItem value="focus-status-workorder" disabled>
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    :
                  </span>
                  Focus Status
                  <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    {pinnedOperatorFocusKind === operatorFocus.kind ? "pinned" : "live"}
                  </span>
                </CommandItem>
                {pinnedOperatorFocusKind === operatorFocus.kind ? (
                  <CommandItem
                    value={withAliases("focus: Unpin Operator Focus", "Unpin Operator Focus")}
                    onSelect={() => clearPinnedOperatorFocus()}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      x
                    </span>
                    Unpin Operator Focus
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      focus
                    </span>
                  </CommandItem>
                ) : (
                  <CommandItem
                    value={withAliases("focus: Pin Current Focus", "Pin Current Focus")}
                    onSelect={() => pinOperatorFocus(operatorFocus.kind)}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      !
                    </span>
                    Pin Current Focus
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      focus
                    </span>
                  </CommandItem>
                )}
                {!pathname.startsWith("/work-orders") && (
                  <CommandItem
                    value={withAliases("route: Open Selected Work Order", "Open Selected Work Order")}
                    onSelect={() => go("/work-orders")}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      {">"}
                    </span>
                    Open Selected Work Order
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      route
                    </span>
                  </CommandItem>
                )}
                {operatorFocus.context.status !== "in_progress" && (
                  <CommandItem
                    value={withAliases(
                      "action: Mark Selected Work Order In Progress",
                      "Mark Selected Work Order In Progress",
                    )}
                    onSelect={() => {
                      void executeAuditedAction({
                        commandKey: "focus:mark-work-order-in-progress",
                        label: "Mark Selected Work Order In Progress",
                        scope: "focus",
                        mutation: updateWorkOrder,
                        args: {
                          id: operatorFocus.context.id,
                          status: "in_progress",
                        },
                      });
                    }}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      +
                    </span>
                    Mark Selected Work Order In Progress
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      action
                    </span>
                  </CommandItem>
                )}
                {operatorFocus.context.status !== "completed" && (
                  <CommandItem
                    value={withAliases(
                      "action: Mark Selected Work Order Completed",
                      "Mark Selected Work Order Completed",
                    )}
                    onSelect={() => {
                      void executeAuditedAction({
                        commandKey: "focus:mark-work-order-completed",
                        label: "Mark Selected Work Order Completed",
                        scope: "focus",
                        mutation: updateWorkOrder,
                        args: {
                          id: operatorFocus.context.id,
                          status: "completed",
                        },
                      });
                    }}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      +
                    </span>
                    Mark Selected Work Order Completed
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      action
                    </span>
                  </CommandItem>
                )}
                <CommandItem value={`work-order-${operatorFocus.context.id}`} disabled>
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    #
                  </span>
                  {operatorFocus.context.title}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {operatorFocus.context.ticketNumber}
                  </span>
                </CommandItem>
              </CommandGroup>
            </>
          )}

          {mode.kind === "root" && rootScopeFilter !== "route" && rootScopeFilter !== "action" && operatorFocus?.kind === "conversation" && (
            <>
              <CommandSeparator />
              <CommandGroup heading="OPERATOR FOCUS">
                <CommandItem
                  value={withAliases("focus: Clear Focus Context", "Clear Focus Context")}
                  onSelect={() => {
                    clearOperatorFocus();
                    handleOpenChange(false);
                  }}
                >
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    -
                  </span>
                  Clear Focus Context
                  <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    reset
                  </span>
                </CommandItem>
                <CommandItem value="focus-status-conversation" disabled>
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    :
                  </span>
                  Focus Status
                  <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    {pinnedOperatorFocusKind === operatorFocus.kind ? "pinned" : "live"}
                  </span>
                </CommandItem>
                {pinnedOperatorFocusKind === operatorFocus.kind ? (
                  <CommandItem
                    value={withAliases("focus: Unpin Operator Focus", "Unpin Operator Focus")}
                    onSelect={() => clearPinnedOperatorFocus()}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      x
                    </span>
                    Unpin Operator Focus
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      focus
                    </span>
                  </CommandItem>
                ) : (
                  <CommandItem
                    value={withAliases("focus: Pin Current Focus", "Pin Current Focus")}
                    onSelect={() => pinOperatorFocus(operatorFocus.kind)}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      !
                    </span>
                    Pin Current Focus
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      focus
                    </span>
                  </CommandItem>
                )}
                {!pathname.startsWith("/messages") && (
                  <CommandItem
                    value={withAliases(
                      "route: Open Active Conversation Thread",
                      "Open Active Conversation Thread",
                    )}
                    onSelect={() => go("/messages")}
                  >
                    <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                      {">"}
                    </span>
                    Open Active Conversation Thread
                    <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                      route
                    </span>
                  </CommandItem>
                )}
                <CommandItem
                  value={withAliases("route: Open Active Guest CRM", "Open Active Guest CRM")}
                  onSelect={() => go(`/guests/${operatorFocus.context.guestId}`)}
                >
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    {">"}
                  </span>
                  Open Active Guest CRM
                  <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                    route
                  </span>
                </CommandItem>
                <CommandItem value={`conversation-${operatorFocus.context.guestPhone}`} disabled>
                  <span className="mr-2 w-4 font-mono text-[10px] uppercase text-muted-foreground">
                    @
                  </span>
                  {operatorFocus.context.guestName}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {operatorFocus.context.guestPhone}
                  </span>
                </CommandItem>
              </CommandGroup>
            </>
          )}

          {mode.kind === "root" &&
            (rootScopeFilter === "all" || rootScopeFilter === "route") &&
            Array.isArray(properties) &&
            properties.length > 0 && (
            <>
              <CommandSeparator />
              <CommandGroup heading="Properties">
                {(properties ?? []).slice(0, 8).map((p) => (
                  <CommandItem key={p.id} value={`route: ${p.name}`} onSelect={() => go(`/properties/${p.id}`)}>
                    <span className="mr-2 w-4 font-mono text-[10px] text-muted-foreground">
                      []
                    </span>
                    {p.name}
                    <span className="ml-auto text-xs text-muted-foreground">
                      {p.bedrooms}BR · Sleeps {p.max_guests}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          )}

          {mode.kind === "root" &&
            (rootScopeFilter === "all" || rootScopeFilter === "route") &&
            Array.isArray(guests) &&
            guests.length > 0 && (
            <>
              <CommandSeparator />
              <CommandGroup heading="Guests">
                {(guests ?? []).slice(0, 6).map((g) => (
                  <CommandItem key={g.id} value={`route: ${getGuestDisplayName(g)}`} onSelect={() => go(`/guests/${g.id}`)}>
                    <span className="mr-2 w-4 font-mono text-[10px] text-muted-foreground">
                      @
                    </span>
                    {getGuestDisplayName(g)}
                    {g.email && (
                      <span className="ml-auto text-xs text-muted-foreground">
                        {g.email}
                      </span>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            </>
          )}
        </CommandList>
        <div className="flex items-center justify-between border-t border-neutral-800 bg-black px-3 py-2 font-mono text-[10px] uppercase tracking-[0.16em] text-neutral-600">
          <span>scope:{mode.kind === "root" ? rootScopeFilter : mode.kind}</span>
          <span>focus:{operatorFocusStateLabel}</span>
          <span className={cn(getLastOutcomeTone(lastCommandOutcome))}>
            last:{getLastOutcomeCode(lastCommandOutcome)}:{lastCommandOutcome}
          </span>
          <span>repeat:{lastSafeRecentCommand ? "armed" : "idle"}</span>
        </div>
      </CommandDialog>
    </>
  );
}
