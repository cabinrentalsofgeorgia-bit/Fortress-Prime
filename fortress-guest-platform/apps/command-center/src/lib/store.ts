"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface AuthUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: string;
}

export interface ActiveAdjudicationContext {
  id: string;
  guestName: string;
  propertyName?: string | null;
  consensusSignal?: string | null;
  consensusConviction?: number;
  draftBody: string;
}

export interface ActiveWorkOrderContext {
  id: string;
  title: string;
  ticketNumber: string;
  status: string;
  priority: string;
  propertyName?: string | null;
  assignedTo?: string | null;
}

export interface ActiveConversationContext {
  guestId: string;
  guestName: string;
  guestPhone: string;
  propertyName?: string | null;
  lastMessage?: string | null;
  unreadCount: number;
}

export type OperatorFocusKind =
  | "adjudication"
  | "workOrder"
  | "conversation";

export type OperatorFocus =
  | { kind: "adjudication"; context: ActiveAdjudicationContext }
  | { kind: "workOrder"; context: ActiveWorkOrderContext }
  | { kind: "conversation"; context: ActiveConversationContext };

export interface RecentCommandEntry {
  commandKey: string;
  label: string;
  scope: "navigation" | "context" | "focus";
  type: "route" | "action";
  sector?: string;
  href?: string;
  actionId?: string;
  executedAt: number;
}

export interface CommandAuditEntry {
  auditKey: string;
  commandKey: string;
  label: string;
  scope: "navigation" | "context" | "focus";
  outcome:
    | "issued"
    | "navigated"
    | "replayed"
    | "succeeded"
    | "rejected"
    | "failed";
  createdAt: number;
}

interface AppState {
  user: AuthUser | null;
  sidebarCollapsed: boolean;
  recentCommandHistory: RecentCommandEntry[];
  commandAuditTrail: CommandAuditEntry[];
  activeAdjudicationContext: ActiveAdjudicationContext | null;
  activeWorkOrderContext: ActiveWorkOrderContext | null;
  activeConversationContext: ActiveConversationContext | null;
  pinnedOperatorFocusKind: OperatorFocusKind | null;
  activeAdjudicationContextUpdatedAt: number;
  activeWorkOrderContextUpdatedAt: number;
  activeConversationContextUpdatedAt: number;
  setUser: (user: AuthUser | null) => void;
  setSidebarCollapsed: (v: boolean) => void;
  toggleSidebar: () => void;
  setActiveAdjudicationContext: (context: ActiveAdjudicationContext | null) => void;
  clearActiveAdjudicationContext: () => void;
  setActiveWorkOrderContext: (context: ActiveWorkOrderContext | null) => void;
  clearActiveWorkOrderContext: () => void;
  setActiveConversationContext: (context: ActiveConversationContext | null) => void;
  clearActiveConversationContext: () => void;
  pinOperatorFocus: (kind: OperatorFocusKind) => void;
  clearPinnedOperatorFocus: () => void;
  clearOperatorFocus: () => void;
  recordRecentCommand: (entry: Omit<RecentCommandEntry, "executedAt">) => void;
  recordCommandAudit: (entry: Omit<CommandAuditEntry, "createdAt">) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      user: null,
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
      setUser: (user) => set({ user }),
      setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setActiveAdjudicationContext: (context) =>
        set({
          activeAdjudicationContext: context,
          activeAdjudicationContextUpdatedAt: context ? Date.now() : 0,
        }),
      clearActiveAdjudicationContext: () =>
        set({ activeAdjudicationContext: null, activeAdjudicationContextUpdatedAt: 0 }),
      setActiveWorkOrderContext: (context) =>
        set({
          activeWorkOrderContext: context,
          activeWorkOrderContextUpdatedAt: context ? Date.now() : 0,
        }),
      clearActiveWorkOrderContext: () =>
        set({ activeWorkOrderContext: null, activeWorkOrderContextUpdatedAt: 0 }),
      setActiveConversationContext: (context) =>
        set({
          activeConversationContext: context,
          activeConversationContextUpdatedAt: context ? Date.now() : 0,
        }),
      clearActiveConversationContext: () =>
        set({ activeConversationContext: null, activeConversationContextUpdatedAt: 0 }),
      pinOperatorFocus: (kind) => set({ pinnedOperatorFocusKind: kind }),
      clearPinnedOperatorFocus: () => set({ pinnedOperatorFocusKind: null }),
      clearOperatorFocus: () =>
        set({
          activeAdjudicationContext: null,
          activeWorkOrderContext: null,
          activeConversationContext: null,
          pinnedOperatorFocusKind: null,
          activeAdjudicationContextUpdatedAt: 0,
          activeWorkOrderContextUpdatedAt: 0,
          activeConversationContextUpdatedAt: 0,
        }),
      recordRecentCommand: (entry) =>
        set((state) => {
          const nextEntry: RecentCommandEntry = {
            ...entry,
            executedAt: Date.now(),
          };
          const deduped = state.recentCommandHistory.filter(
            (item) => item.commandKey !== nextEntry.commandKey,
          );

          return {
            recentCommandHistory: [nextEntry, ...deduped].slice(0, 8),
          };
        }),
      recordCommandAudit: (entry) =>
        set((state) => ({
          commandAuditTrail: [
            {
              ...entry,
              createdAt: Date.now(),
            },
            ...state.commandAuditTrail,
          ].slice(0, 20),
        })),
    }),
    {
      name: "fortress-app-store",
      partialize: (state) => ({
        user: state.user,
        sidebarCollapsed: state.sidebarCollapsed,
        recentCommandHistory: state.recentCommandHistory,
        commandAuditTrail: state.commandAuditTrail,
      }),
    },
  ),
);

