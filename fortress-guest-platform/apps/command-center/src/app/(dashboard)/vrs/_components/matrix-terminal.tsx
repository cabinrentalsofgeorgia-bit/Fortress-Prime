"use client";

import { memo, useEffect, useRef, useState } from "react";
import { Terminal as TerminalIcon } from "lucide-react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { getToken } from "@/lib/api";

type MatrixDispatchResponse = {
  task_id?: string;
  status?: string;
  action_log?: string[];
  result_payload?: Record<string, unknown>;
  sandbox_name?: string;
  execution_path?: string;
  log?: string;
  error?: string;
  details?: string;
  [key: string]: unknown;
};

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
}

type LogEntry = {
  timestamp: string;
  text: string;
  type: "info" | "success" | "error" | "command";
};

const DEFAULT_INPUT = JSON.stringify(
  {
    intent: "draft_recovery_email",
    context_payload: {
      guest_name: "Matrix Canary",
      cabin_name: "Fortress Ridge",
      check_in: "2026-04-12",
      check_out: "2026-04-15",
      cart_value: "1842.50",
      friction_label: "paused before checkout",
    },
    target_node: "auto",
  },
  null,
  0,
);

function timestamp(): string {
  return new Date().toLocaleTimeString();
}

function parseSignal(actionLog: string[] | undefined, prefix: string, fallback: string): string {
  const value = actionLog?.find((entry) => entry.startsWith(prefix));
  return value ? value.slice(prefix.length) : fallback;
}

function parseStreamError(responseText: string): string {
  try {
    const parsed = JSON.parse(responseText) as { detail?: string; title?: string };
    return parsed.detail || parsed.title || responseText;
  } catch {
    return responseText || "Manual matrix dispatch failed";
  }
}

export const MatrixTerminal = memo(function MatrixTerminal() {
  const [input, setInput] = useState(DEFAULT_INPUT);
  const [isExecuting, setIsExecuting] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([
    {
      timestamp: timestamp(),
      text: "Matrix connection established. Awaiting directive...",
      type: "info",
    },
  ]);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  function appendLog(entry: Omit<LogEntry, "timestamp">): void {
    setLogs((current) => [
      ...current,
      {
        timestamp: timestamp(),
        ...entry,
      },
    ]);
  }

  function handleStreamEvent(event: MatrixDispatchResponse): void {
    if (event.log) {
      appendLog({ text: event.log, type: "info" });
    }

    if (event.error) {
      const details = event.details ? `: ${event.details}` : "";
      throw new Error(`${event.error}${details}`);
    }

    if (event.status === "success") {
      const executionPath =
        typeof event.execution_path === "string"
          ? event.execution_path
          : parseSignal(event.action_log, "execution_path=", "unknown");
      const sandboxName =
        typeof event.sandbox_name === "string"
          ? event.sandbox_name
          : parseSignal(event.action_log, "sandbox_name=", "Matrix");
      appendLog({
        text: `[SUCCESS] Node: ${sandboxName} | Path: ${executionPath}`,
        type: "success",
      });

      const draftBody = String(event.result_payload?.draft_body ?? "").trim();
      if (draftBody) {
        appendLog({
          text: `PAYLOAD:\n${draftBody}`,
          type: "info",
        });
      }
    }
  }

  async function handleDispatch(): Promise<void> {
    if (!input.trim()) return;

    appendLog({ text: `> ${input}`, type: "command" });
    setIsExecuting(true);

    try {
      const parsed = JSON.parse(input) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Directive must be a JSON object.");
      }
      const token = getToken();
      const response = await fetch("/api/agent/dispatch/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: "include",
        body: JSON.stringify(parsed),
      });

      if (!response.ok) {
        throw new Error(parseStreamError(await response.text()));
      }

      if (!response.body) {
        throw new Error("No readable stream available from Matrix.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const payload = block
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trim())
            .join("\n");

          if (payload) {
            handleStreamEvent(JSON.parse(payload) as MatrixDispatchResponse);
          }

          boundary = buffer.indexOf("\n\n");
        }
      }

      const trailingPayload = buffer
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("\n");
      if (trailingPayload) {
        handleStreamEvent(JSON.parse(trailingPayload) as MatrixDispatchResponse);
      }
    } catch (error) {
      appendLog({
        text: `[FATAL] ${errorMessage(error, "Invalid JSON payload")}`,
        type: "error",
      });
    } finally {
      setIsExecuting(false);
    }
  }

  return (
    <div className="flex h-full min-h-[560px] flex-col rounded-sm border border-zinc-800 bg-[#111827] p-4 font-mono text-sm">
      <div className="mb-4 flex items-center gap-2 border-b border-zinc-800 pb-2">
        <TerminalIcon className="h-5 w-5 text-cyan-400" />
        <h2 className="font-bold tracking-wide text-white">DIRECT OVERRIDE TERMINAL</h2>
      </div>

      <div className="mb-4 flex-1 overflow-hidden border border-zinc-800 bg-[#050505]">
        <ScrollArea className="h-[360px] px-3 py-3">
          {logs.map((log, index) => (
            <div
              key={`${log.timestamp}-${index}`}
              className={`mb-1 ${
                log.type === "error"
                  ? "text-rose-400"
                  : log.type === "success"
                    ? "text-emerald-400"
                    : log.type === "command"
                      ? "text-white"
                      : "text-zinc-400"
              }`}
            >
              <span className="mr-2 text-xs text-zinc-600">[{log.timestamp}]</span>
              <span className="whitespace-pre-wrap">{log.text}</span>
            </div>
          ))}
          <div ref={bottomRef} />
        </ScrollArea>
      </div>

      <div className="mt-auto flex flex-col gap-2 xl:flex-row">
        <Textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          disabled={isExecuting}
          rows={3}
          className="min-h-[76px] flex-1 rounded-none border-zinc-700 bg-[#050505] font-mono text-xs text-white focus-visible:ring-cyan-400 disabled:opacity-50"
          placeholder='{"intent":"draft_recovery_email","target_node":"auto"}'
        />
        <button
          type="button"
          onClick={() => {
            void handleDispatch();
          }}
          disabled={isExecuting}
          className="whitespace-nowrap bg-cyan-400 px-6 py-2 font-bold text-black transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isExecuting ? "TRANSMITTING..." : "EXECUTE"}
        </button>
      </div>
    </div>
  );
});
