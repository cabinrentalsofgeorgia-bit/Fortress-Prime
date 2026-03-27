"use client";

import { create } from "zustand";

export type SystemHealthWsStatus = "idle" | "connecting" | "connected" | "disconnected";

interface SystemHealthWsSlice {
  wsStatus: SystemHealthWsStatus;
  lastMessageAt: number | null;
  setWsStatus: (wsStatus: SystemHealthWsStatus) => void;
  setLastMessageAt: (ts: number | null) => void;
}

export const useSystemHealthWsStore = create<SystemHealthWsSlice>((set) => ({
  wsStatus: "idle",
  lastMessageAt: null,
  setWsStatus: (wsStatus) => set({ wsStatus }),
  setLastMessageAt: (lastMessageAt) => set({ lastMessageAt }),
}));
