"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Terminal as TerminalIcon } from "lucide-react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";

type MatrixDispatchResponse = {
  task_id?: string;
  status?: string;
  action_log?: string[];
  result_payload?: Record<string, unknown>;
  [key: string]: unknown;
};

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return `${error.status}: ${error.message}`;
  }
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

export function MatrixTerminal() {
  const [input, setInput] = useState(DEFAULT_INPUT);
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

  const dispatch = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post<MatrixDispatchResponse>("/api/agent/dispatch", payload),
    onSuccess: (result) => {
      const executionPath = parseSignal(result.action_log, "execution_path=", "unknown");
      const sandboxName = parseSignal(result.action_log, "sandbox_name=", "Matrix");
      const nextLogs: LogEntry[] = [
        {
          timestamp: timestamp(),
          text: `[SUCCESS] Node: ${sandboxName} | Path: ${executionPath}`,
          type: "success",
        },
      ];
      const draftBody = String(result.result_payload?.draft_body ?? "").trim();
      if (draftBody) {
        nextLogs.push({
          timestamp: timestamp(),
          text: `PAYLOAD:\n${draftBody}`,
          type: "info",
        });
      }
      setLogs((current) => [...current, ...nextLogs]);
    },
    onError: (error) => {
      setLogs((current) => [
        ...current,
        {
          timestamp: timestamp(),
          text: `[FATAL] ${errorMessage(error, "Manual matrix dispatch failed")}`,
          type: "error",
        },
      ]);
    },
  });

  async function handleDispatch(): Promise<void> {
    if (!input.trim()) return;

    setLogs((current) => [
      ...current,
      {
        timestamp: timestamp(),
        text: `> ${input}`,
        type: "command",
      },
    ]);

    try {
      const parsed = JSON.parse(input) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("Directive must be a JSON object.");
      }
      await dispatch.mutateAsync(parsed as Record<string, unknown>);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Invalid JSON payload";
      setLogs((current) => [
        ...current,
        {
          timestamp: timestamp(),
          text: `[FATAL] ${message}`,
          type: "error",
        },
      ]);
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
          disabled={dispatch.isPending}
          rows={3}
          className="min-h-[76px] flex-1 rounded-none border-zinc-700 bg-[#050505] font-mono text-xs text-white focus-visible:ring-cyan-400 disabled:opacity-50"
          placeholder='{"intent":"draft_recovery_email","target_node":"auto"}'
        />
        <button
          type="button"
          onClick={() => {
            void handleDispatch();
          }}
          disabled={dispatch.isPending}
          className="whitespace-nowrap bg-cyan-400 px-6 py-2 font-bold text-black transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {dispatch.isPending ? "TRANSMITTING..." : "EXECUTE"}
        </button>
      </div>
    </div>
  );
}
