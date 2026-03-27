"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Scale, Loader2, CircleStop, Play, Radio } from "lucide-react";
import { useCouncilStream } from "@/lib/use-council-stream";

export default function LegalCouncilPage() {
  const [caseSlug, setCaseSlug] = useState("");
  const council = useCouncilStream(caseSlug.trim());
  const isRunning = council.connectionState !== "idle" &&
    council.connectionState !== "done" &&
    council.connectionState !== "stopped" &&
    council.connectionState !== "error";

  const outputSnapshot = council.finalResult
    ? [
        `Consensus: ${council.finalResult.consensus_signal}`,
        `Conviction: ${council.finalResult.consensus_conviction}`,
        `Defense Count: ${council.finalResult.defense_count}`,
        `Weak Count: ${council.finalResult.weak_count}`,
        "",
        ...council.finalResult.opinions.map(
          (opinion) =>
            `Seat ${opinion.seat} ${opinion.persona}: ${opinion.signal}\n${opinion.reasoning}`,
        ),
      ].join("\n\n")
    : "No output yet.";

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Scale className="h-6 w-6 text-primary" />
            Legal Council Execution Terminal
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Case-scoped Redis replay stream for the Counsel of 9.
          </p>
        </div>
        <Badge variant={isRunning ? "default" : "secondary"} className="gap-1">
          <Radio className="h-3 w-3" />
          {council.connectionState}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Run Deliberation By Case Slug</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            value={caseSlug}
            onChange={(event) => setCaseSlug(event.target.value)}
            placeholder="prime-trust-23-11161"
            disabled={isRunning}
          />
          <div className="flex gap-2">
            <Button
              onClick={() => void council.start()}
              disabled={isRunning || !caseSlug.trim()}
            >
              {isRunning ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Play className="h-4 w-4 mr-2" />}
              Start
            </Button>
            <Button variant="destructive" onClick={council.stop} disabled={!isRunning}>
              <CircleStop className="h-4 w-4 mr-2" />
              Stop
            </Button>
          </div>
        </CardContent>
      </Card>

      {council.error && (
        <Card className="border-destructive/40 bg-destructive/10">
          <CardContent className="pt-4">
            <pre className="text-sm text-destructive font-mono whitespace-pre-wrap">
              {council.error}
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
            {council.streamLines.length
              ? council.streamLines
                  .map((line) => `${line.type}: ${line.label}`)
                  .join("\n")
              : "No events yet."}
          </pre>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Output Snapshot</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="text-xs whitespace-pre-wrap rounded border p-3 bg-muted/30 min-h-20">
            {outputSnapshot}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