export function getOperatorFocus(state: Pick<
  AppState,
  | "activeAdjudicationContext"
  | "activeWorkOrderContext"
  | "activeConversationContext"
  | "pinnedOperatorFocusKind"
  | "activeAdjudicationContextUpdatedAt"
  | "activeWorkOrderContextUpdatedAt"
  | "activeConversationContextUpdatedAt"
>): OperatorFocus | null {
  if (state.pinnedOperatorFocusKind === "adjudication" && state.activeAdjudicationContext) {
    return { kind: "adjudication", context: state.activeAdjudicationContext };
  }

  if (state.pinnedOperatorFocusKind === "workOrder" && state.activeWorkOrderContext) {
    return { kind: "workOrder", context: state.activeWorkOrderContext };
  }

  if (state.pinnedOperatorFocusKind === "conversation" && state.activeConversationContext) {
    return { kind: "conversation", context: state.activeConversationContext };
  }

  const candidates: Array<{
    kind: OperatorFocusKind;
    updatedAt: number;
    context: ActiveAdjudicationContext | ActiveWorkOrderContext | ActiveConversationContext;
  }> = [];

  if (state.activeAdjudicationContext) {
    candidates.push({
      kind: "adjudication",
      updatedAt: state.activeAdjudicationContextUpdatedAt,
      context: state.activeAdjudicationContext,
    });
  }

  if (state.activeWorkOrderContext) {
    candidates.push({
      kind: "workOrder",
      updatedAt: state.activeWorkOrderContextUpdatedAt,
      context: state.activeWorkOrderContext,
    });
  }

  if (state.activeConversationContext) {
    candidates.push({
      kind: "conversation",
      updatedAt: state.activeConversationContextUpdatedAt,
      context: state.activeConversationContext,
    });
  }

  const latest = candidates.sort((a, b) => b.updatedAt - a.updatedAt)[0];
  if (!latest) {
    return null;
  }

  if (latest.kind === "adjudication") {
    return { kind: "adjudication", context: latest.context as ActiveAdjudicationContext };
  }

  if (latest.kind === "workOrder") {
    return { kind: "workOrder", context: latest.context as ActiveWorkOrderContext };
  }

  return { kind: "conversation", context: latest.context as ActiveConversationContext };
}
