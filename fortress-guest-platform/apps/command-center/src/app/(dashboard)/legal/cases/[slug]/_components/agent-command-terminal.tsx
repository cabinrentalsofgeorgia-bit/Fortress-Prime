"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Brain, Loader2, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

type ReasoningStep = {
  iteration: number;
  thought: string;
  action: string;
  action_arg: string;
  observation: string;
  source: string;
  timestamp: string;
};

type MissionResponse = {
  mission_id: string;
  case_slug: string;
  objective: string;
  reasoning_log: ReasoningStep[];
  final_output: string;
  status: string;
};

type AgentCommandTerminalProps = {
  slug: string;
};

const ACTION_COLORS: Record<string, string> = {
  graph_snapshot: "text-blue-400",
  tripwire: "text-red-400",
  omni_search: "text-emerald-400",
  final: "text-amber-400",
};

export function AgentCommandTerminal({ slug }: AgentCommandTerminalProps) {
  const [objective, setObjective] = useState("");
  const [running, setRunning] = useState(false);
  const [mission, setMission] = useState<MissionResponse | null>(null);

  async function handleExecute() {
    if (objective.trim().length < 10) return;
    setRunning(true);
    setMission(null);
    try {
      const res = await api.post<MissionResponse>(
        `/api/legal/cases/${slug}/agent/mission`,
        { strategic_objective: objective.trim() },
      );
      setMission(res);
      toast.success(`Mission ${res.status}: ${res.reasoning_log?.length ?? 0} steps`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Mission failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Brain className="h-4 w-4 text-amber-400" />
        <p className="text-sm font-semibold text-zinc-100">Managing Partner Terminal</p>
      </div>

      <textarea
        value={objective}
        onChange={(e) => setObjective(e.target.value)}
        placeholder="Enter strategic objective (e.g., Cross-examine the March 13th affidavit against the plaintiff's claims and identify every exploitable contradiction)"
        rows={3}
        className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-amber-500 resize-y"
        data-testid="agent-objective-input"
      />

      <Button
        type="button"
        onClick={handleExecute}
        disabled={running || objective.trim().length < 10}
        className="gap-2"
        data-testid="agent-execute-btn"
      >
        {running ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Agent Reasoning...
          </>
        ) : (
          <>
            <Brain className="h-4 w-4" />
            Execute Mission
          </>
        )}
      </Button>

      {mission && (
        <div className="space-y-3" data-testid="agent-mission-output">
          <div className="rounded-md border border-zinc-700 bg-zinc-900/70 p-3">
            <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-2">Reasoning Log</p>
            <ScrollArea className="max-h-64">
              <div className="space-y-2" data-testid="agent-reasoning-log">
                {(mission.reasoning_log ?? []).map((step, idx) => (
                  <div key={idx} className="rounded border border-zinc-800 bg-zinc-950/50 p-2 text-xs space-y-1">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-[9px]">Step {step.iteration}</Badge>
                      <span className={`font-mono font-bold ${ACTION_COLORS[step.action] ?? "text-zinc-400"}`}>
                        {step.action}{step.action_arg ? `(${step.action_arg.slice(0, 40)})` : ""}
                      </span>
                      <Badge variant="outline" className="text-[9px] ml-auto">{step.source}</Badge>
                    </div>
                    {step.thought && (
                      <p className="text-zinc-300"><span className="text-zinc-500">Thought:</span> {step.thought}</p>
                    )}
                    {step.observation && step.observation !== "MISSION COMPLETE" && (
                      <p className="text-zinc-400 truncate"><span className="text-zinc-500">Observation:</span> {step.observation.slice(0, 200)}</p>
                    )}
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>

          {mission.final_output && (
            <div className="space-y-2">
              <div className="rounded-md border-2 border-red-600 bg-red-950/60 p-2 flex items-start gap-2" data-testid="agent-hitl-banner">
                <ShieldAlert className="h-4 w-4 text-red-500 shrink-0 mt-0.5" />
                <p className="text-[11px] font-bold text-red-400 uppercase tracking-wider">
                  Draft Only — Counsel Review Required Prior to Filing or Distribution
                </p>
              </div>

              <div className="rounded-md border border-zinc-700 bg-zinc-900/70 p-3" data-testid="agent-final-output">
                <p className="text-[10px] uppercase tracking-wider text-zinc-500 mb-2">Final Output</p>
                <p className="text-xs text-zinc-100 whitespace-pre-wrap leading-relaxed">
                  {mission.final_output}
                </p>
              </div>

              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-[10px]">
                  {mission.status}
                </Badge>
                <Badge variant="outline" className="text-[10px]">
                  {mission.reasoning_log?.length ?? 0} steps
                </Badge>
                <Badge variant="outline" className="text-[10px]">
                  mission:{mission.mission_id?.slice(0, 8)}
                </Badge>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
