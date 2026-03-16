"use client";

import { useEffect, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

function buildWsUrl(): string | null {
  if (typeof window === "undefined") return null;
  const wsOverride = process.env.NEXT_PUBLIC_WS_URL;
  if (wsOverride) return wsOverride;
  const base = process.env.NEXT_PUBLIC_API_URL;
  if (base) {
    return base.replace("http://", "ws://").replace("https://", "wss://") + "/ws";
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws`;
}

const MIN_RECONNECT_MS = 1_000;
const MAX_RECONNECT_MS = 30_000;

type WsEvent = {
  event: string;
  data: Record<string, unknown>;
  timestamp: string;
};

function handleWsEvent(qc: ReturnType<typeof useQueryClient>, msg: WsEvent) {
  switch (msg.event) {
    case "new_message":
      qc.invalidateQueries({ queryKey: ["messages"] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
      qc.invalidateQueries({ queryKey: ["dashboard-stats"] });
      break;
    case "reservation_update":
      qc.invalidateQueries({ queryKey: ["reservations"] });
      qc.invalidateQueries({ queryKey: ["dashboard-stats"] });
      break;
    case "work_order_update":
      qc.invalidateQueries({ queryKey: ["work-orders"] });
      qc.invalidateQueries({ queryKey: ["dashboard-stats"] });
      break;
    case "review_queue_item":
      qc.invalidateQueries({ queryKey: ["review-queue"] });
      break;
    case "stats_update":
      qc.invalidateQueries({ queryKey: ["dashboard-stats"] });
      break;
  }

  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("fortress-ws", { detail: msg }));
  }
}

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const qc = useQueryClient();
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const attemptRef = useRef(0);
  const connectRef = useRef<() => void>(undefined);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const url = buildWsUrl();
    if (!url) return;

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      return;
    }

    ws.onopen = () => {
      attemptRef.current = 0;
    };

    ws.onmessage = (evt) => {
      try {
        handleWsEvent(qc, JSON.parse(evt.data));
      } catch {
        /* ignore non-json */
      }
    };

    ws.onclose = () => {
      const delay = Math.min(MIN_RECONNECT_MS * 2 ** attemptRef.current, MAX_RECONNECT_MS);
      attemptRef.current += 1;
      reconnectTimer.current = setTimeout(() => connectRef.current?.(), delay);
    };

    ws.onerror = () => {
      ws.close();
    };

    wsRef.current = ws;
  }, [qc]);

  connectRef.current = connect;

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);
}
