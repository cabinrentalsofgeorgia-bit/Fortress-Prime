"use client";

import { useCallback, useRef, useState } from "react";
import { getToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Scale, Loader2, CircleStop, Play } from "lucide-react";

type CouncilEvent = {
  type?: string;
  [key: string]: unknown;
};

const AUTH_SYSTEM_ERROR =
  "[SYSTEM ERROR] Session expired or unauthorized. Re-login required.";

export default function LegalCouncilPage() {
  const [caseBrief, setCaseBrief] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [events, setEvents] = useState<string[]>([]);
  const [finalOutput, setFinalOutput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const appendLine = useCallback((line: string) => {
    setEvents((prev) => {
      const next = [...prev, line];
      return next.length > 400 ? next.slice(-400) : next;
    });
  }, []);

  const runDeliberation = useCallback(async () => {
    const brief = caseBrief.trim();
    if (!brief || isRunning) return;

    setIsRunning(true);
    setEvents([]);
    setFinalOutput("");
    setError(null);

    const token = getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    };
    if (token) headers.Authorization = `Bearer ${token}`;

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch("/api/legal/council/stream", {
        method: "POST",
        headers,
        body: JSON.stringify({
          case_brief: brief,
          context: "",
          trigger_type: "MANUAL_RUN",
        }),
        signal: controller.signal,
      });

      if (res.status === 401) {
        setError(AUTH_SYSTEM_ERROR);
        appendLine(AUTH_SYSTEM_ERROR);
        return;
      }

      if (!res.ok || !res.body) {
        const msg = await res.text().catch(() => "Unknown error");
        throw new Error(`HTTP ${res.status}: ${msg.slice(0, 200)}`);
      }

      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      let assembled = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += value;
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";

        for (const frame of frames) {
          if (!frame.includes("data:")) continue;
          const dataLines = frame
            .split("\n")
            .map((line) => line.trim())
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trim());

          if (dataLines.length === 0) continue;
          const payloadText = dataLines.join("\n");

          let payload: CouncilEvent | null = null;
          try {
            payload = JSON.parse(payloadText) as CouncilEvent;
          } catch {
            continue;
          }

          const type = String(payload.type ?? "event");
          appendLine(`${type}: ${payloadText.slice(0, 300)}`);

          if (type === "persona_complete") {
            const opinion = payload.opinion as Record<string, unknown> | undefined;
            const reasoning = typeof opinion?.reasoning === "string" ? opinion.reasoning : "";
            if (reasoning) assembled += `${reasoning}\n\n`;
          } else if (type === "consensus") {
            assembled += `Consensus: ${String(payload.consensus_signal ?? "UNKNOWN")} (conviction ${String(payload.consensus_conviction ?? "0")})\n`;
          } else if (type === "error") {
            const msg = String(payload.message ?? "Council stream error");
            setError(msg);
          } else if (type === "done") {
            const signal = String(payload.consensus_signal ?? "UNKNOWN");
            const conviction = String(payload.consensus_conviction ?? "0");
            assembled += `\nDone: ${signal} (${conviction})`;
          }
        }
      }

      setFinalOutput(assembled.trim());
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        appendLine("status: execution aborted");
      } else {
        const msg = err instanceof Error ? err.message : "Unknown stream error";
        setError(msg);
      }
    } finally {
      abortRef.current = null;
      setIsRunning(false);
    }
  }, [appendLine, caseBrief, isRunning]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsRunning(false);
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Scale className="h-6 w-6 text-primary" />
            Legal Council Execution Terminal
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Streams deliberation events from `/api/legal/council/stream`.
          </p>
        </div>
        <Badge variant={isRunning ? "default" : "secondary"}>
          {isRunning ? "Streaming" : "Idle"}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Run Deliberation</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <textarea
            value={caseBrief}
            onChange={(e) => setCaseBrief(e.target.value)}
            placeholder="Paste legal case brief..."
            className="w-full min-h-32 rounded-md border bg-background px-3 py-2 text-sm"
            disabled={isRunning}
          />
          <div className="flex gap-2">
            <Button onClick={() => void runDeliberation()} disabled={isRunning || !caseBrief.trim()}>
              {isRunning ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Play className="h-4 w-4 mr-2" />}
              Start
            </Button>
            <Button variant="destructive" onClick={stop} disabled={!isRunning}>
              <CircleStop className="h-4 w-4 mr-2" />
              Stop
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-destructive/40 bg-destructive/10">
          <CardContent className="pt-4">
            <pre className="text-sm text-destructive font-mono whitespace-pre-wrap">
              {error}
            </pre>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Live SSE Events</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="text-xs whitespace-pre-wrap max-h-80 overflow-auto rounded border p-3 bg-muted/30">
            {events.length ? events.join("\n") : "No events yet."}
          </pre>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Output Snapshot</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="text-xs whitespace-pre-wrap rounded border p-3 bg-muted/30 min-h-20">
            {finalOutput || "No output yet."}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
