"use client";

import { useEffect, useState, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Cpu, Radio, Zap } from "lucide-react";

interface InferenceState {
  status: "idle" | "processing" | "complete" | "failed";
  node: string;
  model: string;
  taskType: string;
  sourceModule: string;
  payloadChars: number;
  maxTokens: number;
  durationMs: number;
  source: string;
  healed: boolean;
  error: string;
  startedAt: number;
}

const INITIAL: InferenceState = {
  status: "idle",
  node: "",
  model: "",
  taskType: "",
  sourceModule: "",
  payloadChars: 0,
  maxTokens: 0,
  durationMs: 0,
  source: "",
  healed: false,
  error: "",
  startedAt: 0,
};

export function InferenceRadar() {
  const [state, setState] = useState<InferenceState>(INITIAL);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    function handleWs(e: Event) {
      const detail = (e as CustomEvent).detail;
      if (detail?.event !== "inference_status" || !detail?.data) return;
      const d = detail.data as Record<string, unknown>;

      if (d.status === "processing") {
        setState({
          status: "processing",
          node: String(d.node ?? ""),
          model: String(d.model ?? ""),
          taskType: String(d.task_type ?? ""),
          sourceModule: String(d.source_module ?? ""),
          payloadChars: Number(d.payload_chars ?? 0),
          maxTokens: Number(d.max_tokens ?? 0),
          durationMs: 0,
          source: "",
          healed: false,
          error: "",
          startedAt: Date.now(),
        });
        setElapsed(0);
      } else if (d.status === "complete" || d.status === "failed") {
        setState((prev) => ({
          ...prev,
          status: d.status as "complete" | "failed",
          durationMs: Number(d.duration_ms ?? 0),
          source: String(d.source ?? ""),
          healed: Boolean(d.healed),
          error: String(d.error ?? ""),
        }));
      }
    }

    window.addEventListener("fortress-ws", handleWs);
    return () => window.removeEventListener("fortress-ws", handleWs);
  }, []);

  useEffect(() => {
    if (state.status === "processing") {
      timerRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - state.startedAt) / 1000));
      }, 250);
    } else {
      clearInterval(timerRef.current);
    }
    return () => clearInterval(timerRef.current);
  }, [state.status, state.startedAt]);

  if (state.status === "idle") return null;

  const isProcessing = state.status === "processing";
  const isFailed = state.status === "failed";
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const timerStr = `${mins}:${secs.toString().padStart(2, "0")}`;

  const nodeLabel = state.node
    ? `${state.node.split(".").pop() === "106" ? "Sovereign" : state.node.split(".").pop() === "100" ? "Captain" : state.node.split(".").pop() === "104" ? "Muscle" : state.node.split(".").pop() === "105" ? "Ocular" : state.node} (.${state.node.split(".").pop()})`
    : "DGX Cluster";

  return (
    <div
      className={`rounded-lg border p-3 font-mono text-xs transition-all duration-500 ${
        isProcessing
          ? "border-emerald-500/40 bg-emerald-500/5"
          : isFailed
            ? "border-red-500/40 bg-red-500/5"
            : "border-blue-500/30 bg-blue-500/5"
      }`}
    >
      <div className="flex items-center gap-3 mb-2">
        <div className="flex items-center gap-1.5">
          {isProcessing ? (
            <Radio className="h-3.5 w-3.5 text-emerald-400 animate-pulse" />
          ) : isFailed ? (
            <Zap className="h-3.5 w-3.5 text-red-400" />
          ) : (
            <Cpu className="h-3.5 w-3.5 text-blue-400" />
          )}
          <span className="font-semibold text-foreground">
            Inference Radar
          </span>
        </div>

        <Badge
          variant="outline"
          className={`text-[10px] ${
            isProcessing
              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/30 animate-pulse"
              : isFailed
                ? "bg-red-500/10 text-red-400 border-red-500/30"
                : "bg-blue-500/10 text-blue-400 border-blue-500/30"
          }`}
        >
          {isProcessing ? "COMPUTING" : isFailed ? "FAILED" : "COMPLETE"}
        </Badge>

        {isProcessing && (
          <span className="ml-auto text-emerald-400 font-bold tabular-nums text-sm">
            {timerStr}
          </span>
        )}
        {!isProcessing && state.durationMs > 0 && (
          <span className="ml-auto text-muted-foreground tabular-nums">
            {(state.durationMs / 1000).toFixed(1)}s
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
        <div>
          <span className="text-muted-foreground">Node </span>
          <span className="text-foreground font-medium">{nodeLabel}</span>
        </div>
        <div>
          <span className="text-muted-foreground">Model </span>
          <span className="text-foreground font-medium">{state.model || "—"}</span>
        </div>
        <div>
          <span className="text-muted-foreground">Task </span>
          <span className="text-sky-400">{state.taskType || "—"}</span>
        </div>
        <div>
          <span className="text-muted-foreground">Module </span>
          <span className="text-amber-400">{state.sourceModule || "—"}</span>
        </div>
        {state.payloadChars > 0 && (
          <div>
            <span className="text-muted-foreground">Payload </span>
            <span className="text-foreground">{state.payloadChars.toLocaleString()} chars</span>
          </div>
        )}
        {state.maxTokens > 0 && (
          <div>
            <span className="text-muted-foreground">Max Tokens </span>
            <span className="text-foreground">{state.maxTokens.toLocaleString()}</span>
          </div>
        )}
        {!isProcessing && state.source && (
          <div className="col-span-2">
            <span className="text-muted-foreground">Resolved via </span>
            <span className={state.healed ? "text-violet-400" : "text-green-400"}>
              {state.source}
              {state.healed && " (healed)"}
            </span>
          </div>
        )}
        {state.error && (
          <div className="col-span-2">
            <span className="text-red-400">{state.error}</span>
          </div>
        )}
      </div>

      {isProcessing && (
        <div className="mt-2 h-1 rounded-full bg-muted overflow-hidden">
          <div className="h-full bg-emerald-500/60 rounded-full animate-[radar_2s_ease-in-out_infinite]" style={{ width: "100%" }} />
        </div>
      )}

      <style jsx>{`
        @keyframes radar {
          0%, 100% { transform: scaleX(0.1); transform-origin: left; opacity: 0.4; }
          50% { transform: scaleX(1); transform-origin: left; opacity: 1; }
        }
      `}</style>
    </div>
  );
}
