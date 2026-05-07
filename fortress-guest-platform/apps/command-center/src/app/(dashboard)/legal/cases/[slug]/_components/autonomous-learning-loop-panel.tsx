"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  useAutonomousLearning,
  useAutonomousLearningFeedback,
} from "@/lib/legal-hooks";
import { BrainCircuit, CheckCircle2, ClipboardList, ShieldAlert, Sparkles } from "lucide-react";

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="text-lg font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function tone(status: string) {
  if (status.includes("pass") || status.includes("SAFE")) return "bg-emerald-500/10 text-emerald-300 border-emerald-500/30";
  if (status.includes("human") || status.includes("review")) return "bg-amber-500/10 text-amber-300 border-amber-500/30";
  return "bg-zinc-900 text-zinc-300 border-zinc-700";
}

export function AutonomousLearningLoopPanel({ slug }: { slug: string }) {
  const { data, isLoading, error } = useAutonomousLearning(slug);
  const feedback = useAutonomousLearningFeedback(slug);
  const [note, setNote] = useState("");

  if (isLoading) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/80 p-4 space-y-3">
        <Skeleton className="h-6 w-80" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-950/70 p-4 text-sm text-zinc-400">
        Autonomous Learning Loop has not been initialized yet.
      </div>
    );
  }

  const signals = data.learning_registry.signals.slice(0, 5);
  const evals = data.evaluation_suite.results.slice(0, 6);
  const proposals = data.improvement_proposals.proposals.slice(0, 5);
  const actions = data.next_best_actions.slice(0, 4);

  return (
    <div className="rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-4 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-sm font-semibold text-cyan-200 flex items-center gap-2">
            <BrainCircuit className="h-4 w-4" />
            Autonomous Learning Loop
          </p>
          <p className="text-xs text-zinc-400">
            {data.execution_id} / bounded to {data.cycle_cap} cycles
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Badge variant="outline" className="bg-amber-500/10 text-amber-300 border-amber-500/30 text-[10px]">
            COUNSEL_SIGNOFF_PENDING
          </Badge>
          <Badge variant="outline" className="bg-red-500/10 text-red-300 border-red-500/30 text-[10px]">
            DRAFT / COUNSEL REVIEW REQUIRED
          </Badge>
          <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            NO EXTERNAL MODEL TRAINING
          </Badge>
          <Badge variant="outline" className="bg-zinc-900 text-zinc-300 border-zinc-700 text-[10px]">
            EXTERNAL_SUBMISSION_NOT_AUTHORIZED
          </Badge>
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <Metric label="Cycles" value={data.cycles_completed} />
        <Metric label="Signals" value={data.learning_registry.signal_count} />
        <Metric label="Evals" value={data.evaluation_suite.eval_count} />
        <Metric label="Proposals" value={data.improvement_proposals.proposal_count} />
        <Metric label="Safe Auto-Apply" value={data.improvement_proposals.safe_auto_apply_count} />
        <Metric label="Human Approval" value={data.improvement_proposals.human_approval_required_count} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ClipboardList className="h-3.5 w-3.5 text-cyan-300" />
            Learning Signals
          </p>
          {signals.map((signal) => (
            <div key={signal.signal_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{signal.signal_type.replaceAll("_", " ")}</p>
              <p className="text-[10px] text-zinc-500">{signal.reason}</p>
            </div>
          ))}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" />
            Evaluation Suite Status
          </p>
          {evals.map((result) => (
            <div key={result.eval_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{result.assertion}</p>
              <Badge variant="outline" className={`mt-1 text-[10px] ${tone(result.status)}`}>
                {result.status.replaceAll("_", " ")}
              </Badge>
            </div>
          ))}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <Sparkles className="h-3.5 w-3.5 text-amber-300" />
            Improvement Proposal Queue
          </p>
          {proposals.map((proposal) => (
            <div key={proposal.proposal_id} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{proposal.title}</p>
              <Badge variant="outline" className={`mt-1 text-[10px] ${tone(proposal.status)}`}>
                {proposal.status.replaceAll("_", " ")}
              </Badge>
            </div>
          ))}
        </section>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100 flex items-center gap-2">
            <ShieldAlert className="h-3.5 w-3.5 text-amber-300" />
            Next-Best Actions
          </p>
          {actions.map((action) => (
            <div key={action.rank} className="rounded border border-zinc-800 bg-zinc-900/70 p-2">
              <p className="text-xs text-zinc-100">{action.rank}. {action.action}</p>
              <p className="text-[10px] text-zinc-500">{action.required_authority}</p>
            </div>
          ))}
        </section>

        <section className="rounded-md border border-zinc-800 bg-zinc-950/70 p-3 space-y-2">
          <p className="text-xs font-semibold text-zinc-100">Feedback Capture</p>
          <p className="text-xs text-zinc-500">
            Notes must not include secrets, full document text, or locked/restricted content.
          </p>
          <Textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Capture source, validation, UI, or next-action feedback"
            className="min-h-20 text-xs"
          />
          <Button
            type="button"
            size="sm"
            disabled={!note.trim() || feedback.isPending}
            onClick={() =>
              feedback.mutate({
                item_id: "general-learning-feedback",
                item_type: "learning_loop",
                feedback_type: "operator_feedback",
                severity: "medium",
                note,
                action_requested: "review_feedback",
              })
            }
          >
            {feedback.isPending ? "Capturing..." : "Capture Feedback"}
          </Button>
        </section>
      </div>
    </div>
  );
}
