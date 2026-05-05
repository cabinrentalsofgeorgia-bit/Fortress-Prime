"use client";

import { useEffect, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getToken } from "./api";
import type { SystemHealthResponse } from "./types";
import { useSystemHealthWsStore } from "./system-health-ws-store";

const MIN_RECONNECT_MS = 1_000;
const MAX_RECONNECT_MS = 30_000;

/** Build backend WebSocket URL for `/api/telemetry/ws/system-health` (not the dashboard `/ws` fanout). */
export function buildSystemHealthWsUrl(token: string): string | null {
  if (typeof window === "undefined") return null;
  const t = token.trim();
  if (!t) return null;

  const explicit = process.env.NEXT_PUBLIC_SYSTEM_HEALTH_WS_URL?.trim();
  if (explicit) {
    const u = new URL(explicit, window.location.origin);
    u.searchParams.set("token", t);
    return u.toString();
  }

  const wsOverride = process.env.NEXT_PUBLIC_WS_URL?.trim();
  if (wsOverride) {
    const root = wsOverride.replace(/\/ws\/?$/i, "");
    const proto = root.startsWith("wss://") ? "wss:" : "ws:";
    const hostPath = root.replace(/^wss?:\/\//i, "");
    return `${proto}//${hostPath}/api/telemetry/ws/system-health?token=${encodeURIComponent(t)}`;
  }

  const base = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (base) {
    const wsRoot = base.replace(/^http/i, "ws");
    return `${wsRoot}/api/telemetry/ws/system-health?token=${encodeURIComponent(t)}`;
  }

  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/telemetry/ws/system-health?token=${encodeURIComponent(t)}`;
}

export function useSystemHealthWebSocket() {
  const qc = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const attemptRef = useRef(0);
  const connectRef = useRef<(() => void) | undefined>(undefined);
  const setWsStatus = useSystemHealthWsStore((s) => s.setWsStatus);
  const setLastMessageAt = useSystemHealthWsStore((s) => s.setLastMessageAt);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const token = getToken();
    const url = buildSystemHealthWsUrl(token ?? "");
    if (!url) {
      setWsStatus("disconnected");
      return;
    }

    setWsStatus("connecting");

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      setWsStatus("disconnected");
      return;
    }

    ws.onopen = () => {
      attemptRef.current = 0;
      setWsStatus("connected");
    };

    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data as string) as SystemHealthResponse;
        qc.setQueryData<SystemHealthResponse>(["system-health"], data);
        setLastMessageAt(Date.now());
      } catch {
        /* ignore malformed */
      }
    };

    ws.onclose = () => {
      setWsStatus("disconnected");
      const delay = Math.min(MIN_RECONNECT_MS * 2 ** attemptRef.current, MAX_RECONNECT_MS);
      attemptRef.current += 1;
      reconnectTimer.current = setTimeout(() => connectRef.current?.(), delay);
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, [qc, setLastMessageAt, setWsStatus]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect]);
}
